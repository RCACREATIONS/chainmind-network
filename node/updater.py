"""
node/updater.py
===============
Self-update logic for the ChainMind Node.

Supports two update modes:
  1. Binary swap  – frozen (PyInstaller) builds on Windows / macOS / Linux
  2. Source patch – plain Python installs; downloads a zip and unpacks it
     over the source tree so any file (code, config, assets) can be patched.

Can be called from:
  - Desktop GUI   (progress + status shown in a Toplevel dialog)
  - Dashboard     (Settings → Check for Updates)
  - CLI           : python -m node.updater
  - Launcher      (background thread at startup)

Manifest format  (latest.json)
--------------------------------
{
  "version":   "1.2.5",
  "changelog": "What changed / URL to release notes",
  "assets": {
    "windows_x64":  "<url to .exe>",
    "macos_arm64":  "<url to .zip>",
    "linux_x64":    "<url to binary>",
    "source":       "<url to source .zip – used for plain-Python installs>"
  },
  "checksums": {
    "windows_x64":  "<sha256>",
    "macos_arm64":  "<sha256>",
    "linux_x64":    "<sha256>",
    "source":       "<sha256>"
  }
}
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
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# ── Constants ──────────────────────────────────────────────────────────────────
UPDATE_MANIFEST_URLS = [
    "https://chainmind.com.ng/api/release/latest.json",
    "https://raw.githubusercontent.com/chainmind-network/chainmind-node/main/release/latest.json",
]

INSTALL_DIR  = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.parent
VERSION_FILE = INSTALL_DIR / "VERSION"

# Files / directories that the source-patch extractor will never overwrite
# (user config, database, identity keys, logs).
_SOURCE_PATCH_SKIP = {
    "config.yaml",
    "data",
    ".venv",
    "GENERATED_NODE_TOKEN.txt",
}


def current_version() -> str:
    if VERSION_FILE.exists():
        try:
            raw = VERSION_FILE.read_bytes()
            v = raw.decode("utf-8", errors="ignore").replace("\x00", "").strip()
            return v if v else "0.0.0"
        except Exception:
            return "0.0.0"
    return "0.0.0"


# ── Version comparison ─────────────────────────────────────────────────────────
def _parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.lstrip("v").split(".")[:3])


def version_gt(a: str, b: str) -> bool:
    try:
        return _parse(a) > _parse(b)
    except Exception:
        return False


# ── Platform detection ─────────────────────────────────────────────────────────
def _platform_key() -> str:
    if getattr(sys, "frozen", False):
        p = sys.platform
        if p == "win32":
            return "windows_x64" if platform.machine().endswith("64") else "windows_x86"
        elif p == "darwin":
            return "macos_arm64" if platform.machine() == "arm64" else "macos_x64"
        else:
            return "linux_x64"
    return "source"


# ── Manifest ───────────────────────────────────────────────────────────────────
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


# ── Download ───────────────────────────────────────────────────────────────────
def _download(
    url: str,
    dest: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    status_cb:   Optional[Callable[[str], None]] = None,
):
    """Stream-download url → dest; calls progress_cb(bytes_done, total) and status_cb(msg)."""
    import httpx
    if status_cb:
        status_cb(f"Connecting to download server…")
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done  = 0
        if status_cb and total:
            mb = total / 1_048_576
            status_cb(f"Downloading update ({mb:.1f} MB)…")
        elif status_cb:
            status_cb("Downloading update…")
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


# ── Binary swap (frozen builds) ────────────────────────────────────────────────
def _atomic_swap(new_bin: Path, status_cb: Optional[Callable[[str], None]] = None) -> bool:
    """
    Replace the running executable with new_bin.
    Returns True if swap was immediate, False if staged for next restart (Windows locked exe).
    """
    if status_cb:
        status_cb("Applying update…")
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


# ── Source patch (plain-Python installs) ───────────────────────────────────────
def _apply_source_patch(
    zip_path: Path,
    status_cb: Optional[Callable[[str], None]] = None,
) -> None:
    """
    Extract a source zip over INSTALL_DIR, skipping protected paths.

    Expected zip structure (files relative to a single top-level folder or root):
        chainmind-node-1.2.5/node/server.py
        chainmind-node-1.2.5/node/updater.py
        chainmind-node-1.2.5/VERSION
        ...
    OR flat (files at root of zip):
        node/server.py
        node/updater.py
        VERSION
        ...
    """
    if status_cb:
        status_cb("Applying source patch…")

    dest = INSTALL_DIR

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

        # Detect a common top-level prefix (e.g. "chainmind-node-1.2.5/")
        prefix = ""
        if names:
            first = names[0]
            candidate = first.split("/")[0] + "/"
            if all(n.startswith(candidate) for n in names if n.strip("/")):
                prefix = candidate

        for member in names:
            # Strip the top-level prefix if any
            rel = member[len(prefix):] if prefix else member
            if not rel or rel.endswith("/"):
                continue  # skip directories

            # Skip protected files / dirs
            top = rel.split("/")[0]
            if top in _SOURCE_PATCH_SKIP:
                continue

            out_path = dest / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

    if status_cb:
        status_cb("Source patch applied.")


# ── Public result type ─────────────────────────────────────────────────────────
@dataclass
class UpdateResult:
    available:   bool = False
    applied:     bool = False
    staged:      bool = False   # Windows: will apply on next restart
    new_version: str  = ""
    changelog:   str  = ""
    error:       str  = ""


# ── Main public API ────────────────────────────────────────────────────────────
def check_and_apply(
    progress_cb: Optional[Callable[[int, int], None]] = None,
    status_cb:   Optional[Callable[[str], None]] = None,
    silent_if_current: bool = True,
    force: bool = False,
) -> UpdateResult:
    """
    Full update cycle. Safe to call from any thread.

    progress_cb(bytes_done, total_bytes) — called during download
    status_cb(message)                  — called for human-readable status steps
    silent_if_current=True              — returns UpdateResult(available=False) quietly
    force=True                          — re-apply even if version matches (repair)
    """
    result = UpdateResult()

    if status_cb:
        status_cb("Checking for updates…")

    info = fetch_latest()
    if not info:
        result.error = "Could not reach update server. Check your internet connection."
        return result

    cv = current_version()
    if status_cb:
        status_cb(f"Current: v{cv}  →  Latest: v{info.version}")

    if not force and not version_gt(info.version, cv):
        if status_cb:
            status_cb(f"You are already on the latest version (v{cv}).")
        return result   # already up to date

    result.available   = True
    result.new_version = info.version
    result.changelog   = info.changelog

    pkey = _platform_key()
    url  = info.assets.get(pkey)
    if not url:
        # Source key not in manifest — try falling back to the generic source key
        if pkey == "source":
            result.error = (
                "No source package available for this release yet. "
                "Pull the latest code manually from GitHub."
            )
        else:
            result.error = f"No binary available for platform: {pkey}"
        return result

    # Choose file extension for temp file
    ext = ".zip" if (pkey in ("macos_arm64", "macos_x64", "source") or url.endswith(".zip")) else ""
    tmp = Path(tempfile.gettempdir()) / f"chainmind_{info.version}_{pkey}{ext}"

    try:
        _download(url, tmp, progress_cb=progress_cb, status_cb=status_cb)
    except Exception as e:
        result.error = f"Download failed: {e}"
        return result

    # Verify checksum
    expected_cs = info.checksums.get(pkey)
    if expected_cs:
        if status_cb:
            status_cb("Verifying checksum…")
        actual_cs = _sha256(tmp)
        if actual_cs != expected_cs:
            result.error = (
                f"Checksum mismatch — download may be corrupt.\n"
                f"Expected: {expected_cs[:16]}…\n"
                f"Got:      {actual_cs[:16]}…"
            )
            tmp.unlink(missing_ok=True)
            return result

    # Apply
    try:
        if pkey == "source":
            _apply_source_patch(tmp, status_cb=status_cb)
            VERSION_FILE.write_text(info.version)
            result.applied = True
        else:
            # macOS: binary is inside a zip
            if pkey in ("macos_arm64", "macos_x64") and zipfile.is_zipfile(tmp):
                if status_cb:
                    status_cb("Extracting macOS binary…")
                extract_dir = tmp.parent / f"chainmind_extract_{info.version}"
                extract_dir.mkdir(exist_ok=True)
                with zipfile.ZipFile(tmp, "r") as zf:
                    zf.extractall(extract_dir)
                # Find the binary inside
                candidates = list(extract_dir.rglob("ChainMind*"))
                if candidates:
                    tmp = candidates[0]
                    os.chmod(tmp, 0o755)

            immediate = _atomic_swap(tmp, status_cb=status_cb)
            VERSION_FILE.write_text(info.version)
            if immediate:
                result.applied = True
            else:
                result.staged = True
    except Exception as e:
        result.error = f"Failed to apply update: {e}"
        return result
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    if status_cb:
        if result.applied:
            status_cb(f"✓ Updated to v{info.version}! Restart ChainMind to use the new version.")
        elif result.staged:
            status_cb(f"✓ Update staged (v{info.version}). It will apply automatically on next restart.")

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


# ── CLI usage ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Current version : {current_version()}")
    print(f"Platform key    : {_platform_key()}")
    print("Checking for updates…")

    def _status(msg: str):
        print(f"  {msg}")

    def _progress(done: int, total: int):
        if total:
            pct = done * 100 // total
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            mb_done  = done  / 1_048_576
            mb_total = total / 1_048_576
            print(f"\r  [{bar}] {mb_done:.1f}/{mb_total:.1f} MB  ", end="", flush=True)

    r = check_and_apply(
        progress_cb=_progress,
        status_cb=_status,
        silent_if_current=False,
    )
    print()
    if r.available:
        print(f"Update available: v{r.new_version}")
        if r.applied:  print("Applied! Restart to use the new version.")
        if r.staged:   print("Staged. Will apply on next restart.")
        if r.error:    print(f"Error: {r.error}")
    else:
        if r.error:    print(f"Error: {r.error}")
        else:          print("Already up to date.")
