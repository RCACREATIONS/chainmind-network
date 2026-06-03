"""
chainmind_launcher.py
=====================
Single entry-point for the PyInstaller-frozen ChainMind Node executable.

Internal dispatch flags (handled before argparse, used by frozen subprocesses):
  --_run-server       Run the FastAPI node server (internal use only)
  --_run-dashboard    Run the Streamlit dashboard (internal use only)

Public CLI flags:
  --update            Force update check
  --no-dashboard      Run node API only, no browser UI
  --no-browser        Don't auto-open the browser
  --setup             Re-run the setup wizard
  --no-tray           Disable system tray (run console-only)
"""

from __future__ import annotations

import argparse
import os
import sys
import signal
import subprocess
import threading
import time
import webbrowser
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Resolve paths — works both frozen (PyInstaller) and plain Python
# ─────────────────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BUNDLE_DIR  = Path(sys._MEIPASS)
    INSTALL_DIR = Path(sys.executable).parent
else:
    BUNDLE_DIR  = Path(__file__).parent
    INSTALL_DIR = Path(__file__).parent

DATA_DIR    = INSTALL_DIR / "data"
CONFIG_FILE = INSTALL_DIR / "config.yaml"
LOG_DIR     = DATA_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

if str(BUNDLE_DIR) not in sys.path:
    sys.path.insert(0, str(BUNDLE_DIR))

# Tell every subprocess exactly where config.yaml lives so they don't have
# to guess — avoids the _MEIPASS vs install-dir confusion.
os.environ["CHAINMIND_CONFIG"] = str(INSTALL_DIR / "config.yaml")

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Internal dispatch — MUST run before argparse
#
#     When frozen, the launcher spawns itself with --_run-server or
#     --_run-dashboard instead of trying to call python -m / python -c,
#     which fails because sys.executable is the .exe, not Python.
# ─────────────────────────────────────────────────────────────────────────────
def _internal_dispatch():
    """
    Check for internal flags injected by the frozen subprocess launch.
    If found, run the target and exit — never reaches main().
    """
    args = sys.argv[1:]

    if "--_run-server" in args:
        _run_server_mode()
        sys.exit(0)

    if "--_run-dashboard" in args:
        port = 8501
        for i, a in enumerate(args):
            if a == "--_port" and i + 1 < len(args):
                port = int(args[i + 1])
        _run_dashboard_mode(port)
        sys.exit(0)


def _run_server_mode():
    """Called when subprocess is launched with --_run-server."""
    os.chdir(str(INSTALL_DIR))
    if str(BUNDLE_DIR) not in sys.path:
        sys.path.insert(0, str(BUNDLE_DIR))
    from node.server import run_server
    run_server()


def _run_dashboard_mode(port: int = 8501):
    """Called when subprocess is launched with --_run-dashboard."""
    os.chdir(str(INSTALL_DIR))
    if str(BUNDLE_DIR) not in sys.path:
        sys.path.insert(0, str(BUNDLE_DIR))

    dash_path = str(BUNDLE_DIR / "node" / "dashboard.py")

    # Call Streamlit's CLI directly — avoids the -m flag problem
    from streamlit.web import cli as stcli
    sys.argv = [
        "streamlit", "run", dash_path,
        "--server.port",             str(port),
        "--server.headless",         "true",
        "--server.address",          "localhost",
        "--browser.gatherUsageStats","false",
        "--global.developmentMode",  "false",
    ]
    stcli.main()


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Banner
# ─────────────────────────────────────────────────────────────────────────────
PURPLE = "\033[95m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def _get_version() -> str:
    ver_file = INSTALL_DIR / "VERSION"
    return ver_file.read_text().strip() if ver_file.exists() else "1.0.0"


