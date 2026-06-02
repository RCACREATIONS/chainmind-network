"""
node/updater.py
===============
Self-update logic for the ChainMind Node.

Can be called:
  - From the launcher (background thread at startup)
  - From the Streamlit dashboard (Settings → Check for Updates button)
  - From the CLI: python -m node.cli update

Update strategy
---------------
  chainmind.com.ng/api/release/latest.json (primary)
  → GitHub Releases raw manifest (fallback mirror)

Flow:
  1. Fetch latest.json from update servers (tries both, first success wins)
  2. Compare semantic version against VERSION file in install dir
  3. If newer: stream-download the platform binary to a temp file
  4. Verify SHA-256 checksum from the manifest
  5. Atomic swap: rename old exe → .old, move new exe into place
  6. On Windows: schedule swap via a small .bat if exe is locked
  7. Write new VERSION; signal the caller that a restart is needed
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# ── Constants ─────────────────────────────────────────────────────────────────
UPDATE_MANIFEST_URLS = [
    "https://chainmind.com.ng/api/release/latest.json",
    "https://raw.githubusercontent.com/chainmind-network/chainmind-node/main/release/latest.json",
]

INSTALL_DIR  = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.parent
VERSION_FILE = INSTALL_DIR / "VERSION"


def current_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return "0.0.0"


# ── Version comparison ────────────────────────────────────────────────────────
def _parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.lstrip("v").split(".")[:3])


def version_gt(a: str, b: str) -> bool:
    try:
        return _parse(a) > _parse(b)
    except Exception:
        return False


# ── Platform detection ────────────────────────────────────────────────────────
def _platform_key() -> str:
    p = sys.platform
    if p == "win32":
        return "windows_x64" if platform.machine().endswith("64") else "windows_x86"
    elif p == "darwin":
        return "macos_arm64" if platform.machine() == "arm64" else "macos_x64"
    else:
        return "linux_x64"


# ── Manifest ──────────────────────────────────────────────────────────────────
@dataclass
class ReleaseInfo:
    version:   str
    changelog: str
    assets:    dict[str, str]   # platform_key → download URL
    checksums: dict[str, str]   # platform_key → sha256 hex


def fetch_latest() -> Optional[ReleaseInfo]:
    """Fetch release manifest from update servers. Returns None on total failure."""
    try:
        import httpx
        for url in UPDATE_MANIFEST_URLS:
            try:
                r = httpx.get(url, timeout=10, follow_redirects=True)
                if r.status_code == 200:
                    d = r.json()
                    return ReleaseInfo(
                        version=d["version"],
                        changelog=d.get("changelog", ""),
                        assets=d.get("assets", {}),
                        checksums=d.get("checksums", {}),
                    )
            except Exception:
                continue
    except ImportError:
        pass
    return None


# ── Download ──────────────────────────────────────────────────────────────────
def _download(url: str, dest: Path, progress_cb: Optional[Callable[[int, int], None]] = None):
    """Stream-download url → dest; calls progress_cb(bytes_done, total_bytes)."""
    import httpx
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done  = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(65536):
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ── Atomic swap ───────────────────────────────────────────────────────────────
def _atomic_swap(new_bin: Path) -> bool:
    """
    Replace the running executable with new_bin.
    Returns True if swap was immediate, False if staged for next restart (Windows locked exe).
    """
    exe = Path(sys.executable)
    old = exe.with_suffix(".old")

    if sys.platform != "win32":
        if old.exists():
            old.unlink()
        exe.rename(old)
        shutil.move(str(new_bin), str(exe))
        os.chmod(exe, 0o755)
        return True

    # Windows: running exe is locked → schedule via bat
    bat = exe.parent / "_chainmind_update.bat"
    bat.write_text(
        "@echo off\n"
        "timeout /t 3 /nobreak >nul\n"
        f'move /y "{new_bin}" "{exe}"\n'
        f'start "" "{exe}"\n'
        "del \"%~f0\"\n",
        encoding="utf-8",
    )
    return False


# ── Public result type ────────────────────────────────────────────────────────
@dataclass
class UpdateResult:
    available:   bool = False
    applied:     bool = False
    staged:      bool = False   # Windows: will apply on next restart
    new_version: str  = ""
    changelog:   str  = ""
    error:       str  = ""


# ── Main public API ───────────────────────────────────────────────────────────
def check_and_apply(
    progress_cb: Optional[Callable[[int, int], None]] = None,
    silent_if_current: bool = True,
    force: bool = False,
) -> UpdateResult:
    """
    Full update cycle. Safe to call from any thread.

    progress_cb(bytes_done, total_bytes) — called during download
    silent_if_current=True → returns UpdateResult(available=False) quietly
    force=True → re-apply even if version matches (useful for repair)
    """
    result = UpdateResult()

    info = fetch_latest()
    if not info:
        result.error = "Could not reach update server."
        return result

    cv = current_version()
    if not force and not version_gt(info.version, cv):
        return result   # already up to date

    result.available   = True
    result.new_version = info.version
    result.changelog   = info.changelog

    pkey = _platform_key()
    url  = info.assets.get(pkey)
    if not url:
        result.error = f"No binary available for {pkey}"
        return result

    tmp = Path(tempfile.gettempdir()) / f"chainmind_{info.version}_{pkey}"
    try:
        _download(url, tmp, progress_cb)
    except Exception as e:
        result.error = f"Download failed: {e}"
        return result

    expected_cs = info.checksums.get(pkey)
    if expected_cs:
        actual_cs = _sha256(tmp)
        if actual_cs != expected_cs:
            result.error = f"Checksum mismatch (expected {expected_cs[:16]}…, got {actual_cs[:16]}…)"
            tmp.unlink(missing_ok=True)
            return result

    try:
        immediate = _atomic_swap(tmp)
    except Exception as e:
        result.error = f"Swap failed: {e}"
        return result

    VERSION_FILE.write_text(info.version)

    if immediate:
        result.applied = True
    else:
        result.staged = True

    return result


def background_check() -> None:
    """Fire-and-forget: check silently; print notice if update applied. Never raises."""
    try:
        r = check_and_apply(silent_if_current=True)
        if r.applied:
            print(f"\n\033[92m  ✔ Updated to {r.new_version}. Restart to apply.\033[0m")
        elif r.staged:
            print(f"\n\033[93m  ↑ Update staged ({r.new_version}). Restart ChainMind to apply.\033[0m")
        elif r.error:
            pass   # silent — never disrupt the node over an update failure
    except Exception:
        pass


# ── CLI usage ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Current version : {current_version()}")
    print(f"Platform key    : {_platform_key()}")
    print("Checking for updates…")
    r = check_and_apply(
        progress_cb=lambda d, t: print(f"\r  {d//1024//1024}MB/{t//1024//1024}MB", end=""),
        silent_if_current=False,
    )
    if r.available:
        print(f"\nUpdate available: {r.new_version}")
        if r.applied: print("Applied! Restart to use the new version.")
        if r.staged:  print("Staged. Will apply on next restart.")
        if r.error:   print(f"Error: {r.error}")
    else:
        if r.error:   print(f"Error: {r.error}")
        else:         print("Already up to date.")
