"""Repères d'exécution dans les sources JS/TS, sans importer le projet."""

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from posixpath import normpath
import re

from pygments.lexers import JavascriptLexer, JsxLexer, TsxLexer, TypeScriptLexer
from pygments.token import Comment, String

from .project import CODE_FILE_LIMIT, project_file, project_input
from .project_check import ordinary_directory, project_sources
from .project_common import ProjectError

LEXERS = {".ts": TypeScriptLexer, ".tsx": TsxLexer, ".js": JavascriptLexer, ".jsx": JsxLexer,
          ".mjs": JavascriptLexer, ".cjs": JavascriptLexer, ".mts": TypeScriptLexer, ".cts": TypeScriptLexer}
WORD = r"[A-Za-z_$][\w$]*"
IMPORT = re.compile(r"^[ \t]*import\s+(?!type\b)([\w${}*,\s]+?)\s+from\s+['\"]([^'\"\r\n]+)['\"]", re.M)
FUNCTION = re.compile(rf"^[ \t]*(?:(export\s+(?:default\s+)?))?(?:async\s+)?function\s+({WORD})\b", re.M)
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
WRAPPED = re.compile(rf"^\s*export\s+const\s+({'|'.join(METHODS)})\s*=\s*({WORD})\s*\(\s*({WORD})\b", re.M)
CALL = re.compile(rf"(?<![\w$.])({WORD})\s*\(")
JSX = re.compile(r"<([A-Z][\w$]*)\b")
FILE_LIMIT = 72


@dataclass(frozen=True)
class Routine:
    name: str
    line: int
    export: str
    body: str
    original: str
    calls: tuple[str, ...]
    components: tuple[str, ...]


@dataclass(frozen=True)
class Module:
    name: str
    imports: dict[str, tuple[str, str]]
    routines: dict[str, Routine]
    methods: dict[str, tuple[str, Routine]]


def read_text(project: Path, name: str) -> str:
    return project_input(project_file(project, name), byte_limit=CODE_FILE_LIMIT).decode("utf-8-sig")


def mask_literals(source: str, lexer) -> str:
    chunks = []
    for _, kind, value in lexer().get_tokens_unprocessed(source):
        chunks.append(re.sub(r"[^\r\n]", " ", value) if kind in Comment or kind in String else value)
    return "".join(chunks)


def closing(code: str, start: int, left: str, right: str) -> int:
    depth = 0
    for cursor in range(start, len(code)):
        if code[cursor] == left:
            depth += 1
        elif code[cursor] == right:
            depth -= 1
            if depth == 0:
                return cursor
    return -1


def module_imports(source: str, code: str) -> dict[str, tuple[str, str]]:
    imports = {}
    for match in IMPORT.finditer(source):
        if not code[match.start():match.end()].lstrip().startswith("import"):
            continue
        clause, specifier = match.groups()
        default, _, named = clause.partition("{")
        default = default.strip(" ,\r\n\t")
        if re.fullmatch(WORD, default):
            imports[default] = (specifier, "default")
        for entry in named.rstrip("} \r\n\t").split(","):
            if binding := re.fullmatch(rf"\s*({WORD})(?:\s+as\s+({WORD}))?\s*", entry):
                imports[binding[2] or binding[1]] = (specifier, binding[1])
    return imports


def parse_module(name: str, source: str) -> Module:
    code = mask_literals(source, LEXERS[PurePosixPath(name).suffix.lower()])
    imports = module_imports(source, code)
    functions = list(FUNCTION.finditer(code))
    symbols = imports.keys() | {match[2] for match in functions}
    routines = {}
    for index, match in enumerate(functions):
        limit = functions[index + 1].start() if index + 1 < len(functions) else len(code)
        params = code.find("(", match.end(), limit)
        params_end = closing(code, params, "(", ")") if params != -1 else -1
        if params_end == -1 or params_end >= limit:
            continue
        start = code.find("{", params_end + 1, limit)
        if start == -1 or re.search(r"[;=]", code[params_end + 1:start]):
            continue
        suffix = code[params_end + 1:start].strip()
        if suffix and (not suffix.startswith(":") or suffix == ":" or suffix.count("<") != suffix.count(">")):
            continue
        end = closing(code, start, "{", "}")
        if end == -1 or end >= limit:
            continue
        body = code[start + 1:end]
        calls = tuple(dict.fromkeys(called for called in CALL.findall(body) if called in symbols))
        components = tuple(dict.fromkeys(tag for tag in JSX.findall(body) if tag in symbols))
        routines[match[2]] = Routine(match[2], code.count("\n", 0, match.start()) + 1, match[1] or "", body,
                                      source[start + 1:end], calls, components)
    methods = {method: ("", routines[method]) for method in METHODS if method in routines and routines[method].export}
    methods.update({method: (wrapper, routines[handler]) for method, wrapper, handler in WRAPPED.findall(code)
                    if handler in routines})
    return Module(name, imports, routines, methods)


