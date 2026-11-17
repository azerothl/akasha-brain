"""Préparer et approuver une opération sur un fichier d'un projet local."""

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from difflib import unified_diff
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
from tempfile import NamedTemporaryFile, TemporaryDirectory, gettempdir
from time import perf_counter
from uuid import uuid4

from bench.run_guided_repair import BENCH, file_hash, wsb
from contracts.akasha_contracts.authz import authorize
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .notes_repair import stage_git
from .notes_sandbox import CHANNELS, POWERSHELL, active_sandboxes, guest_exit, read_profile, wait_for_guest
from .planning import PlanningError
from .project_audit import record as audit_decision, verify as verify_audit
from .project_approval import (
    action_key, application_state, approval_deadline, discard_unstarted_application, mark_application,
    new_request, require_fresh,
)
from .project_backup import backup, grant_backup, restore, revoke_backup
from .project_common import ProjectError, digest, identity, reject
from .project_dependencies import create_request, download, stage_dependencies, stage_installer
from .project_evolution import (
    ARTIFACTS, capture_project_memory, check_sample, collect, erase, finish_replay, load_sample, register_replay,
)
from .project_transition import deletion_revision, reject_stale_deletion, verify_deletion

SECRET_PATHS = {".env", ".netrc", ".npmrc", ".pypirc", ".ssh", ".aws", "id_rsa", "id_ed25519",
                "credentials.json", "secrets.json"}
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
CODE_FILE_LIMIT = 256 * 1024
CODE_LINE_LIMIT = 200
CODE_COLUMN_LIMIT = 500


def check_secret_path(components) -> None:
    if any(part in SECRET_PATHS or part.startswith(".env.") or part.endswith((".key", ".pfx", ".p12"))
           for part in (component.casefold() for component in components)):
        reject(ErrorCode.PERMISSION_DENIED, "Les fichiers d'identifiants et de clés sont exclus du parcours projet.",
               reason="secret_input")


def project_file(project: Path, name: str, *, absent: bool = False) -> Path:
    relative = PurePosixPath(name)
    if (not relative.parts or relative.is_absolute() or relative.as_posix() != name
            or any(char in '\\:<>"|?*' or ord(char) < 32 for char in name)
            or any(part.casefold() in {"..", ".git"} or part.endswith((" ", "."))
                   or PureWindowsPath(part).is_reserved() for part in relative.parts)):
        reject(ErrorCode.PERMISSION_DENIED, "Chemin de projet interdit.", path=name)
    check_secret_path(relative.parts)
    path = project
    for index, part in enumerate(relative.parts):
        path /= part
        leaf = index == len(relative.parts) - 1
        try:
            info = path.lstat()
        except FileNotFoundError:
            if leaf and absent:
                return path
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            reject(ErrorCode.PERMISSION_DENIED, "Lien ou point de réanalyse interdit.", path=name)
        if not leaf and not stat.S_ISDIR(info.st_mode):
            reject(ErrorCode.PERMISSION_DENIED, "Dossier parent ordinaire requis.", path=name)
    if absent:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "La destination existe déjà.", reason="destination_exists", path=name)
    if not stat.S_ISREG(info.st_mode):
        reject(ErrorCode.PERMISSION_DENIED, "Fichier ordinaire requis.", path=name)
    return path


def snapshot(project: Path, names, *, byte_limit: int | None = None) -> dict:
    return {name: project_input(project_file(project, name), byte_limit=byte_limit) for name in names}


def project_input(path: Path, *, byte_limit: int | None = None) -> bytes:
    check_secret_path(path.parts)
    with path.open("rb") as stream:
        content = stream.read() if byte_limit is None else stream.read(byte_limit + 1)
    return checked_input(content, byte_limit)


def checked_input(content: bytes, byte_limit: int | None) -> bytes:
    if byte_limit is not None and len(content) > byte_limit:
        reject(ErrorCode.RESOURCE_BUDGET_EXCEEDED, "Le fichier dépasse la fenêtre de lecture du code.",
               maximum_bytes=byte_limit)
    if PRIVATE_KEY.search(content):
        reject(ErrorCode.PERMISSION_DENIED, "Une clé privée a été détectée dans un fichier sélectionné.",
               reason="secret_input")
    return content


