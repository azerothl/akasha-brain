"""Présentation des identifiants et actions explicites sur le coffre."""

from tkinter import messagebox, ttk
import tkinter as tk


class VaultWindow:
    def __init__(self, parent, vault, session_id, errors):
        self.vault, self.session_id, self.errors = vault, session_id, errors
        self.window = tk.Toplevel(parent)
        self.window.title("Secrets de la session")
        self.window.transient(parent.winfo_toplevel())
        content = ttk.Frame(self.window, padding=18)
        content.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(content, width=48, height=7, exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        self.status = ttk.Label(content)
        self.status.pack(fill="x", pady=8)
        buttons = ttk.Frame(content)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Vérifier…", command=self.verify).pack(side="left")
        ttk.Button(buttons, text="Effacer…", command=self.erase).pack(side="left", padx=8)
        ttk.Button(buttons, text="Fermer", command=self.window.destroy).pack(side="right")
        self.refresh()
        self.window.grab_set()
        self.listbox.focus_set()

    def refresh(self):
        self.listbox.delete(0, "end")
        self.handles = ()
        try:
            self.handles = self.vault.handles(self.session_id)
        except self.errors:
            self.status.configure(text="Le coffre est indisponible.")
            return
        for handle in self.handles:
            self.listbox.insert("end", str(handle))
        self.status.configure(text="" if self.handles else "Aucun secret scellé pour cette session.")

    def selected(self):
        positions = self.listbox.curselection()
        return self.handles[positions[0]] if positions else None

    def verify(self):
        if handle := self.selected():
            def approve():
                return messagebox.askyesno("Vérifier le secret", "Autoriser la lecture de cette clé dans le coffre ?",
                                           parent=self.window)

            try:
                with self.vault.resolve(self.session_id, handle, approve=approve):
                    self.status.configure(text="Clé disponible dans le coffre Windows.")
            except self.errors:
                self.status.configure(text="La résolution de cette clé a été refusée ou a échoué.")

    def erase(self):
        if (handle := self.selected()) and messagebox.askyesno(
            "Effacer le secret", "Effacer définitivement cette clé du coffre ?", parent=self.window
        ):
            try:
                self.vault.erase(self.session_id, handle)
            except self.errors:
                self.status.configure(text="L’effacement du secret est en attente.")
                return
            self.refresh()
