"""Vérification locale d'un projet, avec exécution séparée dans le bac."""

import ast
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory, gettempdir
from time import perf_counter
import tomllib

from .project import CODE_FILE_LIMIT, fingerprints, project_file, project_input, snapshot, validate_copy
from .project_common import ProjectError

SOURCE_FILES_LIMIT = 128
SCAN_ENTRIES_LIMIT = 2048
SKIP_DIRECTORIES = {"node_modules", "venv", "__pycache__", "dist", "build", "vendor"}
NODE_SOURCE_FORMATS = {".js", ".cjs", ".mjs"}


@dataclass(frozen=True)
class ProjectTest:
    mode: str
    target: str
    files: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"unittest dans {self.target}" if self.mode == "unittest" else self.target


@dataclass(frozen=True)
class ProjectCheck:
    project: Path
    checks: tuple[str, ...]
    issues: tuple[str, ...]
    python_hashes: dict
    test: ProjectTest | None
    node_hashes: dict
    test_blocker: str | None = None

    @property
    def test_hashes(self) -> dict:
        return self.node_hashes if self.test and self.test.mode == "node" else self.python_hashes

    def summary(self) -> str:
        lines = [f"Vérification statique de {self.project.name}", *self.checks]
        if self.issues:
            lines.extend(f"• {issue}" for issue in self.issues[:8])
            if len(self.issues) > 8:
                lines.append(f"{len(self.issues) - 8} autres fichiers signalés.")
        if not self.checks and not self.issues:
            lines.append("Je n’ai trouvé ni sources Python ni manifeste Python ou npm dans ce dossier.")
        lines.append("Tests non exécutés.")
        if self.test_blocker:
            lines.append(self.test_blocker)
        if self.test is not None:
            lines.append(f"Je peux lancer {self.test.label} sur une copie de {len(self.test_hashes)} fichiers "
                         "dans Windows Sandbox, hors ligne.")
        elif not self.test_blocker and not self.issues:
            lines.append("Aucun test compatible avec le bac n’a été repéré.")
        return "\n".join(lines)


def ordinary_directory(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT


def project_sources(project: Path, extensions: set[str]):
    pending = [project]
    seen = 0
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                seen += 1
                if seen > SCAN_ENTRIES_LIMIT:
                    raise ValueError("L’examen s’arrête après 2 048 entrées. Choisissez un sous-dossier pour le poursuivre.")
                name = entry.name.casefold()
                if name.startswith(".") or name in SKIP_DIRECTORIES:
                    continue
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path))
                elif (stat.S_ISREG(info.st_mode) and Path(name).suffix in extensions
                      and name != "package-lock.json"):
                    yield Path(entry.path).relative_to(project).as_posix()