def inspect_code(project: Path, files: list[str], *, contains: str | None = None, first_line: int = 1,
                 limit: int = 80) -> dict:
    if (not 1 <= len(files) <= 32 or not 1 <= limit <= CODE_LINE_LIMIT or first_line < 1
            or (contains is None and len(files) != 1)
            or (contains is not None and (not contains.strip() or len(contains) > CODE_COLUMN_LIMIT))):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Fenêtre ou périmètre de lecture invalide.")
    project = project.resolve(strict=True)
    paths = {name: project_file(project, name) for name in files}
    rows = []
    query = re.compile(re.escape(contains), re.IGNORECASE) if contains is not None else None
    for name, path in paths.items():
        try:
            lines = project_input(path, byte_limit=CODE_FILE_LIMIT).decode("utf-8-sig").splitlines()
        except UnicodeDecodeError:
            reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "La vue du code exige un fichier texte UTF-8.")
        for number, line in enumerate(lines[first_line - 1:], start=first_line):
            position = 0
            if query is not None:
                match = query.search(line)
                if match is None:
                    continue
                position = match.start()
            if len(rows) == limit:
                return {"status": "inspected", "lines": rows, "more": True}
            start = max(0, position - CODE_COLUMN_LIMIT // 4)
            excerpt = line[start:start + CODE_COLUMN_LIMIT]
            rows.append({"file": name, "line": number, "text": excerpt,
                         "excerpt": start > 0 or len(excerpt) < len(line)})
    return {"status": "inspected", "lines": rows, "more": False}


def fingerprints(files: dict) -> dict:
    return {name: digest(content) for name, content in files.items()}


def text_lines(content: bytes) -> list[str]:
    text = content.decode("utf-8")
    if "\0" in text:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Le diff exige un fichier texte UTF-8.")
    *lines, last = text.split("\n")
    return [line + "\n" for line in lines] + ([last] if last else [])


def make_diff(name: str, before: bytes, after: bytes) -> bytes:
    lines = unified_diff(text_lines(before), text_lines(after), f"a/{name}\t", f"b/{name}\t")
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                   for line in lines).encode("utf-8")


def replace_text(source: bytes, before: str, after: str, byte_limit: int | None) -> bytes:
    search = before.encode("utf-8")
    if not search:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Indiquez le texte exact à remplacer.")
    offset = source.find(search)
    if offset < 0:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Le texte à remplacer est introuvable dans le fichier.")
    if source.find(search, offset + 1) != -1:
        reject(ErrorCode.NEEDS_CLARIFICATION, "Le texte apparaît plusieurs fois. Indiquez un extrait plus précis.")
    replacement = source[:offset] + after.encode("utf-8") + source[offset + len(search):]
    return checked_input(replacement, byte_limit)


def expected_files(manifest: dict) -> tuple[dict, list]:
    files = dict(manifest["files"])
    operation = manifest.get("operation", "replace")
    if operation == "check":
        return files, []
    source = manifest["target"]
    if operation == "replace":
        files[source] = manifest["replacement_sha256"]
        return files, []
    old_digest = files.pop(source)
    if operation == "move":
        files[manifest["destination"]] = old_digest
    return files, [source]


