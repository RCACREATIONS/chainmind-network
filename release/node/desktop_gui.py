"""
node/desktop_gui.py
===================
ChainMind Node — Native Desktop GUI (tkinter)

A lightweight, always-on-top-optional control panel that lives alongside
the system tray.  Shows live node status, stats and logs, and gives the
user one-click access to all common actions.

Launch via:
    python chainmind_launcher.py          (default: GUI + tray + dashboard)
    python chainmind_launcher.py --no-gui (headless / tray-only)
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import (
    BooleanVar, Canvas, Frame, Label, Scrollbar, StringVar,
    Text, Tk, Toplevel, ttk, PhotoImage,
)
import tkinter as tk

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

# ── Palette (matches dashboard CSS) ──────────────────────────────────────────
C_BG        = "#1a1030"   # very dark purple-black
C_PANEL     = "#231840"   # slightly lighter panel
C_ACCENT    = "#7c3aed"   # purple
C_ACCENT2   = "#6d28d9"   # darker purple
C_ACCENT_LT = "#a78bfa"   # light purple text
C_GREEN     = "#10b981"   # online green
C_RED       = "#ef4444"   # error red
C_YELLOW    = "#f59e0b"   # warning
C_TEXT      = "#f5f3ff"   # near-white
C_MUTED     = "#a78bfa"   # muted purple
C_BORDER    = "#3b2f6e"   # border


def _resolve_assets() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).parent.parent / "assets"


def _resolve_log_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "data" / "logs"
    return Path(__file__).parent.parent / "data" / "logs"


# ── Stat polling via node HTTP API ───────────────────────────────────────────
def _fetch_stats(node_port: int) -> dict:
    try:
        import httpx
        base = f"http://localhost:{node_port}"
        stats  = httpx.get(f"{base}/stats",   timeout=2).json()
        net    = httpx.get(f"{base}/network", timeout=2).json()
        system = httpx.get(f"{base}/system",  timeout=2).json()
        return {
            "online": True,
            "peers":  net.get("online_peers", 0),
            "jobs":   stats.get("jobs_done", 0),
            "iq":     stats.get("reputation", {}).get("iq_earned", 0.0),
            "tier":   stats.get("reputation", {}).get("tier", "nano"),
            "uptime": system.get("uptime_seconds", 0),
            "ram_gb": system.get("hardware", {}).get("ram_gb", "?"),
            "cpu":    system.get("hardware", {}).get("cpu_cores", "?"),
        }
    except Exception:
        return {"online": False}


def _fmt_uptime(seconds) -> str:
    try:
        s = int(seconds)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {sec}s"
        return f"{sec}s"
    except Exception:
        return "—"


def _tail_log(log_path: Path, n: int = 30) -> str:
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(8192, size)
            f.seek(max(0, size - chunk))
            raw = f.read().decode("utf-8", errors="replace")
        lines = raw.splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return "(no log yet)"


# ── Main GUI class ────────────────────────────────────────────────────────────
class ChainMindGUI:
    POLL_INTERVAL = 5_000  # ms

    def __init__(self, cfg: dict, node_proc_ref: list, stop_all_cb):
        self._cfg          = cfg
        self._node_ref     = node_proc_ref
        self._stop_all     = stop_all_cb
        self._node_port    = cfg.get("node",      {}).get("port",  8000)
        self._dash_port    = cfg.get("dashboard", {}).get("port",  8501)
        self._assets       = _resolve_assets()
        self._log_dir      = _resolve_log_dir()
        self._destroyed    = False

        self._root = Tk()
        self._root.title("ChainMind Node")
        self._root.configure(bg=C_BG)
        self._root.resizable(True, True)
        self._root.minsize(520, 600)
        self._root.geometry("580x700")
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Window icon
        self._load_window_icon()

        self._build_ui()
        self._poll()

    # ── Icon ─────────────────────────────────────────────────────────────────
    def _load_window_icon(self):
        ico = self._assets / "icon.ico"
        png = self._assets / "icon.png"
        try:
            if ico.exists() and sys.platform == "win32":
                self._root.iconbitmap(str(ico))
            elif png.exists() and PIL_OK:
                img = Image.open(png).resize((32, 32), Image.LANCZOS)
                self._icon_photo = ImageTk.PhotoImage(img)
                self._root.iconphoto(True, self._icon_photo)
        except Exception:
            pass

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        root = self._root

        # ── Header ───────────────────────────────────────────────────────────
        hdr = Frame(root, bg=C_PANEL, pady=16)
        hdr.pack(fill="x")

        # Logo
        logo_path = self._assets / "icon.png"
        if logo_path.exists() and PIL_OK:
            try:
                img = Image.open(logo_path).resize((52, 52), Image.LANCZOS)
                self._logo_photo = ImageTk.PhotoImage(img)
                Label(hdr, image=self._logo_photo, bg=C_PANEL).pack(side="left", padx=(18, 10))
            except Exception:
                pass

        title_frame = Frame(hdr, bg=C_PANEL)
        title_frame.pack(side="left", fill="y", pady=4)
        Label(title_frame, text="ChainMind Node", font=("Segoe UI", 18, "bold"),
              fg=C_TEXT, bg=C_PANEL).pack(anchor="w")

        ver_file = (self._assets.parent / "VERSION")
        version  = ver_file.read_text().strip() if ver_file.exists() else "1.0.0"
        Label(title_frame, text=f"v{version}  ·  Decentralised AI Network",
              font=("Segoe UI", 10), fg=C_MUTED, bg=C_PANEL).pack(anchor="w")

        # Status dot + label (right side)
        status_fr = Frame(hdr, bg=C_PANEL)
        status_fr.pack(side="right", padx=18)
        self._dot_canvas = Canvas(status_fr, width=14, height=14, bg=C_PANEL,
                                  highlightthickness=0)
        self._dot_canvas.pack(side="left", padx=(0, 6))
        self._dot_id = self._dot_canvas.create_oval(2, 2, 12, 12, fill=C_RED, outline="")
        self._status_var = StringVar(value="Connecting…")
        Label(status_fr, textvariable=self._status_var,
              font=("Segoe UI", 10, "bold"), fg=C_TEXT, bg=C_PANEL).pack(side="left")

        # ── Action buttons row ────────────────────────────────────────────────
        btn_frame = Frame(root, bg=C_BG, pady=12, padx=14)
        btn_frame.pack(fill="x")

        btn_cfg = dict(font=("Segoe UI", 10, "bold"), bd=0, padx=14, pady=8,
                       cursor="hand2", activeforeground=C_TEXT)

        self._open_dash_btn = tk.Button(
            btn_frame, text="🌐  Open Dashboard",
            bg=C_ACCENT, fg=C_TEXT, activebackground=C_ACCENT2,
            command=self._open_dashboard, **btn_cfg)
        self._open_dash_btn.pack(side="left", padx=(0, 8))

        tk.Button(
            btn_frame, text="🔄  Restart Node",
            bg=C_PANEL, fg=C_TEXT, activebackground=C_BORDER,
            command=self._restart_node, **btn_cfg).pack(side="left", padx=(0, 8))

        tk.Button(
            btn_frame, text="⬆  Check Updates",
            bg=C_PANEL, fg=C_TEXT, activebackground=C_BORDER,
            command=self._check_updates, **btn_cfg).pack(side="left", padx=(0, 8))

        tk.Button(
            btn_frame, text="✕  Quit",
            bg="#3b1d1d", fg="#fca5a5", activebackground="#5f2020",
            command=self._quit, **btn_cfg).pack(side="right")

        # ── Stats grid ───────────────────────────────────────────────────────
        stats_outer = Frame(root, bg=C_BG, padx=14)
        stats_outer.pack(fill="x")

        self._stat_vars: dict[str, StringVar] = {}
        fields = [
            ("Peers Online",  "peers",  "0"),
            ("IQ Earned",     "iq",     "0.0000"),
            ("Jobs Done",     "jobs",   "0"),
            ("Uptime",        "uptime", "—"),
            ("Node Tier",     "tier",   "—"),
            ("RAM",           "ram",    "—"),
        ]
        stats_grid = Frame(stats_outer, bg=C_BG)
        stats_grid.pack(fill="x", pady=(0, 6))

        for idx, (label, key, default) in enumerate(fields):
            col = idx % 3
            row = idx // 3
            card = Frame(stats_grid, bg=C_PANEL, padx=14, pady=12,
                         highlightthickness=1, highlightbackground=C_BORDER)
            card.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            stats_grid.columnconfigure(col, weight=1)

            Label(card, text=label, font=("Segoe UI", 9),
                  fg=C_MUTED, bg=C_PANEL).pack(anchor="w")
            var = StringVar(value=default)
            self._stat_vars[key] = var
            Label(card, textvariable=var, font=("Segoe UI", 16, "bold"),
                  fg=C_TEXT, bg=C_PANEL).pack(anchor="w")

        # ── Node log tail ─────────────────────────────────────────────────────
        log_hdr = Frame(root, bg=C_BG, padx=14, pady=(6, 0))
        log_hdr.pack(fill="x")
        Label(log_hdr, text="Node Log", font=("Segoe UI", 10, "bold"),
              fg=C_ACCENT_LT, bg=C_BG).pack(side="left")
        tk.Button(log_hdr, text="⟳ Refresh", font=("Segoe UI", 8),
                  bg=C_PANEL, fg=C_MUTED, bd=0, padx=8, pady=4,
                  activebackground=C_BORDER, cursor="hand2",
                  command=self._refresh_log).pack(side="right")

        log_frame = Frame(root, bg=C_BG, padx=14, pady=6)
        log_frame.pack(fill="both", expand=True)

        self._log_text = Text(
            log_frame, bg="#110d23", fg="#c4b5fd",
            font=("Consolas", 8), wrap="none",
            relief="flat", bd=0, state="disabled",
            insertbackground=C_TEXT,
        )
        sb_y = Scrollbar(log_frame, orient="vertical",
                         command=self._log_text.yview)
        sb_x = Scrollbar(log_frame, orient="horizontal",
                         command=self._log_text.xview)
        self._log_text.configure(yscrollcommand=sb_y.set,
                                 xscrollcommand=sb_x.set)
        sb_y.pack(side="right", fill="y")
        sb_x.pack(side="bottom", fill="x")
        self._log_text.pack(side="left", fill="both", expand=True)

        # ── Footer ────────────────────────────────────────────────────────────
        footer = Frame(root, bg=C_PANEL, pady=8)
        footer.pack(fill="x", side="bottom")
        Label(footer,
              text=f"Dashboard → http://localhost:{self._dash_port}",
              font=("Segoe UI", 9), fg=C_MUTED, bg=C_PANEL).pack()

    # ── Polling ───────────────────────────────────────────────────────────────
    def _poll(self):
        if self._destroyed:
            return
        threading.Thread(target=self._fetch_and_update, daemon=True).start()
        self._root.after(self.POLL_INTERVAL, self._poll)

    def _fetch_and_update(self):
        stats = _fetch_stats(self._node_port)
        if not self._destroyed:
            self._root.after(0, lambda: self._apply_stats(stats))
            self._root.after(0, self._refresh_log)

    def _apply_stats(self, s: dict):
        if self._destroyed:
            return
        online = s.get("online", False)
        self._dot_canvas.itemconfigure(
            self._dot_id, fill=C_GREEN if online else C_RED)
        self._status_var.set("Running" if online else "Offline")

        if online:
            self._stat_vars["peers"].set(str(s.get("peers", 0)))
            self._stat_vars["iq"].set(f"{float(s.get('iq', 0)):.4f} IQ")
            self._stat_vars["jobs"].set(str(s.get("jobs", 0)))
            self._stat_vars["uptime"].set(_fmt_uptime(s.get("uptime", 0)))
            self._stat_vars["tier"].set(str(s.get("tier", "—")).upper())
            ram = s.get("ram_gb", "?")
            cpu = s.get("cpu", "?")
            self._stat_vars["ram"].set(f"{ram} GB / {cpu} cores")
        else:
            for k in ["peers", "iq", "jobs", "uptime", "tier", "ram"]:
                if self._stat_vars[k].get() not in ("—", "0", "0.0000"):
                    pass  # keep last value while temporarily offline

    def _refresh_log(self):
        if self._destroyed:
            return
        log_file = self._log_dir / "node.log"
        text     = _tail_log(log_file)
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.insert("end", text)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    # ── Button actions ────────────────────────────────────────────────────────
    def _open_dashboard(self):
        webbrowser.open(f"http://localhost:{self._dash_port}")

    def _restart_node(self):
        p = self._node_ref[0]
        if p:
            try:
                p.terminate()
            except Exception:
                pass
        # The launcher's monitor thread will respawn it

    def _check_updates(self):
        import subprocess
        threading.Thread(
            target=lambda: subprocess.run(
                [sys.executable, "--update"], check=False),
            daemon=True,
        ).start()

    def _quit(self):
        self._stop_all()

    def _on_close(self):
        # Closing the window just hides it (it lives in the tray)
        self._root.withdraw()

    # ── Public API ────────────────────────────────────────────────────────────
    def show(self):
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def run(self):
        """Block — call from the main thread."""
        self._root.mainloop()
        self._destroyed = True

    def destroy(self):
        self._destroyed = True
        try:
            self._root.quit()
            self._root.destroy()
        except Exception:
            pass
