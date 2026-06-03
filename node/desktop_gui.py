"""
node/desktop_gui.py
===================
ChainMind Node — Native Desktop GUI (tkinter)

White + purple theme matching the Streamlit dashboard.
"""

from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path
import tkinter as tk

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

C_BG         = "#ffffff"
C_PANEL      = "#f5f3ff"
C_PANEL2     = "#ede9fe"
C_ACCENT     = "#7c3aed"
C_ACCENT_HOV = "#6d28d9"
C_BORDER     = "#ddd6fe"
C_TEXT       = "#1e1b4b"
C_MUTED      = "#6d28d9"
C_GREEN      = "#059669"
C_RED        = "#dc2626"
C_LOG_BG     = "#faf5ff"
C_LOG_FG     = "#4c1d95"


def _resolve_assets() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    here = Path(__file__).parent
    for c in [here.parent / "assets", here / "assets"]:
        if c.exists():
            return c
    return here.parent / "assets"


def _resolve_log_dir() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) \
        else Path(__file__).parent.parent
    return base / "data" / "logs"


def _get_version(assets: Path) -> str:
    for p in [assets.parent / "VERSION"]:
        try:
            return p.resolve().read_text().strip()
        except Exception:
            pass
    return "1.0.0"


def _load_api_token(cfg: dict) -> str:
    """Read the node API token from config. Returns empty string if not set."""
    return cfg.get("node", {}).get("api_token", "") if cfg else ""


def _fetch_stats(node_port: int, api_token: str = "") -> dict:
    """
    Fetch node stats, merging three sources in priority order:
      1. /stats           — local DB: uptime, tier (always available)
      2. /account/earnings — central server: authoritative IQ, jobs, tokens
      3. /network/central_peers — central server: accurate peers-online count
    Falls back to local DB values if the central endpoints fail or time out.
    """
    try:
        import httpx
        import time as _time

        base    = f"http://localhost:{node_port}"
        auth    = {"Authorization": f"Bearer {api_token}"} if api_token else {}
        client  = httpx.Client(timeout=3)

        # ── 1. Local stats (always fetched) ──────────────────────────────────
        stats = client.get(f"{base}/stats", headers=auth).json()
        rep   = stats.get("reputation", {})

        uptime_start = stats.get("uptime_start", 0)
        uptime_secs  = int(_time.time() - uptime_start) if uptime_start else 0

        # Local fallbacks
        iq_val     = float(stats.get("iq_earned", rep.get("iq_earned", 0.0)))
        jobs_val   = stats.get("total_tasks", stats.get("jobs_done", 0))
        tokens_val = stats.get("total_tokens", 0)
        peers_val  = stats.get("peers_online", 0)
        tier_val   = rep.get("tier", "nano")

        # ── 2. Central earnings (IQ, jobs, tokens) ───────────────────────────
        try:
            earn_data = client.get(f"{base}/account/earnings", headers=auth).json()
            earn = earn_data.get("earnings", earn_data) or {}
            # Central server may use various field names — try all common ones
            central_iq = (
                earn.get("iq_earned") or earn.get("total_iq") or
                earn.get("iq") or earn.get("earnings")
            )
            central_jobs = (
                earn.get("jobs_done") or earn.get("total_tasks") or
                earn.get("tasks_completed") or earn.get("total_jobs")
            )
            central_tokens = (
                earn.get("tokens_earned") or earn.get("total_tokens") or
                earn.get("tokens")
            )
            if central_iq     is not None: iq_val     = float(central_iq)
            if central_jobs   is not None: jobs_val   = int(central_jobs)
            if central_tokens is not None: tokens_val = int(central_tokens)
        except Exception:
            pass  # central server unreachable — keep local values

        # ── 3. Central peers count ────────────────────────────────────────────
        try:
            cp = client.get(f"{base}/network/central_peers", timeout=3).json()
            # Response is a list of peers OR a dict with a "peers" key
            peer_list = cp if isinstance(cp, list) else cp.get("peers", [])
            if peer_list:
                peers_val = len(peer_list)
        except Exception:
            pass  # keep local peers_online value

        client.close()

        return {
            "online":  True,
            "peers":   peers_val,
            "jobs":    jobs_val,
            "tokens":  tokens_val,
            "iq":      iq_val,
            "tier":    tier_val,
            "uptime":  uptime_secs,
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


def _tail_log(log_path: Path, n: int = 35) -> str:
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 12288))
            raw = f.read().decode("utf-8", errors="replace")
        return "\n".join(raw.splitlines()[-n:])
    except Exception:
        return "(no log yet)"