def validate_in_sandbox(stage: Path, runtime: Path, *, checkpoint=None, node: bool = False,
                        prepare_runtime=None, export_result=None, sandbox_memory_mib: int | None = None) -> dict:
    if active_sandboxes():
        reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Une session Windows Sandbox est déjà active.")
    profile = read_profile()
    if sandbox_memory_mib is not None:
        from xml.etree import ElementTree

        configuration = ElementTree.fromstring(profile)
        configuration.find("MemoryInMB").text = str(sandbox_memory_mib)
        profile = ElementTree.tostring(configuration, encoding="unicode")
    tag = secrets.token_hex(4)
    mount_path = fr"C:\AkashaGuidedInput-{tag}"
    scripts = ("probe_notes_isolation.ps1", "probe_guest_channels.ps1", "validate_project.ps1")
    has_dependencies = (stage / "wheels").is_dir()
    if has_dependencies:
        scripts += ("install_project_dependencies.py",)
    for name in scripts:
        shutil.copyfile(BENCH / "harness" / name, stage / name)
    (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
    if node:
        shutil.copyfile(runtime, stage / "node.exe")
    else:
        shutil.copytree(runtime, stage / "python")
    if prepare_runtime is not None:
        prepare_runtime(stage / "python")
    if (stage / "proposal.diff").is_file():
        stage_git(stage)
    pip_version = stage_installer(stage) if has_dependencies else None
    sandbox = str(uuid4())
    try:
        if wsb("start", "--id", sandbox, "--config", profile)["Id"].lower() != sandbox:
            raise RuntimeError("Identifiant du bac inattendu.")
        wait_for_guest(sandbox)
        if checkpoint is not None:
            checkpoint()
        wsb("share", "--id", sandbox, "--host-path", str(stage), "--sandbox-path", mount_path)
        mount = guest_exit(sandbox, f"{POWERSHELL} -File {mount_path}\\probe_notes_isolation.ps1 -Tag {tag}")
        channels = guest_exit(sandbox, f"{POWERSHELL} -File {mount_path}\\probe_guest_channels.ps1")
        denied = authorize({"risk_class": "R1", "confinement_verified": (
            mount == 0x450F and channels in (0x410F, 0x411F) and active_sandboxes() == [sandbox]
        )})
        if denied:
            raise ProjectError(denied)
        if checkpoint is not None:
            checkpoint()
        result = guest_exit(sandbox, f"{POWERSHELL} -File {mount_path}\\validate_project.ps1 -Tag {tag}")
        if result != 0x4700:
            reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "La validation dans le bac a échoué.",
                   guest_exit_code=result)
        exported = export_result(sandbox, mount_path, tag) if export_result is not None else None
    finally:
        if sandbox in active_sandboxes():
            wsb("stop", "--id", sandbox)
        if sandbox in active_sandboxes():
            raise RuntimeError("Arrêt du bac non confirmé.")
    validation = {"status": "passed", "sandbox_id": sandbox, "sandbox_stopped": True, "read_only_input": True,
                  "disabled_channels": list(CHANNELS), "channel_probe": channels, "guest_exit_code": result}
    if pip_version is not None:
        validation["dependency_installation"] = {"offline": True, "pip_version": pip_version}
    if export_result is not None:
        validation["exported"] = exported
    return validation


def prepare(project: Path, output: Path, target: str, replacement: Path | None, test: str, runtime: Path,
            *, inputs=(), delete: bool = False, move_to: str | None = None, dependencies=(),
            input_byte_limit: int | None = None, text_change: tuple[str, str] | None = None) -> dict:
    project = project.resolve(strict=True)
    project_id = identity(project)
    output = output.resolve()
    if output.is_relative_to(project):
        reject(ErrorCode.PERMISSION_DENIED, "La proposition doit être stockée hors du projet.")
    if sum((replacement is not None, text_change is not None, delete, move_to is not None)) != 1:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Une opération par proposition est requise.")
    names = (target, test, *inputs)
    paths = names if move_to is None else (*names, move_to)
    if len({name.casefold() for name in paths}) != len(paths):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Les chemins de l'opération et du test doivent être distincts.")
    if move_to is not None:
        project_file(project, move_to, absent=True)
    if delete:
        source = project_file(project, target)
        revision = deletion_revision(source.stat(follow_symlinks=False))
    original = snapshot(project, names, byte_limit=input_byte_limit)
    hashes = fingerprints(original)
    operation = "delete" if delete else "move" if move_to is not None else "replace"
    manifest = {"version": 2, "project": project_id, "operation": operation, "target": target,
                "test": test, "files": hashes}
    if delete:
        if deletion_revision(source.stat(follow_symlinks=False)) != revision:
            reject_stale_deletion()
        manifest["delete_revision"] = revision
    if move_to is not None:
        manifest["destination"] = move_to
    patch = None
    if operation == "replace":
        candidate = (replace_text(original[target], *text_change, byte_limit=input_byte_limit) if text_change is not None
                     else project_input(replacement, byte_limit=input_byte_limit))
        patch = make_diff(target, original[target], candidate)
        if not patch:
            reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "La proposition ne contient aucune modification.")
        manifest.update(diff_sha256=digest(patch), replacement_sha256=digest(candidate))

    output.mkdir(parents=True)
    began = perf_counter()
    validation, wheels = validate_copy(project, output, manifest, original, patch, runtime, dependencies)
    manifest["validation"] = validation
    if wheels:
        manifest["dependencies"] = wheels
    manifest["approval"] = new_request()
    encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if patch is not None:
        (output / "proposal.diff").write_bytes(patch)
        (output / "replacement.txt").write_bytes(candidate)
    (output / "proposal.json").write_bytes(encoded)
    return {"status": "awaiting_approval", "proposal": str(output), "approval_sha256": digest(encoded),
            "operation": operation, "file": target, "destination": move_to,
            "approval_expires_at": manifest["approval"]["expires_at"],
            "validation": validation, "wall_s": round(perf_counter() - began, 3)}


