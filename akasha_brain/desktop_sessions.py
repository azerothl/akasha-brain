"""Sélection et réouverture des conversations du bureau."""

from pathlib import Path
import sqlite3
import tkinter as tk
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
        self.notification = None
        self.body = ttk.Frame(parent, style="Data.TFrame")
        self.body.pack(fill="both", expand=True)
        try:
            self.store = SessionStore(tasks.directory / "conversation-sessions.sqlite", initialize=False)
            self.entries, record = self.store.startup()
            self.build_selector()
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
        self.selector = ttk.Menubutton(bar, text="Session")
        self.menu = tk.Menu(self.selector, tearoff=False, postcommand=self.refresh)
        self.selector.configure(menu=self.menu)
        self.selector.pack(side="left")
        ttk.Button(bar, text="Nouvelle session", command=self.new).pack(side="left", padx=8)

    def refresh(self):
        self.menu.delete(0, "end")
        try:
            self.entries = self.store.list()
        except SESSION_ERRORS:
            self.notify("Impossible de lire les sessions locales.")
            return
        for session_id, number in self.entries:
            self.menu.add_command(label=f"Session {number}", command=lambda selected=session_id: self.select(selected))

    def notify(self, text=""):
        if text:
            if self.notification is None:
                self.notification = ttk.Label(self.parent, style="DataError.TLabel")
            self.notification.configure(text=text)
            self.notification.pack(fill="x", padx=18, before=self.body)
        elif self.notification is not None:
            self.notification.pack_forget()

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
        self.selector.configure(text=record.title)
        self.notify()

    def new(self):
        try:
            session_id = self.store.create()
            self.entries = self.store.list()
            self.show(session_id)
        except SESSION_ERRORS:
            self.notify("Impossible de créer une session locale.")
        self.focus()

    def select(self, session_id):
        try:
            self.show(session_id)
        except SESSION_ERRORS:
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
