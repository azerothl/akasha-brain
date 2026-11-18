"""De la demande en langue naturelle à un appel vérifié du registre local."""

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from difflib import unified_diff
from functools import lru_cache, partial
import json
from pathlib import Path, PureWindowsPath
import re
from tempfile import TemporaryDirectory
from uuid import uuid4

from contracts.akasha_contracts.authz import authorize
from contracts.akasha_contracts.errors import AkashaError, ErrorCode
from contracts.akasha_contracts.validate import validate

from . import image_assets, image_orientation, image_recovery, meeting_minutes, whisper_pilot
from .capability_recovery import Recovery
from .gap_resolution import (
    READ_COMPARE_SKILL, TRANSCRIPTION, compare_intent, decode_with_utf16_bom, diagnose,
    mask_references, read_compare_steps, replay_comparison, transcription_context,
)
from .ocr_recovery import CAPABILITY as OCR_CAPABILITY, IMAGE_TYPES, MANIFEST as OCR_MANIFEST
from .planning import PlanningError
from .project import CODE_FILE_LIMIT, checked_input, inspect_code, project_file, project_input
from .project_check import ProjectCheck, inspect_project
from .project_common import ProjectError
from .project_summary import summarize_project, wants_detailed_summary
from .rbitnet_session import server
from .specialist_registry import require_specialist

REGISTRY = Path(__file__).with_name("conversation_capabilities.json")
DOCUMENT_FORMATS = {".md", ".txt", ".rst", ".csv", ".tsv"}
REFERENCE = re.compile(
    r'`([^`\r\n]+)`|"([^"\r\n]+)"|«\s*([^»\r\n]+?)\s*»'
    r'|(?<!\w)([A-Za-z]:[\\/][^\s?"<>|;]+)'
    r'|(?<!\w)([^\s:;(),!?"«»`<>]+\.[a-zA-Z0-9]{1,8})\b'
)
PROJECT_TOOLS = ("project.inspect", "project.summarize")
DRIVE_PATH = re.compile(r"^[a-zA-Z]:[\\/]")
INTENT_BOUNDARY = re.compile(
    r"\s+(?:(?:puis|ensuite)\s+|et\s+(?=(?:fais|faites|donne|donnez|résume|resume|vérifie|verifie|présente|compare|"
    r"explique|indique|dis|lance|affiche|envoie|lis|extrais|transcris|génère|genere|crée)\b))", re.IGNORECASE,
)
PROJECT_CHECK_STEP = re.compile(
    r"^(?:(?:tu peux|peux-tu|pouvez-vous)\s+)?(?:v[ée]rifie[rz]?|examine[rz]?|contr[ôo]le[rz]?)\s+"
    r"(?:si\s+)?(?:(?:le|ce|mon|son|ses|les)\s+)?(?:projet|d[ée]p[ôo]t|dossier|tests)\b", re.IGNORECASE,
)
PROJECT_SUMMARY_STEP = re.compile(r"\b(?:r[ée]sum[ée]|r[ée]sume|[àa]\s+quoi\s+sert)\b", re.IGNORECASE)
PROJECT_CONTEXT = re.compile(r"\b(?:projet|d[ée]p[ôo]t|dossier|celui[- ]ci)\b", re.IGNORECASE)
SHORT_REFINEMENT = re.compile(r"(?:plus (?:complet|d[ée]taill[ée]|de d[ée]tails)|d[ée]veloppe|approfondis)[?!.\s]*", re.I)
SUMMARY_REFINEMENT = re.compile(
    r"(?:(?:fais|donne)(?:[- ]moi)?\s+|(?:peux-tu|pouvez-vous)\s+(?:me\s+)?(?:faire|donner)\s+)?"
    r"(?:un\s+)?r[ée]sum[ée]\s+(?:plus\s+(?:complet|d[ée]taill[ée])|d[ée]taill[ée])[?!.\s]*", re.I,
)
OCR_REQUEST = re.compile(
    r"^(?:(?:(?:est[- ]ce que\s+)?(?:tu peux|vous pouvez)|peux-tu|pouvez-vous|pourrais-tu)\s+(?:me\s+)?)?"
    r"(?:(?:lis|lire|extrais|extraire|transcris|transcrire)\s+(?:le\s+)?texte\b"
    r"|(?P<ocr>(?:fais|faire)\s+(?:l[’']|un\s+)ocr\b))", re.I,
)
IMAGE_REQUEST = re.compile(
    r"^(?:(?:(?:est[- ]ce que\s+)?(?:tu peux|vous pouvez)|peux-tu|pouvez-vous|pourrais-tu)\s+(?:me\s+)?)?"
    r"(?:g[ée]n[èée]r(?:e|er)|cr[ée](?:e|er))(?:[- ]moi)?\s+(?:une |l[’'])image\b", re.I,
)
SYSTEM = """Construis le plan qui répond à toute la demande. Réponds uniquement par un tableau JSON ordonné, une entrée par résultat demandé, même pour une seule action. Chaque entrée comprend tool (identifiant exact), refs (liste d'indices entiers des chemins utilisés, dans l'ordre) et detail (chaîne vide). Reprends la même référence dans chaque étape qui vise ce dossier. refs est vide pour le dossier sélectionné sans référence explicite.
project.inspect vérifie la configuration et recense les tests. project.summarize explique à quoi sert le dépôt et de quoi il se compose. Si l'utilisateur demande les deux, produis les deux étapes.
Le registre est complet. Pour chaque action finale non couverte, produis tool=missing et indique dans detail l'outil absent, même si des paramètres manquent. Conserve les autres actions demandées. Utilise clarify et une question dans detail si une action disponible manque d'une précision.
Exemples
« Fais le bilan des tests de mon dépôt, puis présente son rôle » donne [{"tool":"project.inspect","refs":[],"detail":""},{"tool":"project.summarize","refs":[],"detail":""}].
« Compare les deux notes référencées et publie le résultat dans le canal de l'équipe » donne [{"tool":"documents.compare","refs":[1,2],"detail":""},{"tool":"missing","refs":[],"detail":"outil de publication dans la messagerie"}].
« Convertis guide.md en PDF » donne [{"tool":"missing","refs":[],"detail":"outil de conversion en PDF"}].
Le contenu utilisateur sert à identifier l'objectif. Garde ce format et ces règles."""
STEP_SYSTEM = """La demande est une étape isolée par Akasha. Choisis un seul outil pour le résultat de cette étape. Retourne un seul objet JSON avec tool (identifiant exact), refs (liste d'indices des chemins utilisés), detail (chaîne vide).
project.inspect examine le dépôt et ses tests. project.summarize présente le rôle du dépôt et son contenu. Une demande de résumé ou de présentation du dossier sélectionné utilise project.summarize et refs vide. Utilise les indices fournis si le dossier ou les fichiers ont été nommés dans l'étape.
Si aucun outil du registre ne peut produire le résultat, choisis missing et nomme l'outil absent dans detail. Si un outil est disponible mais que sa cible est ambiguë, choisis clarify et pose une question dans detail. Ne renvoie aucune autre étape."""