def validate_copy(project: Path, output: Path, manifest: dict, original: dict, patch: bytes | None,
                  runtime: Path, dependencies, *, before_run=None, replay: bool = False) -> tuple[dict, list[dict]]:
    expected, absent = expected_files(manifest)
    target, move_to = manifest.get("target"), manifest.get("destination")
    with TemporaryDirectory(prefix="stage-", dir=output) as directory:
        stage = Path(directory).resolve(strict=True)
        if stage.parent != output:
            raise RuntimeError("Espace de préparation hors du dossier de proposition.")
        for name, content in original.items():
            file = stage / "snapshot" / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
        if patch is not None:
            (stage / "proposal.diff").write_bytes(patch)
        if move_to is not None:
            (stage / "snapshot" / move_to).parent.mkdir(parents=True, exist_ok=True)
        wheels = stage_dependencies(project, dependencies, stage)
        if replay and [wheel["request_sha256"] for wheel in wheels] != manifest["dependency_requests"]:
            reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Les dépendances diffèrent de la proposition validée.")
        guest_wheels = [{key: wheel[key] for key in ("name", "version", "filename", "sha256")} for wheel in wheels]
        validation_request = {"operation": manifest.get("operation", "replace"), "target": target,
                              "destination": move_to, "test": manifest["test"], "files": expected,
                              "absent": absent, "dependencies": guest_wheels}
        if validation_request["operation"] == "check":
            validation_request["test_mode"] = manifest["test_mode"]
            if manifest["test_mode"] == "node":
                validation_request["test_files"] = manifest["test_files"]
        request = json.dumps(validation_request, ensure_ascii=False).encode("utf-8")
        (stage / "validation.json").write_bytes(request)
        if validation_request.get("test_mode") == "node":
            validation = validate_in_sandbox(stage, runtime, node=True)
        elif before_run is not None:
            before_run()
            validation = validate_in_sandbox(stage, runtime, checkpoint=before_run)
        else:
            validation = validate_in_sandbox(stage, runtime)
        if (fingerprints(snapshot(stage / "snapshot", original)) != manifest["files"]
                or (patch is not None and (stage / "proposal.diff").read_bytes() != patch)
                or (stage / "validation.json").read_bytes() != request
                or any(file_hash(stage / "wheels" / wheel["filename"]) != wheel["sha256"] for wheel in wheels)):
            reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Les entrées de validation ont changé.")

    return validation, wheels


def reuse(project: Path, registry: Path, sample_id: str, category: str, output: Path, runtime: Path,
          *, dependencies=()) -> dict:
    project = project.resolve(strict=True)
    output = output.resolve()
    if output.is_relative_to(project):
        reject(ErrorCode.PERMISSION_DENIED, "Stocker le rapport de rejeu hors du projet.")
    sample = load_sample(project, registry, sample_id, category)
    current = check_current(project, sample.manifest)
    patch = (make_diff(sample.manifest["target"], current[sample.manifest["target"]], sample.payload)
             if category == "source_code" else sample.payload)
    if digest(patch) != sample.manifest["diff_sha256"]:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Le diff à rejouer diffère du diff d'origine.")

    def checkpoint():
        check_sample(project, registry, sample)

    run_id = register_replay(project, registry, sample, output)
    began = perf_counter()
    try:
        validation, _ = validate_copy(project, output, sample.manifest, current, patch, runtime, dependencies,
                                      before_run=checkpoint, replay=True)
    except ProjectError:
        finish_replay(project, registry, sample, run_id, None)
        raise
    result = {"status": "reused", "sample_id": sample_id, "category": category,
              "validation": validation, "wall_s": round(perf_counter() - began, 3)}
    if captured := capture_project_memory(project, registry, sample, validation=validation):
        result["memory"] = captured
    finish_replay(project, registry, sample, run_id, result)
    return result


@contextmanager
def project_lease(project_id: dict):
    import msvcrt

    key = digest(f"{project_id['device']}:{project_id['inode']}".encode("ascii"))
    lock = Path(gettempdir()) / f"akasha-project-{key}.lock"
    with lock.open("a+b") as stream:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            reject(ErrorCode.RESOURCE_BUDGET_EXCEEDED, "Une application est déjà en cours pour ce projet.")
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def check_current(project: Path, manifest: dict) -> dict:
    try:
        current = snapshot(project, manifest["files"]) if identity(project) == manifest["project"] else {}
        if manifest.get("operation") == "move":
            project_file(project, manifest["destination"], absent=True)
    except (OSError, ProjectError):
        current = {}
    if fingerprints(current) != manifest["files"]:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Le projet a changé. Préparer et approuver une nouvelle proposition.",
               reason="project_changed")
    return current