def banner():
    print(f"""
{PURPLE}{BOLD}
  ██████╗██╗  ██╗ █████╗ ██╗███╗   ██╗███╗   ███╗██╗███╗   ██╗██████╗
 ██╔════╝██║  ██║██╔══██╗██║████╗  ██║████╗ ████║██║████╗  ██║██╔══██╗
 ██║     ███████║███████║██║██╔██╗ ██║██╔████╔██║██║██╔██╗ ██║██║  ██║
 ██║     ██╔══██║██╔══██║██║██║╚██╗██║██║╚██╔╝██║██║██║╚██╗██║██║  ██║
 ╚██████╗██║  ██║██║  ██║██║██║ ╚████║██║ ╚═╝ ██║██║██║ ╚████║██████╔╝
  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═════╝
{RESET}{CYAN}  Decentralised AI Network — Node Software  v{_get_version()}{RESET}
""")


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Self-update check (background thread)
# ─────────────────────────────────────────────────────────────────────────────
UPDATE_MANIFEST_URLS = [
    "https://chainmind.com.ng/api/release/latest.json",
    "https://raw.githubusercontent.com/chainmind-network/chainmind-node/main/release/latest.json",
]


def _version_gt(a: str, b: str) -> bool:
    def parts(v):
        return [int(x) for x in v.lstrip("v").split(".")]
    try:
        return parts(a) > parts(b)
    except Exception:
        return False


def _platform_key() -> str:
    import platform
    p = sys.platform
    if p == "win32":
        return "windows_x64" if platform.machine().endswith("64") else "windows_x86"
    elif p == "darwin":
        return "macos_arm64" if platform.machine() == "arm64" else "macos_x64"
    return "linux_x64"


def _do_update(info: dict, current: str, latest: str):
    import tempfile, shutil, hashlib
    pkey = _platform_key()
    url  = info.get("assets", {}).get(pkey)
    if not url:
        return

    print(f"\n{YELLOW}  ↑ Update available: {current} → {latest}{RESET}")
    print(f"{YELLOW}  Downloading…{RESET}")

    try:
        import httpx
        tmp = Path(tempfile.gettempdir()) / f"chainmind_update_{latest}"
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as resp:
            total = int(resp.headers.get("content-length", 0))
            done  = 0
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(65536):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = int(done / total * 40)
                        bar = "█" * pct + "░" * (40 - pct)
                        print(f"\r  [{bar}] {done//1024//1024}MB/{total//1024//1024}MB",
                              end="", flush=True)
        print()

        expected = info.get("checksums", {}).get(pkey)
        if expected:
            h = hashlib.sha256()
            with open(tmp, "rb") as f:
                for block in iter(lambda: f.read(65536), b""):
                    h.update(block)
            if h.hexdigest() != expected:
                print(f"{YELLOW}  Checksum mismatch — skipping update.{RESET}")
                tmp.unlink(missing_ok=True)
                return

        if sys.platform != "win32":
            os.chmod(tmp, 0o755)

        exe = Path(sys.executable)
        old = exe.with_suffix(".old")
        try:
            if old.exists():
                old.unlink()
            exe.rename(old)
            shutil.move(str(tmp), str(exe))
            (INSTALL_DIR / "VERSION").write_text(latest)
            print(f"{GREEN}  ✔ Updated to {latest}. Restart to apply.{RESET}\n")
        except PermissionError:
            bat = exe.parent / "_chainmind_update.bat"
            bat.write_text(
                "@echo off\ntimeout /t 3 /nobreak >nul\n"
                f'move /y "{tmp}" "{exe}"\nstart "" "{exe}"\ndel "%~f0"\n',
                encoding="utf-8",
            )
            (INSTALL_DIR / "VERSION").write_text(latest)
            print(f"{YELLOW}  Update staged. Will apply on next restart.{RESET}")
    except Exception as e:
        print(f"{YELLOW}  Update failed: {e}{RESET}")


def _check_updates_bg(force: bool = False):
    try:
        import httpx
        for url in UPDATE_MANIFEST_URLS:
            try:
                r = httpx.get(url, timeout=10, follow_redirects=True)
                if r.status_code == 200:
                    info    = r.json()
                    latest  = info.get("version", "")
                    current = _get_version()
                    if latest and _version_gt(latest, current):
                        _do_update(info, current, latest)
                    break
            except Exception:
                continue
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Ollama detection / auto-install
# ─────────────────────────────────────────────────────────────────────────────
OLLAMA_URLS = {
    "win32":  "https://ollama.ai/download/OllamaSetup.exe",
    "darwin": "https://ollama.ai/download/Ollama-darwin.zip",
    "linux":  "https://ollama.ai/install.sh",
}


