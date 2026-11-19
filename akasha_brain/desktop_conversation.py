"""Conversation locale du desktop et passage explicite à un parcours évalué."""

import base64
from concurrent.futures import Future, TimeoutError as FutureTimeout
from datetime import datetime
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from queue import Empty, SimpleQueue
import re
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import tkinter as tk
from tkinter import filedialog, font, ttk
from unicodedata import normalize
from uuid import uuid4

from bench.run_guided_repair import CHECKPOINTS, file_hash
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .capability_recovery import Recovery
from .desktop_read_aloud import ReplyReader
from .conversation_planning import (
    DRIVE_PATH, PROJECT_TOOLS, PendingImage, compile_local_plan, execute_intents, explicit_media_step, infer_intent, intent_parts,
    load_conversation_catalog, references, refines_project_summary, web_targets,
)
from .conversation_vault import SessionVault, admit_secret, clear
from .desktop_settings import app_directory
from .desktop_tasks import latest_steps, test_counts
from .desktop_vault import VaultWindow
from .desktop_voice import VoiceComposer
from .gap_resolution import GapReview, LABELS as GAP_LABELS
from .image_recovery import CAPABILITY as GENERATE_IMAGE, ImageResult
from .memory_store import MemoryRefusal
from .planning import PlanningError
from .project import CODE_FILE_LIMIT, inspect_code, prepare, preview_replacement, project_file
from .project_check import ProjectCheck, inspect_project, installed_node, run_project_check
from .project_common import ProjectError
from .project_approval import require_fresh
from .rbitnet_session import server
from .specialist_registry import require_specialist
from .vault_windows import KeyStoreUnavailable, SecretMissing
from .web_collection import Observation, ReadReview, public_target
from .whisper_recovery import describe as describe_audio_download

PROMPT = Path(__file__).resolve().parents[1] / "bench" / "communication" / "qwen35-2b-fr-v2.json"
COMMUNICATION_CHECKPOINTS = {
    "engine": CHECKPOINTS["engine"],
    "model": "1b04acba824817554f4ce23639bc8495ff70453b8fcb047900c731521021f2c1",
    "tokenizer": "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42",
}
QUOTED_TEXT = r'(?:«[^»]*»|"[^"]*"|`[^`]*`)'
REPLACEMENT = re.compile(
    rf"^(?:remplace|remplacer)\s+(?P<before>{QUOTED_TEXT})\s+par\s+(?P<after>{QUOTED_TEXT})\s+dans\s+(?P<target>.+)$",
    re.IGNORECASE,
)
READ_FILE = re.compile(r"^(?:lis|lire|affiche\s+le\s+fichier)\s+(.+)$", re.IGNORECASE)
CHECK_PROJECT = re.compile(
    r"^(?:est-ce que\s+)?(?:(?:tu (?:peux|pourrais)|peux[- ]tu|pourrais[- ]tu|vous pouvez|pouvez[- ]vous)\s+)?"
    r"(?:v[ée]rifie[rz]?|examine[rz]?|analyse[rz]?|audite[rz]?|teste[rz]?|regarde[rz]?)\s+(.*)$",
    re.IGNORECASE,
)
PROJECT_SUBJECT = re.compile(r"^(?:(?:ce|le|mon|un)\s+)?(?:projet|dossier)\b\s*", re.IGNORECASE)
REPLACEMENT_EXAMPLE = 'Remplace "VALUE = 7" par "VALUE = 11" dans value.py'
TEST_LABELS = {"script": "script Python", "unittest": "unittest", "node": "node --test", "none": "aucun test repéré"}
SESSION_WRITE_ERRORS = (MemoryRefusal, OSError, ProjectError, sqlite3.Error, ValueError)
VAULT_ERRORS = (*SESSION_WRITE_ERRORS, KeyStoreUnavailable, SecretMissing)


@dataclass(frozen=True)
class TextChange:
    target: str
    before: str
    after: str


def unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and (text[0], text[-1]) in (("«", "»"), ('"', '"'), ("`", "`")):
        return text[1:-1]
    return text


def parse_replacement(request: str) -> TextChange | None:
    if match := REPLACEMENT.fullmatch(request.strip()):
        return TextChange(unquote(match["target"]), match["before"][1:-1], match["after"][1:-1])
    return None


def parse_project_check(request: str) -> str | None:
    """Return a project path, or an empty string to use the selected project."""
    request = request.strip().rstrip("?!").rstrip()
    path = unquote(request)
    if DRIVE_PATH.match(path):
        return path
    match = CHECK_PROJECT.fullmatch(request)
    if match is None:
        return None
    subject, count = PROJECT_SUBJECT.subn("", match[1], count=1)
    name = unquote(subject.lstrip(": "))
    if count or DRIVE_PATH.match(name):
        return name
    return None


def route_request(request: str) -> str | None:
    words = re.findall(r"[a-z]+", normalize("NFKD", request.casefold()).encode("ascii", "ignore").decode())
    phrase = " ".join(words)
    words = set(words)
    notes = bool(words & {"notes", "note"})
    if notes and re.search(r"\b(?:mis a part|a part|en dehors de|autre chose que|hors|sauf)\b", phrase):
        return "project_capabilities"
    if (phrase in {"aide", "que sais tu faire", "a quoi sers tu"} or "capacites" in words
            or re.search(r"\b(?:tu peux|peux tu|vous pouvez|pouvez vous) faire(?: quoi)?$", phrase)):
        return "capabilities"
    if words & {"tache", "taches", "transfert"}:
        return None
    if re.fullmatch(r"(?:(?:tu peux|peux tu|pouvez vous) )?(?:lance[rz]?|execute[rz]?) (?:les |ces )?tests", phrase):
        return "check_tests"
    if "diff" in words and words & {"affiche", "montre", "voir", "examine"}:
        return "diff"
    project = bool(words & {"projet", "fichier", "diff", "proposition", "dependance"})
    if words & {"resultat", "resultats", "bilan", "verdict", "rapport"}:
        if project and not notes:
            return "review"
        return "result" if notes else "last_result"
    if notes == project:
        return None
    if project:
        return "project"
    actions = {"lance", "lancer", "demarre", "demarrer", "teste", "tester", "repare", "reparer",
               "execute", "executer", "verifie", "verifier"}
    if words & actions and not re.search(r"\b(?:ne|n)\s+(?:[a-z]+\s+){1,5}(?:pas|jamais)\b", phrase):
        return "notes"
    return None