def require_operation_approval(manifest: dict, approved_delete: str | None,
                               approved_move: tuple[str, str] | None) -> None:
    operation = manifest.get("operation", "replace")
    target = manifest["target"]
    if operation == "replace":
        if approved_delete is not None or approved_move is not None:
            reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L'accord spécifique ne correspond pas à la proposition.")
        return
    destination = manifest.get("destination")
    approved = (approved_delete == target and approved_move is None if operation == "delete"
                else approved_move == (target, destination) and approved_delete is None)
    denied = authorize({"risk_class": "R3", "human_approval": approved})
    if denied:
        reject(denied.code, "Accord explicite requis pour cette opération.",
               risk_class="R3", operation=operation, source=target, destination=destination)


def apply_replacement(project: Path, proposal: Path, manifest: dict, original: bytes, before_effect) -> None:
    target = manifest["target"]
    patch = (proposal / "proposal.diff").read_bytes()
    candidate = (proposal / "replacement.txt").read_bytes()
    if digest(patch) != manifest["diff_sha256"] or digest(candidate) != manifest["replacement_sha256"]:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Les artefacts diffèrent de la proposition approuvée.",
               reason="proposal_changed")
    if make_diff(target, original, candidate) != patch:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Le contenu à appliquer diffère du diff approuvé.")
    destination = project_file(project, target)
    temporary = None
    try:
        with NamedTemporaryFile(dir=destination.parent, prefix=".akasha-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copymode(destination, temporary)
        before_effect()
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validated_manifest(encoded: bytes) -> dict:
    manifest = json.loads(encoded)
    target = manifest["target"]
    files = manifest["files"]
    version = manifest["version"]
    operation = manifest.get("operation", "replace")
    destination = manifest.get("destination")
    if (version not in (1, 2) or (version == 1 and operation != "replace")
            or operation not in ("replace", "delete", "move")
            or (operation == "move" and (not isinstance(destination, str)
                                         or destination.casefold() in {name.casefold() for name in files}))
            or manifest["validation"]["status"] != "passed"
            or manifest["validation"]["guest_exit_code"] != 0x4700
            or target not in files or manifest["test"] not in files or manifest["test"] == target):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Proposition non validée.")
    return manifest


def matches_application(project: Path, expected: dict, absent: list) -> bool:
    try:
        for name in absent:
            project_file(project, name, absent=True)
        return fingerprints(snapshot(project, expected)) == expected
    except (OSError, ProjectError):
        return False


def renew_approval(project: Path, proposal: Path) -> dict:
    project, proposal = project.resolve(strict=True), proposal.resolve(strict=True)
    if proposal.is_relative_to(project):
        reject(ErrorCode.PERMISSION_DENIED, "La proposition doit être stockée hors du projet.")
    path = proposal / "proposal.json"
    temporary = None
    with project_lease(identity(project)):
        manifest = validated_manifest(path.read_bytes())
        check_current(project, manifest)
        if application_state(proposal, action_key(manifest)) is not None:
            reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L'application a déjà commencé. Vérifiez l'état du projet.",
                   reason="application_in_doubt")
        request = manifest["approval"] = new_request()
        encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        try:
            with NamedTemporaryFile(dir=proposal, prefix="approval-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {"status": "awaiting_approval", "proposal": str(proposal), "approval_sha256": digest(encoded),
            "approval_expires_at": request["expires_at"]}


def apply(project: Path, proposal: Path, approved_digest: str | None = None, *,
          approved_delete: str | None = None, approved_move: tuple[str, str] | None = None) -> dict:
    project, proposal = project.resolve(strict=True), proposal.resolve(strict=True)
    if proposal.is_relative_to(project):
        reject(ErrorCode.PERMISSION_DENIED, "La proposition doit être stockée hors du projet.")
    try:
        return apply_approved(project, proposal, approved_digest, approved_delete, approved_move)
    except ProjectError as error:
        decision = "paused" if error.error.code == ErrorCode.APPROVAL_EXPIRED else "refused"
        risk = "R3" if error.error.details.get("risk_class") == "R3" else "R2"
        audit_decision(proposal, action="project_apply", risk=risk, actor="runtime", decision=decision,
                       reason=error.error.code.value)
        raise