def source_names(project: Path) -> set[str]:
    names = {f"{stem}{suffix}" for stem in ("index", "main", "app", "server") for suffix in LEXERS
             if (project / f"{stem}{suffix}").is_file()}
    for directory in ("src", "app", "pages", "server", "lib", "backend"):
        root = project / directory
        if ordinary_directory(root):
            try:
                names.update(f"{directory}/{name}" for name in project_sources(root, set(LEXERS))
                             if not name.endswith(".d.ts"))
            except (OSError, ValueError):
                continue
    return names


class Sources:
    def __init__(self, project: Path):
        self.project = project
        self.names = source_names(project)
        self.modules: dict[str, Module | None] = {}
        try:
            options = json.loads(read_text(project, "tsconfig.json")).get("compilerOptions", {})
            self.paths = options.get("paths", {})
            self.base = options.get("baseUrl", ".")
        except (OSError, ValueError, AttributeError, ProjectError):
            self.paths, self.base = {}, "."

    def load(self, name: str) -> Module | None:
        if name not in self.modules and len(self.modules) < FILE_LIMIT:
            try:
                self.modules[name] = parse_module(name, read_text(self.project, name))
            except (OSError, ValueError, ProjectError):
                self.modules[name] = None
        return self.modules.get(name)

    def symbol(self, module: Module, symbol: str) -> tuple[Module, Routine] | None:
        if symbol in module.routines:
            return module, module.routines[symbol]
        if symbol not in module.imports:
            return None
        specifier, original = module.imports[symbol]
        paths = []
        if specifier.startswith("."):
            paths.append(normpath(str(PurePosixPath(module.name).parent / specifier)))
        elif isinstance(self.paths, dict) and isinstance(self.base, str):
            for key, values in self.paths.items():
                if key.endswith("*") and specifier.startswith(key[:-1]) and isinstance(values, list):
                    for value in values:
                        if isinstance(value, str):
                            paths.append(normpath(str(PurePosixPath(self.base) / value.replace("*", specifier[len(key)-1:]))))
        for path in paths:
            candidates = [path, *(path + suffix for suffix in LEXERS), *(path + "/index" + suffix for suffix in LEXERS)]
            for candidate in candidates:
                if candidate not in self.names:
                    continue
                if target := self.load(candidate):
                    definition = target.routines.get(original)
                    if original == "default":
                        definition = next((routine for routine in target.routines.values() if "default" in routine.export), None)
                    if definition:
                        return target, definition
        return None


def app_path(module: Module) -> str:
    parts = PurePosixPath(module.name).parts
    parts = parts[2:-1] if parts[0] == "src" else parts[1:-1]
    return "/" + "/".join(part for part in parts if not part.startswith("("))


def observed(module: Module, routine: Routine, *, head: str = "", wrapper: str = "") -> str:
    label = f"{head} · " if head else ""
    label += f"{wrapper} enveloppe {routine.name}" if wrapper else routine.name
    calls = ", ".join(symbol + "()" for symbol in routine.calls[:8])
    details = [f"Appels repérés à {calls}."] if calls else []
    if routine.components:
        details.append("Composants rendus dans ce bloc · " + ", ".join(routine.components[:5]) + ".")
    if "canAccessSpace" in routine.calls and re.search(r"\.filter\s*\([^;]*\bcanAccessSpace\s*\(", routine.body):
        details.append("Filtre les espaces avec canAccessSpace().")
    if ("notFound" in routine.calls and module.imports.get("notFound", (None,))[0] == "next/navigation"
            and re.search(r"\bif\s*\(\s*!\w+\??\.publishedSnapshot\s*\)\s*notFound\s*\(", routine.body)):
        details.append("Renvoie une page introuvable quand l’instantané publié manque.")
    if re.search(r"\bsearchDocuments\s*\([^,]+,\s*\{[^}]*\ballowedSpaceIds\s*:", routine.body):
        details.append("Transmet à la recherche les espaces autorisés via allowedSpaceIds.")
    if re.search(r"\bif\s*\(\s*mutation\s*\)\s*checkOrigin\s*\(", routine.body):
        details.append("Contrôle l’origine des requêtes de modification.")
    if statuses := sorted(set(re.findall(r"\bstatus\s*:\s*([1-5][0-9]{2})\b", routine.body))):
        details.append("Statuts HTTP présents · " + ", ".join(statuses) + ".")
    if re.search(r"\.publishedSnapshot\s*=\s*\{", routine.body):
        details.append("Construit et affecte un instantané de publication.")
    if re.search(r"\.transaction\s*\(", routine.body):
        details.append("Utilise une transaction.")
    if re.search(r"\bencrypt\s*\(\s*JSON\.stringify\s*\(", routine.body):
        details.append("Sérialise les données en JSON et les transmet à encrypt().")
    description = " ".join([label + ".", *details])
    return f"• {description} [{module.name}:{routine.line}]"


