"""Préparation d'un projet en bac et revue de ses demandes de téléchargement."""

from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, ttk
from uuid import uuid4

from .project import prepare
from .project_approval import expired
from .project_common import ProjectError
from .project_dependencies import create_request, preview_dependency

OPERATIONS = {"Remplacement": "replace", "Suppression": "delete", "Déplacement": "move"}
DOWNLOAD_STATES = {"pending": "À approuver", "expired": "Accord expiré", "used": "Demande utilisée", "cached": "En cache"}


class ProjectWindow:
    def __init__(self, root, project, output, runtime, submit, on_prepared, requests=()):
        self.window = tk.Toplevel(root)
        self.window.title("Akasha Brain - Préparer un projet")
        self.window.geometry("1120x650")
        self.window.minsize(880, 575)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.project = project
        self.output = output
        self.runtime = runtime
        self.submit = submit
        self.on_prepared = on_prepared
        self.requests = {}
        self.download_states = {}
        self.replies = SimpleQueue()
        self.job = None
        self.fields = {name: tk.StringVar(self.window) for name in ("target", "test", "replacement", "destination")}
        self.operation = tk.StringVar(self.window, "Remplacement")
        self.approved = tk.BooleanVar(self.window)
        self.build()
        self.set_project(project)
        for request in requests:
            self.add_request(request)
        self.window.after(150, self.poll)

    def show(self):
        self.window.deiconify()
        self.window.lift()

    def close(self):
        self.approved.set(False)
        self.window.withdraw()

    def build(self):
        page = ttk.Frame(self.window, padding=20, style="Data.TFrame")
        page.pack(fill="both", expand=True)
        page.columnconfigure((0, 1), weight=1, uniform="project")
        page.rowconfigure(1, weight=1)
        header = ttk.Frame(page, style="Data.TFrame")
        header.grid(row=0, columnspan=2, sticky="ew", pady=(0, 18))
        ttk.Label(header, text="Préparer un projet", style="DataTitle.TLabel").pack(side="left")
        self.project_button = ttk.Button(header, text="Choisir le projet…", command=self.choose_project)
        self.project_button.pack(side="right")
        self.project_label = ttk.Label(header, style="DataMuted.TLabel", wraplength=600)
        self.project_label.pack(side="left", padx=12)

        form = ttk.Frame(page, style="Data.TFrame")
        form.grid(row=1, column=0, sticky="new", padx=(0, 20))
        form.columnconfigure(0, weight=1)
        ttk.Label(form, text="Opération", style="DataHeading.TLabel").grid(row=0, sticky="w")
        self.operation_box = ttk.Combobox(form, state="readonly", values=tuple(OPERATIONS), textvariable=self.operation)
        self.operation_box.grid(row=1, sticky="ew", pady=(5, 0))
        self.operation_box.bind("<<ComboboxSelected>>", self.show_operation)
        self.entries = {}
        for row, (name, label) in enumerate((
            ("target", "Fichier source, chemin relatif"), ("test", "Script Python de test, chemin relatif"),
            ("replacement", "Fichier de remplacement"), ("destination", "Destination, chemin relatif"),
        ), 2):
            field = ttk.Frame(form, style="Data.TFrame")
            field.grid(row=row, sticky="ew", pady=(10, 0))
            ttk.Label(field, text=label, style="Data.TLabel").pack(anchor="w", pady=(0, 4))
            if name == "replacement":
                self.replacement_button = ttk.Button(field, text="Parcourir…", command=self.choose_replacement)
                self.replacement_button.pack(side="right", padx=(6, 0))
            entry = ttk.Entry(field, textvariable=self.fields[name])
            entry.pack(side="left", fill="x", expand=True)
            self.entries[name] = (field, entry)
        ttk.Label(form, text="Autres fichiers requis, un chemin relatif par ligne", style="Data.TLabel").grid(
            row=6, sticky="w", pady=(10, 4))
        theme = ttk.Style(self.window)
        text_colors = {"bg": theme.lookup("Data.Treeview", "background"),
                       "fg": theme.lookup("Data.TLabel", "foreground")}
        self.inputs = tk.Text(form, height=3, width=26, font=("Consolas", 10),
                              insertbackground=text_colors["fg"], **text_colors)
        self.inputs.grid(row=7, sticky="ew")
        self.prepare_button = ttk.Button(form, text="Tester dans Windows Sandbox", command=self.prepare,
                                         style="Launch.TButton")
        self.prepare_button.grid(row=8, sticky="w", pady=(16, 0))
        self.show_operation()

        dependencies = ttk.Frame(page, style="Data.TFrame")
        dependencies.grid(row=1, column=1, sticky="nsew")
        ttk.Label(dependencies, text="Dépendances", style="DataHeading.TLabel").pack(anchor="w")
        controls = ttk.Frame(dependencies, style="Data.TFrame")
        controls.pack(fill="x", pady=6)
        self.add_button = ttk.Button(controls, text="Ouvrir une demande…", command=self.choose_request)
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(controls, text="Retirer", command=self.remove_request)
        self.remove_button.pack(side="right")
        self.table = ttk.Treeview(dependencies, columns=("name", "version", "state"), show="headings",
                                  style="Data.Treeview", selectmode="browse", height=4)
        for column, heading, width in (("name", "Nom", 180), ("version", "Version", 75), ("state", "État", 120)):
            self.table.heading(column, text=heading)
            self.table.column(column, width=width)
        self.table.pack(fill="x")
        self.table.bind("<<TreeviewSelect>>", self.select_request)
        self.details = tk.Text(dependencies, height=6, width=30, wrap="word", font=("Consolas", 10),
                               state="disabled", **text_colors)
        self.details.pack(fill="both", expand=True, pady=8)
        self.approval = ttk.Checkbutton(dependencies, text="J’autorise le téléchargement depuis la source affichée",
                                        variable=self.approved, style="Data.TCheckbutton")
        self.approval.pack(anchor="w")
        downloads = ttk.Frame(dependencies, style="Data.TFrame")
        downloads.pack(anchor="w", pady=(6, 0))
        self.download_button = ttk.Button(downloads, text="Télécharger la wheel", command=self.download)
        self.download_button.pack(side="left")
        self.renew_button = ttk.Button(downloads, text="Nouvelle demande", command=self.renew_download)
        self.renew_button.pack(side="left", padx=6)
        self.message = ttk.Label(page, style="DataMuted.TLabel", wraplength=850)
        self.message.grid(row=2, columnspan=2, sticky="w", pady=(12, 0))

    def feedback(self, message, *, error=False):
        self.message.configure(text=message, style="DataError.TLabel" if error else "DataMuted.TLabel")

    def show_operation(self, _event=None):
        operation = OPERATIONS[self.operation.get()]
        for field, visible in (("replacement", operation == "replace"), ("destination", operation == "move")):
            widget, _ = self.entries[field]
            if visible:
                widget.grid()
            else:
                widget.grid_remove()

    def set_project(self, project):
        if self.project != project:
            for value in self.fields.values():
                value.set("")
            self.inputs.delete("1.0", "end")
        self.project = project
        self.project_label.configure(text=str(project) if project else "Sélectionnez le dossier du projet.")
        self.requests.clear()
        self.download_states.clear()
        self.table.delete(*self.table.get_children())
        self.select_request()

    def choose_project(self):
        folder = filedialog.askdirectory(parent=self.window, mustexist=True)
        if folder:
            self.set_project(Path(folder))

    def choose_replacement(self):
        file = filedialog.askopenfilename(parent=self.window)
        if file:
            self.fields["replacement"].set(file)

    def choose_request(self):
        folder = filedialog.askdirectory(parent=self.window, title="Choisir le dossier de la demande", mustexist=True)
        if folder:
            self.add_request(Path(folder))

    def add_request(self, directory):
        if self.project is None:
            self.feedback("Choisissez le projet avant d’ouvrir une demande.", error=True)
            return
        try:
            review = preview_dependency(self.project, directory)
            status = review.state()
        except (OSError, KeyError, TypeError, ValueError, ProjectError) as error:
            self.feedback(str(error), error=True)
            return
        key = str(review.request)
        self.requests[key] = review
        self.download_states[key] = status
        if not self.table.exists(key):
            self.table.insert("", "end", iid=key)
        self.update_row(key)
        self.table.selection_set(key)
        self.select_request()
        self.feedback("La demande est liée au projet sélectionné.")

    def update_row(self, key):
        entry = self.requests[key].dependency
        self.table.item(key, values=(entry["name"], entry["version"], DOWNLOAD_STATES[self.download_states[key]]))

    def selected(self):
        return next(iter(self.table.selection()), None)

    def select_request(self, _event=None):
        self.approved.set(False)
        review = self.requests.get(self.selected())
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if review:
            entry = review.dependency
            expires = review.approval_expires_at.astimezone()
            self.details.insert("1.0", f"{entry['name']} {entry['version']}\n{entry['url']}\n"
                                       f"Licence {entry['license']}\nSHA-256 {entry['sha256']}\n"
                                       f"Accord avant {expires:%d/%m %H:%M}")
        self.details.configure(state="disabled")
        self.update_controls()

    def remove_request(self):
        selected = self.selected()
        if selected is not None:
            del self.requests[selected]
            del self.download_states[selected]
            self.table.delete(selected)
            self.select_request()

    def update_controls(self):
        idle = self.job is None
        selected = self.selected()
        pending = self.download_states.get(selected) == "pending"
        for widget, enabled in (
            (self.project_button, idle), (self.add_button, idle and self.project is not None),
            (self.remove_button, idle and selected is not None), (self.approval, idle and pending),
            (self.download_button, idle and pending),
            (self.renew_button, idle and self.download_states.get(selected) == "expired"),
            (self.prepare_button, idle and self.project is not None),
            (self.replacement_button, idle),
        ):
            widget.state(["!disabled"] if enabled else ["disabled"])
        for _, entry in self.entries.values():
            entry.state(["!disabled"] if idle else ["disabled"])
        self.inputs.configure(state="normal" if idle else "disabled")
        self.operation_box.configure(state="readonly" if idle else "disabled")

    def download(self):
        key = self.selected()
        if self.job is not None or self.download_states.get(key) != "pending":
            return
        review = self.requests[key]
        approved = self.approved.get()
        self.approved.set(False)
        self.start("download", key, lambda: review.download(approved))

    def renew_download(self):
        key = self.selected()
        if self.job is not None or self.download_states.get(key) != "expired":
            return
        dependency = self.requests[key].dependency
        fields = {name: dependency[name] for name in ("name", "version", "url", "sha256", "license")}
        try:
            request = create_request(self.project, self.output / "dependencies" / str(uuid4()), **fields)
        except (OSError, ValueError, ProjectError) as error:
            self.feedback(str(error), error=True)
            return
        self.remove_request()
        self.add_request(Path(request["request"]))

    def prepare(self):
        runtime = self.runtime()
        if self.project is None or self.job is not None:
            return
        if runtime is None or not (runtime / "python.exe").is_file():
            self.feedback("Choisissez le dossier Python portable dans la fenêtre principale.", error=True)
            return
        if any(state != "cached" for state in self.download_states.values()):
            self.feedback("Approuvez chaque téléchargement requis ou retirez sa demande.", error=True)
            return
        project = self.project
        if self.output.resolve().is_relative_to(project.resolve()):
            self.feedback("Choisissez un emplacement de travail en dehors du projet.", error=True)
            return
        fields = {name: value.get() for name, value in self.fields.items()}
        operation = OPERATIONS[self.operation.get()]
        if (not fields["target"] or not fields["test"] or (operation == "replace" and not fields["replacement"])
                or (operation == "move" and not fields["destination"])):
            self.feedback("Renseignez le fichier source, le script de test et les chemins de l’opération.", error=True)
            return
        replacement = Path(fields["replacement"]) if operation == "replace" else None
        destination = fields["destination"] if operation == "move" else None
        inputs = tuple(line for line in self.inputs.get("1.0", "end").split("\n") if line)
        requests = tuple(self.requests.values())
        output = self.output / str(uuid4())
        self.start("prepare", project, lambda: prepare(project, output, fields["target"], replacement,
                   fields["test"], runtime, inputs=inputs, delete=operation == "delete", move_to=destination,
                   dependencies=requests))

    def start(self, job, key, operation):
        self.job = job
        self.update_controls()
        self.feedback("Préparation demandée, en attente du bac…" if job == "prepare" else "Traitement de la demande…")

        def operation_in_progress():
            if job == "prepare":
                self.replies.put(("preparing", key, None, None))
            return operation()

        def publish(result):
            try:
                value = result()
            except Exception as error:
                self.replies.put((job, key, None, error))
            else:
                self.replies.put((job, key, value, None))

        if job == "prepare":
            self.submit(operation_in_progress).add_done_callback(lambda task: publish(task.result))
        else:
            Thread(target=publish, args=(operation_in_progress,), name="Akasha Dépendances").start()

    def poll(self):
        try:
            job, key, result, error = self.replies.get_nowait()
        except Empty:
            pass
        else:
            if job == "preparing":
                self.feedback("Préparation et tests dans Windows Sandbox…")
            else:
                self.complete(job, key, result, error)
        if self.job is None:
            for key, review in self.requests.items():
                if self.download_states[key] == "pending" and expired(review.approval_expires_at):
                    self.download_states[key] = "expired"
                    self.update_row(key)
                    if key == self.selected():
                        self.approved.set(False)
                        self.feedback("L’accord de téléchargement a expiré. Créez une nouvelle demande.", error=True)
        self.update_controls()
        self.window.after(150, self.poll)

    def complete(self, job, key, result, error):
        self.job = None
        if job == "download":
            review = self.requests[key]
            if result:
                self.download_states[key] = "cached"
            elif (review.request / "download.claim").exists():
                self.download_states[key] = "used"
            self.update_row(key)
        if error:
            self.feedback(str(error), error=True)
        elif job == "prepare":
            self.feedback("Tests réussis. Proposition prête à examiner.")
            self.on_prepared(key, Path(result["proposal"]))
        else:
            self.feedback("Wheel vérifiée et mise en cache pour l’installation hors ligne.")
