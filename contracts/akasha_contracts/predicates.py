"""Bibliothèque fermée de prédicats de réussite (spec §5.4).

Chaque prédicat est évalué sur l'état vérifié par l'adaptateur, jamais sur
la sortie d'un modèle. Composition bornée : `all_of` / `any_of`, profondeur
maximale 2 (imposée par le schéma : pas d'imbrication).

Un prédicat sans évaluateur disponible (fenêtre, élément UI) ou exigeant un
humain ne réussit jamais par défaut : il retourne une erreur typée.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess

from .errors import AkashaError, ErrorCode
from .validate import validate

MAX_PREDICATE_DEPTH = 2

# Prédicats évaluables localement par cet adaptateur de référence.
_CODE_PREDICATES = {
    "file_exists", "file_matches_regex", "git_diff_applies",
    "test_suite_passes", "process_exit_zero",
}
_DESKTOP_PREDICATES = {
    "file_hash_equals", "registry_key_equals", "process_running",
}

_PASS = (True, None)


def evaluate(node: dict, workspace: str) -> tuple[bool, AkashaError | None]:
    """Évalue un nœud SuccessPredicate. `(réussi, erreur)` ; jamais d'exception."""
    errors = validate(node, "SuccessPredicate")
    if errors:
        err = errors[0]
        return False, AkashaError(ErrorCode.CONTRACT_SCHEMA_VIOLATION, err.message, err.details)
    if "all_of" in node:
        for child in node["all_of"]:
            ok, err = _evaluate_leaf(child, workspace)
            if not ok:
                return False, err
        return _PASS
    if "any_of" in node:
        last_err = None
        for child in node["any_of"]:
            ok, err = _evaluate_leaf(child, workspace)
            if ok:
                return _PASS
            last_err = err
        return False, last_err
    return _evaluate_leaf(node, workspace)


def _evaluate_leaf(node: dict, workspace: str) -> tuple[bool, AkashaError | None]:
    name = node["predicate"]
    args = node.get("args", {})
    try:
        if name == "file_exists":
            return (True, None) if os.path.isfile(_join(workspace, args["path"])) else (
                False, _fail(name, f"Fichier absent : {args.get('path')}"))
        if name == "file_matches_regex":
            path = _join(workspace, args["path"])
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            return (True, None) if re.search(args["pattern"], content) else (
                False, _fail(name, f"Motif absent dans {args.get('path')}"))
        if name == "file_hash_equals":
            digest = hashlib.sha256()
            with open(_join(workspace, args["path"]), "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    digest.update(chunk)
            return (True, None) if digest.hexdigest() == args["sha256"] else (
                False, _fail(name, f"Empreinte différente pour {args.get('path')}"))
        if name == "process_exit_zero":
            proc = subprocess.run(args["command"], shell=True, cwd=workspace,
                                  capture_output=True, timeout=args.get("timeout_s", 120))
            return (True, None) if proc.returncode == 0 else (
                False, _fail(name, f"Sortie {proc.returncode} : {args.get('command')}"))
        if name == "test_suite_passes":
            return _evaluate_leaf({"predicate": "process_exit_zero", "on": node["on"],
                                   "args": {"command": args.get("command", "pytest -q"),
                                            "timeout_s": args.get("timeout_s", 600)}},
                                  workspace)
        if name == "git_diff_applies":
            proc = subprocess.run(["git", "apply", "--check", args["patch"]],
                                  cwd=workspace, capture_output=True, timeout=60)
            return (True, None) if proc.returncode == 0 else (
                False, _fail(name, "Le patch ne s'applique pas proprement"))
        if name == "registry_key_equals":
            return _registry_check(args)
        if name == "process_running":
            return _process_check(args)
        if name in ("window_foreground", "ui_element_state"):
            return False, AkashaError(
                ErrorCode.PREDICATE_EVALUATOR_UNAVAILABLE,
                f"Prédicat {name} : pas d'évaluateur UIA disponible en Phase 0.",
                {"predicate": name})
        if name == "human_confirms":
            return False, AkashaError(
                ErrorCode.HUMAN_CONFIRM_PENDING,
                "Confirmation humaine en attente (nœud humain, jamais un jugement LLM).",
                {"predicate": name})
        return False, AkashaError(
            ErrorCode.CONTRACT_PREDICATE_UNKNOWN,
            f"Prédicat hors ensemble fermé : {name}.",
            {"predicate": name})
    except (OSError, subprocess.SubprocessError, KeyError, re.error) as exc:
        return False, AkashaError(
            ErrorCode.ENVIRONMENT_OBSERVATION_FAILED,
            f"Prédicat {name} : observation impossible ({exc}).",
            {"predicate": name})


def _join(workspace: str, path: str) -> str:
    full = os.path.normpath(os.path.join(workspace, path))
    if not full.startswith(os.path.normpath(workspace)):
        raise OSError(f"Chemin hors espace de travail : {path}")
    return full


def _fail(name: str, message: str) -> AkashaError:
    return AkashaError(ErrorCode.CONTRACT_POSTCONDITION_FAILED,
                       f"Prédicat {name} : {message}.", {"predicate": name})


def _registry_check(args: dict) -> tuple[bool, AkashaError | None]:
    try:
        import winreg
    except ImportError:
        return False, AkashaError(
            ErrorCode.PREDICATE_EVALUATOR_UNAVAILABLE,
            "Registre Windows indisponible sur cette plateforme.",
            {"predicate": "registry_key_equals"})
    try:
        hive = getattr(winreg, args["hive"])
        with winreg.OpenKey(hive, args["key"]) as key:
            value, _kind = winreg.QueryValueEx(key, args["value_name"])
    except (OSError, AttributeError, KeyError) as exc:
        return False, AkashaError(
            ErrorCode.ENVIRONMENT_OBSERVATION_FAILED,
            f"Lecture du registre impossible ({exc}).",
            {"predicate": "registry_key_equals"})
    if str(value) == str(args["expected"]):
        return _PASS
    return False, _fail("registry_key_equals", "Valeur différente de l'attendue")


def _process_check(args: dict) -> tuple[bool, AkashaError | None]:
    try:
        proc = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {args['image']}",
                               "/FO", "CSV", "/NH"],
                              capture_output=True, timeout=30, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, AkashaError(
            ErrorCode.ENVIRONMENT_OBSERVATION_FAILED,
            f"Liste des processus inaccessible ({exc}).",
            {"predicate": "process_running"})
    if args["image"].lower() in proc.stdout.lower():
        return _PASS
    return False, _fail("process_running", f"Processus absent : {args.get('image')}")
