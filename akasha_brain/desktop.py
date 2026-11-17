"""Interface Windows du banc Notes et des données d'évolution locales."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty
import sqlite3
import tkinter as tk
from tkinter import filedialog, font, ttk

from .desktop_conversation import ConversationPane
from .desktop_data import DataWindow
from .desktop_project import ProjectWindow
from .desktop_review import ReviewWindow
from .desktop_settings import app_directory, configured_runtime, remember_runtime
from .desktop_tasks import (
    DEFAULT_EVOLUTION_BUDGET, NotesTasks, STATUSES, STEP_TITLES, checked_task_diff, latest_steps, layers,
    saved_tasks, test_counts,
)
from .model_resources import DEFAULT_VRAM_MIB
from .notes_evolution import STAGES, EvolutionBudget, rollback, set_evolution_paused
from .notes_repair import RbitnetPaths
from .phase6_runtime import Phase6Session
from .planning import PlanningError

BASE = "#111723"
PANEL = "#192232"
CANVAS = "#101722"
BORDER = "#334258"
TEXT = "#ECF1F8"
MUTED = "#AEBED2"
ACCENT = "#8CE1C1"
STATE_COLOR = {"waiting": MUTED, "running": "#8DBBFF", "passed": ACCENT, "failed": "#FF9DA8"}


def step_title(step_id: str) -> str:
    return STEP_TITLES.get(step_id, step_id)


class GraphView(tk.Canvas):
    WIDTH, HEIGHT, XGAP, YGAP = 254, 82, 34, 34

    def __init__(self, parent, family: str, on_select):
        super().__init__(parent, bg=CANVAS, highlightthickness=0, takefocus=True)
        self.family = family
        self.on_select = on_select
        self.steps = []
        self.bounds = {}
        self.trace = {}
        self.selected = None
        self.scale = 1.0
        self.offset = (0.0, 0.0)
        self.drag_start = None
        self.auto_fit = True
        self.bind("<Configure>", lambda _: self.fit() if self.auto_fit else self.draw())
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<B1-Motion>", self.drag)
        self.bind("<ButtonRelease-1>", lambda _: setattr(self, "drag_start", None))
        self.bind("<MouseWheel>", self.wheel)
        self.bind("<Down>", lambda _: self.follow(1))
        self.bind("<Up>", lambda _: self.follow(-1))
        self.bind("<plus>", lambda _: self.zoom(1.2))
        self.bind("<minus>", lambda _: self.zoom(1 / 1.2))

    def set_graph(self, plan, trace, selected, *, recenter=False):
        self.steps = plan["steps"]
        self.selected = selected
        self.trace = trace
        self.bounds = {}
        for level, steps in enumerate(layers(plan)):
            span = len(steps) * self.WIDTH + (len(steps) - 1) * self.XGAP
            for index, step in enumerate(steps):
                self.bounds[step["id"]] = (index * (self.WIDTH + self.XGAP) - span / 2,
                                           level * (self.HEIGHT + self.YGAP))
        if recenter:
            self.fit()
        else:
            self.draw()

    def fit(self):
        self.auto_fit = True
        if not self.bounds:
            return
        width = 2 * max(-point[0] for point in self.bounds.values())
        height = max(point[1] for point in self.bounds.values()) + self.HEIGHT
        view_width = max(self.winfo_width(), 240)
        view_height = max(self.winfo_height(), 240)
        self.scale = max(0.45, min(1.15, (view_width - 60) / width, (view_height - 56) / height))
        self.offset = (view_width / 2, (view_height - height * self.scale) / 2)
        self.draw()

    def point(self, x, y):
        return x * self.scale + self.offset[0], y * self.scale + self.offset[1]

    def box(self, step_id):
        x, y = self.bounds[step_id]
        return (*self.point(x, y), *self.point(x + self.WIDTH, y + self.HEIGHT))

    def zoom(self, factor, anchor=None):
        self.auto_fit = False
        x, y = anchor or (self.winfo_width() / 2, self.winfo_height() / 2)
        scale = max(0.45, min(2.3, self.scale * factor))
        ratio = scale / self.scale
        self.offset = (x + (self.offset[0] - x) * ratio, y + (self.offset[1] - y) * ratio)
        self.scale = scale
        self.draw()

    def wheel(self, event):
        self.zoom(1.13 if event.delta > 0 else 1 / 1.13, (event.x, event.y))
        return "break"

    def press(self, event):
        self.focus_set()
        for step_id in self.bounds:
            left, top, right, bottom = self.box(step_id)
            if left <= event.x <= right and top <= event.y <= bottom:
                self.on_select(step_id)
                return
        self.drag_start = (event.x, event.y)

    def drag(self, event):
        if self.drag_start is None:
            return
        self.auto_fit = False
        x, y = self.drag_start
        self.offset = (self.offset[0] + event.x - x, self.offset[1] + event.y - y)
        self.drag_start = (event.x, event.y)
        self.draw()

    def follow(self, direction):
        ids = list(self.bounds)
        if self.selected in ids:
            self.on_select(ids[(ids.index(self.selected) + direction) % len(ids)])
        return "break"

    def draw(self):
        self.delete("all")
        spacing = max(18, int(27 * self.scale))
        for x in range(int(self.offset[0] % spacing), self.winfo_width(), spacing):
            for y in range(int(self.offset[1] % spacing), self.winfo_height(), spacing):
                self.create_oval(x, y, x + 1, y + 1, fill="#344154", outline="")
        for step in self.steps:
            left, top, right, _ = self.box(step["id"])
            target_x = (left + right) / 2
            for source in step["depends_on"]:
                start_left, _, start_right, start_y = self.box(source)
                source_x = (start_left + start_right) / 2
                middle = (top + start_y) / 2
                active = self.trace.get(source, {}).get("status") == "passed" and step["id"] in self.trace
                self.create_line(source_x, start_y, source_x, middle, target_x, middle, target_x, top,
                                 width=2, fill=ACCENT if active else BORDER, arrow=tk.LAST)
        ratio = self.scale
        for step in self.steps:
            step_id = step["id"]
            left, top, right, bottom = self.box(step_id)
            status = self.trace.get(step_id, {}).get("status", "waiting")
            tint = STATE_COLOR[status]
            selected = step_id == self.selected
            self.create_rectangle(left, top, right, bottom, fill="#202E40" if selected else PANEL,
                                  outline=tint if selected else BORDER, width=2 if selected else 1)
            self.create_rectangle(left + 1, top + 1, left + 4 * ratio, bottom - 1, fill=tint, outline="")
            self.create_text(left + 16 * ratio, top + 16 * ratio, text=step_title(step_id), anchor="nw", fill=TEXT,
                             width=int((self.WIDTH - 30) * ratio), font=(self.family, max(7, int(11 * ratio)), "bold"))
            self.create_text(left + 16 * ratio, bottom - 15 * ratio, text=STATUSES[status], anchor="sw", fill=tint,
                             font=(self.family, max(7, int(9 * ratio))))


class Desktop:
    def __init__(self, root, tasks, *, data_registry=None, data_project=None, proposal=None, dependency_requests=(),
                 communication=None):
        self.root = root
        self.tasks = tasks
        self.data_registry = (data_registry or tasks.directory.parent / "project-evolution.db").resolve()
        self.data_project = data_project
        self.data_window = None
        self.proposal = proposal
        self.review_window = None
        self.project_window = None
        self.dependency_requests = dependency_requests
        self.communication = communication
        self.records = dict(saved_tasks(tasks.directory))
        self.current = None
        self.message = None
        self.step = tasks.plan["steps"][0]["id"]
        self.history_paths = []
        self.family = "Inter" if "Inter" in font.families(root) else "Segoe UI"
        root.title("Akasha Brain")
        root.geometry("1240x744")
        root.minsize(960, 600)
        root.configure(bg=BASE)
        self.styles()
        self.build()
        self.refresh_history()
        self.render(recenter=True)
        if tasks.evolution_db:
            self.poll_evolution()
        root.after_idle(self.conversation.focus)
        root.after(100, self.poll)

    def styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TButton", font=(self.family, 10), padding=(12, 7), foreground=TEXT, background=PANEL,
                        bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL, focuscolor=ACCENT)
        style.map("TButton", background=[("active", BORDER)], foreground=[("disabled", MUTED)])
        style.configure("Launch.TButton", background=ACCENT, foreground=BASE, font=(self.family, 10, "bold"),
                        bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("Launch.TButton", background=[("disabled", BORDER), ("active", "#AFEDD6")],
                  foreground=[("disabled", MUTED)])
        style.configure("Main.TNotebook", background=BASE, borderwidth=0, tabmargins=(18, 0, 0, 0))
        style.configure("Main.TNotebook.Tab", font=(self.family, 10, "bold"), foreground=MUTED,
                        background=BASE, borderwidth=0, padding=(16, 9))
        style.map("Main.TNotebook.Tab", foreground=[("selected", ACCENT)], background=[("selected", PANEL)])
        style.configure("Conversation.TEntry", fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT,
                        bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL, padding=(10, 8),
                        font=(self.family, 11))
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=BORDER, bordercolor=PANEL,
                        lightcolor=ACCENT, darkcolor=ACCENT, thickness=5)
        style.configure("Data.TFrame", background=BASE)
        style.configure("Data.TLabel", background=BASE, foreground=TEXT, font=(self.family, 10))
        style.configure("DataTitle.TLabel", background=BASE, foreground=TEXT, font=(self.family, 17, "bold"))
        style.configure("DataHeading.TLabel", background=BASE, foreground=TEXT, font=(self.family, 12, "bold"))
        style.configure("DataMuted.TLabel", background=BASE, foreground=MUTED, font=(self.family, 10))
        style.configure("DataError.TLabel", background=BASE, foreground=STATE_COLOR["failed"], font=(self.family, 10))
        style.configure("Data.TCheckbutton", background=BASE, foreground=TEXT, font=(self.family, 10),
                        indicatorbackground=PANEL, indicatorforeground=ACCENT, focuscolor=ACCENT)
        style.map("Data.TCheckbutton", background=[("active", PANEL)])
        style.configure("Data.Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        bordercolor=BORDER, rowheight=27, font=(self.family, 10))
        style.map("Data.Treeview", background=[("selected", BORDER)], foreground=[("selected", TEXT)])
        style.configure("Data.Treeview.Heading", background=BORDER, foreground=TEXT,
                        relief="flat", padding=(5, 5), font=(self.family, 9, "bold"))
        style.map("Data.Treeview.Heading", background=[("active", BORDER)])

    def label(self, parent, text="", *, bg=BASE, fg=TEXT, size=10, bold=False, **options):
        return tk.Label(parent, text=text, bg=bg, fg=fg, font=(self.family, size, "bold" if bold else "normal"),
                        anchor="w", **options)

    def build(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        header = tk.Frame(self.root, bg=BASE, padx=22, pady=16)
        header.grid(row=0, column=0, sticky="ew")
        task_header = tk.Frame(header, bg=BASE)
        task_header.pack(fill="x")
        heading = tk.Frame(task_header, bg=BASE)
        heading.pack(side="left")
        self.label(heading, "Akasha Brain", size=17, bold=True).pack(anchor="w")
        self.launch_button = ttk.Button(task_header, text="Lancer Notes", style="Launch.TButton", command=self.launch)
        self.launch_button.pack(side="right")
        ttk.Button(task_header, text="Python portable…", command=self.choose_runtime).pack(side="right", padx=10)
        ttk.Button(task_header, text="Données", command=self.open_data).pack(side="right")
        ttk.Button(task_header, text="Proposition du projet", command=self.open_review).pack(side="right", padx=(0, 10))
        ttk.Button(task_header, text="Préparer un projet", command=self.open_project).pack(side="right", padx=(0, 10))
        if self.tasks.evolution_db:
            self.build_evolution(header)
        elif self.tasks.integrated is not None:
            bar = tk.Frame(header, bg=PANEL, padx=12, pady=8)
            bar.pack(fill="x", pady=(12, 0))
            self.integrated_label = self.label(bar, bg=PANEL, fg=MUTED, size=9)
            self.integrated_label.pack(side="left")
            self.integrated_button = ttk.Button(bar, command=self.toggle_integrated_pause)
            self.integrated_button.pack(side="right")
            self.integrated_rollback = ttk.Button(bar, text="Retour à la référence", command=self.rollback_integrated)
            self.integrated_rollback.pack(side="right", padx=8)
            self.update_integrated()

        self.tabs = ttk.Notebook(self.root, style="Main.TNotebook")
        self.tabs.grid(row=1, column=0, sticky="nsew")
        conversation_tab = ttk.Frame(self.tabs, style="Data.TFrame")
        self.execution_tab = tk.Frame(self.tabs, bg=BASE)
        self.execution_tab.columnconfigure(1, weight=1)
        self.execution_tab.rowconfigure(0, weight=1)
        self.tabs.add(conversation_tab, text="Conversation")
        self.tabs.add(self.execution_tab, text="Exécutions")
        self.conversation = ConversationPane(
            conversation_tab, lambda: self.launch(show_execution=False), self.open_project, self.open_review,
            self.latest_notes_report, self.tasks, project=self.data_project, review_prepared=self.review_prepared,
            communication=self.communication,
        )

        sidebar = tk.Frame(self.execution_tab, bg=PANEL, padx=16, pady=16)
        sidebar.grid(row=0, column=0, sticky="nsew")
        self.label(sidebar, "Exécutions", bg=PANEL, size=12, bold=True).pack(fill="x", pady=(0, 12))
        ttk.Button(sidebar, text="Voir le plan Notes", command=self.show_plan).pack(fill="x", pady=(0, 12))
        self.history = tk.Listbox(sidebar, width=27, bg=PANEL, fg=TEXT, selectbackground=BORDER, selectforeground=TEXT,
                                  font=(self.family, 10), borderwidth=0, highlightthickness=1,
                                  highlightbackground=PANEL, highlightcolor=ACCENT, activestyle="none", exportselection=False)
        self.history.pack(fill="both", expand=True)
        self.history.bind("<<ListboxSelect>>", self.select_task)

        center = tk.Frame(self.execution_tab, bg=CANVAS)
        center.grid(row=0, column=1, sticky="nsew", padx=1)
        toolbar = tk.Frame(center, bg=CANVAS, padx=16, pady=12)
        toolbar.pack(fill="x")
        heading = tk.Frame(toolbar, bg=CANVAS)
        heading.pack(side="left", fill="x")
        self.label(heading, "Graphe d’exécution", bg=CANVAS, size=12, bold=True).pack(anchor="w")
        self.graph_version = self.label(heading, bg=CANVAS, fg=MUTED, size=9)
        self.graph_version.pack(anchor="w", pady=(3, 0))
        ttk.Button(toolbar, text="Centrer", command=lambda: self.graph.fit()).pack(side="right")
        ttk.Button(toolbar, text="+", width=2, command=lambda: self.graph.zoom(1.2)).pack(side="right", padx=4)
        ttk.Button(toolbar, text="−", width=2, command=lambda: self.graph.zoom(1 / 1.2)).pack(side="right")
        self.graph = GraphView(center, self.family, self.select_step)
        self.graph.pack(fill="both", expand=True)
        self.label(center, "Molette pour zoomer · Glisser le fond pour déplacer", bg=CANVAS, fg=MUTED, size=9,
                   padx=16, pady=12).pack(fill="x")

        inspector = tk.Frame(self.execution_tab, bg=PANEL, padx=18, pady=16)
        inspector.grid(row=0, column=2, sticky="nsew")
        self.label(inspector, "Inspection du nœud", bg=PANEL, size=12, bold=True).pack(fill="x", pady=(0, 15))
        self.detail = tk.Text(inspector, width=34, height=8, wrap="word", bg=PANEL, fg=TEXT, borderwidth=0,
                              highlightthickness=1, highlightbackground=PANEL, highlightcolor=ACCENT,
                              font=(self.family, 10), padx=0, pady=0)
        self.detail.pack(fill="both", expand=True)
        self.detail.tag_configure("title", font=(self.family, 13, "bold"), spacing3=10)
        self.detail.tag_configure("caption", foreground=MUTED, spacing1=5, spacing3=3)
        self.detail.configure(state="disabled")

        footer = tk.Frame(self.root, bg=BASE, padx=22, pady=13)
        footer.grid(row=2, column=0, sticky="ew")
        self.task_status = self.label(footer, size=10, bold=True)
        self.task_status.pack(side="left")
        self.progress = ttk.Progressbar(footer, orient="horizontal", length=128, mode="determinate")
        self.progress.pack(side="right")
        self.task_time = self.label(footer, fg=MUTED)
        self.task_time.pack(side="right", padx=12)
        self.tabs.bind("<<NotebookTabChanged>>", self.tab_changed)

    def open_data(self):
        if self.data_window is None:
            self.data_window = DataWindow(self.root, self.data_registry, self.data_project)
        self.data_window.show()

    def tab_changed(self, _event):
        if self.tabs.select() == str(self.execution_tab):
            self.root.after_idle(self.graph.fit)
        else:
            self.conversation.focus()

    def latest_notes_report(self):
        finished = (record for record in self.records.values() if record["status"] in ("passed", "failed"))
        return max(finished, key=lambda record: record["created_at"], default=None)

    def open_review(self):
        if self.review_window is None:
            self.review_window = ReviewWindow(self.root, self.selected_project(), self.proposal)
        self.review_window.show()

    def selected_project(self):
        selected = self.data_window.data if self.data_window is not None else None
        return selected.project if selected is not None else self.data_project

    def open_project(self):
        if self.project_window is None:
            self.project_window = ProjectWindow(
                self.root, self.selected_project(), self.tasks.directory / "proposals", lambda: self.tasks.runtime,
                self.tasks.submit_project, self.review_prepared, self.dependency_requests,
            )
        self.project_window.show()

    def review_prepared(self, project, proposal):
        self.data_project, self.proposal = project, proposal
        if self.review_window is not None:
            self.review_window.project, self.review_window.proposal = project, proposal
            self.review_window.load()
        else:
            self.review_window = ReviewWindow(self.root, project, proposal)
        self.review_window.show()

    def build_evolution(self, header):
        bar = tk.Frame(header, bg=PANEL, padx=12, pady=8)
        bar.pack(fill="x", pady=(12, 0))
        for title, attribute in (("Version active", "active_version"), ("Version candidate", "candidate_version")):
            block = tk.Frame(bar, bg=PANEL)
            block.pack(side="left", padx=(0, 24))
            self.label(block, title, bg=PANEL, fg=MUTED, size=9).pack(anchor="w")
            version = self.label(block, bg=PANEL, bold=True)
            version.pack(anchor="w")
            setattr(self, attribute, version)

        self.evolution_message = self.label(bar, bg=PANEL, size=9, justify="left", wraplength=170)
        self.evolution_message.pack(side="left", fill="x", expand=True)
        actions = (
            ("Retour arrière", rollback),
            ("Reprendre", lambda path: set_evolution_paused(path, False)),
            ("Pause", lambda path: set_evolution_paused(path, True)),
        )
        self.evolution_buttons = []
        for title, action in actions:
            button = ttk.Button(bar, text=title, command=lambda action=action: self.control_evolution(action))
            button.pack(side="right", padx=(6, 0))
            self.evolution_buttons.append(button)

    def control_evolution(self, action):
        try:
            action(self.tasks.evolution_db)
        except (OSError, sqlite3.Error, PlanningError) as error:
            self.evolution_message.configure(text=str(error), fg=STATE_COLOR["failed"])
            return
        self.refresh_evolution()

    def poll_evolution(self):
        self.root.after(800, self.poll_evolution)
        self.refresh_evolution()

    def refresh_evolution(self):
        previous = self.tasks.plan
        try:
            state = self.tasks.read_evolution()
        except (OSError, sqlite3.Error) as error:
            self.evolution_message.configure(text=str(error), fg=STATE_COLOR["failed"])
            for button in self.evolution_buttons:
                button.state(["disabled"])
            return
        for widget, plan in ((self.active_version, state["active"]), (self.candidate_version, state["candidate"])):
            widget.configure(text=f"{plan['graph_id']} · v{plan['graph_version']}" if plan else "Aucune")
        latest = state["latest"]
        event = latest.get("event")
        reason = latest.get("details", {}).get("reason")
        if state["paused"]:
            pending = self.tasks.scheduler.working_in_background and event in ("pause_requested", "trial_started")
            label = "Pause demandée" if pending else "Évolution en pause"
        elif event in ("trial_started", "trial_finished"):
            stage = STAGES.index(latest["details"]["stage"]) + 1
            label = f"Essai candidat {stage}/{len(STAGES)}" if event == "trial_started" else f"{stage}/{len(STAGES)} essais terminés"
        else:
            label = {"activated": "Candidate activée", "rolled_back": "Version précédente rétablie",
                     "waiting": "Aucun candidat compatible" if reason == "no_compatible_candidate"
                     else "Cycle arrêté par le budget", "retained": "Version active conservée",
                     "synthetic_reference_started": "Vérification de la référence synthétique",
                     "interactive_priority": "Tâche interactive prioritaire",
                     "triggered": "Évolution planifiée",
                     "resume_requested": "Évolution autorisée"}.get(event, "Évolution prête")
        self.evolution_message.configure(text=label, fg=MUTED)
        enabled = (state["can_rollback"] and not self.tasks.busy, state["paused"],
                   not state["paused"] and state["candidate"] is not None)
        for button, available in zip(self.evolution_buttons, enabled):
            button.configure(state="normal" if available else "disabled")
        if self.current is None and self.tasks.plan != previous:
            self.render(recenter=True)

    def choose_runtime(self):
        selected = filedialog.askdirectory(parent=self.root, title="Choisir le dossier Python portable")
        if selected and (Path(selected) / "python.exe").is_file():
            try:
                remember_runtime(Path(selected))
            except OSError as error:
                self.message = f"Impossible d’enregistrer le dossier Python portable. {error}"
            else:
                self.tasks.runtime = Path(selected)
                self.message = None
            self.update_status()
        elif selected:
            self.message = "python.exe est introuvable dans ce dossier."
            self.update_status()

    def record(self):
        return self.records[self.current] if self.current is not None else {"graph": self.tasks.plan, "trace": []}

    def show_plan(self):
        self.message = None
        self.history.selection_clear(0, tk.END)
        self.current = None
        self.render(recenter=True)

    def select_task(self, _event):
        selected = self.history.curselection()
        if selected:
            self.message = None
            self.current = self.history_paths[selected[0]]
            self.render(recenter=True)

    def select_step(self, step_id):
        self.step = step_id
        self.render()

    def refresh_history(self):
        self.history_paths = sorted(self.records, key=lambda path: self.records[path]["created_at"], reverse=True)
        self.history.delete(0, tk.END)
        for index, path in enumerate(self.history_paths):
            record = self.records[path]
            started = datetime.fromisoformat(record["created_at"]).astimezone()
            self.history.insert(tk.END, f"{started:%d/%m %H:%M}  ·  {STATUSES[record['status']]}")
            if path == self.current:
                self.history.selection_set(index)

    def launch(self, *, show_execution=True):
        try:
            self.current, record = self.tasks.start()
        except (OSError, RuntimeError, sqlite3.Error, PlanningError) as error:
            self.message = str(error)
            self.update_status()
            return None
        self.message = None
        self.records[self.current] = record
        self.step = record["graph"]["steps"][0]["id"]
        self.refresh_history()
        self.render(recenter=True)
        if show_execution:
            self.tabs.select(self.execution_tab)
        return self.current

    def render(self, *, recenter=False):
        record = self.record()
        plan = record["graph"]
        steps = {step["id"]: step for step in plan["steps"]}
        if self.step not in steps:
            self.step = next(iter(steps))
        trace = latest_steps(record)
        self.graph_version.configure(text=f"{plan['graph_id']} · v{plan['graph_version']}")
        self.graph.set_graph(plan, trace, self.step, recenter=recenter)
        self.render_detail(steps[self.step], trace.get(self.step, {}))
        self.update_status()

    def render_detail(self, step, row):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", tk.END)
        self.detail.insert(tk.END, step_title(step["id"]) + "\n", "title")
        status = row.get("status", "waiting")
        self.detail.insert(tk.END, f"{STATUSES[status]}\n")
        if row.get("wall_s") is not None:
            self.detail.insert(tk.END, f"{row['wall_s']:.2f} s\n")
        if row.get("attempt") is not None:
            self.detail.insert(tk.END, f"Tentative {row['attempt']}\n")
        self.detail.insert(tk.END, "\nCapacité\n", "caption")
        self.detail.insert(tk.END, f"{step['capability_id']}\nv{step['version']}\n")
        self.detail.insert(tk.END, "\nDépendances\n", "caption")
        self.detail.insert(tk.END, "\n".join(map(step_title, step["depends_on"])) or "Aucune")
        result = row.get("result", {})
        if residency := result.get("residency"):
            self.detail.insert(tk.END, "\n\nRessources\n", "caption")
            for key, label in (("ram_reserved_mib", "RAM réservée"), ("vram_reserved_mib", "VRAM réservée"),
                               ("host_ram_free_mib", "RAM hôte disponible à l’admission"),
                               ("device_vram_free_mib", "VRAM disponible à l’admission")):
                if type(residency.get(key)) is int:
                    self.detail.insert(tk.END, f"{label}  {residency[key]} Mio\n")
            if residency.get("lease_s") is not None:
                self.detail.insert(tk.END, f"Bail  {residency['lease_s']:.2f} s\n")
        if counts := test_counts(result):
            self.detail.insert(tk.END, "\n\nVérifications\n", "caption")
            self.detail.insert(tk.END, f"Tests  {counts[0]}/{counts[1]}\n")
        if "sqlite_verdict" in result:
            self.detail.insert(tk.END, f"SQLite  {STATUSES.get(result['sqlite_verdict'], result['sqlite_verdict'])}\n")
        if result.get("diff_applied"):
            self.detail.insert(tk.END, "\nDiff appliqué dans le bac\n")
            if self.current is not None and (diff := checked_task_diff(self.current, row)) is not None:
                self.detail.insert(tk.END, "\nDiff vérifié\n", "caption")
                self.detail.insert(tk.END, diff)
        if result.get("reference_sha256_verified_in_guest"):
            self.detail.insert(tk.END, "\nEmpreinte vérifiée dans le bac\n")
        if "desktop" in result:
            self.detail.insert(tk.END, "\nOCR et SQLite après relance\n" + ("Réussis" if all(result["desktop"].values()) else "Échec"))
        if error := self.record().get("error"):
            self.detail.insert(tk.END, "\n\nErreur\n", "caption")
            self.detail.insert(tk.END, error.get("message", "Exécution interrompue."))
        self.detail.configure(state="disabled")

    def update_status(self):
        record = self.record()
        ready = self.tasks.runtime is not None and (self.tasks.runtime / "python.exe").is_file()
        self.launch_button.configure(state="normal" if ready and not self.tasks.busy else "disabled")
        total = len(record["graph"]["steps"])
        trace = latest_steps(record)
        passed = sum(trace.get(step["id"], {}).get("status") == "passed" for step in record["graph"]["steps"])
        self.progress.configure(maximum=total, value=passed)
        if self.message is not None:
            self.task_status.configure(text=self.message, fg=STATE_COLOR["failed"])
            return
        if self.current is None:
            self.task_status.configure(text="Plan prêt" if ready else "Choisir le dossier Python portable", fg=TEXT)
            self.task_time.configure(text="")
            return
        status = record["status"]
        label = STATUSES[status]
        if status == "waiting":
            label = "En attente du bac"
        elif status == "running" and not record.get("trace"):
            label = "Préparation de Windows Sandbox"
        self.task_status.configure(text=f"{label} · {passed}/{total} étapes", fg=STATE_COLOR[status])
        duration = record.get("wall_s")
        if duration is None and status == "running":
            duration = (datetime.now(timezone.utc) - datetime.fromisoformat(record["created_at"])).total_seconds()
        self.task_time.configure(text=f"{max(0, duration):.1f} s" if duration is not None else "")

    def poll(self):
        self.root.after(150, self.poll)
        if self.tasks.integrated is not None:
            self.update_integrated()
        changed = False
        while True:
            try:
                folder, record = self.tasks.updates.get_nowait()
            except Empty:
                break
            self.records[folder] = record
            self.conversation.task_update(folder, record)
            changed = True
        if changed:
            self.refresh_history()
            self.render()

    def update_integrated(self):
        state = self.tasks.integrated_status
        jobs = state["jobs"]
        activity = ("Suivi en pause" if state["paused"] else "Suivi en cours"
                    if self.tasks.scheduler.working_in_background else f"{jobs.get('waiting', 0)} suivi(s) en attente")
        if jobs.get("failed", 0) or jobs.get("interrupted", 0):
            activity += f" · {jobs.get('failed', 0) + jobs.get('interrupted', 0)} suivi(s) interrompu(s) ou en échec"
        self.integrated_label.configure(text=f"Autonomie {state['autonomy_phase']} · {activity}")
        self.integrated_button.configure(text="Reprendre" if state["paused"] else "Pause")
        busy = self.tasks.busy or self.tasks.scheduler.working_in_background
        self.integrated_rollback.configure(state="normal" if state["autonomy_phase"] == 6 and not busy else "disabled")

    def toggle_integrated_pause(self):
        try:
            self.tasks.integrated.set_paused(not self.tasks.integrated_status["paused"])
            self.tasks.schedule_integrated(self.tasks.runtime)
        except (OSError, RuntimeError, sqlite3.Error) as error:
            self.message = str(error)
            self.update_status()
        else:
            self.update_status()

    def rollback_integrated(self):
        try:
            self.tasks.integrated_status = self.tasks.integrated.request_rollback()
            self.message = "Les politiques de référence sont actives."
        except (OSError, RuntimeError, PlanningError, sqlite3.Error) as error:
            self.message = str(error)
        self.update_status()
        self.update_integrated()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-runtime", type=Path)
    parser.add_argument("--runs", type=Path, default=app_directory() / "runs")
    parser.add_argument("--rbitnet", nargs=3, type=Path, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
    parser.add_argument("--cuda-library", type=Path, help="Bibliothèque CUDA Rbitnet qualifiée pour Notes")
    parser.add_argument("--model-vram-mib", type=int, default=DEFAULT_VRAM_MIB, help="Plafond VRAM du modèle CUDA")
    parser.add_argument("--communication", nargs=3, type=Path, metavar=("BINAIRE", "GGUF", "TOKENIZER"),
                        help="Qwen3.5-2B CPU pour interpréter les demandes libres et synthétiser les résultats Notes")
    parser.add_argument("--rapidocr", action="store_true")
    parser.add_argument("--evolution-db", type=Path, help="Registre d’évolution du banc synthétique Notes")
    parser.add_argument("--integrated-session", type=Path, help="Session de phase 6 qualifiée pour le banc Notes")
    parser.add_argument("--integrated-key", type=Path, help="Clé locale de décision de la session de phase 6")
    defaults = DEFAULT_EVOLUTION_BUDGET
    parser.add_argument("--evolution-wall-s", type=int, default=defaults.wall_s, help="Durée du cycle candidat")
    parser.add_argument("--evolution-max-trials", type=int, default=defaults.max_trials, help="Nombre d’essais candidats")
    parser.add_argument("--evolution-cpu-threads", type=int, default=defaults.cpu_threads, help="Taille des pools CPU Rbitnet")
    parser.add_argument("--evolution-model-ram-mb", type=int, default=defaults.model_ram_mb, help="Mémoire Rbitnet en Mio")
    parser.add_argument("--data-db", type=Path, help="Registre des données du parcours projet")
    parser.add_argument("--project", "--data-project", dest="data_project", type=Path,
                        help="Dossier initial des écrans projet")
    parser.add_argument("--proposal", type=Path, help="Dossier initial de la proposition à examiner")
    parser.add_argument("--dependency-request", action="append", type=Path, default=[],
                        help="Dossier d’une demande de téléchargement à examiner")
    args = parser.parse_args()
    runtime = args.python_runtime or configured_runtime()
    if args.rapidocr and not args.rbitnet:
        parser.error("--rapidocr exige --rbitnet")
    if args.cuda_library and (not args.rbitnet or args.model_vram_mib <= 0):
        parser.error("--cuda-library exige --rbitnet et un budget VRAM positif")
    if args.evolution_db and (not args.rbitnet or args.rapidocr):
        parser.error("--evolution-db exige --rbitnet et sélectionne le graphe actif")
    if bool(args.integrated_session) != bool(args.integrated_key):
        parser.error("--integrated-session et --integrated-key doivent être fournis ensemble")
    if args.integrated_session and (not args.rbitnet or not runtime or args.cuda_library or args.evolution_db):
        parser.error("--integrated-session exige --python-runtime et --rbitnet CPU avec un seul registre")
    if min(args.evolution_cpu_threads, args.evolution_model_ram_mb) <= 0:
        parser.error("Les limites de threads et de RAM de Rbitnet doivent être positives")
    repair = (RbitnetPaths(*(path.resolve() for path in args.rbitnet),
                          cuda_library=args.cuda_library.resolve() if args.cuda_library else None,
                          vram_mib=args.model_vram_mib) if args.rbitnet else None)
    communication = RbitnetPaths(*(path.resolve() for path in args.communication)) if args.communication else None
    budget = EvolutionBudget(args.evolution_wall_s, args.evolution_max_trials,
                             args.evolution_cpu_threads, args.evolution_model_ram_mb)
    try:
        integrated = Phase6Session(args.integrated_session, args.integrated_key) if args.integrated_session else None
        app = NotesTasks(args.runs.resolve(), runtime, repair, args.rapidocr,
                         evolution_db=args.evolution_db.resolve() if args.evolution_db else None,
                         evolution_budget=budget, integrated=integrated)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    root = tk.Tk()
    Desktop(root, app, data_registry=args.data_db, data_project=args.data_project, proposal=args.proposal,
            dependency_requests=args.dependency_request, communication=communication)
    root.mainloop()


if __name__ == "__main__":
    main()
