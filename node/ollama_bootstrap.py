"""
ollama_bootstrap.py — Auto-detect, install, start Ollama and pull the recommended model.

Called by:
  - setup_wizard.py  (first-run wizard — interactive)
  - run.sh           (every startup — so existing users always have Ollama ready)
  - chainmind_launcher.py (frozen exe entry-point)

Design:
  - Works on Linux, macOS, Windows
  - Verbose / silent modes
  - Idempotent — safe to call multiple times
  - Non-fatal: if Ollama cannot be installed the node still starts, dashboard
    shows "Ollama: Not running" as before
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

# ── Config path resolution (mirrors setup_wizard.py) ─────────────────────────
if os.environ.get("CHAINMIND_CONFIG"):
    _cfg_path = Path(os.environ["CHAINMIND_CONFIG"])
elif getattr(sys, "frozen", False):
    _cfg_path = Path(sys.executable).parent / "config.yaml"
else:
    _cfg_path = Path(__file__).parent.parent / "config.yaml"

OLLAMA_PORT = 11434
OLLAMA_BASE  = f"http://localhost:{OLLAMA_PORT}"

# ─────────────────────────────────────────────────────────────────────────────
# Detection helpers
# ─────────────────────────────────────────────────────────────────────────────

def find_ollama_exe() -> Optional[str]:
    """Return the path to the ollama executable or None if not found."""
    sys_path = shutil.which("ollama")
    if sys_path:
        return sys_path

    # Legacy: bundled tools/ folder
    tools_dir = Path(__file__).parent.parent / "tools"
    for name in ("ollama.exe", "ollama"):
        candidate = tools_dir / name
        if candidate.exists():
            return str(candidate)

    # Common install locations
    candidates = []
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            Path(local_app) / "Programs" / "Ollama" / "ollama.exe",
            Path("C:/Program Files/Ollama/ollama.exe"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            Path("/usr/local/bin/ollama"),
            Path("/opt/homebrew/bin/ollama"),
            Path.home() / ".ollama" / "bin" / "ollama",
        ]
    else:
        candidates = [
            Path("/usr/local/bin/ollama"),
            Path("/usr/bin/ollama"),
            Path.home() / ".local" / "bin" / "ollama",
            Path.home() / "bin" / "ollama",
        ]

    for c in candidates:
        if c.exists():
            return str(c)

    return None


def is_ollama_installed() -> bool:
    return find_ollama_exe() is not None


def is_ollama_running() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def list_local_models() -> list[str]:
    """Return list of model names currently installed in Ollama."""
    try:
        r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Install Ollama
# ─────────────────────────────────────────────────────────────────────────────

def _print(msg: str, verbose: bool) -> None:
    if verbose:
        print(msg, flush=True)


def install_ollama(verbose: bool = True) -> bool:
    """
    Attempt to install Ollama for the current platform.
    Returns True on success, False on failure.
    """
    plat = sys.platform
    _print(f"\n[Ollama] Not installed — attempting automatic installation on {platform.system()}…", verbose)

    try:
        if plat == "linux":
            return _install_linux(verbose)
        elif plat == "darwin":
            return _install_macos(verbose)
        elif plat == "win32":
            return _install_windows(verbose)
        else:
            _print(f"[Ollama] Unsupported platform: {plat}. Install from https://ollama.ai/download", verbose)
            return False
    except Exception as exc:
        _print(f"[Ollama] Installation error: {exc}", verbose)
        return False


def _install_linux(verbose: bool) -> bool:
    """Install Ollama on Linux using the official install script."""
    _print("[Ollama] Running: curl -fsSL https://ollama.ai/install.sh | sh", verbose)
    try:
        result = subprocess.run(
            "curl -fsSL https://ollama.ai/install.sh | sh",
            shell=True,
            capture_output=not verbose,
            timeout=300,
        )
        if result.returncode == 0:
            _print("[Ollama] ✅ Installed successfully.", verbose)
            return True
        _print(f"[Ollama] Install script exited {result.returncode}.", verbose)
        return False
    except subprocess.TimeoutExpired:
        _print("[Ollama] Installation timed out.", verbose)
        return False


def _install_macos(verbose: bool) -> bool:
    """Install Ollama on macOS — download and open the .pkg installer."""
    import urllib.request

    url = "https://ollama.ai/download/Ollama-darwin.zip"
    _print(f"[Ollama] Downloading macOS package from {url}…", verbose)

    try:
        tmp = tempfile.mkdtemp()
        zip_path = os.path.join(tmp, "Ollama-darwin.zip")

        with urllib.request.urlopen(url, timeout=120) as resp:
            with open(zip_path, "wb") as f:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if verbose and total:
                        pct = downloaded * 100 // total
                        print(f"\r[Ollama] Downloading… {pct}%", end="", flush=True)

        if verbose:
            print()

        _print("[Ollama] Extracting…", verbose)
        subprocess.run(["unzip", "-q", "-o", zip_path, "-d", tmp], check=True)

        app_src = os.path.join(tmp, "Ollama.app")
        app_dst = "/Applications/Ollama.app"

        if os.path.exists(app_src):
            subprocess.run(["cp", "-r", app_src, app_dst], check=True)
            subprocess.run(["open", app_dst], check=False)
            _print("[Ollama] ✅ Ollama.app installed to /Applications. Waiting for it to start…", verbose)
            for _ in range(15):
                time.sleep(2)
                if is_ollama_running():
                    return True
            return is_ollama_running()
        else:
            _print("[Ollama] Could not find Ollama.app in download.", verbose)
            return False

    except Exception as exc:
        _print(f"[Ollama] macOS install failed: {exc}", verbose)
        _print("[Ollama] Please install manually from https://ollama.ai/download", verbose)
        return False


def _install_windows(verbose: bool) -> bool:
    """Install Ollama on Windows — download and run OllamaSetup.exe silently."""
    import urllib.request

    url = "https://ollama.ai/download/OllamaSetup.exe"
    _print(f"[Ollama] Downloading Windows installer from {url}…", verbose)

    try:
        tmp = tempfile.mkdtemp()
        exe_path = os.path.join(tmp, "OllamaSetup.exe")

        with urllib.request.urlopen(url, timeout=120) as resp:
            with open(exe_path, "wb") as f:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if verbose and total:
                        pct = downloaded * 100 // total
                        print(f"\r[Ollama] Downloading… {pct}%", end="", flush=True)

        if verbose:
            print()

        _print("[Ollama] Running OllamaSetup.exe /S (silent install)…", verbose)
        result = subprocess.run([exe_path, "/S"], timeout=300)

        if result.returncode == 0:
            _print("[Ollama] ✅ Installed. Waiting for Ollama to start…", verbose)
            time.sleep(5)
            return True

        _print(f"[Ollama] Installer exited {result.returncode}.", verbose)
        return False

    except Exception as exc:
        _print(f"[Ollama] Windows install failed: {exc}", verbose)
        _print("[Ollama] Please install manually from https://ollama.ai/download", verbose)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Start Ollama server
# ─────────────────────────────────────────────────────────────────────────────

def start_ollama(ollama_exe: str, verbose: bool = True) -> bool:
    """
    Start 'ollama serve' in the background.
    Returns True once the server responds on port 11434, False on timeout.
    """
    _print("[Ollama] Starting Ollama server in background…", verbose)
    try:
        subprocess.Popen(
            [ollama_exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        _print(f"[Ollama] Could not start ollama serve: {exc}", verbose)
        return False

    # Wait up to 20 s for the server to come up
    for i in range(20):
        time.sleep(1)
        if is_ollama_running():
            _print("[Ollama] ✅ Ollama server is running.", verbose)
            return True
        if verbose:
            print(f"\r[Ollama] Waiting for server… {i + 1}s", end="", flush=True)

    if verbose:
        print()
    _print("[Ollama] ⚠ Ollama server did not start in time.", verbose)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Model selection
# ─────────────────────────────────────────────────────────────────────────────

def _load_catalog() -> dict:
    """Load model catalog from config.yaml."""
    try:
        import yaml
        with open(_cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("models", {})
    except Exception:
        return {}


def pick_recommended_model(catalog: dict, hw: dict) -> Optional[str]:
    """
    Pick the single best model for this hardware.
    Uses the existing system_check helpers.
    Returns a model name string, or None if nothing fits.
    """
    try:
        from .system_check import filter_models_for_system, get_tier_for_system
    except ImportError:
        from node.system_check import filter_models_for_system, get_tier_for_system

    tier = get_tier_for_system(hw)
    compatible = filter_models_for_system(catalog, hw)

    # For each tier, pick from appropriate catalog sections (best quality that fits)
    tier_sections: dict[str, list[str]] = {
        "nano":       ["tiny"],
        "micro":      ["small", "tiny"],
        "standard":   ["small", "medium", "tiny"],
        "pro":        ["medium", "small", "large"],
        "enterprise": ["large", "medium"],
    }

    for section in tier_sections.get(tier, ["tiny"]):
        models = compatible.get(section, [])
        fitting = [m for m in models if m.get("fits")]
        if fitting:
            # Pick the last (highest quality) fitting model in this section
            return fitting[-1]["name"]

    # Absolute fallback — smallest model that fits anything
    for section in ["tiny", "small", "medium", "large"]:
        models = compatible.get(section, [])
        fitting = [m for m in models if m.get("fits")]
        if fitting:
            return fitting[0]["name"]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Pull model
# ─────────────────────────────────────────────────────────────────────────────

def pull_model(model_name: str, ollama_exe: str, verbose: bool = True) -> bool:
    """
    Pull a model via `ollama pull <model>`.
    Shows live progress if verbose=True.
    Returns True on success.
    """
    _print(f"\n[Ollama] Pulling model: {model_name}  (this may take a while)…", verbose)
    try:
        result = subprocess.run(
            [ollama_exe, "pull", model_name],
            capture_output=not verbose,
            timeout=3600,
        )
        if result.returncode == 0:
            _print(f"[Ollama] ✅ Model '{model_name}' is ready.", verbose)
            return True
        _print(f"[Ollama] Pull exited {result.returncode}.", verbose)
        return False
    except subprocess.TimeoutExpired:
        _print("[Ollama] Model pull timed out (1 hour limit).", verbose)
        return False
    except Exception as exc:
        _print(f"[Ollama] Pull error: {exc}", verbose)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main entry-point
# ─────────────────────────────────────────────────────────────────────────────

def ensure_ollama_ready(
    catalog: Optional[dict] = None,
    verbose: bool = True,
    auto_install: bool = True,
    auto_pull: bool = True,
) -> dict:
    """
    Full Ollama bootstrap sequence:
      1. Check if Ollama is installed → install if missing
      2. Check if Ollama server is running → start it if not
      3. Check if any models are installed → pull recommended model if none

    Returns a result dict:
      {
        "installed": bool,
        "running": bool,
        "model_pulled": str | None,   # model name that was pulled, or None
        "models": list[str],          # all installed model names after bootstrap
        "skipped": bool,              # True if install was skipped (no permission etc)
      }
    """
    try:
        from .system_check import get_system_info
    except ImportError:
        from node.system_check import get_system_info

    result: dict = {
        "installed": False,
        "running": False,
        "model_pulled": None,
        "models": [],
        "skipped": False,
    }

    if catalog is None:
        catalog = _load_catalog()

    hw = get_system_info()

    # ── Step 1: Ensure Ollama is installed ───────────────────────────────────
    ollama_exe = find_ollama_exe()

    if not ollama_exe:
        if auto_install:
            ok = install_ollama(verbose=verbose)
            if ok:
                ollama_exe = find_ollama_exe()
            if not ollama_exe:
                _print(
                    "[Ollama] ⚠ Could not install Ollama automatically.\n"
                    "         Download it manually from https://ollama.ai/download\n"
                    "         The node will start without Ollama.",
                    verbose,
                )
                result["skipped"] = True
                return result
        else:
            result["skipped"] = True
            return result

    result["installed"] = True

    # ── Step 2: Ensure server is running ─────────────────────────────────────
    if is_ollama_running():
        _print("[Ollama] Server already running.", verbose)
        result["running"] = True
    else:
        result["running"] = start_ollama(ollama_exe, verbose=verbose)

    if not result["running"]:
        _print("[Ollama] ⚠ Could not start Ollama server. Node will start anyway.", verbose)
        return result

    # ── Step 3: Ensure at least one model is installed ───────────────────────
    existing = list_local_models()
    result["models"] = existing

    if existing:
        _print(f"[Ollama] Models already installed: {', '.join(existing)}", verbose)
        return result

    if not auto_pull:
        return result

    recommended = pick_recommended_model(catalog, hw)
    if not recommended:
        _print("[Ollama] ⚠ No compatible model found for your hardware.", verbose)
        return result

    _print(f"\n[Ollama] No models installed. Recommended for your hardware: {recommended}", verbose)
    ok = pull_model(recommended, ollama_exe, verbose=verbose)
    if ok:
        result["model_pulled"] = recommended
        result["models"] = list_local_models()
    else:
        _print(
            f"[Ollama] ⚠ Could not pull '{recommended}'. "
            "You can pull a model manually via the Models page in the dashboard.",
            verbose,
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# __main__ — called from run.sh as: python -m node.ollama_bootstrap
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ensure_ollama_ready(verbose=True)