def _ensure_ollama() -> bool:
    import shutil as sh
    if sh.which("ollama"):
        return True

    candidates = [
        Path.home() / ".ollama" / "bin" / "ollama",
        Path("/usr/local/bin/ollama"),
    ]
    win_user = os.environ.get("USERNAME", "")
    if win_user:
        candidates.append(Path("C:/Users") / win_user / "AppData/Local/Programs/Ollama/ollama.exe")

    for c in candidates:
        if c.exists():
            os.environ["PATH"] = str(c.parent) + os.pathsep + os.environ["PATH"]
            return True

    print(f"\n{YELLOW}  ⚠  Ollama not found.{RESET}")
    answer = input("  Download and install Ollama now? [Y/n]: ").strip().lower()
    if answer and not answer.startswith("y"):
        print("  Install it later from https://ollama.ai/download")
        return False
    _download_ollama()
    return bool(sh.which("ollama"))


def _ensure_ollama_running(cfg: dict) -> None:
    """
    If Ollama is installed but not responding on its port, show a clear prompt
    and wait up to 90 s for it to start. Works in both GUI (Tk dialog) and
    headless (console) mode.  Does NOT block the launch — just warns and waits.
    """
    ollama_port = cfg.get("ollama", {}).get("port", 11434)
    ollama_host = cfg.get("ollama", {}).get("host", "http://localhost").rstrip("/")
    check_url   = f"{ollama_host}:{ollama_port}/api/tags"

    def _is_up() -> bool:
        try:
            import httpx
            r = httpx.get(check_url, timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    if _is_up():
        print(f"{GREEN}  ✔ Ollama is running on port {ollama_port}{RESET}")
        return

    # ── Ollama not responding ──────────────────────────────────────────────────
    print(f"\n{YELLOW}  ⚠  Ollama is not running (checked {check_url}).{RESET}")
    print(f"{YELLOW}     ChainMind needs Ollama to process AI jobs.{RESET}")
    print(f"{CYAN}     ➜  Start Ollama, then the node will proceed automatically.{RESET}")
    print(f"{CYAN}     ➜  Download: https://ollama.ai/download{RESET}\n")

    # Try to show a Tk dialog if we're on a desktop session
    _shown_dialog = False
    try:
        import tkinter as tk
        from tkinter import messagebox

        _root = tk.Tk()
        _root.withdraw()
        _root.attributes("-topmost", True)
        messagebox.showwarning(
            "Ollama Not Running — ChainMind",
            f"Ollama is not running on port {ollama_port}.\n\n"
            "ChainMind needs Ollama to process AI jobs.\n\n"
            "Please start Ollama, then click OK — the node will\n"
            "keep waiting until Ollama is ready (up to 90 seconds).\n\n"
            "Download Ollama: https://ollama.ai/download",
        )
        _root.destroy()
        _shown_dialog = True
    except Exception:
        pass  # headless / no display — console message already printed above

    # Wait up to 90 s for Ollama to come up, checking every 3 s
    wait_secs = 90
    interval  = 3
    for attempt in range(wait_secs // interval):
        if _is_up():
            print(f"{GREEN}  ✔ Ollama is now running — continuing.{RESET}\n")
            return
        remaining = wait_secs - attempt * interval
        print(f"\r{YELLOW}  Waiting for Ollama… {remaining}s remaining{RESET}    ", end="", flush=True)
        time.sleep(interval)

    print(f"\n{YELLOW}  ⚠  Ollama still not detected — starting node anyway.{RESET}")
    print(f"{YELLOW}     Jobs will be skipped until Ollama is available.{RESET}\n")


def _download_ollama():
    import tempfile, subprocess as sp
    url = OLLAMA_URLS.get(sys.platform)
    if not url:
        print("  Visit https://ollama.ai/download")
        return
    print(f"\n{CYAN}  Downloading Ollama (~150 MB)…{RESET}")
    try:
        import httpx
        tmp = Path(tempfile.gettempdir()) / url.split("/")[-1]
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as resp:
            total = int(resp.headers.get("content-length", 0))
            done  = 0
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(65536):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = int(done / total * 40)
                        bar = "█" * pct + "░" * (40 - pct)
                        print(f"\r  [{bar}] {done//1024//1024}MB/{total//1024//1024}MB", end="", flush=True)
        print()
        if sys.platform == "win32":
            sp.run([str(tmp), "/S"], check=True)
        elif sys.platform == "darwin":
            sp.run(["unzip", "-qo", str(tmp), "-d", "/Applications"], check=True)
        else:
            os.chmod(tmp, 0o755)
            sp.run(["sudo", "sh", str(tmp)], check=True)
        print(f"{GREEN}  ✔ Ollama installed.{RESET}")
    except Exception as e:
        print(f"{YELLOW}  Ollama install failed: {e}{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Desktop shortcut


def _get_ico_path() -> str:
    """Return path to icon.ico for use in shortcuts/taskbar. Falls back to exe."""
    for candidate in [
        BUNDLE_DIR  / "assets" / "icon.ico",
        INSTALL_DIR / "assets" / "icon.ico",
    ]:
        if candidate.exists():
            return str(candidate.resolve())
    return str(Path(sys.executable).resolve())
# ─────────────────────────────────────────────────────────────────────────────
def _create_desktop_shortcut() -> None:
    """
    Create a 'ChainMind Node.lnk' shortcut on the Windows Desktop
    pointing to the running .exe. Safe to call every launch — skips
    if the shortcut already exists. No-op on macOS/Linux.

    Uses PowerShell -EncodedCommand (base64-encoded UTF-16LE) so that
    apostrophes or spaces in the Windows username / path never break the
    PowerShell string parser (the original single-quoted approach failed
    for usernames like "Miillyy's Gaming PC").
    """
    if sys.platform != "win32":
        return

    try:
        import base64

        exe_path  = str(Path(sys.executable).resolve())
        work_dir  = str(Path(sys.executable).parent.resolve())
        desktop   = os.path.join(os.path.expanduser("~"), "Desktop")
        shortcut  = os.path.join(desktop, "ChainMind Node.lnk")

        if os.path.exists(shortcut):
            return

        # Build the script with double-quoted PS strings (safe for apostrophes).
        # Backslashes in paths are fine inside double-quoted PS strings.
        # We then base64-encode the whole thing as UTF-16LE so PowerShell's
        # argument parser never sees any special characters at all.
        # Pass --no-setup so the shortcut never re-fires the wizard,
        # and set CHAINMIND_CONFIG via an env var wrapper argument so the
        # node always finds the pre-configured config.yaml regardless of cwd.
        cfg_path_arg = str(INSTALL_DIR / "config.yaml")

        ps_lines = [
            "$ws = New-Object -ComObject WScript.Shell",
            f'$sc = $ws.CreateShortcut("{shortcut}")',
            f'$sc.TargetPath = "{exe_path}"',
            f'$sc.Arguments = "--no-setup"',
            f'$sc.WorkingDirectory = "{work_dir}"',
            '$sc.Description = "ChainMind Network Node"',
            f'$sc.IconLocation = "{_get_ico_path()},0"',
            "$sc.Save()",
        ]
        ps_script = "; ".join(ps_lines)

        # PowerShell -EncodedCommand expects UTF-16LE base64
        encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")

        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", encoded],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            print(f"{GREEN}  ✔ Desktop shortcut created{RESET}")
        else:
            err = result.stderr.decode(errors="replace").strip()
            print(f"{YELLOW}  Desktop shortcut: {err}{RESET}")
    except Exception as e:
        print(f"{YELLOW}  Desktop shortcut failed: {e}{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Windows startup registration
# ─────────────────────────────────────────────────────────────────────────────
_STARTUP_KEY   = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_ENTRY = "ChainMind Network"


def _register_windows_startup() -> None:
    """Add this .exe to the Windows current-user startup registry key."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        exe = str(Path(sys.executable).resolve())
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY,
            0, winreg.KEY_SET_VALUE,
        )
        # --no-browser: don't pop up browser on background auto-start
        winreg.SetValueEx(key, _STARTUP_ENTRY, 0, winreg.REG_SZ,
                          f'"{exe}" --no-browser')
        winreg.CloseKey(key)
        print(f"{GREEN}  ✔ Added to Windows startup (runs automatically at login){RESET}")
    except Exception as e:
        print(f"{YELLOW}  Startup registration failed: {e}{RESET}")


def _is_registered_for_startup() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_READ,
        )
        winreg.QueryValueEx(key, _STARTUP_ENTRY)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _remove_windows_startup() -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_SET_VALUE,
        )
        winreg.DeleteValue(key, _STARTUP_ENTRY)
        winreg.CloseKey(key)
        print(f"{YELLOW}  Removed from Windows startup{RESET}")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 8.  Launch node server + dashboard as self-subprocesses
# ─────────────────────────────────────────────────────────────────────────────
_procs: list[subprocess.Popen] = []


def _spawn(args: list[str], log_file: Path) -> subprocess.Popen:
    logf = open(log_file, "a")
    proc = subprocess.Popen(
        [sys.executable] + args,
        stdout=logf, stderr=logf,
        cwd=str(INSTALL_DIR),
    )
    _procs.append(proc)
    return proc


def _launch_node(cfg: dict) -> subprocess.Popen:
    port = cfg.get("node", {}).get("port", 8000)
    proc = _spawn(["--_run-server"], LOG_DIR / "node.log")
    print(f"{GREEN}  ✔ Node API starting on port {port}  (log: data/logs/node.log){RESET}")
    return proc


def _launch_dashboard(cfg: dict, open_browser: bool = True) -> subprocess.Popen:
    dash_port = cfg.get("dashboard", {}).get("port", 8501)
    proc = _spawn(["--_run-dashboard", "--_port", str(dash_port)], LOG_DIR / "dashboard.log")
    url  = f"http://localhost:{dash_port}"
    print(f"{GREEN}  ✔ Dashboard starting at {CYAN}{url}{RESET}")

    if open_browser:
        def _open():
            time.sleep(4.0)   # give streamlit time to bind
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    return proc


def _on_exit(*_):
    print(f"\n{YELLOW}  Shutting down ChainMind Node…{RESET}")
    for p in _procs:
        try:
            p.terminate()
        except Exception:
            pass
    time.sleep(1)
    for p in _procs:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass
    print(f"{GREEN}  Goodbye!{RESET}")
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
# 9.  System tray icon
# ─────────────────────────────────────────────────────────────────────────────
def _make_tray_icon_image():
    """Load the ChainMind logo for the system tray."""
    try:
        from PIL import Image
    except ImportError:
        return None

    # Prefer the pre-built tray PNG in the assets folder
    candidates = [
        BUNDLE_DIR  / "assets" / "tray.png",
        INSTALL_DIR / "assets" / "tray.png",
        BUNDLE_DIR  / "assets" / "icon.png",
        INSTALL_DIR / "assets" / "icon.png",
    ]
    for path in candidates:
        if path.exists():
            try:
                img = Image.open(path).convert("RGBA").resize((64, 64))
                return img
            except Exception:
                continue

    # Absolute fallback: purple circle with "CM"
    try:
        from PIL import ImageDraw
        size = 64
        img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, size - 2, size - 2], fill=(124, 58, 237, 255))
        font = None
        try:
            from PIL import ImageFont
            font = ImageFont.load_default()
        except Exception:
            pass
        draw.text((18, 22), "CM", fill=(255, 255, 255, 255), font=font)
        return img
    except Exception:
        return None


def _run_tray(cfg: dict, node_proc_ref: list, no_dashboard: bool):
    """
    Start the system tray icon.  Blocks until the user clicks Exit.
    Should be called from the main thread on most platforms.
    Returns if pystray is unavailable (graceful degradation).
    """
    try:
        import pystray
    except ImportError:
        print(f"{YELLOW}  pystray not available — running without system tray.{RESET}")
        _console_wait_loop(node_proc_ref, cfg)
        return

    img = _make_tray_icon_image()
    if img is None:
        print(f"{YELLOW}  PIL not available — running without system tray.{RESET}")
        _console_wait_loop(node_proc_ref, cfg)
        return

    dash_port = cfg.get("dashboard", {}).get("port", 8501)
    dash_url  = f"http://localhost:{dash_port}"

    # ── Tray menu actions ────────────────────────────────────────────────────
    def on_open_dashboard(icon, item):
        webbrowser.open(dash_url)

    def on_restart_node(icon, item):
        p = node_proc_ref[0]
        if p:
            try:
                p.terminate()
            except Exception:
                pass
            time.sleep(1.5)
        _procs[:] = [x for x in _procs if x is not p]
        node_proc_ref[0] = _launch_node(cfg)

    def on_startup_toggle(icon, item):
        if _is_registered_for_startup():
            _remove_windows_startup()
        else:
            _register_windows_startup()

    def _startup_label(item):
        return "✔ Run on Windows login" if _is_registered_for_startup() else "Run on Windows login"

    def on_quit(icon, item):
        icon.stop()
        _on_exit()

    menu_items = [
        pystray.MenuItem("Open Dashboard", on_open_dashboard, default=True),
        pystray.MenuItem("Restart Node",   on_restart_node),
        pystray.Menu.SEPARATOR,
    ]
    if sys.platform == "win32":
        menu_items.append(
            pystray.MenuItem(_startup_label, on_startup_toggle)
        )
        menu_items.append(pystray.Menu.SEPARATOR)
    menu_items.append(pystray.MenuItem("Exit ChainMind", on_quit))

    icon = pystray.Icon(
        "ChainMind Network",
        img,
        f"ChainMind Node  v{_get_version()}",
        pystray.Menu(*menu_items),
    )

    # Background thread: watch the node process and restart on crash
    def _monitor():
        while True:
            time.sleep(5)
            p = node_proc_ref[0]
            if p and p.poll() is not None:
                print(f"{YELLOW}  Node process exited. Restarting…{RESET}")
                _procs[:] = [x for x in _procs if x is not p]
                node_proc_ref[0] = _launch_node(cfg)

    threading.Thread(target=_monitor, daemon=True).start()

    print(f"{GREEN}  ✔ ChainMind is running in the system tray. Right-click the tray icon to manage it.{RESET}\n")
    icon.run()   # blocks until icon.stop() is called


def _console_wait_loop(node_proc_ref: list, cfg: dict):
    """Fallback when no system tray: watch node process in a console loop."""
    print(f"\n{BOLD}  ChainMind Node is running.{RESET}")
    print(f"  Press {YELLOW}Ctrl+C{RESET} to stop.\n")
    while True:
        time.sleep(5)
        p = node_proc_ref[0]
        if p and p.poll() is not None:
            print(f"{YELLOW}  Node process exited. Restarting…{RESET}")
            _procs[:] = [x for x in _procs if x is not p]
            node_proc_ref[0] = _launch_node(cfg)


# ─────────────────────────────────────────────────────────────────────────────
# 10.  Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    # ── Windows taskbar & shortcut icon ────────────────────────────────────────
    # Must be called before ANY window (Tk or console) is created.
    # Without this, Windows groups the running process under a generic app ID
    # and ignores the shortcut's IconLocation, showing a white file icon instead.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ChainMind.Node"
            )
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="ChainMind Node")
    parser.add_argument("--update",       action="store_true", help="Force update check")
    parser.add_argument("--no-dashboard", action="store_true", help="Run node API only")
    parser.add_argument("--no-browser",   action="store_true", help="Don't open browser")
    parser.add_argument("--no-tray",      action="store_true", help="Disable system tray")
    parser.add_argument("--no-gui",       action="store_true", help="Disable desktop GUI window")
    parser.add_argument("--no-setup",      action="store_true",
                        help="Skip setup wizard even if config looks default")
    parser.add_argument("--setup",        action="store_true", help="Re-run setup wizard")
    args = parser.parse_args()

    banner()

    os.chdir(str(INSTALL_DIR))
    if str(INSTALL_DIR) not in sys.path:
        sys.path.insert(0, str(INSTALL_DIR))

    if args.setup:
        os.environ["CHAINMIND_SETUP"] = "1"
    if args.no_setup:
        os.environ["CHAINMIND_NO_SETUP"] = "1"
    from node.setup_wizard import maybe_run_wizard
    cfg = maybe_run_wizard()

    # ── Frozen-mode config relocation ──────────────────────────────────────────
    if getattr(sys, "frozen", False):
        import shutil as _shutil
        import yaml as _yaml
        install_cfg = INSTALL_DIR / "config.yaml"
        bundle_cfg  = BUNDLE_DIR / "config.yaml"
        if not install_cfg.exists():
            if bundle_cfg.exists():
                _shutil.copy2(str(bundle_cfg), str(install_cfg))
            else:
                for candidate in [
                    BUNDLE_DIR.parent / "config.yaml",
                    Path(sys.executable).parent / "config.yaml",
                ]:
                    if candidate.exists() and candidate != install_cfg:
                        _shutil.copy2(str(candidate), str(install_cfg))
                        break
                else:
                    if cfg:
                        with open(install_cfg, "w") as _f:
                            _yaml.dump(cfg, _f, default_flow_style=False)
        if install_cfg.exists():
            with open(install_cfg) as _f:
                cfg = _yaml.safe_load(_f) or cfg

    # ── One-time setup tasks ───────────────────────────────────────────────────
    _create_desktop_shortcut()

    # Register for Windows startup on first run (only if not already registered)
    if sys.platform == "win32" and not _is_registered_for_startup():
        _register_windows_startup()

    # ── Background update check ────────────────────────────────────────────────
    threading.Thread(
        target=_check_updates_bg,
        args=(args.update,),
        daemon=True,
    ).start()

    _ensure_ollama()
    _ensure_ollama_running(cfg)

    signal.signal(signal.SIGINT,  _on_exit)
    signal.signal(signal.SIGTERM, _on_exit)

    print()
    node_proc    = _launch_node(cfg)
    node_proc_ref = [node_proc]   # mutable ref so threads can swap it
    time.sleep(1.5)

    if not args.no_dashboard:
        _launch_dashboard(cfg, open_browser=not args.no_browser)

    # ── Desktop GUI window (optional, default ON) ─────────────────────────────
    _gui = None
    if not args.no_gui and not args.no_browser:
        try:
            from node.desktop_gui import ChainMindGUI
            _gui = ChainMindGUI(cfg, node_proc_ref, _on_exit)
        except Exception as _gui_err:
            print(f"{YELLOW}  Desktop GUI unavailable: {_gui_err}{RESET}")

    # Patch tray's "Open Dashboard" to also show the GUI window
    def _open_gui_from_tray():
        if _gui is not None:
            _gui.show()

    if args.no_tray:
        if _gui is not None:
            _gui.run()   # blocks; GUI is the main window
        else:
            _console_wait_loop(node_proc_ref, cfg)
    else:
        if _gui is not None:
            # Run tray in a background thread; GUI mainloop owns the main thread
            threading.Thread(
                target=_run_tray,
                args=(cfg, node_proc_ref, args.no_dashboard),
                daemon=True,
            ).start()
            _gui.run()
        else:
            _run_tray(cfg, node_proc_ref, args.no_dashboard)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point — dispatch before argparse for internal flags
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _internal_dispatch()   # exits early if --_run-server or --_run-dashboard
    main()