class ChainMindGUI:
    POLL_MS = 5000

    def __init__(self, cfg: dict, node_proc_ref: list, stop_all_cb):
        self._cfg       = cfg
        self._node_ref  = node_proc_ref
        self._stop_all  = stop_all_cb
        self._node_port = cfg.get("node",      {}).get("port", 8000)
        self._dash_port = cfg.get("dashboard", {}).get("port", 8501)
        self._api_token = _load_api_token(cfg)
        self._assets    = _resolve_assets()
        self._log_dir   = _resolve_log_dir()
        self._destroyed = False
        self._version   = _get_version(self._assets)

        self._root = tk.Tk()
        self._root.title("ChainMind Node")
        self._root.configure(bg=C_BG)
        self._root.resizable(True, True)
        self._root.minsize(540, 620)
        self._root.geometry("600x720")
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._load_window_icon()
        self._build_ui()
        self._root.after(400, self._schedule_poll)

    def _load_window_icon(self):
        try:
            ico = self._assets / "icon.ico"
            png = self._assets / "icon.png"
            if ico.exists() and sys.platform == "win32":
                self._root.iconbitmap(str(ico))
            elif png.exists() and PIL_OK:
                img = Image.open(png).resize((32, 32), Image.LANCZOS)
                self._icon_photo = ImageTk.PhotoImage(img)
                self._root.iconphoto(True, self._icon_photo)
        except Exception:
            pass

    def _build_ui(self):
        r = self._root

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(r, bg=C_PANEL)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=C_ACCENT, height=3).pack(fill="x")

        hdr_body = tk.Frame(hdr, bg=C_PANEL)
        hdr_body.pack(fill="x", padx=16, pady=10)

        logo_path = self._assets / "icon.png"
        if logo_path.exists() and PIL_OK:
            try:
                img = Image.open(logo_path).resize((48, 48), Image.LANCZOS)
                self._logo_photo = ImageTk.PhotoImage(img)
                lbl = tk.Label(hdr_body, image=self._logo_photo, bg=C_PANEL)
                lbl.pack(side="left")
                # spacer via padx on next widget, NOT a width=N Frame (avoids "N 0" screen distance)
            except Exception:
                pass

        title_col = tk.Frame(hdr_body, bg=C_PANEL)
        title_col.pack(side="left", fill="y", padx=10)
        tk.Label(title_col, text="ChainMind Node",
                 font=("Segoe UI", 17, "bold"),
                 fg=C_TEXT, bg=C_PANEL).pack(anchor="w")
        tk.Label(title_col,
                 text=f"v{self._version}  ·  Decentralised AI Network",
                 font=("Segoe UI", 9), fg=C_MUTED, bg=C_PANEL).pack(anchor="w")

        status_col = tk.Frame(hdr_body, bg=C_PANEL)
        status_col.pack(side="right")
        self._dot_canvas = tk.Canvas(status_col, width=12, height=12,
                                     bg=C_PANEL, highlightthickness=0)
        self._dot_canvas.pack(side="left")
        self._dot_id = self._dot_canvas.create_oval(1, 1, 11, 11,
                                                    fill="#94a3b8", outline="")
        # Status label — padx=4 left adds the gap that the old width=6 Frame provided
        self._status_var = tk.StringVar(value="Starting…")
        tk.Label(status_col, textvariable=self._status_var,
                 font=("Segoe UI", 10, "bold"),
                 fg=C_TEXT, bg=C_PANEL).pack(side="left", padx=4)

        tk.Frame(hdr, bg=C_BORDER, height=1).pack(fill="x")

        # ── Buttons ───────────────────────────────────────────────────────────
        # IMPORTANT: never pass padx=/pady= to Button() constructor — on some
        # Windows Tk versions the pair (pady, bd=0) gets stringified as "6 0"
        # causing "bad screen distance" crash.  Use ipadx/ipady in pack() instead.
        btn_row = tk.Frame(r, bg=C_BG)
        btn_row.pack(fill="x", padx=16, pady=10)

        for text, cmd, bg, fg in [
            ("🌐  Open Dashboard",  self._open_dashboard, C_ACCENT,  "#ffffff"),
            ("🔄  Restart Node",    self._restart_node,   C_PANEL2,  C_MUTED),
            ("⬆  Check Updates",   self._check_updates,  C_PANEL2,  C_MUTED),
            ("✕  Quit",            self._quit,           "#fee2e2",  "#991b1b"),
        ]:
            tk.Button(btn_row, text=text, command=cmd,
                      bg=bg, fg=fg,
                      activebackground=C_ACCENT_HOV, activeforeground="#ffffff",
                      font=("Segoe UI", 9, "bold"),
                      relief="flat", bd=0,
                      cursor="hand2").pack(side="left", padx=3, ipadx=10, ipady=5)

        # ── Stats grid ────────────────────────────────────────────────────────
        grid_frame = tk.Frame(r, bg=C_BG)
        grid_frame.pack(fill="x", padx=16, pady=2)

        self._stat_vars: dict[str, tk.StringVar] = {}
        fields = [
            ("Peers Online", "peers",  "—"),
            ("IQ Earned",    "iq",     "—"),
            ("Jobs Done",    "jobs",   "—"),
            ("Uptime",       "uptime", "—"),
            ("Node Tier",    "tier",   "—"),
            ("Tokens",       "tokens", "—"),
        ]
        for idx, (label, key, default) in enumerate(fields):
            col = idx % 3
            row = idx // 3
            card = tk.Frame(grid_frame, bg=C_PANEL,
                            highlightthickness=1,
                            highlightbackground=C_BORDER)
            card.grid(row=row, column=col, padx=3, pady=3, sticky="nsew")
            grid_frame.columnconfigure(col, weight=1)

            tk.Label(card, text=label,
                     font=("Segoe UI", 8), fg=C_MUTED,
                     bg=C_PANEL).pack(anchor="w", padx=10, pady=4)
            var = tk.StringVar(value=default)
            self._stat_vars[key] = var
            tk.Label(card, textvariable=var,
                     font=("Segoe UI", 15, "bold"),
                     fg=C_TEXT, bg=C_PANEL).pack(anchor="w", padx=10, pady=4)

        # ── Log ───────────────────────────────────────────────────────────────
        log_hdr = tk.Frame(r, bg=C_BG)
        log_hdr.pack(fill="x", padx=16, pady=4)
        tk.Label(log_hdr, text="Node Log",
                 font=("Segoe UI", 10, "bold"),
                 fg=C_MUTED, bg=C_BG).pack(side="left")
        tk.Button(log_hdr, text="↻ Refresh",
                  command=self._refresh_log,
                  bg=C_PANEL2, fg=C_MUTED,
                  font=("Segoe UI", 8), relief="flat", bd=0,
                  cursor="hand2").pack(side="right", ipadx=6, ipady=2)

        log_wrap = tk.Frame(r, bg=C_BG)
        log_wrap.pack(fill="both", expand=True, padx=16, pady=3)

        self._log_text = tk.Text(
            log_wrap,
            bg=C_LOG_BG, fg=C_LOG_FG,
            font=("Consolas", 8),
            wrap="none",
            relief="flat", bd=0,
            state="disabled",
            highlightbackground=C_BORDER,
            highlightthickness=1,
        )
        sb_y = tk.Scrollbar(log_wrap, orient="vertical",
                            command=self._log_text.yview)
        sb_x = tk.Scrollbar(log_wrap, orient="horizontal",
                            command=self._log_text.xview)
        self._log_text.configure(yscrollcommand=sb_y.set,
                                 xscrollcommand=sb_x.set)
        sb_y.pack(side="right", fill="y")
        sb_x.pack(side="bottom", fill="x")
        self._log_text.pack(side="left", fill="both", expand=True)

        # ── Footer ────────────────────────────────────────────────────────────
        tk.Frame(r, bg=C_BORDER, height=1).pack(fill="x")
        footer = tk.Frame(r, bg=C_PANEL)
        footer.pack(fill="x")
        tk.Label(footer,
                 text=f"Dashboard  →  http://localhost:{self._dash_port}",
                 font=("Segoe UI", 8), fg=C_MUTED,
                 bg=C_PANEL).pack(pady=5)

    # ── Polling ───────────────────────────────────────────────────────────────
    def _schedule_poll(self):
        if self._destroyed:
            return
        threading.Thread(target=self._bg_fetch, daemon=True).start()
        self._root.after(self.POLL_MS, self._schedule_poll)

    def _bg_fetch(self):
        stats = _fetch_stats(self._node_port, self._api_token)
        if self._destroyed:
            return
        try:
            self._root.after(0, lambda s=stats: self._apply_stats(s))
            self._root.after(0, self._refresh_log)
        except Exception:
            pass

    def _apply_stats(self, s: dict):
        if self._destroyed:
            return
        online = s.get("online", False)
        self._dot_canvas.itemconfigure(
            self._dot_id, fill=C_GREEN if online else C_RED)
        self._status_var.set("Running" if online else "Offline")
        if online:
            self._stat_vars["peers"].set(str(s.get("peers", 0)))
            self._stat_vars["iq"].set(f"{s.get('iq', 0.0):.4f}")
            self._stat_vars["jobs"].set(str(s.get("jobs", 0)))
            self._stat_vars["tokens"].set(str(s.get("tokens", 0)))
            self._stat_vars["uptime"].set(_fmt_uptime(s.get("uptime", 0)))
            self._stat_vars["tier"].set(str(s.get("tier", "—")).upper())

    def _refresh_log(self):
        if self._destroyed:
            return
        text = _tail_log(self._log_dir / "node.log")
        try:
            self._log_text.configure(state="normal")
            self._log_text.delete("1.0", "end")
            self._log_text.insert("end", text)
            self._log_text.see("end")
            self._log_text.configure(state="disabled")
        except Exception:
            pass

    # ── Actions ───────────────────────────────────────────────────────────────
    def _open_dashboard(self):
        webbrowser.open(f"http://localhost:{self._dash_port}")

    def _restart_node(self):
        p = self._node_ref[0]
        if p:
            try:
                p.terminate()
            except Exception:
                pass

    def _check_updates(self):
        threading.Thread(
            target=lambda: __import__("subprocess").run(
                [sys.executable, "--update"], check=False),
            daemon=True,
        ).start()

    def _quit(self):
        self._stop_all()

    def _on_close(self):
        self._root.withdraw()

    # ── Public ────────────────────────────────────────────────────────────────
    def show(self):
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def run(self):
        self._root.mainloop()
        self._destroyed = True

    def destroy(self):
        self._destroyed = True
        try:
            self._root.quit()
            self._root.destroy()
        except Exception:
            pass
