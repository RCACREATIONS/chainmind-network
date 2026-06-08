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
def _get_user_data_dir() -> Path:
    """
    Platform-specific user-writable data directory.
    Keeps config + database out of the install/exe folder so the app
    works correctly when installed to Program Files or any read-only location.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base) / "ChainMind"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ChainMind"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(xdg) / "chainmind"


if getattr(sys, "frozen", False):
    BUNDLE_DIR    = Path(sys._MEIPASS)
    INSTALL_DIR   = Path(sys.executable).parent
    USER_DATA_DIR = _get_user_data_dir()
else:
    BUNDLE_DIR    = Path(__file__).parent
    INSTALL_DIR   = Path(__file__).parent
    USER_DATA_DIR = INSTALL_DIR   # dev mode: data lives alongside the source

USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR    = USER_DATA_DIR / "data"
CONFIG_FILE = USER_DATA_DIR / "config.yaml"
LOG_DIR     = DATA_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

if str(BUNDLE_DIR) not in sys.path:
    sys.path.insert(0, str(BUNDLE_DIR))

# Tell every subprocess exactly where config.yaml lives so they don't have
# to guess — avoids the _MEIPASS vs install-dir confusion.
os.environ["CHAINMIND_CONFIG"] = str(CONFIG_FILE)

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
    "https://raw.githubusercontent.com/RCACREATIONS/chainmind-network/main/release/latest.json",
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

    releases_page = f"https://github.com/RCACREATIONS/chainmind-network/releases/tag/v{latest}"
    try:
        import httpx
        tmp = Path(tempfile.gettempdir()) / f"chainmind_update_{latest}"
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as resp:
            if resp.status_code == 404:
                print(f"{YELLOW}  Binary not available (private repository).{RESET}")
                print(f"{YELLOW}  Opening releases page in your browser: {releases_page}{RESET}")
                webbrowser.open(releases_page)
                return
            resp.raise_for_status()
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
        cfg_path_arg = str(CONFIG_FILE)

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
# 6.5  Windows self-installer
#
#  On first run (frozen exe NOT in the proper install directory) the launcher
#  acts as an installer:
#    1. Runs the setup wizard to collect node name / secrets
#    2. Copies itself to  %LOCALAPPDATA%\Programs\ChainMind Network\
#    3. Copies config.yaml + VERSION into the install dir
#    4. Creates a Desktop shortcut   → installed exe  --no-setup
#    5. Creates Start Menu entries   → installed exe  --no-setup
#    6. Registers the startup key    → installed exe  --no-setup --no-browser
#    7. Launches the installed exe and exits this (installer) process
#
#  All shortcuts/startup use --no-setup so the wizard never fires again.
# ─────────────────────────────────────────────────────────────────────────────

def _win_install_dir() -> Path:
    """Per-user install location — no administrator rights required."""
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(local) / "Programs" / "ChainMind Network"


def _is_running_from_install_dir() -> bool:
    """True when the frozen exe is already living in the proper install location."""
    if not getattr(sys, "frozen", False):
        return True   # plain Python / dev mode — skip installer entirely
    try:
        exe = Path(sys.executable).resolve()
        if sys.platform == "win32":
            return exe.parent.resolve() == _win_install_dir().resolve()
        elif sys.platform == "darwin":
            # Running inside a .app bundle: …/ChainMind Network.app/Contents/MacOS/…
            return ".app/Contents/MacOS" in str(exe)
        else:
            return exe.parent.resolve() == _linux_install_dir().resolve()
    except Exception:
        return True   # if in doubt, skip installer


def _make_lnk(lnk_path: str, target: str, workdir: str,
              args: str, icon: str) -> None:
    """Create a Windows .lnk shortcut via PowerShell EncodedCommand (handles spaces/apostrophes)."""
    import base64
    ps_lines = [
        "$ws = New-Object -ComObject WScript.Shell",
        f'$sc = $ws.CreateShortcut("{lnk_path}")',
        f'$sc.TargetPath = "{target}"',
        f'$sc.Arguments = "{args}"',
        f'$sc.WorkingDirectory = "{workdir}"',
        '$sc.Description = "ChainMind Network — Decentralised AI Node"',
        f'$sc.IconLocation = "{icon},0"',
        "$sc.Save()",
    ]
    ps      = "; ".join(ps_lines)
    encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-EncodedCommand", encoded],
        capture_output=True, timeout=15,
    )


def _win_install(cfg: dict) -> None:
    """
    Install to %LOCALAPPDATA%\\Programs\\ChainMind Network\\,
    create all shortcuts, register startup, then launch installed copy and exit.
    This function ALWAYS ends with sys.exit(0).
    """
    import shutil, base64

    install_dir = _win_install_dir()
    install_dir.mkdir(parents=True, exist_ok=True)

    exe_src = Path(sys.executable).resolve()
    exe_dst = install_dir / "ChainMind Node.exe"

    print(f"\n{CYAN}  Installing ChainMind Network to:{RESET}")
    print(f"  {install_dir}\n")

    # ── 1. Copy the executable ────────────────────────────────────────────────
    print(f"{CYAN}  Copying executable…{RESET}", end=" ", flush=True)
    shutil.copy2(str(exe_src), str(exe_dst))
    print(f"{GREEN}done{RESET}")

    # ── 2. Copy VERSION to install dir; seed config in user data dir ──────────
    ver_src = INSTALL_DIR / "VERSION"
    if ver_src.exists():
        shutil.copy2(str(ver_src), str(install_dir / "VERSION"))
    if not CONFIG_FILE.exists():
        for _cfg_src in [INSTALL_DIR / "config.yaml", BUNDLE_DIR / "config.yaml"]:
            if _cfg_src.exists():
                USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(_cfg_src), str(CONFIG_FILE))
                break

    # ── 3. Ensure data/logs directory ─────────────────────────────────────────
    (install_dir / "data" / "logs").mkdir(parents=True, exist_ok=True)
    (USER_DATA_DIR / "data" / "logs").mkdir(parents=True, exist_ok=True)

    # ── 4. Resolve icon path ──────────────────────────────────────────────────
    ico = str(exe_dst)   # fallback: Windows extracts icon from .exe
    for candidate in [
        BUNDLE_DIR  / "assets" / "icon.ico",
        INSTALL_DIR / "assets" / "icon.ico",
    ]:
        if candidate.exists():
            ico = str(candidate.resolve())
            break

    exe_str     = str(exe_dst)
    install_str = str(install_dir)

    # ── 5. Desktop shortcut ───────────────────────────────────────────────────
    print(f"{CYAN}  Creating Desktop shortcut…{RESET}", end=" ", flush=True)
    desktop  = os.path.join(os.path.expanduser("~"), "Desktop")
    lnk_desk = os.path.join(desktop, "ChainMind Node.lnk")
    _make_lnk(lnk_desk, exe_str, install_str, "--no-setup", ico)
    print(f"{GREEN}done{RESET}")

    # ── 6. Start Menu ─────────────────────────────────────────────────────────
    print(f"{CYAN}  Creating Start Menu entries…{RESET}", end=" ", flush=True)
    appdata   = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    sm_folder = os.path.join(appdata, "Microsoft", "Windows",
                             "Start Menu", "Programs", "ChainMind Network")
    os.makedirs(sm_folder, exist_ok=True)
    _make_lnk(os.path.join(sm_folder, "ChainMind Node.lnk"),
              exe_str, install_str, "--no-setup", ico)
    _make_lnk(os.path.join(sm_folder, "Uninstall ChainMind.lnk"),
              exe_str, install_str, "--uninstall", ico)
    print(f"{GREEN}done{RESET}")

    # ── 7. Auto-start on Windows login ───────────────────────────────────────
    print(f"{CYAN}  Registering auto-start…{RESET}", end=" ", flush=True)
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "ChainMind Network", 0, winreg.REG_SZ,
                          f'"{exe_str}" --no-setup --no-browser')
        winreg.CloseKey(key)
        print(f"{GREEN}done{RESET}")
    except Exception as e:
        print(f"{YELLOW}skipped ({e}){RESET}")

    # ── 8. Launch installed exe and exit installer ────────────────────────────
    print(f"\n{GREEN}  ✔ Installation complete!{RESET}")
    print(f"{GREEN}  Launching ChainMind Node from installation directory…{RESET}\n")
    subprocess.Popen(
        [str(exe_dst), "--no-setup"],
        cwd=str(install_dir),
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    sys.exit(0)


def _win_uninstall() -> None:
    """Remove install dir, shortcuts, and startup registry entry."""
    import shutil

    install_dir = _win_install_dir()

    # Remove startup entry
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        winreg.DeleteValue(key, "ChainMind Network")
        winreg.CloseKey(key)
    except Exception:
        pass

    # Remove Desktop shortcut
    lnk = os.path.join(os.path.expanduser("~"), "Desktop", "ChainMind Node.lnk")
    if os.path.exists(lnk):
        os.unlink(lnk)

    # Remove Start Menu folder
    appdata   = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    sm_folder = os.path.join(appdata, "Microsoft", "Windows",
                             "Start Menu", "Programs", "ChainMind Network")
    if os.path.exists(sm_folder):
        shutil.rmtree(sm_folder, ignore_errors=True)

    print(f"{GREEN}  ✔ ChainMind shortcuts and startup entry removed.{RESET}")
    print(f"{YELLOW}  To fully remove, delete: {install_dir}{RESET}")

    # Schedule self-deletion of install dir (happens after this process exits)
    if install_dir.exists():
        bat = Path(os.environ.get("TEMP", str(Path.home()))) / "_chainmind_uninstall.bat"
        bat.write_text(
            "@echo off\n"
            "timeout /t 2 /nobreak >nul\n"
            f'rmdir /s /q "{install_dir}"\n'
            "del \"%~f0\"\n",
            encoding="utf-8",
        )
        subprocess.Popen(["cmd", "/c", str(bat)],
                         creationflags=subprocess.DETACHED_PROCESS)

    print(f"{GREEN}  ChainMind Node has been uninstalled.{RESET}")
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
# 6.6  macOS self-installer
#
#  On first run (frozen binary NOT inside a .app bundle) the launcher acts as
#  an installer:
#    1. Runs the setup wizard to collect node name / secrets
#    2. Creates ~/Applications/ChainMind Network.app/ bundle structure
#    3. Copies binary → Contents/MacOS/ChainMind Node
#    4. Writes Contents/Info.plist + copies icon.icns → Contents/Resources/
#    5. Creates a LaunchAgent plist → auto-start at login
#    6. Registers app via 'open' so Finder/Dock recognise it
#    7. Launches the installed app and exits the installer process
# ─────────────────────────────────────────────────────────────────────────────

def _mac_app_dir() -> Path:
    """~/Applications/ChainMind Network.app"""
    return Path.home() / "Applications" / "ChainMind Network.app"


def _mac_binary_path() -> Path:
    """The installed binary inside the .app bundle."""
    return _mac_app_dir() / "Contents" / "MacOS" / "ChainMind Node"


def _mac_launch_agent_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.chainmind.network.plist"


def _mac_install(cfg: dict) -> None:
    """
    Build ~/Applications/ChainMind Network.app, install LaunchAgent, then
    launch the installed copy and exit.  Always ends with sys.exit(0).
    """
    import shutil

    app_dir     = _mac_app_dir()
    macos_dir   = app_dir / "Contents" / "MacOS"
    res_dir     = app_dir / "Contents" / "Resources"
    binary_dst  = macos_dir / "ChainMind Node"
    plist_path  = app_dir / "Contents" / "Info.plist"

    print(f"\n{CYAN}  Installing ChainMind Network to:{RESET}")
    print(f"  {app_dir}\n")

    # ── 1. Build bundle directory structure ───────────────────────────────────
    macos_dir.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "Contents" / "MacOS" / "data" / "logs").mkdir(parents=True, exist_ok=True)

    # ── 2. Copy executable ────────────────────────────────────────────────────
    print(f"{CYAN}  Copying executable…{RESET}", end=" ", flush=True)
    src_exe = Path(sys.executable).resolve()
    shutil.copy2(str(src_exe), str(binary_dst))
    os.chmod(str(binary_dst), 0o755)
    print(f"{GREEN}done{RESET}")

    # ── 3. Copy VERSION; seed config in user data dir ────────────────────────
    ver_src = INSTALL_DIR / "VERSION"
    if ver_src.exists():
        shutil.copy2(str(ver_src), str(macos_dir / "VERSION"))
    if not CONFIG_FILE.exists():
        for _cfg_src in [INSTALL_DIR / "config.yaml", BUNDLE_DIR / "config.yaml"]:
            if _cfg_src.exists():
                USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(_cfg_src), str(CONFIG_FILE))
                break

    # ── 4. Copy icon into Resources ───────────────────────────────────────────
    for candidate in [
        BUNDLE_DIR  / "assets" / "icon.icns",
        INSTALL_DIR / "assets" / "icon.icns",
    ]:
        if candidate.exists():
            shutil.copy2(str(candidate), str(res_dir / "icon.icns"))
            break

    # ── 5. Write Info.plist ───────────────────────────────────────────────────
    print(f"{CYAN}  Writing Info.plist…{RESET}", end=" ", flush=True)
    version_str = "1.0.0"
    try:
        version_str = (macos_dir / "VERSION").read_text(encoding="utf-8",
                                                         errors="ignore").strip().lstrip("v")
    except Exception:
        pass
    plist_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>ChainMind Node</string>
    <key>CFBundleIdentifier</key>
    <string>com.chainmind.network</string>
    <key>CFBundleName</key>
    <string>ChainMind Node</string>
    <key>CFBundleDisplayName</key>
    <string>ChainMind Network</string>
    <key>CFBundleVersion</key>
    <string>{version_str}</string>
    <key>CFBundleShortVersionString</key>
    <string>{version_str}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleIconFile</key>
    <string>icon</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
"""
    plist_path.write_text(plist_xml, encoding="utf-8")
    print(f"{GREEN}done{RESET}")

    # ── 6. LaunchAgent plist (auto-start at login) ────────────────────────────
    print(f"{CYAN}  Installing LaunchAgent…{RESET}", end=" ", flush=True)
    la_plist = _mac_launch_agent_plist()
    la_plist.parent.mkdir(parents=True, exist_ok=True)
    la_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.chainmind.network</string>
    <key>ProgramArguments</key>
    <array>
        <string>{binary_dst}</string>
        <string>--no-setup</string>
        <string>--no-browser</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{app_dir}/Contents/MacOS/data/logs/launchagent.log</string>
    <key>StandardErrorPath</key>
    <string>{app_dir}/Contents/MacOS/data/logs/launchagent.log</string>