def verification_details(report: dict) -> str:
    steps = latest_steps(report)
    detail = ""
    if steps.get("verify", {}).get("result", {}).get("sqlite_verdict") == "passed":
        detail += " SQLite a confirmé la persistance."
    if steps.get("verify_desktop", {}).get("status") == "passed":
        detail += " RapidOCR a retrouvé la note après relance."
    return detail


def result_summary(report: dict) -> tuple[str, tuple[int, int, str] | None]:
    checked = latest_steps(report)
    verification = checked.get("verify", {}).get("result", {})
    counts = test_counts(verification)
    duration = report.get("wall_s")
    if report["status"] != "passed":
        return "Le banc Notes a échoué. Le détail de l’étape est disponible dans le graphe.", None
    if counts is None or duration is None:
        return "Le banc Notes est terminé. Le détail est disponible dans le graphe.", None
    passed, total = counts
    seconds = f"{float(duration):.1f}".replace(".", ",")
    evidence = f"Le banc Notes a réussi {passed} tests sur {total} en {seconds} secondes."
    return evidence + verification_details(report), (passed, total, seconds)


def communication_profile(paths) -> dict:
    if any(file_hash(getattr(paths, key)) != expected for key, expected in COMMUNICATION_CHECKPOINTS.items()):
        raise ValueError("Les fichiers du modèle de communication ne correspondent pas au gel.")
    data = json.loads(PROMPT.read_bytes())
    system = data["system"]
    if sha256(system.encode("utf-8")).hexdigest() != data["system_sha256"]:
        raise ValueError("La consigne de communication a changé.")
    return data


def communicate(paths, facts: tuple[int, int, str]) -> str | None:
    data = communication_profile(paths)
    passed, total, elapsed = facts
    fiche = (f"État=résultat constaté; objet=le banc Notes; auteur=le banc Notes; opération=exécuter les tests; "
             f"succès={passed}/{total} tests; durée totale={elapsed} secondes.")
    settings = data["settings"]
    with TemporaryDirectory(prefix="akasha-communication-") as work:
        with server(paths, Path(work), template=data["chat_template"]) as model:
            response, _ = model.chat([{"role": "system", "content": data["system"]},
                                      {"role": "user", "content": "Fiche : " + fiche}],
                                     seed=settings["seed"], max_tokens=settings["max_tokens"],
                                     stop=settings["stop"], timeout=65)
    text = (response["choices"][0]["message"].get("content") or "").strip()
    duration = re.escape(elapsed).replace(",", "[,.]")
    # La synthèse affichée ne peut pas remplacer le verdict déterministe.
    if ("notes" not in text.casefold() or not re.search(rf"\b{passed}\s*(?:sur|/)\s*{total}\b", text)
            or not re.search(rf"\b{duration}\s*(?:s\b|secondes\b)", text, re.I)
            or "\n" in text or "<" in text or "?" in text or len(text) > 220
            or len(re.findall(r"[.!](?!\d)", text)) > 1
            or re.search(r"échec|échou|\bnon\b|\bpas\b", text, re.I)):
        return None
    return text


def compose_image_prompt(paths, subject: str) -> str:
    try:
        specialist = require_specialist("image.prompt", "intent", "image-prompt.v1", "rbitnet")
        profile = communication_profile(paths)
        with TemporaryDirectory(prefix="akasha-image-prompt-") as work:
            with server(paths, Path(work), template=profile["chat_template"], ram_mib=specialist.ram_mib) as model:
                reply, _ = model.chat([
                    {"role": "system", "content": "Translate the visual description to natural English for a text-to-image model. "
                     "Keep all subjects, objects, actions, composition and style. Return the description only."},
                    {"role": "user", "content": subject},
                ], seed=3927, max_tokens=320, stop=profile["settings"]["stop"], timeout=90)
        prompt = (reply["choices"][0]["message"].get("content") or "").strip()
        if 1 <= len(prompt) <= 1500 and "<" not in prompt and "\n" not in prompt:
            if re.search(r"\bselfie\b", subject, re.I) and re.search(r"\b(?:miroir|mirror)\b", subject, re.I):
                return prompt.rstrip(".") + ", smartphone visible in the mirror"
            return prompt
    except (OSError, RuntimeError, ValueError, KeyError, PlanningError):
        pass
    return subject


