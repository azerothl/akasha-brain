"""Présentation en lecture seule à partir des sources déclaratives du dépôt."""

import json
from pathlib import Path
import re
import tomllib

from .project import CODE_FILE_LIMIT, project_file, project_input
from .project_check import ordinary_directory, project_sources
from .project_code_summary import explain_project_code
from .project_common import ProjectError

MANIFESTS = (
    ("package.json", "JavaScript ou TypeScript", json.loads, None),
    ("pyproject.toml", "Python", tomllib.loads, "project"),
    ("Cargo.toml", "Rust", tomllib.loads, "package"),
)
README_FILES = ("README.md", "README.rst", "README.txt", "README")
DOC_FORMATS = {".md", ".rst", ".txt"}
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
TOPICS = re.compile(r"architecture|fonctionnalit|features|workflow|donn[ée]es|storage|security|s[ée]curit|usage|tests?", re.I)
DETAIL = re.compile(r"\b(?:plus\s+(?:complet(?:e)?|d[ée]taill[ée]e?|de\s+d[ée]tails?)|d[ée]taill[ée]e?|"
                    r"d[ée]taille[rz]?|approfondi(?:s|r|e)?|d[ée]veloppe[rz]?)\b", re.I)


def wants_detailed_summary(request: str) -> bool:
    return DETAIL.search(request) is not None


def project_text(project: Path, name: str) -> str | None:
    try:
        return project_input(project_file(project, name), byte_limit=CODE_FILE_LIMIT).decode("utf-8-sig")
    except (OSError, ValueError, ProjectError):
        return None


def prose(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<!--.*?(?:-->|\Z)|```.*?(?:```|\Z)", "", text, flags=re.DOTALL)
    return re.sub(r"\[!\[[^\]\r\n]*\]\([^\r\n]*?\)\]\([^\r\n]*?\)|!\[[^\]\r\n]*\]\([^\r\n]*?\)", "", text)


def paragraphs(text: str, *, detailed: bool = False):
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if detailed and len(lines) >= 3 and lines[0].startswith("|") and re.fullmatch(r"[|:\s-]+", lines[1]):
            rows = [" · ".join(cell.strip() for cell in line.strip("|").split("|"))
                    for line in lines[2:4] if line.startswith("|")]
            if rows:
                yield shorten(" / ".join(rows), 520)
        paragraph = " ".join(line for line in lines if not line.startswith(("#", "..", ">", "<", "|", "[", "$")))
        paragraph = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", paragraph)
        words = len(paragraph.split())
        if words >= 7 or (words >= 3 and (paragraph.endswith((".", "!", "?"))
                                         or (detailed and paragraph.startswith(("- ", "* "))))):
            yield shorten(paragraph, 520)


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def additional_documents(project: Path):
    names = ["ARCHITECTURE.md", "FEATURES.md", "SECURITY.md"]
    for directory in ("docs", "doc"):
        root = project / directory
        if not ordinary_directory(root):
            continue
        found = []
        try:
            for name in project_sources(root, DOC_FORMATS):
                found.append(f"{directory}/{name}")
        except (OSError, ValueError):
            pass
        names.extend(sorted(found, key=lambda name: (not TOPICS.search(Path(name).stem), name.casefold()))[:6])
    for name in names:
        if text := project_text(project, name):
            yield name, prose(text)


def document_highlights(text: str, used: set[str], *, limit: int):
    chunks = HEADING.split(text)
    sections = list(zip(chunks[1::2], chunks[2::2]))
    sections.sort(key=lambda entry: not TOPICS.search(entry[0]))
    found = 0
    for title, body in sections or [("", text)]:
        for paragraph in paragraphs(body, detailed=True):
            if paragraph in used:
                continue
            used.add(paragraph)
            yield title, shorten(paragraph, 340)
            found += 1
            break
        if found >= limit:
            return


def add_document_details(lines: list[str], project: Path, readme: tuple[str, str] | None, description: str) -> None:
    evidence = []
    used = {description}
    if readme is not None:
        name, text = readme
        evidence.extend((name, title, detail) for title, detail in document_highlights(text, used, limit=4))
    for name, text in additional_documents(project):
        evidence.extend((name, title, detail) for title, detail in document_highlights(text, used, limit=1))
        if len(evidence) >= 7:
            break
    if evidence:
        lines.append("\nFonctionnalités et conception documentées")
        for name, title, detail in evidence:
            source = f"{name} · {shorten(title, 100)}" if title else name
            lines.append(f"• {detail} [{source}]")
    else:
        lines.append("Les documents consultés fournissent peu de détails supplémentaires.")
    directories = [name + "/" for name in ("app", "src", "packages", "components", "server", "docs", "tests", "scripts")
                   if ordinary_directory(project / name)]
    if directories:
        lines.append("\nDossiers présents · " + ", ".join(directories))


def summarize_project(project: Path, *, detailed: bool = False) -> str:
    lines = [f"Résumé {'détaillé ' if detailed else ''}du projet {project.name}"]
    description = ""
    readme_source = None
    for name in README_FILES:
        if readme := project_text(project, name):
            cleaned = prose(readme)
            readme_source = readme_source or (name, cleaned)
            if description := next(paragraphs(cleaned), ""):
                readme_source = name, cleaned
                lines.append(f"Présentation d’après {name}\n{description}")
                break

    for name, stack, parse, section in MANIFESTS:
        text = project_text(project, name)
        if text is None:
            continue
        try:
            manifest = parse(text)
        except ValueError:
            continue
        if not isinstance(manifest, dict):
            continue
        metadata = manifest.get(section, {}) if section else manifest
        lines.append(f"Technologie déclarée dans {name} · {stack}")
        if not isinstance(metadata, dict):
            continue
        if not description and isinstance(metadata.get("description"), str) and metadata["description"].strip():
            description = " ".join(metadata["description"].split())[:520]
            lines.append(f"Présentation d’après {name}\n{description}")
        dependencies = metadata.get("dependencies")
        if isinstance(dependencies, dict) and dependencies:
            names = [key for key in dependencies if re.fullmatch(r"[@\w./-]{1,80}", key)]
            if names:
                if detailed:
                    families = {library.split("/")[0] for library in names if library.startswith("@")}
                    names = sorted(library for library in names if not library.startswith("@")) + sorted(families)
                lines.append("Bibliothèques déclarées · " + ", ".join(names[:10 if detailed else 6]))
        scripts = metadata.get("scripts")
        if detailed and isinstance(scripts, dict):
            declared = [key for key in scripts if re.fullmatch(r"[\w:-]{1,40}", key)]
            if declared:
                lines.append(f"Scripts déclarés dans {name} · " + ", ".join(declared[:10]))

    if not description:
        lines.append("La documentation et les manifestes consultés ne décrivent pas le rôle de ce projet.")
    if detailed:
        code = explain_project_code(project)
        if code:
            lines.extend(("\nParcours observés dans le code", *code))
        add_document_details(lines, project, readme_source, description)
    return "\n".join(lines)