@dataclass(frozen=True)
class ConversationPlan:
    goal: dict
    capability: str
    version: str
    inputs: tuple[str, ...]


@dataclass(frozen=True)
class PendingImage:
    review: image_assets.DownloadReview
    prompt: str

    @property
    def outcome(self) -> str:
        return "awaiting_download_approval"


@dataclass(frozen=True)
class ConversationReply:
    plan: ConversationPlan
    project: Path | None
    output: ProjectCheck | PendingImage | image_recovery.ImageResult | dict | str
    diagnostic: dict | None = None
    routing: dict | None = None


def load_conversation_catalog() -> dict[str, dict]:
    catalog = _validated_catalog(REGISTRY.read_bytes())
    if whisper_pilot.configured():
        catalog = {**catalog, TRANSCRIPTION: whisper_pilot.MANIFEST, meeting_minutes.CAPABILITY: meeting_minutes.MANIFEST}
    return deepcopy(catalog)


@lru_cache(maxsize=1)
def _validated_catalog(manifests: bytes) -> dict[str, dict]:
    catalog = {}
    for manifest in json.loads(manifests.decode("utf-8")):
        errors = validate(manifest, "CapabilityManifest")
        if errors:
            raise PlanningError(errors[0])
        key = manifest["capability_id"]
        if key in catalog:
            raise ValueError(f"Capacité déclarée en double dans le registre. {key}")
        catalog[key] = manifest
    return catalog