</dict>
</plist>
"""
    la_plist.write_text(la_xml, encoding="utf-8")
    try:
        subprocess.run(["launchctl", "load", "-w", str(la_plist)],
                       capture_output=True, timeout=5)
    except Exception:
        pass
    print(f"{GREEN}done{RESET}")

    # ── 7. Register with Launch Services so Finder/Spotlight see the app ──────
    try:
        subprocess.run(
            ["/System/Library/Frameworks/CoreServices.framework/Frameworks/"
             "LaunchServices.framework/Support/lsregister",
             "-f", str(app_dir)],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass

    # ── 8. Launch installed app and exit installer ────────────────────────────
    print(f"\n{GREEN}  ✔ Installation complete!{RESET}")
    print(f"{GREEN}  Launching ChainMind Node from {app_dir.name}…{RESET}\n")
    subprocess.Popen(
        [str(binary_dst), "--no-setup"],
        cwd=str(macos_dir),
        start_new_session=True,
    )
    sys.exit(0)


def _mac_uninstall() -> None:
    """Remove the .app bundle and LaunchAgent."""
    import shutil

    app_dir = _mac_app_dir()
    la      = _mac_launch_agent_plist()

    try:
        subprocess.run(["launchctl", "unload", "-w", str(la)],
                       capture_output=True, timeout=5)
    except Exception:
        pass

    if la.exists():
        la.unlink()
        print(f"{YELLOW}  Removed LaunchAgent{RESET}")

    if app_dir.exists():
        shutil.rmtree(str(app_dir), ignore_errors=True)
        print(f"{GREEN}  ✔ Removed {app_dir}{RESET}")

    print(f"{GREEN}  ChainMind Node has been uninstalled.{RESET}")
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
# 6.7  Linux self-installer
#
#  On first run (frozen binary NOT in ~/.local/share/chainmind-network/) the
#  launcher acts as an installer:
#    1. Runs the setup wizard to collect node name / secrets
#    2. Copies binary → ~/.local/share/chainmind-network/chainmind-node
#    3. Creates ~/.local/share/applications/chainmind-network.desktop
#    4. Creates ~/.config/autostart/chainmind-network.desktop
#    5. Creates symlink in ~/.local/bin/chainmind-node (if dir on PATH)
#    6. Launches the installed binary and exits the installer process
# ─────────────────────────────────────────────────────────────────────────────

def _linux_install_dir() -> Path:
    """~/.local/share/chainmind-network/"""
    return Path.home() / ".local" / "share" / "chainmind-network"


def _linux_install(cfg: dict) -> None:
    """
    Install to ~/.local/share/chainmind-network/, create .desktop entries and
    autostart, then launch the installed binary and exit.
    Always ends with sys.exit(0).
    """
    import shutil

    install_dir  = _linux_install_dir()
    binary_dst   = install_dir / "chainmind-node"
    icon_dst     = install_dir / "icon.png"
    desktop_dir  = Path.home() / ".local" / "share" / "applications"
    autostart_dir = Path.home() / ".config" / "autostart"
    bin_dir      = Path.home() / ".local" / "bin"

    print(f"\n{CYAN}  Installing ChainMind Network to:{RESET}")
    print(f"  {install_dir}\n")

    # ── 1. Create directories ─────────────────────────────────────────────────
    install_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / "data" / "logs").mkdir(parents=True, exist_ok=True)
    desktop_dir.mkdir(parents=True, exist_ok=True)
    autostart_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)

    # ── 2. Copy executable ────────────────────────────────────────────────────
    print(f"{CYAN}  Copying executable…{RESET}", end=" ", flush=True)
    shutil.copy2(str(Path(sys.executable).resolve()), str(binary_dst))
    os.chmod(str(binary_dst), 0o755)
    print(f"{GREEN}done{RESET}")

    # ── 3. Copy VERSION; seed config in user data dir ────────────────────────
    ver_src = INSTALL_DIR / "VERSION"
    if ver_src.exists():
        shutil.copy2(str(ver_src), str(install_dir / "VERSION"))
    if not CONFIG_FILE.exists():
        for _cfg_src in [INSTALL_DIR / "config.yaml", BUNDLE_DIR / "config.yaml"]:
            if _cfg_src.exists():
                USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(_cfg_src), str(CONFIG_FILE))
                break

    # ── 4. Copy icon ──────────────────────────────────────────────────────────
    for candidate in [
        BUNDLE_DIR  / "assets" / "icon.png",
        INSTALL_DIR / "assets" / "icon.png",
    ]:
        if candidate.exists():
            shutil.copy2(str(candidate), str(icon_dst))
            break

    # ── 5. .desktop launcher file ─────────────────────────────────────────────
    print(f"{CYAN}  Creating application entry…{RESET}", end=" ", flush=True)
    icon_line = f"Icon={icon_dst}" if icon_dst.exists() else "Icon=network-wired"
    desktop_entry = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=ChainMind Node\n"
        "Comment=Decentralised AI Network Node\n"
        f"Exec={binary_dst} --no-setup\n"
        f"{icon_line}\n"
        "Terminal=false\n"
        "Categories=Network;Science;\n"
        "StartupNotify=true\n"
    )
    desktop_file = desktop_dir / "chainmind-network.desktop"
    desktop_file.write_text(desktop_entry, encoding="utf-8")
    os.chmod(str(desktop_file), 0o755)
    print(f"{GREEN}done{RESET}")

    # ── 6. Autostart entry ────────────────────────────────────────────────────
    print(f"{CYAN}  Registering auto-start…{RESET}", end=" ", flush=True)
    autostart_entry = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=ChainMind Node\n"
        f"Exec={binary_dst} --no-setup --no-browser\n"
        f"{icon_line}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Comment=ChainMind Network node — starts at login\n"
    )
    autostart_file = autostart_dir / "chainmind-network.desktop"
    autostart_file.write_text(autostart_entry, encoding="utf-8")
    os.chmod(str(autostart_file), 0o755)
    print(f"{GREEN}done{RESET}")

    # ── 7. Symlink in ~/.local/bin ────────────────────────────────────────────
    link = bin_dir / "chainmind-node"
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(binary_dst)
        print(f"{GREEN}  ✔ Symlink: {link} → {binary_dst}{RESET}")
    except Exception as e:
        print(f"{YELLOW}  Symlink skipped: {e}{RESET}")

    # ── 8. Refresh desktop database ──────────────────────────────────────────
    try:
        subprocess.run(["update-desktop-database", str(desktop_dir)],
                       capture_output=True, timeout=5)
    except Exception:
        pass

    # ── 9. Launch installed binary and exit installer ─────────────────────────
    print(f"\n{GREEN}  ✔ Installation complete!{RESET}")
    print(f"{GREEN}  Launching ChainMind Node from {install_dir}…{RESET}\n")
    subprocess.Popen(
        [str(binary_dst), "--no-setup"],
        cwd=str(install_dir),
        start_new_session=True,
    )
    sys.exit(0)


def _linux_uninstall() -> None:
    """Remove install dir, .desktop entries, symlink."""
    import shutil

    install_dir   = _linux_install_dir()
    desktop_file  = Path.home() / ".local" / "share" / "applications" / "chainmind-network.desktop"
    autostart_file = Path.home() / ".config" / "autostart" / "chainmind-network.desktop"
    link          = Path.home() / ".local" / "bin" / "chainmind-node"

    for p in (desktop_file, autostart_file):
        if p.exists():
            p.unlink()

    if link.is_symlink():
        link.unlink()

    try:
        subprocess.run(["update-desktop-database",
                        str(Path.home() / ".local" / "share" / "applications")],
                       capture_output=True, timeout=5)
    except Exception:
        pass

    if install_dir.exists():
        shutil.rmtree(str(install_dir), ignore_errors=True)
        print(f"{GREEN}  ✔ Removed {install_dir}{RESET}")

    print(f"{GREEN}  ChainMind Node has been uninstalled.{RESET}")
    sys.exit(0)


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
                          f'"{exe}" --no-browser --no-setup')
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
    parser = argparse.ArgumentParser(description="ChainMind Node")
    parser.add_argument("--update",       action="store_true", help="Force update check")
    parser.add_argument("--no-dashboard", action="store_true", help="Run node API only")
    parser.add_argument("--no-browser",   action="store_true", help="Don't open browser")
    parser.add_argument("--no-tray",      action="store_true", help="Disable system tray")
    parser.add_argument("--no-gui",       action="store_true", help="Disable desktop GUI window")
    parser.add_argument("--no-setup",     action="store_true",
                        help="Skip setup wizard (used by shortcuts launched from install dir)")
    parser.add_argument("--setup",        action="store_true", help="Re-run setup wizard")
    parser.add_argument("--uninstall",    action="store_true", help="Uninstall ChainMind Node")
    args = parser.parse_args()

    # ── Uninstall (all platforms) ──────────────────────────────────────────────
    if args.uninstall:
        banner()
        if sys.platform == "win32":
            _win_uninstall()       # exits
        elif sys.platform == "darwin":
            _mac_uninstall()       # exits
        else:
            _linux_uninstall()     # exits

    banner()

    # ── Self-install on first run (frozen binary not yet in install location) ──
    # Triggers when: frozen exe + not already in install dir + no --no-setup
    _needs_install = (
        getattr(sys, "frozen", False)
        and not args.no_setup
        and not args.setup
        and not _is_running_from_install_dir()
    )
    if _needs_install:
        # Run wizard so the user can name their node before we install
        os.chdir(str(INSTALL_DIR))
        if str(INSTALL_DIR) not in sys.path:
            sys.path.insert(0, str(INSTALL_DIR))
        from node.setup_wizard import maybe_run_wizard
        cfg = maybe_run_wizard()
        if sys.platform == "win32":
            _win_install(cfg)      # copies exe, creates shortcuts, exits
        elif sys.platform == "darwin":
            _mac_install(cfg)      # creates .app bundle, LaunchAgent, exits
        else:
            _linux_install(cfg)    # copies to ~/.local/share/, .desktop, exits

    # ── Normal startup (running from install dir or non-Windows) ──────────────
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
    # config.yaml lives in USER_DATA_DIR (%APPDATA%\ChainMind on Windows,
    # ~/Library/Application Support/ChainMind on macOS, ~/.config/chainmind on Linux).
    # Seed it from the bundle or install dir on first run if not yet present.
    if getattr(sys, "frozen", False):
        import shutil as _shutil
        import yaml as _yaml
        if not CONFIG_FILE.exists():
            for candidate in [
                BUNDLE_DIR / "config.yaml",
                BUNDLE_DIR.parent / "config.yaml",
                INSTALL_DIR / "config.yaml",
                Path(sys.executable).parent / "config.yaml",
            ]:
                if candidate.exists() and candidate.resolve() != CONFIG_FILE.resolve():
                    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                    _shutil.copy2(str(candidate), str(CONFIG_FILE))
                    break
            else:
                if cfg:
                    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                    with open(CONFIG_FILE, "w") as _f:
                        _yaml.dump(cfg, _f, default_flow_style=False)
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as _f:
                cfg = _yaml.safe_load(_f) or cfg

    # ── One-time setup tasks (only when running from the install dir) ──────────
    # The installer already created shortcuts on Windows; these are no-ops if
    # shortcuts/registry entries already exist.
    if not sys.platform == "win32" or _is_running_from_install_dir():
        _create_desktop_shortcut()
        if sys.platform == "win32" and not _is_registered_for_startup():
            _register_windows_startup()

    # ── Background update check ────────────────────────────────────────────────
    threading.Thread(
        target=_check_updates_bg,
        args=(args.update,),
        daemon=True,
    ).start()

    # ── Ollama bootstrap: install → start server → pull recommended model ────
    try:
        from node.ollama_bootstrap import ensure_ollama_ready
        _catalog = cfg.get("models", {}) if isinstance(cfg, dict) else {}
        _result = ensure_ollama_ready(catalog=_catalog, verbose=True)
        if _result.get("skipped") and not _result.get("installed"):
            # New bootstrap couldn't find or install Ollama — fall back to
            # the legacy interactive installer so the user still gets prompted.
            _ensure_ollama()
    except Exception as _boot_exc:
        print(f"{YELLOW}  Ollama bootstrap error: {_boot_exc} — falling back.{RESET}")
        _ensure_ollama()

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
