import tkinter as tk
from tkinter import messagebox
import threading
from database import init_db
from auth import sign_up, login

BG = "#1a1a2e"
PANEL = "#16213e"
ACCENT = "#e94560"
SUCCESS = "#00b894"
TEXT = "#e0e0e0"
MUTED = "#8a8a9a"


class FaceAuthApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Facial Recognition Auth")
        self.root.geometry("460x520")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        init_db()
        self._show_home()

    # ------------------------------------------------------------------ helpers

    def _clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    def _label(self, parent, text, size=11, bold=False, color=TEXT):
        return tk.Label(parent, text=text, bg=BG, fg=color,
                        font=("Segoe UI", size, "bold" if bold else "normal"))

    def _entry(self, parent, show=None):
        return tk.Entry(parent, show=show, font=("Segoe UI", 11),
                        bg=PANEL, fg=TEXT, insertbackground=TEXT,
                        relief="flat", bd=8, highlightthickness=1,
                        highlightbackground=PANEL, highlightcolor=ACCENT)

    def _btn(self, parent, text, cmd, bg=ACCENT):
        return tk.Button(parent, text=text, command=cmd,
                         font=("Segoe UI", 11, "bold"),
                         bg=bg, fg="white", relief="flat",
                         padx=18, pady=9, cursor="hand2",
                         activebackground="#c73652", activeforeground="white")

    def _status(self, parent):
        var = tk.StringVar()
        tk.Label(parent, textvariable=var, bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10), wraplength=360).pack(pady=6)
        return var

    # ------------------------------------------------------------------ screens

    def _show_home(self):
        self._clear()
        f = tk.Frame(self.root, bg=BG)
        f.pack(expand=True)

        self._label(f, "Facial Recognition", 22, True, ACCENT).pack(pady=(50, 4))
        self._label(f, "Secure Biometric Authentication", 10, color=MUTED).pack(pady=(0, 50))

        self._btn(f, "   Create Account   ", self._show_signup, "#0f3460").pack(pady=8, ipadx=10)
        self._btn(f, "   Login   ", self._show_login, ACCENT).pack(pady=8, ipadx=10)

    def _show_signup(self):
        self._clear()
        f = tk.Frame(self.root, bg=BG)
        f.pack(expand=True, fill="both", padx=50)

        self._label(f, "Create Account", 17, True, ACCENT).pack(pady=(30, 22))

        self._label(f, "First Name").pack(anchor="w")
        name_e = self._entry(f)
        name_e.pack(fill="x", pady=(3, 14))

        self._label(f, "Password").pack(anchor="w")
        pass_e = self._entry(f, show="*")
        pass_e.pack(fill="x", pady=(3, 14))

        self._label(f, "Confirm Password").pack(anchor="w")
        conf_e = self._entry(f, show="*")
        conf_e.pack(fill="x", pady=(3, 18))

        status = self._status(f)

        def _run():
            name = name_e.get()
            pw = pass_e.get()
            cp = conf_e.get()
            status.set("Opening camera for face enrollment…")
            self.root.update()

            def task():
                ok, msg = sign_up(name, pw, cp)
                if ok:
                    self.root.after(0, lambda: messagebox.showinfo("Success", msg))
                    self.root.after(0, self._show_home)
                else:
                    self.root.after(0, lambda: status.set(msg))

            threading.Thread(target=task, daemon=True).start()

        row = tk.Frame(f, bg=BG)
        row.pack(fill="x")
        self._btn(row, "Enroll Face & Sign Up", _run, "#0f3460").pack(side="left")
        self._btn(row, "Back", self._show_home, "#444").pack(side="right")

    def _show_login(self):
        self._clear()
        f = tk.Frame(self.root, bg=BG)
        f.pack(expand=True, fill="both", padx=50)

        self._label(f, "Login", 17, True, ACCENT).pack(pady=(30, 22))

        self._label(f, "First Name").pack(anchor="w")
        name_e = self._entry(f)
        name_e.pack(fill="x", pady=(3, 14))

        self._label(f, "Password").pack(anchor="w")
        pass_e = self._entry(f, show="*")
        pass_e.pack(fill="x", pady=(3, 22))

        status = self._status(f)

        def _run():
            name = name_e.get()
            pw = pass_e.get()
            status.set("Checking credentials…")
            self.root.update()

            def task():
                ok, msg, user = login(name, pw)
                if ok:
                    self.root.after(0, lambda: self._show_dashboard(user))
                else:
                    self.root.after(0, lambda: status.set(msg))

            threading.Thread(target=task, daemon=True).start()

        pass_e.bind("<Return>", lambda _: _run())

        row = tk.Frame(f, bg=BG)
        row.pack(fill="x")
        self._btn(row, "Login", _run, ACCENT).pack(side="left")
        self._btn(row, "Back", self._show_home, "#444").pack(side="right")

    def _show_dashboard(self, user):
        self._clear()
        f = tk.Frame(self.root, bg=BG)
        f.pack(expand=True)

        self._label(f, "Access Granted", 20, True, SUCCESS).pack(pady=(70, 10))
        self._label(f, f"Welcome, {user[1].title()}!", 15).pack(pady=6)
        self._label(f, "Identity verified successfully.", 10, color=MUTED).pack(pady=4)
        self._label(f, f"Member since: {user[4][:10]}", 9, color=MUTED).pack(pady=2)

        self._btn(f, "Logout", self._show_home, "#444").pack(pady=40)