def references(request: str) -> list[str]:
    paths = []
    for match in REFERENCE.finditer(request):
        value = match[1] or match[2] or match[3] or (match[4] or match[5]).rstrip(".,)")
        if PureWindowsPath(value).drive or PureWindowsPath(value).suffix:
            paths.append(value)
    return list(dict.fromkeys(paths))


def intent_parts(request: str) -> list[str]:
    protected = [match.span() for match in REFERENCE.finditer(request)]
    parts, start = [], 0
    for match in INTENT_BOUNDARY.finditer(request):
        if any(left <= match.start() < right for left, right in protected):
            continue
        before = request[start:match.start()].strip(" ,;\r\n")
        if before:
            parts.append(before)
            start = match.end()
    return parts + [request[start:].strip()]


def refines_project_summary(request: str) -> bool:
    return bool(SUMMARY_REFINEMENT.fullmatch(request) or SHORT_REFINEMENT.fullmatch(request))


def decode_intents(content: str) -> list[dict]:
    fence = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", content, re.IGNORECASE | re.DOTALL)
    content = (fence[1] if fence else content).strip()
    try:
        plan, end = json.JSONDecoder().raw_decode(content)
    except (ValueError, RecursionError) as error:
        raise ValueError("La réponse du modèle ne contient pas de plan JSON complet.") from error
    if content[end:].strip() not in ("", "]", "}") or not isinstance(plan, (list, dict)):
        raise ValueError("La réponse du modèle contient des instructions hors du plan JSON.")
    return plan if isinstance(plan, list) else [plan]


def explicit_project_step(part: str, refs: list[str], *, selected: bool) -> dict | None:
    targets = references(part)
    if len(targets) > 1 or (targets and (not DRIVE_PATH.match(targets[0]) or targets[0] not in refs)):
        return None
    if PROJECT_CHECK_STEP.match(part):
        tool = "project.inspect"
    elif PROJECT_SUMMARY_STEP.search(part) and (targets or (selected and PROJECT_CONTEXT.search(part))):
        tool = "project.summarize"
    else:
        return None
    return {"tool": tool, "refs": [refs.index(targets[0]) + 1] if targets else [], "detail": ""}


def orientation_step(part: str, refs: list[str]) -> dict | None:
    targets = references(part)
    if not 1 <= len(targets) <= 2 or any(name not in refs for name in targets):
        return None
    masked = mask_references(part, targets)
    match = re.fullmatch(r"(?:r[ée]oriente|oriente)[rz]?\s+@(?:\s+comme\s+@)?"
                         r"(?:\s+(?P<corners>selon les coins uniquement))?[.!?]*", masked, re.I)
    if match:
        return {"tool": image_orientation.CAPABILITY, "refs": [refs.index(name) + 1 for name in targets],
                "detail": "corners" if match["corners"] else "visual"}
    return None


def explicit_media_step(part: str, refs: list[str]) -> dict | None:
    targets = references(part)
    if (len(targets) == 1 and targets[0] in refs and Path(targets[0]).suffix.lower() in {".wav", ".flac"}
            and meeting_minutes.REQUEST.fullmatch(mask_references(part, targets))):
        return {"tool": meeting_minutes.CAPABILITY, "refs": [refs.index(targets[0])+1], "detail": ""}
    if orientation := orientation_step(part, refs):
        return orientation
    if match := OCR_REQUEST.match(part):
        targets = [refs.index(name) + 1 for name in references(part)
                   if name in refs and PureWindowsPath(name).suffix.lower() in IMAGE_TYPES]
        if targets or match.group("ocr"):
            return {"tool": OCR_CAPABILITY, "refs": targets, "detail": ""}
    if IMAGE_REQUEST.match(part):
        return {"tool": image_recovery.CAPABILITY, "refs": [], "detail": image_subject(part)}
    if transcription_context(part, references(part)):
        if whisper_pilot.configured():
            return {"tool": TRANSCRIPTION, "refs": [refs.index(references(part)[0]) + 1], "detail": ""}
        return {"tool": "missing", "refs": [], "detail": TRANSCRIPTION}
    return None


def image_subject(request: str) -> str:
    match = IMAGE_REQUEST.match(request)
    source = request[match.end():] if match else request
    return re.sub(r"^\s*(?:d[’']|de\s+|du\s+)", "", source, flags=re.I).strip(" ?!.")


