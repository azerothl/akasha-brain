"""Conversation locale du desktop et passage explicite à un parcours évalué."""

from hashlib import sha256
import json
from pathlib import Path
from queue import Empty, SimpleQueue
import re
from tempfile import TemporaryDirectory
import tkinter as tk
from tkinter import ttk
from unicodedata import normalize

from bench.communication.templates import render_template
from bench.run_guided_repair import CHECKPOINTS, file_hash

from .desktop_tasks import latest_steps, test_counts
from .planning import PlanningError
from .rbitnet_session import server

PROMPT = Path(__file__).resolve().parents[1] / "bench" / "communication" / "qwen35-2b-fr-v2.json"
COMMUNICATION_CHECKPOINTS = {
    "engine": CHECKPOINTS["engine"],
    "model": "1b04acba824817554f4ce23639bc8495ff70453b8fcb047900c731521021f2c1",
    "tokenizer": "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42",
}


def route_request(request: str) -> str | None:
    words = set(re.findall(r"[a-z]+", normalize("NFKD", request.casefold()).encode("ascii", "ignore").decode()))
    if words & {"tache", "taches", "transfert"}:
        return None
    notes = bool(words & {"notes", "note"})
    project = bool(words & {"projet", "fichier", "diff", "proposition", "dependance"})
    if words & {"resultat", "resultats", "bilan", "verdict", "rapport"}:
        return "review" if project and not notes else "result"
    if notes == project:
        return None
    return "notes" if notes else "project"


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


def communicate(paths, facts: tuple[int, int, str]) -> str | None:
    if any(file_hash(getattr(paths, key)) != expected for key, expected in COMMUNICATION_CHECKPOINTS.items()):
        raise ValueError("Les fichiers du modèle de communication ne correspondent pas au gel.")
    data = json.loads(PROMPT.read_bytes())
    system = data["system"]
    if sha256(system.encode("utf-8")).hexdigest() != data["system_sha256"]:
        raise ValueError("La consigne de communication a changé.")
    passed, total, elapsed = facts
    fiche = (f"État=résultat constaté; objet=le banc Notes; auteur=le banc Notes; opération=exécuter les tests; "
             f"succès={passed}/{total} tests; durée totale={elapsed} secondes.")
    settings = data["settings"]
    with TemporaryDirectory(prefix="akasha-communication-") as work:
        with server(paths, Path(work), template=data["chat_template"]) as model:
            response, _ = model.chat([{"role": "system", "content": system},
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


class ConversationWindow:
    def __init__(self, root, launch_notes, prepare_project, review_project, latest_report, submit, communication=None):
        self.window = tk.Toplevel(root)
        self.window.title("Akasha Brain - Conversation")
        self.window.geometry("770x540")
        self.window.minsize(620, 420)
        self.window.protocol("WM_DELETE_WINDOW", self.window.withdraw)
        self.launch_notes, self.prepare_project, self.latest_report = launch_notes, prepare_project, latest_report
        self.submit = submit
        self.review_project = review_project
        self.communication = communication
        self.watched = set()
        self.replies = SimpleQueue()
        self.responding = False
        self.action = None
        self.build()
        self.add("Akasha", "Vous pouvez lancer le banc Notes, préparer une proposition ou consulter le dernier résultat Notes.")
        self.window.after(150, self.poll)

    def show(self):
        self.window.deiconify()
        self.window.lift()
        self.entry.focus_set()

    def build(self):
        page = ttk.Frame(self.window, padding=18, style="Data.TFrame")
        page.pack(fill="both", expand=True)
        ttk.Label(page, text="Conversation", style="DataTitle.TLabel").pack(anchor="w", pady=(0, 12))
        theme = ttk.Style(self.window)
        panel = ttk.Frame(page, style="Data.TFrame")
        panel.pack(fill="both", expand=True)
        self.transcript = tk.Text(panel, wrap="word", state="disabled", padx=12, pady=8, width=1, height=1,
                                  font=("Segoe UI", 11), bg=theme.lookup("Data.Treeview", "background"),
                                  fg=theme.lookup("Data.TLabel", "foreground"))
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.transcript.pack(side="left", fill="both", expand=True)
        self.transcript.tag_configure("speaker", font=("Segoe UI", 11, "bold"))
        controls = ttk.Frame(page, style="Data.TFrame")
        controls.pack(fill="x", pady=(10, 0))
        self.confirm = ttk.Button(controls, command=self.confirm_action)
        ttk.Button(controls, text="Envoyer", style="Launch.TButton", command=self.send).pack(side="right")
        self.entry = ttk.Entry(controls)
        self.entry.pack(side="left", fill="x", expand=True, padx=8)
        self.entry.bind("<Return>", self.send)

    def add(self, speaker, text):
        self.transcript.configure(state="normal")
        self.transcript.insert("end", speaker + "\n", "speaker")
        self.transcript.insert("end", text + "\n\n")
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def send(self, _event=None):
        request = self.entry.get().strip()
        if not request:
            return
        self.entry.delete(0, "end")
        self.add("Vous", request)
        self.action = route_request(request)
        self.confirm.pack_forget()
        if self.action == "notes":
            self.add("Akasha", "Le banc Notes vérifiera la réparation dans Windows Sandbox. Lancez-le quand vous êtes prêt.")
            self.offer("Lancer Notes")
        elif self.action == "project":
            ordered = render_template("État=à venir; étape 1=vous choisissez le dossier, le fichier et le test; "
                                      "étape 2=je prépare la proposition dans Windows Sandbox après votre lancement; "
                                      "étape 3=vous examinez la proposition avant de l’approuver.")
            self.add("Akasha", ordered)
            self.offer("Préparer un projet")
        elif self.action == "review":
            self.add("Akasha", "Vous pouvez examiner la proposition et son verdict dans la fenêtre du projet.")
            self.offer("Voir la proposition")
        elif self.action == "result":
            report = self.latest_report()
            if report is None:
                self.add("Akasha", "Aucun résultat Notes n’est encore disponible.")
            else:
                self.reply_to_report(report)
        else:
            self.add("Akasha", render_template(
                "État=info manquante; objet=si vous souhaitez lancer Notes, préparer un projet ou voir un résultat."
            ))

    def offer(self, title):
        self.confirm.configure(text=title)
        self.confirm.pack(side="left", before=self.entry)

    def confirm_action(self):
        action = self.action
        self.action = None
        self.confirm.pack_forget()
        if action == "notes":
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

    def task_update(self, folder, report):
        if folder not in self.watched or report.get("status") not in ("passed", "failed"):
            return
        self.watched.remove(folder)
        self.reply_to_report(report)

    def reply_to_report(self, report):
        evidence, facts = result_summary(report)
        if self.communication is None or facts is None or self.responding:
            self.add("Résultat du banc", evidence)
            return
        self.responding = True

        def generate():
            try:
                answer = communicate(self.communication, facts)
            except (OSError, RuntimeError, ValueError, KeyError, PlanningError):
                answer = None
            self.replies.put((answer + verification_details(report), True) if answer else (evidence, False))

        self.submit(generate)

    def poll(self):
        try:
            answer, generated = self.replies.get_nowait()
        except Empty:
            pass
        else:
            self.responding = False
            self.add("Akasha · synthèse locale" if generated else "Résultat du banc", answer)
        self.window.after(150, self.poll)
