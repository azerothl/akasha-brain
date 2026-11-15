"""Examen et approbation d'une proposition de remplacement."""

from pathlib import Path
import sqlite3
import tkinter as tk
from tkinter import filedialog, ttk

from contracts.akasha_contracts.errors import ErrorCode

from .project import ReplacementReview, preview_replacement
from .project_common import ProjectError

REVIEW_ERRORS = (OSError, ValueError, KeyError, TypeError, sqlite3.Error)


class ReviewWindow:
    def __init__(self, root, project: Path | None, proposal: Path | None):
        self.window = tk.Toplevel(root)
        self.window.title("Akasha Brain - Aperçu du diff")
        self.window.geometry("1120x690")
        self.window.minsize(840, 500)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.project = project
        self.proposal = proposal
        self.review: ReplacementReview | None = None
        self.approved = tk.BooleanVar(self.window)
        self.build()
        self.load()

    def show(self):
        self.window.deiconify()
        self.window.lift()

    def close(self):
        self.approved.set(False)
        self.window.withdraw()

    def build(self):
        page = ttk.Frame(self.window, padding=20, style="Data.TFrame")
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        ttk.Label(page, text="Aperçu du diff", style="DataTitle.TLabel").grid(sticky="w", pady=(0, 12))

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
        self.approval_box = ttk.Checkbutton(controls, text="J’approuve ce diff pour ce projet",
                                           variable=self.approved, style="Data.TCheckbutton")
        self.approval_box.pack(side="left")
        self.apply_button = ttk.Button(controls, text="Appliquer le diff", style="Launch.TButton", command=self.apply)
        self.apply_button.pack(side="right")
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
        self.project_label.configure(text=f"Projet  {self.project}" if self.project else "Choisissez le dossier du projet.")
        self.proposal_label.configure(text=f"Proposition  {self.proposal}" if self.proposal else "Ouvrez un dossier de proposition.")
        self.validation.configure(text="")
        self.set_diff("")
        if self.project is None or self.proposal is None:
            self.feedback("Sélectionnez un projet et sa proposition validée.")
            return
        try:
            self.review = preview_replacement(self.project, self.proposal)
        except ProjectError as exc:
            self.feedback(str(exc), error=True)
        except REVIEW_ERRORS as exc:
            self.feedback(f"Proposition illisible. {exc}", error=True)
        else:
            self.set_diff(self.review.diff)
            self.validation.configure(text=f"{self.review.target}  ·  Test {self.review.test} réussi dans Windows Sandbox")
            self.approval_box.state(["!disabled"])
            self.apply_button.state(["!disabled"])
            self.feedback("Vérifiez le diff avant de l’approuver.")

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

    def invalidate_review(self):
        self.review = None
        self.approved.set(False)
        self.approval_box.state(["disabled"])
        self.apply_button.state(["disabled"])

    def apply(self):
        if self.review is None:
            return
        approved = self.approved.get()
        self.approved.set(False)
        try:
            result = self.review.apply(approved)
        except ProjectError as exc:
            error = exc.error
            message = str(exc)
            if error.code == ErrorCode.APPROVAL_REQUIRED:
                if approved:
                    self.invalidate_review()
                    message = "La proposition a changé. Ouvrez-la à nouveau pour examiner son diff."
                else:
                    message = "Accord requis. Cochez l’approbation du diff avant l’application."
            elif (error.details.get("reason") in {"project_changed", "proposal_changed"}
                  or error.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED):
                self.invalidate_review()
            self.feedback(message, error=True)
        except REVIEW_ERRORS as exc:
            self.invalidate_review()
            self.feedback(f"Application interrompue. {exc}", error=True)
        else:
            self.invalidate_review()
            self.feedback(f"Diff appliqué à {result['file']}.")

    def feedback(self, text: str, *, error: bool = False):
        self.message.configure(text=text, style="DataError.TLabel" if error else "DataMuted.TLabel")