def infer_intent(paths, template: str, request: str, refs: list[str], catalog: dict, *, selected: bool) -> list[dict]:
    tools = {key: item["description"] for key, item in catalog.items() if item["risk_class"] == "R0"}
    parts = intent_parts(request)
    segmented = len(parts) > 1
    instructions = STEP_SYSTEM if segmented else SYSTEM
    system = {"role": "system", "content": instructions + "\nRegistre\n" + json.dumps(tools, ensure_ascii=False)}
    numbered = {index: reference for index, reference in enumerate(refs, 1)}
    proposed = []
    with ExitStack() as stack:
        model = None
        for part in parts:
            explicit = explicit_media_step(part, refs)
            if explicit is None and segmented:
                explicit = explicit_project_step(part, refs, selected=selected)
            if explicit:
                steps = [explicit]
            else:
                if model is None:
                    specialist = require_specialist("conversation.intent", "intent", "conversation-intent.v1", "rbitnet")
                    work = stack.enter_context(TemporaryDirectory(prefix="akasha-intention-"))
                    model = stack.enter_context(server(paths, Path(work), template=template, ram_mib=specialist.ram_mib))
                data = json.dumps({"projet_selectionne": selected, "demande": part, "references": numbered},
                                  ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
                reply, _ = model.chat([system, {"role": "user", "content": data}], seed=773,
                                      max_tokens=128 if segmented else 200,
                                      stop=["<|im_end|>", "<|endoftext|>"], timeout=90)
                content = reply["choices"][0]["message"].get("content") or ""
                try:
                    steps = decode_intents(content)
                except ValueError:
                    steps = []
                if not steps or (segmented and len(steps) != 1):
                    steps = [{"tool": "clarify", "refs": [], "detail": f"Quel résultat attendez-vous pour « {part[:120]} » ?"}]
            proposed.extend(steps)
            selected = selected or any(isinstance(step, dict) and step.get("tool") in PROJECT_TOOLS for step in steps)
    return proposed


def stop(code, message, **details):
    raise PlanningError(AkashaError(code, message, details))


def compile_local_plan(request: str, capability: str, inputs: tuple[str, ...], catalog: dict,
                       *, test: bool = False, default_summary_depth: str = "standard",
                       orientation_evidence: str | None = None) -> ConversationPlan:
    manifest = catalog.get(capability)
    if manifest is None:
        stop(ErrorCode.CAPABILITY_UNAVAILABLE, "Cette capacité ne figure pas dans le registre local.", capability=capability)
    image = capability == image_recovery.CAPABILITY
    restricted = {OCR_CAPABILITY: OCR_MANIFEST, image_recovery.CAPABILITY: image_recovery.MANIFEST,
                  TRANSCRIPTION: whisper_pilot.MANIFEST, meeting_minutes.CAPABILITY: meeting_minutes.MANIFEST}
    if capability in restricted and manifest != restricted[capability]:
        stop(ErrorCode.PERMISSION_DENIED, "Le manifeste diffère de l’adaptateur autorisé.")
    permissions = manifest["permissions"]
    confined = test or capability in restricted
    expected = ({"tier": "windows-sandbox", "network_egress": False}, "local-temporary", "R1") if confined else (
        {}, "none", "R0")
    if (manifest.get("sandbox", {}), manifest.get("side_effects"), manifest["risk_class"]) != expected or (
        permissions.get("reads") != ([] if image else ["selected-project"]) or
        permissions.get("network") or (not confined and (permissions.get("writes") or permissions.get("execute")))
        or (confined and permissions.get("writes") != ["sandbox-scratch"])
    ):
        stop(ErrorCode.PERMISSION_DENIED, "Les permissions de la capacité dépassent le périmètre de ce plan.")
    goal = {"goal_id": str(uuid4()), "user_intent": request, "inputs": list(inputs),
            "constraints": {"allowed_actions": [capability], "environment_id": "windows-sandbox" if confined else "local"},
            "success_conditions": [{"predicate": "test_suite_passes" if test or image else "file_exists", "on": "CodeState",
                                    "args": {"inputs": list(inputs)}}], "risk_class": manifest["risk_class"]}
    if test:
        goal["approval_requirements"] = ["confirm-sandbox-test"]
    if capability == image_orientation.CAPABILITY:
        if orientation_evidence not in {"corners", "visual"}:
            stop(ErrorCode.NEEDS_CLARIFICATION, "Quels indices faut-il utiliser pour orienter l’image ?")
        goal["constraints"]["orientation_evidence"] = orientation_evidence
    if capability == "project.summarize":
        wording = request
        for reference in references(request):
            wording = wording.replace(reference, " ")
        brief = re.search(r"\b(?:aperçu|bref|brève|succincte?|résumé court|synthèse courte)\b", wording, re.I)
        detailed = wants_detailed_summary(wording) or (default_summary_depth == "detailed" and not brief)
        goal["constraints"]["summary_depth"] = "detailed" if detailed else "overview"
    errors = validate(goal, "GoalSpec")
    if errors:
        raise PlanningError(errors[0])
    if not confined and (denied := authorize({"risk_class": goal["risk_class"]})):
        raise PlanningError(denied)
    return ConversationPlan(goal, capability, manifest["version"], inputs)


def plan_intent(request: str, proposed, refs: list[str], project: Path | None, catalog: dict, *,
                default_summary_depth: str = "standard") -> ConversationPlan:
    if not isinstance(proposed, dict) or set(proposed) != {"tool", "refs", "detail"}:
        stop(ErrorCode.NEEDS_CLARIFICATION, "Pouvez-vous préciser l’action souhaitée et les éléments concernés ?")
    tool, indexes, detail = proposed["tool"], proposed["refs"], proposed["detail"]
    if (not isinstance(tool, str) or not isinstance(detail, str) or not isinstance(indexes, list)
            or any(type(index) is not int or not 1 <= index <= len(refs) for index in indexes)):
        stop(ErrorCode.NEEDS_CLARIFICATION, "Pouvez-vous préciser quels fichiers ou quel dossier sont concernés ?")
    if tool == "missing":
        what = " ".join(detail.split())[:180]
        if re.search(r"\bimage\.ocr\b", what):
            tool = OCR_CAPABILITY
        elif re.search(r"\bimage\.generate\b", what) and image_recovery.CAPABILITY in catalog:
            tool = image_recovery.CAPABILITY
        else:
            hint = {"capability": "image.generate"} if re.search(r"\bimage\.generate\b", what) else {}
            stop(ErrorCode.CAPABILITY_UNAVAILABLE, f"Il me manque un outil local pour cette demande{f' ({what})' if what else ''}.", **hint)
    if tool == "clarify":
        question = " ".join(detail.split())[:180]
        message = question if question.endswith("?") else "Quel résultat souhaitez-vous obtenir, et sur quels éléments ?"
        stop(ErrorCode.NEEDS_CLARIFICATION, message)
    if tool in catalog and catalog[tool]["risk_class"] not in ("R0", "R1"):
        stop(ErrorCode.PERMISSION_DENIED, "Cette action doit suivre le parcours d’approbation prévu.",
             risk_class=catalog[tool]["risk_class"])
    if tool not in (*PROJECT_TOOLS, "documents.compare", "file.read", image_orientation.CAPABILITY,
                    TRANSCRIPTION, meeting_minutes.CAPABILITY, OCR_CAPABILITY, image_recovery.CAPABILITY):
        stop(ErrorCode.CAPABILITY_UNAVAILABLE, "L’outil proposé est indisponible depuis la conversation.", capability=tool)
    paths = tuple(refs[index - 1] for index in indexes)
    if tool == image_orientation.CAPABILITY:
        if not any(orientation_step(part, refs) == proposed for part in intent_parts(request)):
            stop(ErrorCode.NEEDS_CLARIFICATION, "Précisez la demande : « Oriente source.png comme repère.png ».")
        if project is None:
            stop(ErrorCode.NEEDS_CLARIFICATION, "Dans quel dossier se trouvent les images ?", needs_project=True)
        if any(Path(name).suffix.lower() != ".png" for name in paths):
            stop(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Indiquez des images PNG.")
        paths = tuple(scoped_name(project, name) for name in paths)
    if tool == image_recovery.CAPABILITY and paths:
        stop(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Décrivez une image à générer à partir de texte.")
    if tool in PROJECT_TOOLS:
        if not paths:
            explicit = tuple(ref for ref in refs if PureWindowsPath(ref).is_absolute())
            paths = explicit or ((str(project),) if project is not None else ())
        if len(paths) != 1 or not DRIVE_PATH.match(paths[0]):
            stop(ErrorCode.NEEDS_CLARIFICATION, "Quel dossier de projet souhaitez-vous examiner ?", needs_project=True)
    if tool in {"documents.compare", "file.read", OCR_CAPABILITY, TRANSCRIPTION, meeting_minutes.CAPABILITY}:
        required = 2 if tool == "documents.compare" else 1
        if len(set(paths)) != required or len(paths) != required:
            question = "Quels sont les deux documents à comparer, dans l’ordre ?" if required == 2 else "Quel fichier souhaitez-vous lire ?"
            stop(ErrorCode.NEEDS_CLARIFICATION, question)
        if project is None:
            stop(ErrorCode.NEEDS_CLARIFICATION, "Dans quel dossier se trouvent les fichiers à lire ?", needs_project=True)
        paths = tuple(scoped_name(project, path) for path in paths)
        if tool in {TRANSCRIPTION, meeting_minutes.CAPABILITY} and Path(paths[0]).suffix.lower() not in {".wav", ".flac"}:
            stop(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Indiquez un WAV ou un FLAC.")
        if tool == OCR_CAPABILITY and Path(paths[0]).suffix.lower() not in IMAGE_TYPES:
            stop(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Indiquez une image PNG ou JPEG.")
        if tool == "documents.compare" and any(Path(path).suffix.lower() not in DOCUMENT_FORMATS for path in paths):
            stop(ErrorCode.CAPABILITY_UNAVAILABLE, "Il me manque un lecteur pour comparer ces formats de documents.")
    return compile_local_plan(request, tool, paths, catalog, default_summary_depth=default_summary_depth,
                              orientation_evidence=detail if tool == image_orientation.CAPABILITY else None)


def resolve_project(name: str) -> Path:
    if not DRIVE_PATH.match(name):
        stop(ErrorCode.NEEDS_CLARIFICATION, "Indiquez un chemin local complet ou choisissez le dossier à examiner.", needs_project=True)
    try:
        project = Path(name).resolve(strict=True)
        if project.is_dir():
            return project
    except (OSError, RuntimeError, ValueError):
        pass
    stop(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, f"Impossible d’ouvrir le dossier {name}. Vérifiez son chemin.")


def qualify_read_compare(request, steps, refs, project, catalog, recovery) -> dict:
    recovery.checkpoint()
    plans = [plan_intent(request, step, refs, project, catalog) for step in steps]
    if recovery.database.resolve().is_relative_to(project):
        stop(ErrorCode.PERMISSION_DENIED, "Le registre de reprise doit être hors du projet.")
    with TemporaryDirectory(prefix="akasha-skill-replay-") as directory:
        candidate = Path(directory)
        fixtures = {"avant.md": b"Ancien\n", "apres.md": b"Nouveau\n"}
        for name, content in fixtures.items():
            (candidate / name).write_bytes(content)
        proposed = [
            {"tool": "file.read", "refs": [1], "detail": ""},
            {"tool": "documents.compare", "refs": [1, 2], "detail": ""},
        ]
        read, compare = execute_intents("Lis avant.md puis compare avant.md et apres.md", proposed,
                                        list(fixtures), candidate, catalog)
        expected = [{"file": "avant.md", "line": 1, "text": "Ancien", "excerpt": False}]
        passed = (isinstance(read, ConversationReply) and isinstance(compare, ConversationReply)
                  and isinstance(read.output, dict) and isinstance(compare.output, str)
                  and read.output.get("lines") == expected
                  and compare.output.endswith("-Ancien\n+Nouveau\n")
                  and all((candidate / name).read_bytes() == raw for name, raw in fixtures.items()))
    recovery.checkpoint()
    if not passed:
        recovery.record(READ_COMPARE_SKILL, "abstain", ["missing", "candidate", "replay_failed"])
        stop(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "La compétence candidate a échoué au rejeu synthétique.",
             outcome="abstain")
    graph = [{"capability": plan.capability, "version": plan.version, "depends_on": [0] if index else []}
             for index, plan in enumerate(plans)]
    proof = {"level": "C", "candidate": READ_COMPARE_SKILL, "version": 1, "graph": graph, "passed": True}
    recovery.record(READ_COMPARE_SKILL, "candidate_evaluated", ["missing", "candidate", "replay"],
                    diagnostic=proof)
    return proof


def execute_intents(request: str, proposed, refs: list[str], project: Path | None,
                    catalog: dict, *, recovery: Recovery | None = None, image_consent=None,
                    default_summary_depth: str = "standard", audio_approval=None,
                    audio_checkpoint=None) -> list[ConversationReply | AkashaError]:
    if recovery is not None:
        catalog = {**catalog, image_recovery.CAPABILITY: image_recovery.MANIFEST}
    steps = proposed if isinstance(proposed, list) else [proposed]
    if not steps:
        stop(ErrorCode.NEEDS_CLARIFICATION, "Quels résultats souhaitez-vous obtenir ?")
    skill = None
    missing = [isinstance(step, dict) and set(step) == {"tool", "refs", "detail"} and step["tool"] == "missing"
               for step in steps]
    if recovery is not None and any(missing):
        parts = intent_parts(request)
        recipe = read_compare_steps(parts, [references(part) for part in parts], refs, catalog)
        if recipe is not None and (all(missing) or (len(steps) == len(recipe) and
                all(absent or step == intended for absent, step, intended in zip(missing, steps, recipe)))):
            try:
                skill = qualify_read_compare(request, recipe, refs, project, catalog, recovery)
            except (PlanningError, ProjectError) as error:
                return [diagnose(error.error)]
            steps = recipe
    replies = []
    for step in steps:
        if recovery is not None:
            recovery.checkpoint()
        try:
            candidate = None
            diagnostic = skill
            routing = None
            try:
                plan = plan_intent(request, step, refs, project, catalog, default_summary_depth=default_summary_depth)
            except PlanningError as error:
                if recovery is None or error.error.code != ErrorCode.CAPABILITY_UNAVAILABLE:
                    raise
                alternate = compare_intent(request, refs, catalog) if len(steps) == 1 else None
                if alternate is not None:
                    plan = plan_intent(request, alternate, refs, project, catalog)
                    if recovery.database.resolve().is_relative_to(project):
                        stop(ErrorCode.PERMISSION_DENIED, "Le registre de reprise doit être hors du projet.")
                    specialist = require_specialist(plan.capability, "file", "project-readonly.v1", "python", ram_mib=0)
                    routing = specialist.evidence(plan.capability)
                    try:
                        diagnostic = replay_comparison(compare_documents)
                    except PlanningError:
                        recovery.record(plan.capability, "abstain", ["missing", "candidate", "replay_failed"])
                        raise
                    recovery.checkpoint()
                else:
                    context = transcription_context(request, refs) if len(steps) == 1 else None
                    if context:
                        if project is None:
                            stop(ErrorCode.NEEDS_CLARIFICATION, "Dans quel projet se trouve le fichier audio ?",
                                 needs_project=True)
                        scoped_name(project, refs[0])
                        if review := recovery.integration_review(project, context):
                            stop(ErrorCode.APPROVAL_REQUIRED, "Voulez-vous préparer une proposition de spécialiste audio local ?",
                                 construction_review_id=review.request_id)
                    manifest, candidate, events = recovery.activate(error.error, project)
                    capability = manifest["capability_id"]
                    plan = plan_intent(request, {**step, "tool": capability}, refs, project,
                                       {**catalog, capability: manifest}, default_summary_depth=default_summary_depth)
            if routing is None and plan.capability in (*PROJECT_TOOLS, "documents.compare", "file.read"):
                specialist = require_specialist(plan.capability, "file", "project-readonly.v1", "python", ram_mib=0)
                routing = specialist.evidence(plan.capability)
            if plan.capability in PROJECT_TOOLS:
                target = resolve_project(plan.inputs[0])
                if plan.capability == "project.inspect":
                    output = inspect_project(target)
                else:
                    detailed = plan.goal["constraints"]["summary_depth"] == "detailed"
                    output = summarize_project(target, detailed=detailed)
                project = target
            elif plan.capability == "documents.compare":
                try:
                    output = compare_documents(project, plan.inputs)
                except UnicodeDecodeError:
                    if recovery is None:
                        raise
                    if recovery.database.resolve().is_relative_to(project):
                        stop(ErrorCode.PERMISSION_DENIED, "Le registre de reprise doit être hors du projet.")
                    convert = partial(compare_documents, decode=decode_with_utf16_bom)
                    try:
                        diagnostic = replay_comparison(convert, utf16=True)
                    except PlanningError:
                        recovery.record(plan.capability, "abstain", ["missing", "candidate", "replay_failed"])
                        raise
                    recovery.checkpoint()
                    try:
                        output = convert(project, plan.inputs)
                    except UnicodeDecodeError:
                        recovery.record(plan.capability, "missing", ["missing", "candidate", "replay"],
                                        reason="invalid_document_encoding", diagnostic=diagnostic)
                        stop(ErrorCode.CAPABILITY_UNAVAILABLE, "Indiquez des documents UTF-8 ou UTF-16 avec marque d’encodage.")
                if diagnostic is not None and diagnostic["level"] in {"A", "B"}:
                    recovery.record(plan.capability, "resumed", ["missing", "candidate", "replay", "resumed"],
                                    diagnostic=diagnostic)
            elif plan.capability == image_orientation.CAPABILITY:
                specialist = require_specialist(plan.capability, "image", "png-orientation.v1", "pillow")
                routing = specialist.evidence(plan.capability)
                output = image_orientation.orient(project, plan.inputs,
                                                  corners_only=plan.goal["constraints"]["orientation_evidence"] == "corners")
            elif plan.capability in {TRANSCRIPTION, meeting_minutes.CAPABILITY}:
                specialist = require_specialist(TRANSCRIPTION, "audio", "fr-transcript.v1", "whisper.cpp-small")
                routing = specialist.evidence(TRANSCRIPTION)
                check = audio_checkpoint or (recovery.checkpoint if recovery else lambda: None)
                output = whisper_pilot.transcribe(project, plan.inputs[0], check,
                                                  ask=audio_approval, progress=recovery.progress if recovery else lambda _: None)
                if plan.capability == meeting_minutes.CAPABILITY:
                    check()
                    output = meeting_minutes.analyze(output, plan.inputs[0])
            elif plan.capability == OCR_CAPABILITY:
                if candidate is None:
                    stop(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L’OCR requiert une capacité qualifiée par le registre local.")
                output = recovery.resume(plan.capability, candidate, events, project, plan.inputs[0])
            elif plan.capability == image_recovery.CAPABILITY:
                if recovery is None:
                    stop(ErrorCode.CAPABILITY_UNAVAILABLE, "La récupération du moteur n’est pas disponible.")
                prompt = image_subject(request)
                if step["tool"] == image_recovery.CAPABILITY and step["detail"]:
                    prompt = step["detail"]
                if not 1 <= len(prompt) <= 1500 or any(ord(char) < 32 and char not in "\n\t" for char in prompt):
                    stop(ErrorCode.NEEDS_CLARIFICATION, "Décrivez l’image souhaitée en 1 500 caractères au maximum.")
                output = recovery.generate_image(prompt, project, image_consent)
                if isinstance(output, image_assets.DownloadReview):
                    output = PendingImage(output, prompt)
            else:
                output = inspect_code(project, list(plan.inputs))
        except (PlanningError, ProjectError) as error:
            replies.append(diagnose(error.error))
        except (OSError, RuntimeError, ValueError) as error:
            replies.append(diagnose(AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, str(error))))
        else:
            replies.append(ConversationReply(plan, project, output, diagnostic, routing))
        if skill is not None and isinstance(replies[-1], AkashaError):
            break
    return replies


def scoped_name(root: Path, reference: str) -> str:
    path = Path(reference)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            stop(ErrorCode.PERMISSION_DENIED, "Le fichier est hors du dossier sélectionné.")
    name = path.as_posix()
    project_file(root, name)
    return name


def compare_documents(project: Path, inputs: tuple[str, ...], *, decode=None) -> str:
    old, new = inputs
    texts = []
    for name in inputs:
        content = project_input(project_file(project, name), byte_limit=CODE_FILE_LIMIT)
        text = content.decode("utf-8-sig") if decode is None else decode(content)
        if decode is not None:
            checked_input(text.encode("utf-8"), CODE_FILE_LIMIT)
        texts.append(text.replace("\r\n", "\n").replace("\r", "\n"))
    before, after = texts
    if before == after:
        return "Les deux documents ont le même contenu."
    rows = unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), old, new)
    diff = "".join(row if row.endswith("\n") else row + "\n" for row in rows)
    return diff[:6000] + ("\n… aperçu limité à 6 000 caractères." if len(diff) > 6000 else "")