def apply_approved(project: Path, proposal: Path, approved_digest: str | None,
                   approved_delete: str | None, approved_move: tuple[str, str] | None) -> dict:
    path = proposal / "proposal.json"
    encoded = path.read_bytes()
    proposal_digest = digest(encoded)
    denied = authorize({"risk_class": "R2", "human_approval": approved_digest == proposal_digest})
    if denied:
        raise ProjectError(denied)
    manifest = validated_manifest(encoded)
    operation = manifest.get("operation", "replace")
    target, destination = manifest["target"], manifest.get("destination")
    expires_at = approval_deadline(manifest, path)
    require_fresh(expires_at)
    require_operation_approval(manifest, approved_delete, approved_move)
    expected, absent = expected_files(manifest)
    key = action_key(manifest)
    risk = "R2" if operation == "replace" else "R3"
    result = {"status": "applied", "operation": operation, "file": target, "destination": destination,
              "proposal_sha256": proposal_digest}

    project_id = identity(project)
    with project_lease(project_id):
        if path.read_bytes() != encoded:
            reject(ErrorCode.APPROVAL_REQUIRED, "La demande d'approbation a changé.", risk_class="R2")
        if project_id != manifest["project"]:
            check_current(project, manifest)
        require_fresh(expires_at)
        state = application_state(proposal, key)
        if state is not None:
            if not matches_application(project, expected, absent):
                reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Le résultat de l'application doit être vérifié.",
                       reason="application_in_doubt" if state == "applying" else "project_changed_after_apply")
            if state == "applying":
                mark_application(proposal, key, "applied")
            return {**result, "replayed": True, "recovered": state == "applying"}

        current = check_current(project, manifest)

        def begin_effect():
            check_current(project, manifest)
            require_fresh(expires_at)
            audit_decision(proposal, action=operation, risk=risk, actor="human", decision="approved")
            mark_application(proposal, key, "applying")
            try:
                require_fresh(expires_at)
            except ProjectError:
                discard_unstarted_application(proposal, key)
                raise

        if operation == "replace":
            apply_replacement(project, proposal, manifest, current[target], begin_effect)
        elif operation == "delete":
            source = project_file(project, target)
            revision = manifest.get("delete_revision")
            if revision is None:
                revision = deletion_revision(source.stat(follow_symlinks=False))
            begin_effect()
            with ExitStack() as verified:
                try:
                    remove = verified.enter_context(verify_deletion(source, manifest["files"][target], revision))
                    companions = {name: checksum for name, checksum in manifest["files"].items() if name != target}
                    check_current(project, {**manifest, "files": companions})
                    if path.read_bytes() != encoded:
                        reject(ErrorCode.APPROVAL_REQUIRED, "La demande d'approbation a changé.", risk_class="R3")
                    require_fresh(expires_at)
                except ProjectError:
                    discard_unstarted_application(proposal, key)
                    raise
                except OSError:
                    discard_unstarted_application(proposal, key)
                    reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Impossible de vérifier la suppression.",
                           reason="transition_unverifiable", guard="transition", risk_class="R3")
                remove()
        else:
            source = project_file(project, target)
            target_path = project_file(project, destination, absent=True)
            begin_effect()
            # Sur Windows, rename échoue si la destination existe et préserve le fichier concurrent.
            source.rename(target_path)

        if not matches_application(project, expected, absent):
            reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Opération effectuée, état du projet à vérifier.",
                   reason="application_in_doubt")
        mark_application(proposal, key, "applied")
    return result


@dataclass(frozen=True)
class ProposalReview:
    """Lie le diff ou les chemins affichés à la proposition validée."""

    project: Path
    proposal: Path
    target: str
    test: str
    operation: str
    destination: str | None
    diff: str | None
    approval_sha256: str
    approval_expires_at: datetime

    def apply(self, approved: bool, *, approved_operation: bool = False) -> dict:
        delete = self.target if approved_operation and self.operation == "delete" else None
        move = None
        if approved_operation and self.operation == "move" and self.destination is not None:
            move = (self.target, self.destination)
        return apply(self.project, self.proposal, self.approval_sha256 if approved else None,
                     approved_delete=delete, approved_move=move)