class ConversationPane:
    voice: VoiceComposer | None = None

    def __init__(self, parent, launch_notes, prepare_project, review_project, latest_report, tasks, *,
                 project, review_prepared, communication=None, session=None):
        self.parent = parent
        self.launch_notes, self.prepare_project, self.latest_report = launch_notes, prepare_project, latest_report
        self.tasks = tasks
        self.review_project = review_project
        self.review_prepared = review_prepared
        self.session_store, self.session_record = session if session is not None else (None, None)
        self.vault = None
        self.project = project if session is not None else (project.resolve() if project is not None else None)
        self.summary_depth = "standard"
        self.change = self.test_file = self.project_job = self.proposal = self.project_error = None
        self.inspection = self.check_job = self.check_result = None
        self.intent_job = self.pending_intent = self.conversation_plan = self.test_plan = None
        self.intent_cancel = Event()
        self.intent_progress = SimpleQueue()
        self.pending_image = None
        self.pending_web = None
        self.web_urls = ()
        self.audio_decision = None
        self.pending_gap = None
        self.previews = []
        self.intent_error = None
        self.conversation_steps = ()
        self.last_summary_project = None
        self.catalog = load_conversation_catalog()
        self.communication = communication
        self.watched = set()
        self.replies = SimpleQueue()
        self.responding = False
        self.action = None
        self.build()
        self.transcript.bind("<Destroy>", lambda _: self.intent_cancel.set(), add="+")
        if self.session_record is not None:
            self.refresh_session(self.session_record)
        self.add("Akasha", "Que souhaitez-vous faire ? Vous pouvez indiquer un lien HTTPS ou un dossier de projet.")
        self.parent.after(150, self.poll)

    def focus(self):
        self.entry.focus_set()

    def build(self):
        page = ttk.Frame(self.parent, padding=18, style="Data.TFrame")
        page.pack(fill="both", expand=True)
        theme = ttk.Style(self.parent)
        project_bar = ttk.Frame(page, style="Data.TFrame")
        project_bar.pack(fill="x", pady=(0, 10))
        ttk.Button(project_bar, text="Choisir un projet…", command=self.choose_project).pack(side="right")
        self.project_label = ttk.Label(project_bar, style="DataMuted.TLabel")
        self.project_label.pack(side="left", fill="x", expand=True)
        self.update_project_label()
        if self.session_store is not None:
            self.session_observation = ttk.Label(page, style="DataMuted.TLabel")
            self.session_observation.pack(fill="x", pady=(0, 8))
            self.summary_detail = tk.BooleanVar(project_bar, value=False)
            self.summary_choice = ttk.Checkbutton(project_bar, text="Résumé détaillé", variable=self.summary_detail,
                                                  command=self.set_summary_depth, style="Data.TCheckbutton")
            self.summary_choice.pack(side="right", padx=12)
            ttk.Button(project_bar, text="Secrets…", command=self.open_vault).pack(side="right")
        panel = ttk.Frame(page, style="Data.TFrame")
        panel.pack(fill="both", expand=True)
        window = self.parent.winfo_toplevel()
        if not hasattr(window, "_akasha_transcript_fonts"):
            window._akasha_transcript_fonts = (
                font.Font(root=window, family="Segoe UI", size=11),
                font.Font(root=window, family="Segoe UI", size=11, weight=font.BOLD),
                font.Font(root=window, family="Consolas", size=10),
            )
        conversation_font, speaker_font, code_font = window._akasha_transcript_fonts
        self.transcript = tk.Text(panel, wrap="word", state="disabled", padx=12, pady=8, width=1, height=1,
                                  font=conversation_font, bg=theme.lookup("Data.Treeview", "background"),
                                  fg=theme.lookup("Data.TLabel", "foreground"))
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.transcript.pack(side="left", fill="both", expand=True)
        self.transcript.tag_configure("speaker", font=speaker_font)
        self.transcript.tag_configure("code", font=code_font)
        self.reader = ReplyReader(page, self.tasks.scheduler, lambda: self.project)
        controls = ttk.Frame(page, style="Data.TFrame")
        controls.pack(fill="x", pady=(10, 0))
        self.confirm = ttk.Button(controls, command=self.confirm_action)
        self.refuse_audio = ttk.Button(controls, text="Refuser", command=lambda: self.answer_audio("decline"))
        ttk.Button(controls, text="Envoyer", style="Launch.TButton", command=self.send).pack(side="right")
        self.entry = ttk.Entry(controls, style="Conversation.TEntry")
        self.entry.pack(side="left", fill="x", expand=True, padx=8)
        self.entry.bind("<Return>", self.send)
        self.voice = VoiceComposer(page, self)

    def add(self, speaker, text, *, tag=None, narration_only=False):
        if speaker != "Vous":
            self.reader.set_text(text, narration_only=narration_only)
        self.transcript.configure(state="normal")
        self.transcript.insert("end", speaker + "\n", "speaker")
        self.transcript.insert("end", text + "\n\n", tag or ())
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def send(self, _event=None):
        request = self.entry.get().strip()
        if not request:
            return
        if self.audio_decision is not None:
            if request.casefold() not in ("annule", "annuler"):
                self.add("Akasha", "Autorisez ou refusez le téléchargement, ou saisissez « Annuler ».")
                return
            self.answer_audio("cancel")
        self.entry.delete(0, "end")
        if self.voice is not None:
            self.voice.sent()
        if self.seal_request(request):
            return
        self.add("Vous", request)
        self.action = None
        self.pending_image = None
        self.pending_web = None
        self.pending_gap = None
        self.confirm.pack_forget()
        followup = self.project is not None and self.last_summary_project == self.project and refines_project_summary(request)
        self.last_summary_project = None
        cancelled = request.casefold() in ("annule", "annuler")
        cancelling_job = cancelled and self.intent_job is not None
        replacement = parse_replacement(request)
        if cancelled:
            self.pending_intent = None
            self.intent_cancel.set()
            if self.intent_job is not None:
                self.intent_job[3].cancel()
            self.intent_job = None
        elif replacement is None and (urls := web_targets(request, self.web_urls)):
            self.pending_intent = None
            self.change = self.test_file = None
            self.web_urls = urls
            self.offer_web_read(urls)
            return
        elif self.pending_intent is not None:
            original, turn = self.pending_intent
            self.request_intent(f"{original}\nPrécision de l’utilisateur\n{request}", turn=turn)
            return
        if followup:
            self.change = self.test_file = None
            self.request_intent(request, refine_summary=True)
            return
        if self.communication is not None and len(intent_parts(request)) > 1:
            self.change = self.test_file = None
            self.request_intent(request)
            return
        if len(intent_parts(request)) == 1 and explicit_media_step(request, references(request)):
            self.change = self.test_file = None
            self.request_intent(request)
            return
        if replacement is not None:
            if self.project is not None or self.choose_project():
                self.change, self.test_file = replacement, None
                self.add("Akasha", f"Quel script Python doit vérifier le remplacement dans {replacement.target} ? "
                                   "Indiquez son chemin relatif au projet.")
            return
        if match := READ_FILE.fullmatch(request):
            name = unquote(match[1].rstrip("?"))
            if self.communication is None or Path(name).suffix:
                self.change = None
                self.read_file(name)
                return
        path = parse_project_check(request)
        if path is not None and (self.communication is None or DRIVE_PATH.match(unquote(request))):
            self.change = self.test_file = None
            self.check_project(path)
            return
        action = route_request(request)
        if self.communication is not None and (
            (action == "notes" and not re.search(r"\bbanc\s+notes\b", request, re.IGNORECASE))
            or (action in {"review", "diff", "result", "last_result"} and references(request))
        ):
            action = None
        if self.change is not None and not cancelled and (
            action is None or unquote(request).lower().endswith(".py")
        ):
            self.set_test_file(unquote(request))
            return
        self.change = self.test_file = None
        if action == "notes":
            self.add("Akasha", "Le banc Notes vérifiera la réparation dans Windows Sandbox. Lancez-le quand vous êtes prêt.")
            self.offer("Lancer Notes", "notes")
        elif action == "project" and self.communication is None:
            self.add("Akasha", "Je peux examiner le dossier et repérer ses tests. Écrivez « Vérifie ce projet » "
                               "avec le chemin du dossier. Pour préparer une modification, ouvrez le formulaire.")
            self.offer("Préparer un projet", "project")
        elif action == "check_tests":
            if self.inspection is None or self.check_job is not None:
                self.check_project("")
            else:
                self.offer_tests(self.inspection)
        elif action in ("review", "diff"):
            self.show_project_result(include_check=action == "review")
        elif action in ("result", "last_result"):
            if action == "last_result" and (
                self.project_job or self.proposal or self.project_error or self.check_job or self.check_result
            ):
                self.show_project_result()
            elif (report := self.latest_report()) is None:
                self.add("Akasha", "Aucun résultat Notes n’est encore disponible.")
            else:
                self.reply_to_report(report)
        elif action in ("capabilities", "project_capabilities"):
            self.show_capabilities(action == "capabilities")
        elif cancelled:
            message = ("Annulation de la demande en cours." if cancelling_job else
                       "Une vérification est déjà en cours. Son résultat apparaîtra ici."
                       if self.project_job is not None or self.check_job is not None
                       else "La demande en cours de saisie est effacée.")
            self.add("Akasha", message)
        elif self.communication is not None:
            self.request_intent(request)
        else:
            self.show_capabilities(include_notes=False)

    def offer_web_read(self, urls):
        if len(urls) != 1:
            self.add("Akasha", "Quel lien souhaitez-vous consulter ? Indiquez une seule URL.")
            return
        if self.intent_job is not None:
            self.add("Akasha", "Une demande est déjà en cours. Son résultat apparaîtra ici.")
            return
        try:
            self.pending_web = ReadReview(public_target(urls[0]))
        except PlanningError as error:
            self.add("Accès refusé", error.error.message)
            return
        self.add("Accord requis", f"Autorisez une requête HTTPS en lecture seule vers cette adresse.\n"
                 f"{self.pending_web.target.url}\nCet accord vaut pour une seule lecture et expire après cinq minutes.")
        self.offer("Autoriser la lecture", "read_web")

    def offer(self, title, action):
        self.action = action
        self.confirm.configure(text=title)
        self.confirm.pack(side="left", before=self.entry)

    def answer_audio(self, decision):
        pending, self.audio_decision = self.audio_decision, None
        if pending is not None:
            self.action = None
            self.confirm.pack_forget()
            self.refuse_audio.pack_forget()
            pending.set_result(decision)

    def update_project_label(self):
        label = str(self.project) if self.project is not None else "Aucun projet choisi"
        self.project_label.configure(text=label)

    def session_vault(self):
        if self.session_record is None:
            raise MemoryRefusal("storage_unavailable", "Ouvrez une session durable pour sceller une clé.")
        if self.vault is None:
            self.vault = SessionVault(self.tasks.directory, self.session_store)
        return self.vault

    def seal_request(self, request):
        try:
            value = admit_secret(request)
        except ValueError as error:
            self.add("Akasha", str(error))
            return True
        if value is None:
            return False
        try:
            handle = self.session_vault().seal(self.session_record.id, value)
        except VAULT_ERRORS:
            self.add("Akasha", "La clé n’a pas pu être scellée pour cette session.")
        else:
            self.add("Akasha", f"Clé scellée · {handle}")
        finally:
            clear(value)
        return True

    def open_vault(self):
        try:
            vault = self.session_vault()
        except VAULT_ERRORS:
            self.add("Akasha", "Le coffre est indisponible.")
        else:
            VaultWindow(self.parent, vault, self.session_record.id, VAULT_ERRORS)

    def refresh_session(self, record):
        self.session_record = record
        facts = {(fact.kind, fact.project_scope): fact.value for fact in record.facts}
        self.summary_depth = facts.get(("summary_depth", None), "standard")
        self.summary_detail.set(self.summary_depth == "detailed")
        observation = ""
        if self.project == record.active_project and record.active_project_scope:
            if mode := facts.get(("project_test", record.active_project_scope)):
                observation = f"Dernier repérage de cette session · {TEST_LABELS[mode]}"
        self.session_observation.configure(text=observation)

    def set_summary_depth(self):
        self.remember_session_fact("summary_depth", "detailed" if self.summary_detail.get() else "standard")

    def remember_session_fact(self, kind, value, *, project=None):
        try:
            self.session_store.remember(self.session_record.id, kind, value, project=project)
            self.refresh_session(self.session_store.open(self.session_record.id))
        except SESSION_WRITE_ERRORS:
            self.summary_detail.set(self.summary_depth == "detailed")
            self.add("Akasha", "Le contexte local n’a pas pu être enregistré.")

    def choose_project(self):
        chosen = filedialog.askdirectory(parent=self.parent, title="Choisir un projet pour la conversation", mustexist=True)
        if chosen:
            self.select_project(Path(chosen).resolve(), remember=True)
            self.change = self.test_file = self.action = None
            self.confirm.pack_forget()
        return bool(chosen)

    def select_project(self, project, *, remember=False):
        if remember and self.session_store is not None:
            try:
                self.session_store.bind_project(self.session_record.id, project)
            except SESSION_WRITE_ERRORS:
                self.add("Akasha", "Ce dossier reste accessible pour la conversation en cours.")
        if project != self.project:
            self.reader.stop()
            self.voice.erase()
            if self.intent_job is not None:
                self.intent_cancel.set()
            self.answer_audio("cancel")
            self.project = project
            self.pending_gap = None
            self.inspection = self.check_result = self.test_plan = None
            self.last_summary_project = None
            if self.action == "run_project_check":
                self.action = None
                self.confirm.pack_forget()
            self.update_project_label()
        if self.session_store is not None:
            try:
                self.refresh_session(self.session_store.open(self.session_record.id))
            except SESSION_WRITE_ERRORS:
                self.session_observation.configure(text="")

    def show_capabilities(self, include_notes):
        message = ("Collez une URL HTTPS pour consulter le texte d’une page publique.\n\n"
                   "Écrivez « Vérifie ce projet » avec le chemin de son dossier. Je vérifie les fichiers de "
                   "configuration et la syntaxe Python, puis je repère les tests que le bac peut lancer.\n\n"
                   f"Je peux aussi lire un fichier (« Lis value.py ») ou tester un remplacement dans le bac "
                   f"(« {REPLACEMENT_EXAMPLE} »). Le diff reste soumis à votre accord.")
        if self.communication is not None:
            message += "\nJe peux aussi résumer le projet à partir de sa documentation et comparer deux documents texte."
        if include_notes:
            message += "\nLe banc de démonstration est aussi disponible avec « Lance le banc Notes »."
        self.add("Akasha", message)
        if self.project is None:
            self.offer("Choisir un projet…", "choose_project")

    def request_intent(self, request, *, turn=0, refine_summary=False, image_consent=None, web_review=None):
        if self.intent_job is not None:
            self.add("Akasha", "J’analyse déjà une demande. Son résultat apparaîtra ici.")
            return
        self.pending_intent = None
        self.conversation_plan = self.intent_error = None
        self.conversation_steps = ()
        if web_review is not None:
            self.intent_cancel = cancelled = Event()
            self.intent_progress = SimpleQueue()
            audit_path = app_directory() / "web-audit.sqlite"
            job = self.tasks.scheduler.submit(lambda: web_review.collect(
                audit_path, approved=True, cancelled=cancelled.is_set))
            self.intent_job = (request, self.project, turn, job)
            self.add("Akasha", "Je consulte la page publique.")
            return
        if len(request) > 8000:
            self.add("Akasha", "Précisez l’objectif en 8 000 caractères maximum, avec le chemin des fichiers concernés.")
            return
        if self.session_store is not None:
            try:
                self.refresh_session(self.session_store.open(self.session_record.id))
            except SESSION_WRITE_ERRORS:
                self.summary_depth = "standard"
                self.summary_detail.set(False)
                self.session_observation.configure(text="")
        project = self.project
        communication, catalog, summary_depth = self.communication, self.catalog, self.summary_depth
        self.intent_cancel = cancelled = Event()
        self.intent_progress = progress = SimpleQueue()
        database = (self.tasks.directory / "capability-recovery.sqlite").resolve()
        translation = (lambda subject: compose_image_prompt(communication, subject)) if communication is not None else None
        recovery = Recovery(database, self.tasks.runtime, progress.put, cancelled.is_set, image_prompt=translation)
        if project is not None and database.is_relative_to(project):
            recovery = None

        def approve_audio(review):
            decision = Future()
            progress.put((review, decision))
            expires = datetime.fromisoformat(review.expires_at)
            while not cancelled.is_set():
                require_fresh(expires)
                try:
                    return decision.result(timeout=.1)
                except FutureTimeout:
                    continue
            raise InterruptedError("Transcription annulée.")

        def plan():
            refs = references(request)
            consent = None
            if image_consent is not None:
                pending = image_consent
                proposed = {"tool": GENERATE_IMAGE, "refs": [], "detail": pending.prompt}
                consent = (pending.review, pending.review.approval_sha256)
            elif refine_summary:
                proposed = {"tool": "project.summarize", "refs": [], "detail": ""}
            elif len(intent_parts(request)) == 1 and (media := explicit_media_step(request, refs)):
                proposed = media
            else:
                profile = communication_profile(communication)
                proposed = infer_intent(communication, profile["chat_template"], request, refs, catalog,
                                        selected=project is not None)
            return execute_intents(request, proposed, refs, project, catalog, recovery=recovery, image_consent=consent,
                                   default_summary_depth=summary_depth, audio_approval=approve_audio,
                                   audio_checkpoint=audio_checkpoint)

        def audio_checkpoint():
            if cancelled.is_set():
                raise InterruptedError("Transcription annulée.")

        self.intent_job = (request, project, turn, self.tasks.scheduler.submit(plan))
        self.add("Akasha", "J’analyse votre demande.")

    def poll_intent(self):
        if self.intent_job is None:
            return
        request, project, turn, job = self.intent_job
        if self.project == project:
            while True:
                try:
                    update = self.intent_progress.get_nowait()
                    if isinstance(update, tuple):
                        review, self.audio_decision = update
                        self.add("Akasha", describe_audio_download(review))
                        self.offer("Autoriser ce téléchargement", "download_audio_artifact")
                        self.refuse_audio.pack(side="left", before=self.entry)
                    else:
                        self.add("Akasha", update)
                except Empty:
                    break
        if not job.done():
            return
        self.intent_job = None
        self.answer_audio("cancel")
        if project != self.project:
            self.add("Akasha", "Le dossier a changé pendant l’analyse. Reformulez la demande pour ce dossier.")
            return
        try:
            replies = job.result()
        except PlanningError as error:
            replies = [error.error]
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self.add("Akasha", f"La demande n’a pas pu aboutir. {error}")
            return
        if isinstance(replies, Observation):
            collected_at = datetime.fromisoformat(replies.collected_at).astimezone().strftime("%d/%m/%Y à %H:%M")
            truncated = "\n[Extrait tronqué.]" if replies.truncated else ""
            self.add("Texte public relevé", f"{replies.url}\nRelevé le {collected_at}\n\n{replies.text}{truncated}",
                     narration_only=True)
            return

        self.conversation_steps = tuple(reply.plan for reply in replies if not isinstance(reply, AkashaError))
        if self.conversation_steps:
            self.conversation_plan = self.conversation_steps[0]
        for reply in replies:
            if isinstance(reply, AkashaError):
                self.intent_error = reply
                if review_id := reply.details.get("construction_review_id"):
                    self.pending_gap = GapReview(review_id)
                    self.offer("Préparer la proposition", "prepare_gap_proposal")
                if reply.code == ErrorCode.NEEDS_CLARIFICATION and not self.conversation_steps and turn < 2:
                    self.pending_intent = (request, turn + 1)
                    if reply.details.get("needs_project"):
                        self.offer("Choisir le dossier…", "choose_intent_project")
                self.add(GAP_LABELS.get(reply.details.get("outcome"), "Akasha"), reply.message)
                continue
            plan, output = reply.plan, reply.output
            if plan.capability in PROJECT_TOOLS:
                self.select_project(reply.project)
            if isinstance(output, ProjectCheck):
                self.show_inspection(output)
            elif isinstance(output, PendingImage):
                self.pending_image = request, output
                asset = output.review.artifact
                self.add("Akasha", f"Accord requis pour télécharger {asset.name} ({asset.size / 1_000_000:.2f} Mo).\n"
                         f"Version {asset.version}\nSource {asset.source}\n"
                         f"Licence {asset.license}\n{asset.license_url}\nSHA-256 {asset.sha256}")
                self.offer("Autoriser ce téléchargement", "download_image_artifact")
            elif isinstance(output, ImageResult):
                if plan.capability == "image.orient":
                    angle = output.proof["clockwise_degrees"]
                    self.show_generated_image(output, f"Orientation déterminée : {angle}° dans le sens horaire.")
                else:
                    self.show_generated_image(output)
            elif plan.capability == "documents.compare":
                if reply.diagnostic is not None:
                    self.add("Akasha", "J’ai vérifié un autre chemin de comparaison sur des documents synthétiques.")
                self.add("Akasha", f"Modifications entre {plan.inputs[0]} et {plan.inputs[1]}.")
                self.add("Comparaison", output, tag="code")
            elif plan.capability == "file.read":
                self.show_file(plan.inputs[0], output)
            elif plan.capability == "audio.meeting_minutes":
                from .meeting_minutes import display
                self.add("Compte rendu", display(output), narration_only=True)
            elif plan.capability == "audio.transcribe":
                from .whisper_pilot import display
                execution = output.get("execution", {})
                label = {"cuda": "GPU à chaud" if execution.get("reused") else "GPU",
                         "cpu": "CPU"}.get(execution.get("device"))
                self.add("Transcription · "+label if label else "Transcription", display(output))
            else:
                self.add("Akasha", output, narration_only=plan.capability == "project.summarize")
                if reply is replies[-1] and plan.capability == "project.summarize":
                    self.last_summary_project = reply.project

    def show_generated_image(self, result, message="Voici l’image générée dans Windows Sandbox."):
        preview = tk.PhotoImage(master=self.transcript, data=base64.b64encode(result.png), format="png")
        self.previews.append(preview)
        self.add("Akasha", message)
        self.transcript.configure(state="normal")
        self.transcript.image_create("end", image=preview)
        self.transcript.insert("end", "\n\n")
        self.transcript.see("end")
        self.transcript.configure(state="disabled")
        self.offer("Enregistrer l’image…", "save_generated_image")
        self.generated_image = result

    def check_project(self, name):
        if self.check_job is not None:
            self.add("Akasha", "Une vérification de projet est en cours. Son résultat apparaîtra ici.")
            return
        if name:
            if not DRIVE_PATH.match(name):
                self.add("Akasha", "Indiquez un chemin local complet ou choisissez le dossier à vérifier.")
                self.offer("Choisir et vérifier…", "choose_checked_project")
                return
            try:
                project = Path(name).resolve(strict=True)
                if not project.is_dir():
                    raise ValueError()
            except (OSError, RuntimeError, ValueError):
                self.add("Akasha", f"Impossible d’ouvrir le dossier {name}. Vérifiez le chemin ou choisissez le dossier.")
                self.offer("Choisir et vérifier…", "choose_checked_project")
                return
            self.select_project(project, remember=True)
        if self.project is None:
            self.add("Akasha", "Quel dossier souhaitez-vous vérifier ? Donnez-moi son chemin complet ou choisissez-le.")
            self.offer("Choisir et vérifier…", "choose_checked_project")
            return
        project = self.project
        self.conversation_plan = compile_local_plan("Vérifier le projet", "project.inspect", (str(project),), self.catalog)
        self.inspection = self.check_result = None
        self.check_job = (project, self.tasks.scheduler.submit(lambda: inspect_project(project)))
        self.add("Akasha", f"J’examine {project} en lecture seule.")

    def offer_tests(self, inspection):
        if inspection.test is None:
            self.add("Akasha", "Aucun test compatible avec le bac n’est prêt à lancer. Consultez le relevé de vérification.")
        else:
            self.add("Akasha", f"Confirmez le lancement de {inspection.test.label} dans Windows Sandbox.")
            self.offer("Lancer les tests dans le bac", "run_project_check")

    def start_project_check(self):
        inspection = self.inspection
        if inspection is None or inspection.test is None or self.check_job is not None:
            return
        node = inspection.test.mode == "node"
        runtime = installed_node(inspection.project) if node else self.tasks.runtime
        if runtime is None or not (runtime if node else runtime / "python.exe").is_file():
            self.add("Akasha", "Il me manque un exécutable Node.js dans le PATH pour ce test." if node else
                     "Choisissez le dossier Python portable pour lancer les tests dans Windows Sandbox.")
            self.offer("Lancer les tests dans le bac", "run_project_check")
            return
        capability = "project.test.node" if node else "project.test.python"
        self.test_plan = compile_local_plan(f"Exécuter {inspection.test.label}", capability,
                                            (str(inspection.project), *inspection.test.files), self.catalog, test=True)
        # Cette vérification locale n'alimente aucun cycle d'évolution.
        self.check_job = (inspection.project, self.tasks.scheduler.submit(lambda: run_project_check(inspection, runtime)))
        self.add("Akasha", f"Test demandé pour {inspection.project.name}. Le verdict apparaîtra ici.")

    def poll_check(self):
        if self.check_job is None or not self.check_job[1].done():
            return
        project, job = self.check_job
        self.check_job = None
        try:
            result = job.result()
        except (OSError, RuntimeError, ValueError) as error:
            message = f"Vérification de {project.name} interrompue. {error}"
        else:
            if isinstance(result, ProjectCheck):
                self.show_inspection(result)
                return
            duration = f"{result['wall_s']:.1f}".replace(".", ",")
            verdict = result.get("message", "Le test a réussi dans Windows Sandbox.")
            message = f"{project.name} · {result['test']}\n{verdict} Durée totale de {duration} s."
        if project == self.project:
            self.check_result = message
        self.add("Akasha", message)

    def show_inspection(self, inspection):
        message = inspection.summary()
        if inspection.project == self.project:
            self.inspection, self.check_result = inspection, message
            if self.session_record is not None and self.project in self.session_record.projects:
                mode = inspection.test.mode if inspection.test is not None else "none"
                self.remember_session_fact("project_test", mode, project=self.project)
            if inspection.test is not None and self.action is None and self.change is None:
                self.offer("Lancer les tests dans le bac", "run_project_check")
        self.add("Akasha", message)

    def read_file(self, name):
        if self.project is None and not self.choose_project():
            self.add("Akasha", "Choisissez d’abord le dossier du projet à lire.")
            return
        try:
            result = inspect_code(self.project, [name])
        except FileNotFoundError:
            self.add("Akasha", f"Le fichier {name} est introuvable dans le projet choisi.")
        except (OSError, RuntimeError, ValueError) as error:
            self.add("Akasha", str(error))
        else:
            self.show_file(name, result)

    def show_file(self, name, result):
        lines = "\n".join(f"{row['line']:>3}  {row['text']}{'…' if row['excerpt'] else ''}" for row in result["lines"])
        self.add(name, lines or "Le fichier est vide.", tag="code",
                 narration_only=Path(name).suffix.casefold() in {".txt", ".md", ".rst"})
        if result["more"]:
            self.add("Akasha", "L’aperçu est limité aux 80 premières lignes.")

    def set_test_file(self, name):
        self.test_file = None
        try:
            project_file(self.project, name)
        except FileNotFoundError:
            self.add("Akasha", "Test introuvable. Indiquez le chemin relatif d’un script de test existant.")
        except (OSError, RuntimeError, ValueError) as error:
            self.add("Akasha", str(error))
        else:
            self.test_file = name
            self.add("Akasha", f"Je testerai le remplacement dans {self.change.target} avec {name} sur une copie du projet.")
            self.offer("Tester le remplacement", "prepare_replacement")

    def start_replacement(self):
        if self.project_job is not None:
            self.add("Akasha", "Une validation de projet est en cours.")
            self.offer("Tester le remplacement", "prepare_replacement")
            return
        runtime = self.tasks.runtime
        if runtime is None or not (runtime / "python.exe").is_file():
            self.add("Akasha", "Choisissez le dossier Python portable pour lancer Windows Sandbox.")
            self.offer("Tester le remplacement", "prepare_replacement")
            return
        project, change, test = self.project, self.change, self.test_file
        output = self.tasks.directory / "proposals" / str(uuid4())

        def run():
            prepare(project, output, change.target, None, test, runtime,
                    text_change=(change.before, change.after), input_byte_limit=CODE_FILE_LIMIT)
            return preview_replacement(project, output)

        self.project_job = self.tasks.submit_project(run)
        self.change = self.test_file = self.proposal = self.project_error = None
        self.add("Akasha", "Validation demandée dans Windows Sandbox.")

    def show_project_result(self, *, include_check=True):
        if self.project_job is not None:
            self.add("Akasha", "Le test de la proposition est en cours.")
        elif include_check and self.check_job is not None:
            self.add("Akasha", "La vérification de projet est en cours.")
        elif include_check and self.check_result is not None:
            self.add("Akasha", self.check_result)
            if self.inspection is not None and self.inspection.test is not None:
                self.offer("Lancer les tests dans le bac", "run_project_check")
        elif self.project_error is not None:
            self.add("Akasha", self.project_error)
        elif self.proposal is not None:
            self.add("Akasha", f"La proposition pour {self.proposal.target} dans {self.proposal.project.name} "
                               "est disponible pour examen.")
            self.offer("Examiner le diff", "review_prepared")
        else:
            self.add("Akasha", "Ouvrez la proposition pour examiner le diff et le verdict du bac.")
            self.offer("Voir la proposition", "review")

    def confirm_action(self):
        action = self.action
        self.action = None
        self.confirm.pack_forget()
        if action == "download_audio_artifact":
            self.answer_audio("accept")
        elif action == "read_web" and self.pending_web is not None:
            review, self.pending_web = self.pending_web, None
            self.request_intent("Lire la page publique", web_review=review)
        elif action == "download_image_artifact" and self.pending_image is not None:
            request, pending = self.pending_image
            self.pending_image = None
            self.request_intent(request, image_consent=pending)
        elif action == "prepare_gap_proposal" and self.pending_gap is not None:
            self.prepare_gap_proposal()
        elif action == "save_generated_image":
            path = filedialog.asksaveasfilename(parent=self.parent, defaultextension=".png",
                                               filetypes=(("Image PNG", "*.png"),), initialfile="akasha-image.png")
            if path:
                try:
                    Path(path).write_bytes(self.generated_image.png)
                except OSError as error:
                    self.add("Akasha", f"L’image n’a pas pu être enregistrée. {error}")
        elif action == "notes":
            folder = self.launch_notes()
            if folder is None:
                self.add("Akasha", "Le banc Notes n’a pas démarré. Consultez l’état dans la fenêtre principale.")
            else:
                self.watched.add(folder)
                self.add("Akasha", "Le lancement est demandé. Le graphe affiche l’attente du bac et les étapes.")
        elif action == "project":
            self.prepare_project()
        elif action == "review":
            self.review_project()
        elif action == "choose_project":
            self.choose_project()
        elif action == "choose_checked_project":
            if self.choose_project():
                self.check_project("")
        elif action == "choose_intent_project":
            if self.pending_intent is not None and self.choose_project():
                request, turn = self.pending_intent
                self.request_intent(request, turn=turn)
        elif action == "run_project_check":
            self.start_project_check()
        elif action == "prepare_replacement":
            self.start_replacement()
        elif action == "review_prepared":
            self.review_prepared(self.proposal.project, self.proposal.proposal)

    def prepare_gap_proposal(self):
        review, self.pending_gap = self.pending_gap, None
        state = Recovery((self.tasks.directory / "capability-recovery.sqlite").resolve(), self.tasks.runtime,
                         lambda _: None, lambda: False)
        try:
            proposal = state.prepare_integration(review, approved=True)
        except (OSError, RuntimeError, sqlite3.Error, ValueError):
            self.add("Akasha", "La proposition est indisponible. Relancez la demande de transcription.")
            return
        details = [proposal["expected"], *proposal["evaluation"], *proposal["required_evidence"]]
        self.add("Proposition de spécialiste", "\n".join(details))

    def task_update(self, folder, report):
        if folder not in self.watched or report.get("status") not in ("passed", "failed"):
            return
        self.watched.remove(folder)
        self.reply_to_report(report)

    def reply_to_report(self, report):
        evidence, facts = result_summary(report)
        if self.communication is None or facts is None or self.responding:
            self.add("Résultat du banc", evidence, narration_only=True)
            return
        self.responding = True

        def generate():
            try:
                answer = communicate(self.communication, facts)
            except (OSError, RuntimeError, ValueError, KeyError, PlanningError):
                answer = None
            self.replies.put((answer + verification_details(report), True) if answer else (evidence, False))

        self.tasks.scheduler.submit(generate)

    def poll(self):
        self.poll_intent()
        self.poll_check()
        self.poll_project()
        try:
            answer, generated = self.replies.get_nowait()
        except Empty:
            pass
        else:
            self.responding = False
            self.add("Akasha · synthèse locale" if generated else "Résultat du banc", answer, narration_only=True)
        self.parent.after(150, self.poll)

    def poll_project(self):
        if self.project_job is None or not self.project_job.done():
            return
        job, self.project_job = self.project_job, None
        try:
            self.proposal = job.result()
        except (OSError, RuntimeError, ValueError) as error:
            self.project_error = f"La validation de la proposition a échoué. {error}"
            self.add("Akasha", self.project_error)
            return
        review = self.proposal
        self.add("Akasha", f"{review.test} a réussi dans Windows Sandbox pour {review.project.name}. "
                           "Le diff est prêt à examiner. Votre accord est requis pour l’appliquer.")
        self.add(review.target, review.diff[:4000], tag="code")
        if len(review.diff) > 4000:
            self.add("Akasha", "Le diff complet est disponible dans la fenêtre de proposition.")
        if self.action is None and self.change is None:
            self.offer("Examiner le diff", "review_prepared")
