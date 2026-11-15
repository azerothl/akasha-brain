"""Écran desktop des accords de réutilisation et des demandes d'effacement."""

from datetime import datetime
from pathlib import Path
from queue import Empty, SimpleQueue
import sqlite3
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .planning import PlanningError
from .project_common import ProjectError
from .project_data import ProjectData
from .project_evolution import ARTIFACTS

CATEGORIES = {
    "source_code": "Code source", "diffs": "Diffs", "user_requests": "Demandes", "assistant_responses": "Réponses",
    "test_outputs": "Résultats des tests", "screenshots": "Captures", "ocr": "Texte OCR", "user_comments": "Commentaires",
}
STATUS = {
    "active": "Actif", "revoked": "Révoqué", "expired": "Expiré", "available": "Disponible",
    "consent_missing": "Accord introuvable", "consent_invalid": "Accord invalide",
    "consent_revoked": "Accord révoqué", "consent_inactive": "Accord hors validité",
    "consent_scope_mismatch": "Hors périmètre", "data_excluded": "Donnée exclue",
    "content_erasure_requested": "Effacement demandé", "content_expired": "Expirée",
    "pending": "En attente", "erased": "Effacé",
}
ERASURE_REASONS = {
    "replay_in_progress": "Rejeu en cours", "copy_unreachable": "Copie ou rapport inaccessible",
    "verification_incomplete": "Vérification incomplète", "key_unavailable": "Coffre de clés inaccessible",
}
DATA_ERRORS = (OSError, sqlite3.Error, ProjectError, PlanningError, ValueError)


def local_date(value: str | None) -> str:
    return datetime.fromisoformat(value).astimezone().strftime("%d/%m/%Y %H:%M") if value else "Sans échéance"