def explain_project_code(project: Path) -> list[str]:
    sources = Sources(project)
    pages, routes = [], []
    entry_names = sorted(name for name in sources.names if name.startswith(("app/", "src/app/"))
                         and PurePosixPath(name).stem in {"page", "route"})
    for name in entry_names[:FILE_LIMIT - 12]:
        if not (module := sources.load(name)):
            continue
        if PurePosixPath(name).stem == "page":
            pages.extend((module, routine) for routine in module.routines.values()
                         if "default" in routine.export and (routine.calls or routine.components))
        else:
            routes.extend((module, method, wrapper, routine) for method, (wrapper, routine) in module.methods.items()
                          if routine.calls)

    pages.sort(key=lambda item: -(len(item[1].calls) + len(item[1].components)))
    lines = [observed(module, routine, head=f"Page {app_path(module)}")
             for module, routine in sorted(pages[:2], key=lambda row: row[0].name)]
    selected = []
    for prefix in ("create", "search", "publish", "authenticate"):
        candidates = [row for row in routes if any(call.lower().startswith(prefix) for call in row[3].calls)]
        listings = []
        if prefix == "create":
            listings = [row for row in candidates if row[1] == "POST" and "GET" in row[0].methods
                        and any(call.lower().startswith("list") for call in row[0].methods["GET"][1].calls)]
        if listings:
            candidates = listings
        if candidates:
            entry = min(candidates, key=lambda row: (len(PurePosixPath(row[0].name).parts), row[0].name))
            if prefix == "create" and entry in listings:
                selected.append((entry[0], "GET", *entry[0].methods["GET"]))
            if entry not in selected:
                selected.append(entry)
    for module, method, wrapper, routine in selected or routes[:3]:
        lines.append(observed(module, routine, head=f"{method} {app_path(module)}", wrapper=wrapper))

    wrapper = next((resolved for module, _, name, _ in selected or routes[:3]
                    if name and (resolved := sources.symbol(module, name))), None)
    if wrapper:
        lines.append(observed(*wrapper, head="Traitement commun des routes"))
    action = next((resolved for module, _, _, routine in selected
                   for call in routine.calls if call.lower().startswith("publish") and (resolved := sources.symbol(module, call))), None)
    if action:
        lines.append(observed(*action, head="Mise à disposition du contenu"))
        persisted = next((resolved for call in action[1].calls if call.lower().startswith(("persist", "save"))
                          and (resolved := sources.symbol(action[0], call))), None)
        if persisted:
            lines.append(observed(*persisted, head="Écriture"))
            for call in persisted[1].calls:
                if not (resolved := sources.symbol(persisted[0], call)):
                    continue
                origin, implementation = resolved
                if any(specifier in {"better-sqlite3", "node:sqlite", "sqlite3"}
                       and binding in implementation.calls for binding, (specifier, _) in origin.imports.items()):
                    lines.append(f"• {implementation.name} utilise le pilote SQLite [{origin.name}:{implementation.line}].")
                if origin.imports.get("createCipheriv", (None,))[0] in {"node:crypto", "crypto"}:
                    for cipher in re.finditer(r"\bcreateCipheriv\(\s*['\"](aes-[0-9]+-gcm)['\"]", implementation.original):
                        if implementation.body[cipher.start():].startswith("createCipheriv("):
                            lines.append(f"• {implementation.name} chiffre avec {cipher[1]} [{origin.name}:{implementation.line}].")
                            break

    if not lines:
        for name in sorted(sources.names, key=lambda name: (name.count("/"), name)):
            if module := sources.load(name):
                lines.extend(observed(module, routine) for routine in module.routines.values()
                             if routine.export and routine.calls)
            if len(lines) >= 3 or len(sources.modules) >= FILE_LIMIT:
                break
        lines = lines[:3]
    if lines:
        files = sum(module is not None for module in sources.modules.values())
        lines.append(f"Analyse statique d’une sélection de {files} fichiers JavaScript ou TypeScript.")
    return lines