def preview_proposal(project: Path, proposal: Path) -> ProposalReview:
    project, proposal = project.resolve(strict=True), proposal.resolve(strict=True)
    if proposal.is_relative_to(project):
        reject(ErrorCode.PERMISSION_DENIED, "La proposition doit être stockée hors du projet.")
    path = proposal / "proposal.json"
    encoded = path.read_bytes()
    manifest = validated_manifest(encoded)
    if identity(project) != manifest["project"]:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Cette proposition appartient à un autre projet.",
               reason="consent_scope_mismatch")
    operation = manifest.get("operation", "replace")
    diff = None
    if operation == "replace":
        patch = (proposal / "proposal.diff").read_bytes()
        if digest(patch) != manifest["diff_sha256"]:
            reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Le diff ne correspond pas à la proposition validée.",
                   reason="proposal_changed")
        diff = patch.decode("utf-8")
    return ProposalReview(project, proposal, manifest["target"], manifest["test"], operation,
                          manifest.get("destination"), diff, digest(encoded), approval_deadline(manifest, path))


def preview_replacement(project: Path, proposal: Path) -> ProposalReview:
    review = preview_proposal(project, proposal)
    if review.operation != "replace":
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Sélectionnez une proposition contenant un diff de remplacement.")
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspection = commands.add_parser("inspect-code", help="Lire ou chercher dans des fichiers projet sélectionnés")
    inspection.add_argument("--project", required=True, type=Path)
    inspection.add_argument("--file", required=True, action="append", help="Fichier relatif au projet, répétable pour la recherche")
    inspection.add_argument("--contains", help="Texte littéral à chercher, sans tenir compte de la casse")
    inspection.add_argument("--first-line", type=int, default=1)
    inspection.add_argument("--limit", type=int, default=80)
    preparation = commands.add_parser("prepare", help="Préparer et tester une opération dans Windows Sandbox")
    preparation.add_argument("--project", required=True, type=Path)
    preparation.add_argument("--output", required=True, type=Path)
    preparation.add_argument("--file", required=True, help="Fichier existant, relatif au projet")
    operation = preparation.add_mutually_exclusive_group(required=True)
    operation.add_argument("--replacement", type=Path, help="Fichier texte de remplacement")
    operation.add_argument("--delete", action="store_true", help="Préparer la suppression du fichier")
    operation.add_argument("--move-to", help="Préparer le déplacement vers ce chemin relatif")
    preparation.add_argument("--test", required=True, help="Script Python de test, relatif au projet")
    preparation.add_argument("--input", action="append", default=[], help="Autre fichier autorisé dans la copie")
    preparation.add_argument("--dependency", type=Path, action="append", default=[],
                             help="Dossier d'une demande déjà approuvée et téléchargée")
    preparation.add_argument("--python-runtime", required=True, type=Path)
    request = commands.add_parser("dependency-request", help="Présenter un téléchargement de wheel à approuver")
    request.add_argument("--project", required=True, type=Path)
    request.add_argument("--output", required=True, type=Path)
    request.add_argument("--name", required=True)
    request.add_argument("--version", required=True)
    request.add_argument("--url", required=True)
    request.add_argument("--sha256", required=True)
    request.add_argument("--license", required=True)
    fetch = commands.add_parser("dependency-download", help="Télécharger la wheel d'une demande approuvée")
    fetch.add_argument("--project", required=True, type=Path)
    fetch.add_argument("--request", required=True, type=Path)
    fetch.add_argument("--approve-download", help="Empreinte exacte de la demande après examen")
    capture = commands.add_parser("collect", help="Conserver un artefact validé pour l'évolution locale")
    capture.add_argument("--project", required=True, type=Path)
    capture.add_argument("--proposal", required=True, type=Path)
    capture.add_argument("--evolution-db", required=True, type=Path)
    capture.add_argument("--category", required=True, choices=ARTIFACTS)
    capture.add_argument("--consent")
    capture.add_argument("--reviewed-without-secrets", metavar="SHA256",
                         help="Empreinte de la proposition examinée et déclarée sans secrets")
    playback = commands.add_parser("reuse", help="Rejouer dans Windows Sandbox une copie d'évolution autorisée")
    playback.add_argument("--project", required=True, type=Path)
    playback.add_argument("--evolution-db", required=True, type=Path)
    playback.add_argument("--sample", required=True)
    playback.add_argument("--category", required=True, choices=ARTIFACTS)
    playback.add_argument("--output", required=True, type=Path)
    playback.add_argument("--python-runtime", required=True, type=Path)
    playback.add_argument("--dependency", type=Path, action="append", default=[])
    erasure = commands.add_parser("erase", help="Bloquer puis effacer une copie d'évolution et ses dérivés")
    erasure.add_argument("--project", required=True, type=Path)
    erasure.add_argument("--evolution-db", required=True, type=Path)
    erasure.add_argument("--sample", required=True)
    backup_grant = commands.add_parser("backup-grant", help="Accorder la sauvegarde locale de catégories précises")
    save = commands.add_parser("backup", help="Créer une sauvegarde locale chiffrée de l'évolution")
    restore_cmd = commands.add_parser("restore", help="Restaurer les copies admissibles depuis une sauvegarde")
    backup_revoke = commands.add_parser("backup-revoke", help="Révoquer un accord de sauvegarde")
    for action in (backup_grant, save, restore_cmd, backup_revoke):
        action.add_argument("--project", required=True, type=Path)
        action.add_argument("--evolution-db", required=True, type=Path)
    backup_grant.add_argument("--category", required=True, action="append", choices=ARTIFACTS)
    backup_grant.add_argument("--expires-at")
    save.add_argument("--output", required=True, type=Path)
    save.add_argument("--consent")
    restore_cmd.add_argument("--backup", required=True, type=Path)
    backup_revoke.add_argument("--consent", required=True)
    application = commands.add_parser("apply", help="Appliquer une proposition validée et approuvée")
    application.add_argument("--project", required=True, type=Path)
    application.add_argument("--proposal", required=True, type=Path)
    application.add_argument("--approve", help="Empreinte exacte de la proposition après examen")
    approval = application.add_mutually_exclusive_group()
    approval.add_argument("--approve-delete", metavar="SOURCE", help="Accord explicite pour supprimer cette source")
    approval.add_argument("--approve-move", nargs=2, metavar=("SOURCE", "DESTINATION"),
                          help="Accord explicite pour ce déplacement")
    renewal = commands.add_parser("renew-approval", help="Émettre une nouvelle demande pour une proposition intacte")
    renewal.add_argument("--project", required=True, type=Path)
    renewal.add_argument("--proposal", required=True, type=Path)
    audit = commands.add_parser("verify-audit", help="Vérifier la chaîne locale des décisions")
    audit.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "inspect-code":
            result = inspect_code(args.project, args.file, contains=args.contains, first_line=args.first_line, limit=args.limit)
        elif args.command == "prepare":
            result = prepare(args.project, args.output, args.file, args.replacement, args.test, args.python_runtime,
                             inputs=args.input, delete=args.delete, move_to=args.move_to, dependencies=args.dependency)
        elif args.command == "dependency-request":
            result = create_request(args.project, args.output, name=args.name, version=args.version,
                                    url=args.url, sha256=args.sha256, license=args.license)
        elif args.command == "dependency-download":
            result = download(args.project, args.request, args.approve_download)
        elif args.command == "collect":
            result = collect(args.project, args.proposal, args.evolution_db, args.category, args.consent,
                             args.reviewed_without_secrets)
        elif args.command == "reuse":
            result = reuse(args.project, args.evolution_db, args.sample, args.category, args.output,
                           args.python_runtime, dependencies=args.dependency)
        elif args.command == "erase":
            result = erase(args.project, args.evolution_db, args.sample)
        elif args.command == "backup-grant":
            result = grant_backup(args.project, args.evolution_db, args.category, args.expires_at)
        elif args.command == "backup":
            result = backup(args.project, args.evolution_db, args.output, args.consent)
        elif args.command == "restore":
            result = restore(args.project, args.evolution_db, args.backup)
        elif args.command == "backup-revoke":
            result = revoke_backup(args.project, args.evolution_db, args.consent)
        elif args.command == "renew-approval":
            result = renew_approval(args.project, args.proposal)
        elif args.command == "verify-audit":
            result = verify_audit(args.audit)
        else:
            result = apply(args.project, args.proposal, args.approve, approved_delete=args.approve_delete,
                           approved_move=tuple(args.approve_move) if args.approve_move is not None else None)
    except (ProjectError, PlanningError) as exc:
        status = "paused" if exc.error.code == ErrorCode.APPROVAL_EXPIRED else "refused"
        result = {"status": status, "error": exc.error.as_dict()}
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, sqlite3.Error, subprocess.SubprocessError) as exc:
        error = AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, str(exc))
        result = {"status": "failed", "error": error.as_dict()}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return int(result["status"] in {"refused", "failed", "pending", "paused"})


if __name__ == "__main__":
    raise SystemExit(main())