class DataWindow:
    def __init__(self, root, registry: Path, project: Path | None):
        self.window = tk.Toplevel(root)
        self.window.title("Akasha Brain - Données d’évolution")
        self.window.geometry("1120x660")
        self.window.minsize(900, 540)
        self.window.protocol("WM_DELETE_WINDOW", self.window.withdraw)
        self.registry = registry
        self.data = None
        self.snapshot = {}
        self.busy = False
        self.replies = SimpleQueue()
        self.build()
        if project is not None:
            self.open_project(project)
        self.window.after(150, self.poll)
        self.window.after(1200, self.poll_inventory)

    def show(self):
        self.window.deiconify()
        self.refresh()
        self.window.lift()

    def build(self):
        page = ttk.Frame(self.window, padding=20, style="Data.TFrame")
        page.pack(fill="both", expand=True)
        page.columnconfigure((0, 1), weight=1, uniform="data")
        page.rowconfigure(1, weight=3)
        page.rowconfigure(2, weight=2)

        header = ttk.Frame(page, style="Data.TFrame")
        header.grid(row=0, columnspan=2, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Données d’évolution", style="DataTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.choose = ttk.Button(header, text="Choisir un projet…", command=self.choose_project)
        self.choose.grid(row=0, column=1, sticky="ne", padx=(12, 0))
        self.project_label = ttk.Label(header, text="Choisissez le dossier du projet.", style="Data.TLabel")
        self.project_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 2))
        registry_label = ttk.Label(header, text=f"Registre local  {self.registry}", style="DataMuted.TLabel")
        registry_label.grid(row=2, column=0, columnspan=2, sticky="w")

        def wrap_paths(event):
            self.project_label.configure(wraplength=event.width)
            registry_label.configure(wraplength=event.width)

        header.bind("<Configure>", wrap_paths)

        consents = self.section(page, "Accords de réutilisation", row=1, column=0, padx=(0, 12))
        checks = ttk.Frame(consents, style="Data.TFrame")
        checks.pack(fill="x", pady=(0, 8))
        self.categories = {category: tk.BooleanVar(self.window) for category in ARTIFACTS}
        self.category_buttons = []
        for category, selected in self.categories.items():
            button = ttk.Checkbutton(checks, text=CATEGORIES[category], variable=selected,
                                     style="Data.TCheckbutton", command=self.update_actions)
            button.pack(side="left", padx=(0, 12))
            self.category_buttons.append(button)
        self.grant_button = ttk.Button(checks, text="Accorder", command=self.grant, style="Launch.TButton")
        self.grant_button.pack(side="right")
        self.revoke_button = ttk.Button(consents, text="Révoquer l’accord", command=self.revoke)
        self.revoke_button.pack(side="bottom", anchor="e", pady=(8, 0))
        self.consents = self.table(consents, (("Accord", 83), ("Catégories", 145), ("État", 75), ("Échéance", 118)), 5)

        copies = self.section(page, "Copies d’évolution", row=1, column=1)
        self.erase_button = ttk.Button(copies, text="Demander l’effacement…", command=self.request_erasure)
        self.erase_button.pack(side="bottom", anchor="e", pady=(8, 0))
        self.copies = self.table(copies, (("Copie", 83), ("Catégorie", 95), ("État", 125), ("Échéance", 118)), 6)

        erasures = self.section(page, "Demandes d’effacement", row=2, column=0, columnspan=2, pady=(14, 0))
        self.retry_button = ttk.Button(erasures, text="Reprendre l’effacement", command=self.retry)
        self.retry_button.pack(side="bottom", anchor="e", pady=(8, 0))
        self.erasures = self.table(erasures,
                                   (("Demande", 95), ("Date", 125), ("Copies", 54), ("État", 95), ("Motif", 230)), 4)

        self.message = ttk.Label(page, style="DataMuted.TLabel", text="Le périmètre dépend du dossier sélectionné.",
                                 wraplength=840)
        self.message.grid(row=3, columnspan=2, sticky="w", pady=(12, 0))
        self.update_actions()

    def section(self, parent, title, **grid):
        frame = ttk.Frame(parent, style="Data.TFrame")
        frame.grid(sticky="nsew", **grid)
        ttk.Label(frame, text=title, style="DataHeading.TLabel").pack(anchor="w", pady=(0, 8))
        return frame

    def table(self, parent, columns, height):
        frame = ttk.Frame(parent, style="Data.TFrame")
        frame.pack(fill="both", expand=True)
        names = [name for name, _ in columns]
        table = ttk.Treeview(frame, columns=names, show="headings", selectmode="browse", height=height,
                             style="Data.Treeview")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        scrollbar.pack(side="right", fill="y")
        table.configure(yscrollcommand=scrollbar.set)
        table.pack(side="left", fill="both", expand=True)
        for name, width in columns:
            table.heading(name, text=name)
            table.column(name, width=width, minwidth=min(width, 54))
        table.bind("<<TreeviewSelect>>", self.update_actions)
        return table

    def choose_project(self):
        folder = filedialog.askdirectory(parent=self.window, title="Choisir le dossier du projet", mustexist=True)
        if folder:
            self.open_project(Path(folder))

    def open_project(self, folder):
        try:
            data = ProjectData(folder, self.registry)
            snapshot = data.inventory()
        except DATA_ERRORS as exc:
            self.feedback(str(exc), error=True)
            return
        self.data = data
        for selected in self.categories.values():
            selected.set(False)
        self.project_label.configure(text=str(data.project))
        self.render(snapshot)
        self.feedback("Les accords portent sur la réutilisation locale pour l’évolution.")

    def render(self, snapshot):
        self.snapshot = snapshot
        self.fill(self.consents, (
            (row["consent_id"], (row["consent_id"][:8], ", ".join(CATEGORIES.get(key, key) for key in row["categories"]),
                                 STATUS.get(row["status"], row["status"]), local_date(row.get("expires_at"))))
            for row in snapshot["consents"]
        ))
        self.fill(self.copies, (
            (row["sample_id"], (row["sample_id"][:8], CATEGORIES.get(row["category"], row["category"]),
                                STATUS.get(row["status"], row["status"]),
                                local_date(row["expires_at"]))) for row in snapshot["copies"]
        ))
        self.fill(self.erasures, (
            (row["request_id"], (row["request_id"][:8], local_date(row["requested_at"]), row["count"],
                                 STATUS.get(row["status"], row["status"]),
                                 ERASURE_REASONS.get(row["reason"], row["reason"] or "")))
            for row in snapshot["erasures"]
        ))
        self.update_actions()

    @staticmethod
    def fill(table, records):
        selection = table.selection()
        table.delete(*table.get_children())
        for key, values in records:
            table.insert("", "end", iid=key, values=values)
        if selection and table.exists(selection[0]):
            table.selection_set(selection)

    def selected(self, table, inventory, key):
        selection = table.selection()
        if selection:
            return next((row for row in self.snapshot.get(inventory, []) if row[key] == selection[0]), None)
        return None

    def update_actions(self, _event=None):
        ready = self.data is not None and not self.busy
        consent = self.selected(self.consents, "consents", "consent_id")
        copy = self.selected(self.copies, "copies", "sample_id")
        request = self.selected(self.erasures, "erasures", "request_id")
        for button in self.category_buttons:
            button.state(["!disabled"] if ready else ["disabled"])
        for button, enabled in (
            (self.choose, not self.busy),
            (self.grant_button, ready and any(selected.get() for selected in self.categories.values())),
            (self.revoke_button, ready and consent and consent["status"] == "active"),
            (self.erase_button, ready and copy and copy["status"] != "content_erasure_requested"),
            (self.retry_button, ready and request and request["status"] == "pending"),
        ):
            button.configure(state="normal" if enabled else "disabled")

    def grant(self):
        data = self.data
        categories = [category for category, selected in self.categories.items() if selected.get()]
        self.act(data.grant, categories, "Accord enregistré.")

    def revoke(self):
        row = self.selected(self.consents, "consents", "consent_id")
        if row:
            self.act(self.data.revoke, row["consent_id"], "Accord révoqué. Le rejeu des copies liées est bloqué.")

    def request_erasure(self):
        row = self.selected(self.copies, "copies", "sample_id")
        if row and messagebox.askyesno("Effacer les copies d’évolution",
                                      "Effacer toutes les copies de cette proposition et leurs rapports de rejeu ?",
                                      parent=self.window, default="no"):
            self.act(self.data.erase, row["sample_id"], "Effacement vérifié.")

    def retry(self):
        row = self.selected(self.erasures, "erasures", "request_id")
        if row:
            self.act(self.data.erase, row["sample_id"], "Effacement vérifié.")

    def act(self, operation, value, success):
        self.busy = True
        self.update_actions()
        self.feedback("Opération en cours…")

        def run():
            try:
                result = operation(value)
            except Exception as exc:
                self.replies.put((None, str(exc)))
            else:
                self.replies.put((result, success))

        Thread(target=run, name="Akasha Données").start()

    def feedback(self, message, *, error=False):
        self.message.configure(text=message, style="DataError.TLabel" if error else "DataMuted.TLabel")

    def refresh(self):
        if self.data is None or self.busy:
            return
        try:
            snapshot = self.data.inventory()
        except DATA_ERRORS as exc:
            self.feedback(str(exc), error=True)
            return
        if snapshot != self.snapshot:
            self.render(snapshot)

    def poll_inventory(self):
        if self.window.winfo_viewable():
            self.refresh()
        self.window.after(1200, self.poll_inventory)

    def poll(self):
        try:
            result, message = self.replies.get_nowait()
        except Empty:
            pass
        else:
            self.busy = False
            if result and result["status"] == "pending":
                message = "Demande enregistrée. La réutilisation est bloquée pendant l’effacement."
            if result and result["status"] == "active":
                for selected in self.categories.values():
                    selected.set(False)
            self.feedback(message, error=result is None)
            self.refresh()
            self.update_actions()
        self.window.after(150, self.poll)
