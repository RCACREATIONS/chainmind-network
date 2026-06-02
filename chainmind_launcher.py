"""
chainmind_launcher.py
=====================
Single entry-point for the PyInstaller-frozen ChainMind Node executable.

Responsibilities
----------------
1.  Fix sys.path so frozen imports work (streamlit, node.*, etc.)
2.  Run the first-boot setup wizard if config.yaml is not yet configured
3.  Check for updates in the background (non-blocking)
4.  Launch the Streamlit dashboard + the FastAPI node server side-by-side
5.  On Ctrl-C / window close → cleanly shut down both processes

Usage (frozen .exe / app / AppImage):
    ChainMind-Node.exe                   # normal launch
    ChainMind-Node.exe --update          # force update check
    ChainMind-Node.exe --no-dashboard    # node API only, no browser UI
    ChainMind-Node.exe --setup           # re-run setup wizard
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
    BUNDLE_DIR  = Path(sys._MEIPASS)           # extracted bundle temp dir
    INSTALL_DIR = Path(sys.executable).parent  # where ChainMind-Node.exe lives
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

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Banner
# ─────────────────────────────────────────────────────────────────────────────
PURPLE = "\033[95m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def _get_version() -> str:
    ver_file = INSTALL_DIR / "VERSION"
    if ver_file.exists():
        return ver_file.read_text().strip()
    return "1.0.0"


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
# 3.  Self-update check (background thread, non-blocking)
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
    else:
        return "linux_x64"


def _do_update(info: dict, current: str, latest: str):
    import tempfile, shutil

    pkey = _platform_key()
    url  = info.get("assets", {}).get(pkey)
    if not url:
        print(f"{YELLOW}  No binary for {pkey} in this release.{RESET}")
        return

    print(f"\n{YELLOW}  ↑ Update available: {current} → {latest}{RESET}")
    print(f"{YELLOW}  Downloading ({url.split('/')[-1]})…{RESET}")

    try:
        import httpx
        tmp = Path(tempfile.gettempdir()) / f"chainmind_update_{latest}"
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as resp:
            total      = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded / total * 40)
                        bar = "█" * pct + "░" * (40 - pct)
                        print(f"\r  [{bar}] {downloaded//1024//1024}MB/{total//1024//1024}MB",
                              end="", flush=True)
        print()

        # Verify checksum if present
        expected = info.get("checksums", {}).get(pkey)
        if expected:
            import hashlib
            h = hashlib.sha256()
            with open(tmp, "rb") as f:
                for block in iter(lambda: f.read(65536), b""):
                    h.update(block)
            if h.hexdigest() != expected:
                print(f"{YELLOW}  Checksum mismatch — aborting update.{RESET}")
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
            print(f"{GREEN}  ✔ Updated to {latest}. Restart ChainMind to apply.{RESET}\n")
        except PermissionError:
            # Windows: exe is locked — schedule via bat on next restart
            bat = exe.parent / "_chainmind_update.bat"
            bat.write_text(
                "@echo off\n"
                "timeout /t 3 /nobreak >nul\n"
                f'move /y "{tmp}" "{exe}"\n'
                f'start "" "{exe}"\n'
                "del \"%~f0\"\n",
                encoding="utf-8",
            )
            (INSTALL_DIR / "VERSION").write_text(latest)
            print(f"{YELLOW}  Update staged. Will apply on next restart.{RESET}")
    except Exception as e:
        print(f"{YELLOW}  Update failed: {e}  (continuing with current version){RESET}")


def _check_updates_bg(force: bool = False):
    """Background thread: fetch manifest, silently download+swap if newer."""
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
# 4.  Ollama detection / auto-install
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
        Path("C:/Users") / os.environ.get("USERNAME", "") / "AppData/Local/Programs/Ollama/ollama.exe",
    ]
    for c in candidates:
        if c.exists():
            os.environ["PATH"] = str(c.parent) + os.pathsep + os.environ["PATH"]
            return True

    print(f"\n{YELLOW}  ⚠  Ollama not found.{RESET}")
    print(f"  Ollama is the AI engine that runs models on your machine.")
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
            print(f"{GREEN}  ✔ Ollama installed.{RESET}")
        elif sys.platform == "darwin":
            sp.run(["unzip", "-qo", str(tmp), "-d", "/Applications"], check=True)
            print(f"{GREEN}  ✔ Ollama.app installed in /Applications{RESET}")
        else:
            os.chmod(tmp, 0o755)
            sp.run(["sudo", "sh", str(tmp)], check=True)
            print(f"{GREEN}  ✔ Ollama installed.{RESET}")
    except Exception as e:
        print(f"{YELLOW}  Ollama install failed: {e}{RESET}")
        print(f"  Download manually: {url}")


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Launch node server + dashboard
# ─────────────────────────────────────────────────────────────────────────────
_procs: list[subprocess.Popen] = []


def _launch_node(cfg: dict) -> subprocess.Popen:
    port  = cfg.get("node", {}).get("port", 8000)
    logf  = open(LOG_DIR / "node.log", "a")
    python = sys.executable

    if getattr(sys, "frozen", False):
        cmd = [python, "-c",
               "import sys; sys.path.insert(0, sys._MEIPASS); "
               "from node.server import run_server; run_server()"]
    else:
        cmd = [python, "-m", "node.cli", "node", "start"]

    proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, cwd=str(INSTALL_DIR))
    print(f"{GREEN}  ✔ Node API started on port {port}  (log: data/logs/node.log){RESET}")
    _procs.append(proc)
    return proc


def _launch_dashboard(cfg: dict, open_browser: bool = True) -> subprocess.Popen:
    dash_port = cfg.get("dashboard", {}).get("port", 8501)
    logf      = open(LOG_DIR / "dashboard.log", "a")
    python    = sys.executable
    dash_path = BUNDLE_DIR / "node" / "dashboard.py"

    cmd = [
        python, "-m", "streamlit", "run", str(dash_path),
        "--server.port", str(dash_port),
        "--server.headless", "true",
        "--server.address", "localhost",
        "--browser.gatherUsageStats", "false",
    ]
    proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, cwd=str(INSTALL_DIR))
    url  = f"http://localhost:{dash_port}"
    print(f"{GREEN}  ✔ Dashboard started at {CYAN}{url}{RESET}")

    if open_browser:
        def _open():
            time.sleep(2.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    _procs.append(proc)
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
# 6.  Main
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

    update_thread = threading.Thread(
        target=_check_updates_bg,
        args=(args.update,),
        daemon=True,
    )
    update_thread.start()

    _ensure_ollama()

    signal.signal(signal.SIGINT,  _on_exit)
    signal.signal(signal.SIGTERM, _on_exit)

    print()
    node_proc = _launch_node(cfg)
    time.sleep(1.2)

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


if __name__ == "__main__":
    main()
