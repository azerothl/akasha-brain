"""Sélection et réouverture des conversations du bureau."""

from pathlib import Path
import sqlite3
from tkinter import ttk

from .conversation_sessions import SessionStore
from .desktop_conversation import ConversationPane
from .memory_store import MemoryRefusal
from .project_common import ProjectError

SESSION_ERRORS = (MemoryRefusal, OSError, ProjectError, sqlite3.Error, ValueError)


class ConversationWorkspace:
    def __init__(self, parent, launch_notes, prepare_project, review_project, latest_report, tasks, *,
                 project, review_prepared, communication=None):
        self.parent = parent
        self.launch = launch_notes, prepare_project, review_project, latest_report, tasks
        self.settings = {"review_prepared": review_prepared, "communication": communication}
        self.sessions = {}
        self.current = None
        self.store = None
        self.notification = ttk.Label(parent, style="DataError.TLabel")
        self.notification.pack(fill="x", padx=18)
        self.body = ttk.Frame(parent, style="Data.TFrame")
        self.body.pack(fill="both", expand=True)
        try:
            self.store = SessionStore(tasks.directory / "conversation-sessions.sqlite")
            self.build_selector()
            entries, record = self.store.startup()
            self.set_entries(entries)
            if project is not None:
                self.store.bind_project(record.id, Path(project))
                record = self.store.open(record.id)
            self.render_session(record)
        except SESSION_ERRORS:
            self.notify("Le registre des sessions est indisponible. Cette conversation reste en mémoire.")
            self.show_volatile(project)

    def build_selector(self):
        bar = ttk.Frame(self.parent, style="Data.TFrame", padding=(18, 10, 18, 0))
        bar.pack(fill="x", before=self.body)
        ttk.Label(bar, text="Session", style="Data.TLabel").pack(side="left", padx=(0, 8))
        self.selector = ttk.Combobox(bar, state="readonly", width=20, postcommand=self.refresh)
        self.selector.pack(side="left")
        self.selector.bind("<<ComboboxSelected>>", self.select)
        ttk.Button(bar, text="Nouvelle session", command=self.new).pack(side="left", padx=8)

    def refresh(self):
        self.set_entries(self.store.list())

    def set_entries(self, entries):
        self.entries = entries
        self.selector.configure(values=tuple(f"Session {number}" for _, number in self.entries))

    def notify(self, text=""):
        self.notification.configure(text=text)

    def show_volatile(self, project):
        host = ttk.Frame(self.body, style="Data.TFrame")
        host.pack(fill="both", expand=True)
        self.current = ConversationPane(host, *self.launch, project=project, **self.settings)

    def show(self, session_id):
        self.render_session(self.store.open(session_id))

    def render_session(self, record):
        session_id = record.id
        if session_id not in self.sessions:
            host = ttk.Frame(self.body, style="Data.TFrame")
            conversation = ConversationPane(host, *self.launch, project=record.active_project, **self.settings,
                                            session=(self.store, record))
            self.sessions[session_id] = conversation
        else:
            conversation = self.sessions[session_id]
            conversation.refresh_session(record)
        if self.current is not None and self.current is not conversation:
            self.current.parent.pack_forget()
        self.current = conversation
        self.current.parent.pack(fill="both", expand=True)
        self.selector.set(record.title)
        self.notify()

    def new(self):
        try:
            session_id = self.store.create()
            self.refresh()
            self.show(session_id)
        except SESSION_ERRORS:
            self.notify("Impossible de créer une session locale.")
        self.focus()

    def select(self, _event):
        index = self.selector.current()
        if index < 0:
            return
        try:
            self.show(self.entries[index][0])
        except SESSION_ERRORS:
            if self.current is not None and self.current.session_record is not None:
                self.selector.set(self.current.session_record.title)
            self.notify("Impossible de rouvrir cette session.")
        self.focus()

    def focus(self):
        if self.current is not None:
            self.current.focus()

    def task_update(self, folder, report):
        for conversation in self.sessions.values():
            conversation.task_update(folder, report)
        if self.current is not None and self.current.session_record is None:
            self.current.task_update(folder, report)