def inspect_project(project: Path) -> ProjectCheck:
    project = project.resolve(strict=True)
    if not project.is_dir():
        raise ValueError("Choisissez un dossier de projet.")
    checks, issues = [], []
    node_manifest = None
    test_blocker = None
    for name, parse in (("pyproject.toml", tomllib.loads), ("package.json", json.loads)):
        try:
            content = project_input(project_file(project, name), byte_limit=CODE_FILE_LIMIT)
            manifest = parse(content.decode("utf-8-sig"))
            if not isinstance(manifest, dict):
                raise ValueError("Un objet de configuration est attendu.")
            if name == "package.json":
                scripts = manifest.get("scripts", {})
                if not isinstance(scripts, dict) or any(not isinstance(value, str) for value in scripts.values()):
                    raise ValueError("La section scripts doit associer des noms à des commandes texte.")
                if scripts.get("test"):
                    checks.append("Un script npm test est déclaré.")
                    if scripts["test"].strip() == "node --test":
                        node_manifest = content
                    else:
                        test_blocker = "Le script npm déclaré utilise un autre lanceur. Le bac prend en charge node --test."
            checks.append(f"{name} est lisible.")
        except FileNotFoundError:
            continue
        except (OSError, ValueError, ProjectError) as error:
            # Les erreurs de parsing peuvent inclure du texte du projet.
            detail = f" à la ligne {error.lineno}" if getattr(error, "lineno", None) else ""
            issues.append(f"{name} contient une erreur ou ne peut pas être lu{detail}.")

    sources, node_sources = {}, {}
    unittest_locations = set()
    syntax_checked = total_bytes = 0
    try:
        extensions = {".py"} | (NODE_SOURCE_FORMATS | {".json"} if node_manifest is not None else set())
        for name in project_sources(project, extensions):
            if len(sources) + len(node_sources) >= SOURCE_FILES_LIMIT:
                raise ValueError("La fenêtre d’analyse est pleine. Choisissez un sous-dossier pour la compléter.")
            try:
                content = project_input(project_file(project, name), byte_limit=CODE_FILE_LIMIT)
            except (OSError, ProjectError):
                issues.append(f"{name} n’a pas pu être examiné.")
                continue
            total_bytes += len(content)
            if total_bytes > 4 * 1024**2:
                raise ValueError("La fenêtre d’analyse dépasse 4 Mio. Choisissez un sous-dossier.")
            if Path(name).suffix.casefold() != ".py":
                node_sources[name] = content
                continue
            sources[name] = content
            try:
                tree = ast.parse(content, filename=name)
                compile(tree, name, "exec", dont_inherit=True)
            except (SyntaxError, ValueError, RecursionError) as error:
                row = f", ligne {error.lineno}" if getattr(error, "lineno", None) else ""
                issues.append(f"Syntaxe Python invalide dans {name}{row}.")
                continue
            syntax_checked += 1
            path = Path(name)
            if path.match("test*.py") and any(
                isinstance(node, ast.Import) and any(alias.name == "unittest" for alias in node.names)
                or isinstance(node, ast.ImportFrom) and node.module == "unittest"
                for node in tree.body
            ):
                if len(path.parts) == 1:
                    unittest_locations.add(".")
                elif path.parts[0] == "tests":
                    unittest_locations.add("tests")
    except ValueError as error:
        issues.append(str(error))
    if sources:
        if len(sources) == 1:
            checks.append(f"Syntaxe Python valide dans {syntax_checked} fichier sur 1 examiné.")
        else:
            checks.append(f"Syntaxe Python valide dans {syntax_checked} fichiers sur {len(sources)} examinés.")
    if any(name.startswith("tests/") or Path(name).match("test*.py") for name in sources):
        checks.append("Des fichiers de test Python ont été repérés.")

    test = None
    if not issues:
        node_tests = tuple(sorted(name for name in node_sources if node_test_path(Path(name))))
        if node_tests:
            if node_manifest != node_sources.get("package.json"):
                raise ValueError("Le manifeste npm a changé. Demandez une nouvelle vérification.")
            checks.append(f"{len(node_tests)} fichier(s) de test Node.js natif(s) repéré(s).")
            test = ProjectTest("node", "node --test", node_tests)
        elif unittest_locations:
            test = ProjectTest("unittest", "tests" if "tests" in unittest_locations else ".")
        else:
            script = next((name for name in ("check.py", "verify.py") if name in sources), None)
            if script:
                test = ProjectTest("script", script)
    return ProjectCheck(project, tuple(checks), tuple(issues), fingerprints(sources), test,
                        fingerprints(node_sources), test_blocker)


def node_test_path(path: Path) -> bool:
    return path.suffix in NODE_SOURCE_FORMATS and (
        any(part in {"test", "tests"} for part in path.parts[:-1]) or path.stem == "test"
        or path.stem.startswith("test-") or path.stem.endswith((".test", "-test", "_test"))
    )


def installed_node(project: Path) -> Path | None:
    for entry in os.get_exec_path():
        directory = Path(entry.strip('"'))
        if directory.is_absolute() and (node := directory / "node.exe").is_file():
            candidate = node.resolve()
            if not candidate.is_relative_to(project):
                return candidate
    return None


def run_project_check(check: ProjectCheck, runtime: Path) -> dict:
    began = perf_counter()
    if check.test is None:
        raise ValueError("Aucun test compatible trouvé.")
    if check.project.resolve(strict=True) != check.project:
        raise ValueError("Le dossier du projet a changé. Demandez une nouvelle vérification.")
    source = snapshot(check.project, check.test_hashes, byte_limit=CODE_FILE_LIMIT)
    if fingerprints(source) != check.test_hashes:
        raise ValueError("Les sources ont changé depuis l’examen. Demandez une nouvelle vérification.")
    scratch = Path(gettempdir()).resolve()
    if scratch.is_relative_to(check.project):
        raise ValueError("Choisissez un dossier de projet distinct du dossier temporaire Windows.")
    with TemporaryDirectory(prefix="akasha-check-", dir=scratch) as output:
        manifest = {"operation": "check", "test": check.test.target,
                    "test_mode": check.test.mode, "test_files": check.test.files, "files": check.test_hashes}
        try:
            verdict, _ = validate_copy(check.project, Path(output), manifest, source, None, runtime, ())
        except ProjectError as error:
            code = error.error.details.get("guest_exit_code")
            messages = {0x4714: "Le test a échoué dans Windows Sandbox.",
                        0x4715: "Le test a modifié des sources dans le bac. Leur intégrité n’a pas été validée.",
                        0x4719: "Aucun test exécutable n’a été trouvé."}
            if code not in messages:
                raise
            verdict = {"status": "failed", "message": messages[code], "guest_exit_code": code,
                       "sandbox_stopped": True}
        except subprocess.TimeoutExpired:
            raise RuntimeError("Le délai de Windows Sandbox a expiré.") from None
    return {**verdict, "test": check.test.label, "project": str(check.project),
            "wall_s": round(perf_counter() - began, 3)}
