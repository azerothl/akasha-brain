"""Examen et approbation d'une proposition sur un fichier du projet."""

from pathlib import Path
import sqlite3
import tkinter as tk
from tkinter import filedialog, ttk

from contracts.akasha_contracts.errors import ErrorCode

from .project import ProposalReview, preview_proposal, renew_approval
from .project_approval import expired
from .project_common import ProjectError

REVIEW_ERRORS = (OSError, ValueError, KeyError, TypeError, sqlite3.Error)
OPERATION_TITLES = {"replace": "Aperçu du diff", "delete": "Suppression d’un fichier", "move": "Déplacement d’un fichier"}


class ReviewWindow:
    def __init__(self, root, project: Path | None, proposal: Path | None):
        self.window = tk.Toplevel(root)
        self.window.title("Akasha Brain - Proposition du projet")
        self.window.geometry("1120x690")
        self.window.minsize(840, 500)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.project = project
        self.proposal = proposal
        self.review: ProposalReview | None = None
        self.approved = tk.BooleanVar(self.window)
        self.approved_operation = tk.BooleanVar(self.window)
        self.build()
        self.load()
        self.window.after(500, self.poll_approval)

    def show(self):
        self.window.deiconify()
        self.window.lift()

    def close(self):
        self.clear_approval()
        self.window.withdraw()

    def build(self):
        page = ttk.Frame(self.window, padding=20, style="Data.TFrame")
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self.heading = ttk.Label(page, style="DataTitle.TLabel")
        self.heading.grid(sticky="w", pady=(0, 12))

        sources = ttk.Frame(page, style="Data.TFrame")
        sources.grid(sticky="ew", pady=(0, 12))
        sources.columnconfigure(0, weight=1)
        self.project_label = ttk.Label(sources, style="Data.TLabel")
        self.project_label.grid(row=0, column=0, sticky="w", padx=(0, 12), pady=(0, 5))
        self.proposal_label = ttk.Label(sources, style="Data.TLabel")
        self.proposal_label.grid(row=1, column=0, sticky="w", padx=(0, 12))
        ttk.Button(sources, text="Choisir un projet…", command=self.choose_project).grid(
            row=0, column=1, sticky="ew", pady=(0, 5))
        ttk.Button(sources, text="Ouvrir une proposition…", command=self.choose_proposal).grid(
            row=1, column=1, sticky="ew")
        self.validation = ttk.Label(sources, style="DataMuted.TLabel")
        self.validation.grid(row=2, column=0, columnspan=2, sticky="w", pady=(7, 0))

        def wrap_paths(_event):
            for label in (self.project_label, self.proposal_label):
                label.configure(wraplength=sources.grid_bbox(0, 0)[2] - 12)

        sources.bind("<Configure>", wrap_paths)
        self.build_diff(page)

        controls = ttk.Frame(page, style="Data.TFrame")
        controls.grid(sticky="ew", pady=(12, 2))
        checks = ttk.Frame(controls, style="Data.TFrame")
        checks.pack(side="left")
        self.approval_box = ttk.Checkbutton(checks, text="J’approuve ce diff pour ce projet",
                                           variable=self.approved, style="Data.TCheckbutton")
        self.approval_box.pack(anchor="w")
        self.operation_box = ttk.Checkbutton(checks, variable=self.approved_operation, style="Data.TCheckbutton")
        self.apply_button = ttk.Button(controls, text="Appliquer le diff", style="Launch.TButton", command=self.apply)
        self.apply_button.pack(side="right", anchor="s")
        self.renew_button = ttk.Button(controls, text="Nouvelle demande d’accord", command=self.renew)
        self.message = ttk.Label(page, style="DataMuted.TLabel", wraplength=780)
        self.message.grid(sticky="w", pady=(8, 0))

    def build_diff(self, page):
        body = ttk.Frame(page, style="Data.TFrame")
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        color = ttk.Style(self.window)
        self.diff = tk.Text(body, wrap="none", font=("Consolas", 10), borderwidth=0, highlightthickness=1,
                            width=1, height=1, padx=12, pady=10,
                            bg=color.lookup("Data.Treeview", "background"), fg=color.lookup("Data.TLabel", "foreground"),
                            highlightbackground=color.lookup("Data.Treeview", "bordercolor"),
                            highlightcolor=color.lookup("Launch.TButton", "background"))
        self.diff.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(body, orient="vertical", command=self.diff.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(body, orient="horizontal", command=self.diff.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.diff.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.diff.tag_configure("added", foreground="#8CE1C1")
        self.diff.tag_configure("removed", foreground="#FF9DA8")
        self.diff.tag_configure("hunk", foreground="#8DBBFF")

    def choose_project(self):
        chosen = filedialog.askdirectory(parent=self.window, title="Choisir le dossier du projet", mustexist=True)
        if chosen:
            self.project = Path(chosen)
            self.load()

    def choose_proposal(self):
        chosen = filedialog.askdirectory(parent=self.window, title="Choisir le dossier de la proposition", mustexist=True)
        if chosen:
            self.proposal = Path(chosen)
            self.load()

    def load(self):
        self.invalidate_review()
        self.set_title("Proposition du projet")
        self.approval_box.configure(text="J’approuve cette proposition pour ce projet")
        self.operation_box.pack_forget()
        self.apply_button.configure(text="Appliquer")
        self.project_label.configure(text=f"Projet  {self.project}" if self.project else "Choisissez le dossier du projet.")
        self.proposal_label.configure(text=f"Proposition  {self.proposal}" if self.proposal else "Ouvrez un dossier de proposition.")
        self.validation.configure(text="")
        self.set_diff("")
        if self.project is None or self.proposal is None:
            self.feedback("Sélectionnez un projet et sa proposition validée.")
            return
        try:
            self.review = preview_proposal(self.project, self.proposal)
        except ProjectError as exc:
            self.feedback(str(exc), error=True)
        except REVIEW_ERRORS as exc:
            self.feedback(f"Proposition illisible. {exc}", error=True)
        else:
            self.show_review(self.review)

    def set_title(self, title):
        self.window.title(f"Akasha Brain - {title}")
        self.heading.configure(text=title)

    def show_review(self, review: ProposalReview):
        self.set_title(OPERATION_TITLES[review.operation])
        expires = review.approval_expires_at.astimezone()
        self.validation.configure(text=f"Test {review.test} réussi dans Windows Sandbox · Accord avant {expires:%d/%m %H:%M}")
        if review.operation == "replace":
            self.set_diff(review.diff)
            self.approval_box.configure(text="J’approuve ce diff pour ce projet")
            self.apply_button.configure(text="Appliquer le diff")
            self.feedback("Vérifiez le diff avant de l’approuver.")
        else:
            if review.operation == "delete":
                self.set_diff(f"Fichier à supprimer\n\n{review.target}")
                self.operation_box.configure(text="J’autorise la suppression du fichier affiché")
                self.apply_button.configure(text="Supprimer le fichier")
            else:
                self.set_diff(f"Source\n\n{review.target}\n\nDestination\n\n{review.destination}")
                self.operation_box.configure(text="J’autorise le déplacement vers la destination affichée")
                self.apply_button.configure(text="Déplacer le fichier")
            self.operation_box.pack(anchor="w", pady=(6, 0))
            self.operation_box.state(["!disabled"])
            self.feedback("Vérifiez les chemins avant d’approuver la proposition et d’autoriser l’opération.")
        self.approval_box.state(["!disabled"])
        self.apply_button.state(["!disabled"])
        if expired(review.approval_expires_at):
            self.expire_review()

    def set_diff(self, text: str):
        self.diff.configure(state="normal")
        self.diff.delete("1.0", "end")
        self.diff.insert("1.0", text)
        for number, line in enumerate(text.split("\n"), start=1):
            prefix = line[:1]
            tag = {"@": "hunk", "+": "added", "-": "removed"}.get(prefix)
            if tag:
                self.diff.tag_add(tag, f"{number}.0", f"{number}.end")
        self.diff.configure(state="disabled")

    def clear_approval(self):
        self.approved.set(False)
        self.approved_operation.set(False)

    def invalidate_review(self):
        self.review = None
        self.clear_approval()
        self.approval_box.state(["disabled"])
        self.operation_box.state(["disabled"])
        self.apply_button.state(["disabled"])
        self.renew_button.pack_forget()

    def poll_approval(self):
        if self.review is not None and expired(self.review.approval_expires_at):
            self.expire_review()
        self.window.after(500, self.poll_approval)

    def expire_review(self):
        self.invalidate_review()
        self.renew_button.pack(side="right", padx=8)
        self.feedback("Approbation expirée. Demandez un nouvel accord pour reprendre.", error=True)

    def renew(self):
        try:
            renew_approval(self.project, self.proposal)
        except (ProjectError, *REVIEW_ERRORS) as error:
            self.feedback(str(error), error=True)
        else:
            self.load()

    def apply(self):
        if self.review is None:
            return
        review = self.review
        approved = self.approved.get()
        approved_operation = self.approved_operation.get()
        self.clear_approval()
        try:
            result = review.apply(approved, approved_operation=approved_operation)
        except ProjectError as exc:
            error = exc.error
            message = str(exc)
            if error.code == ErrorCode.APPROVAL_EXPIRED:
                self.expire_review()
                return
            if error.code == ErrorCode.APPROVAL_REQUIRED:
                if error.details.get("risk_class") == "R3":
                    label = "la suppression" if review.operation == "delete" else "le déplacement"
                    message = f"Accord explicite requis pour {label}. Cochez les deux accords avant de réessayer."
                elif approved:
                    self.invalidate_review()
                    message = "La proposition a changé. Ouvrez-la à nouveau pour l’examiner."
                else:
                    message = "Accord requis. Approuvez la proposition avant l’application."
            elif (error.details.get("reason") in {"project_changed", "proposal_changed"}
                  or error.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED):
                self.invalidate_review()
            self.feedback(message, error=True)
        except REVIEW_ERRORS as exc:
            self.invalidate_review()
            self.feedback(f"Application interrompue. {exc}", error=True)
        else:
            self.invalidate_review()
            source = result["file"]
            if result.get("replayed"):
                message = "L’application précédente a été confirmée."
            elif review.operation == "delete":
                message = f"Fichier supprimé  {source}"
            elif review.operation == "move":
                message = f"Fichier déplacé  {source} → {result['destination']}"
            else:
                message = f"Diff appliqué à {source}."
            self.feedback(message)

    def feedback(self, text: str, *, error: bool = False):
        self.message.configure(text=text, style="DataError.TLabel" if error else "DataMuted.TLabel")
