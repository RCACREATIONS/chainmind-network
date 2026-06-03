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
# 6.  Launch node server + dashboard as self-subprocesses
#     Uses --_run-server / --_run-dashboard so the frozen .exe routes
#     correctly without needing python -c or python -m flags.
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
# 7.  Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="ChainMind Node")
    parser.add_argument("--update",       action="store_true", help="Force update check")
    parser.add_argument("--no-dashboard", action="store_true", help="Run node API only")
    parser.add_argument("--no-browser",   action="store_true", help="Don't open browser")
    parser.add_argument("--setup",        action="store_true", help="Re-run setup wizard")
    args = parser.parse_args()

    banner()

    os.chdir(str(INSTALL_DIR))
    if str(INSTALL_DIR) not in sys.path:
        sys.path.insert(0, str(INSTALL_DIR))

    if args.setup:
        os.environ["CHAINMIND_SETUP"] = "1"
    from node.setup_wizard import maybe_run_wizard
    cfg = maybe_run_wizard()

    # ── Frozen-mode config relocation ──────────────────────────────────────────
    # setup_wizard.py uses Path(__file__).parent.parent to find the save location,
    # which in a frozen exe resolves to _MEIPASS (temp dir), NOT the install dir.
    # After the wizard runs, copy config.yaml from wherever it was written to
    # INSTALL_DIR so all subprocesses (pointed via CHAINMIND_CONFIG) find it.
    if getattr(sys, "frozen", False):
        import shutil as _shutil
        import yaml as _yaml
        install_cfg = INSTALL_DIR / "config.yaml"
        # Where the wizard likely saved it (relative to __file__ in frozen mode)
        bundle_cfg  = BUNDLE_DIR / "config.yaml"
        if not install_cfg.exists():
            if bundle_cfg.exists():
                _shutil.copy2(str(bundle_cfg), str(install_cfg))
            else:
                # Last resort: walk up from BUNDLE_DIR looking for config.yaml
                for candidate in [
                    BUNDLE_DIR.parent / "config.yaml",
                    Path(sys.executable).parent / "config.yaml",
                ]:
                    if candidate.exists() and candidate != install_cfg:
                        _shutil.copy2(str(candidate), str(install_cfg))
                        break
                else:
                    # Config still missing — write it from the dict the wizard returned
                    if cfg:
                        with open(install_cfg, "w") as _f:
                            _yaml.dump(cfg, _f, default_flow_style=False)
        # Re-read cfg from the canonical location so it's always consistent
        if install_cfg.exists():
            with open(install_cfg) as _f:
                cfg = _yaml.safe_load(_f) or cfg

    threading.Thread(
        target=_check_updates_bg,
        args=(args.update,),
        daemon=True,
    ).start()

    _ensure_ollama()

    signal.signal(signal.SIGINT,  _on_exit)
    signal.signal(signal.SIGTERM, _on_exit)

    print()
    node_proc = _launch_node(cfg)
    time.sleep(1.5)

    if not args.no_dashboard:
        _launch_dashboard(cfg, open_browser=not args.no_browser)

    print(f"\n{BOLD}  ChainMind Node is running.{RESET}")
    print(f"  Press {YELLOW}Ctrl+C{RESET} to stop.\n")

    while True:
        time.sleep(5)
        if node_proc.poll() is not None:
            print(f"{YELLOW}  Node process exited. Restarting…{RESET}")
            _procs.remove(node_proc)
            node_proc = _launch_node(cfg)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point — dispatch before argparse for internal flags
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _internal_dispatch()   # exits early if --_run-server or --_run-dashboard
    main()
