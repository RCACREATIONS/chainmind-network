"""
image_gen.py — ChainMind Image Generation Engine

Manages a separate Python venv (data/imgenv/) with diffusers + transformers.
Runs image generation as a subprocess so it never loads GPU memory into the
main node process.

Job flow:
  1. central_client._poll_once() receives job_type='image_gen'
  2. Calls ImageGenEngine.generate(params) -> base64 PNG string
  3. base64 is submitted to submit-result.php in result_images field
  4. Image is NEVER saved to disk on the node operator's machine
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger("image_gen")

# ── Paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT  = Path(__file__).parent.parent
_DATA_DIR   = _REPO_ROOT / "data"
_VENV_DIR   = _DATA_DIR / "imgenv"
_MODEL_DIR  = _DATA_DIR / "imgmodels"
_READY_FILE = _DATA_DIR / "imgenv_ready.flag"
_WORKER     = Path(__file__).parent / "_imgworker.py"

# Map tier → (model_id, min_vram_gb, min_ram_gb, label)
_MODEL_MAP = {
    "enterprise": ("stabilityai/stable-diffusion-xl-base-1.0", 10.0, 16.0, "SDXL"),
    "pro":        ("stabilityai/stable-diffusion-xl-base-1.0", 10.0, 16.0, "SDXL"),
    "standard":   ("runwayml/stable-diffusion-v1-5",           4.0,  8.0,  "SD 1.5"),
    "micro":      ("CompVis/stable-diffusion-v1-4",            4.0,  6.0,  "SD 1.4"),
    "nano":       ("nota-ai/bk-sdm-small",                     0.0,  4.0,  "BK-SDM-Small (CPU)"),
}

# Packages installed in the dedicated image venv
_IMG_PACKAGES = [
    "torch",
    "diffusers>=0.27",
    "transformers>=4.40",
    "accelerate>=0.30",
    "safetensors>=0.4",
    "huggingface_hub>=0.23",
    "Pillow>=10.0",
]


def _venv_python() -> str:
    if platform.system() == "Windows":
        return str(_VENV_DIR / "Scripts" / "python.exe")
    return str(_VENV_DIR / "bin" / "python")


def _venv_pip() -> str:
    if platform.system() == "Windows":
        return str(_VENV_DIR / "Scripts" / "pip.exe")
    return str(_VENV_DIR / "bin" / "pip")


def is_imgenv_ready() -> bool:
    """Return True if the image gen venv is installed and flagged ready."""
    return _READY_FILE.exists() and Path(_venv_python()).exists()


def get_image_model_for_hw(hw: dict) -> tuple[str, str]:
    """
    Return (model_id, label) appropriate for this hardware.
    Walks down from best to CPU fallback until something fits.
    """
    vram = hw.get("gpu_vram_gb", 0.0)
    ram  = hw.get("ram_gb", 4.0)
    for t in ["enterprise", "pro", "standard", "micro", "nano"]:
        model_id, min_vram, min_ram, label = _MODEL_MAP[t]
        if t == "nano":
            return model_id, label
        if vram >= min_vram or ram >= min_ram:
            return model_id, label
    return _MODEL_MAP["nano"][0], _MODEL_MAP["nano"][3]


def get_image_model_for_tier(tier: str) -> tuple[str, str]:
    """Return the canonical (model_id, label) for a given tier key."""
    entry = _MODEL_MAP.get(tier, _MODEL_MAP["nano"])
    return entry[0], entry[3]


def is_model_downloaded(model_id: str) -> bool:
    """Check whether a model snapshot exists in _MODEL_DIR."""
    safe_name  = model_id.replace("/", "--")
    model_path = _MODEL_DIR / safe_name
    return model_path.exists() and any(model_path.iterdir())


# ── Venv setup ────────────────────────────────────────────────────────────────

def setup_imgenv(progress_cb=None) -> bool:
    """
    Install the dedicated image-generation venv synchronously.
    progress_cb(msg: str) receives status lines.
    Returns True on success.
    """
    def _log(msg: str):
        log.info(msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _MODEL_DIR.mkdir(parents=True, exist_ok=True)

        if not _VENV_DIR.exists():
            _log("Creating image generation virtual environment…")
            subprocess.run(
                [sys.executable, "-m", "venv", str(_VENV_DIR)],
                check=True, capture_output=True,
            )
            _log("Virtual environment created.")

        _log("Upgrading pip in image venv…")
        subprocess.run(
            [_venv_python(), "-m", "pip", "install", "--upgrade", "pip"],
            check=True, capture_output=True,
        )

        total = len(_IMG_PACKAGES)
        for i, pkg in enumerate(_IMG_PACKAGES, 1):
            _log(f"  [{i}/{total}] Installing {pkg}…")
            subprocess.run(
                [_venv_pip(), "install", pkg, "--quiet"],
                check=True, capture_output=True,
            )

        _READY_FILE.write_text("ready")
        _log("✅ Image generation environment ready.")
        return True

    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else ""
        _log(f"Setup failed: {stderr[:400]}")
        return False
    except Exception as e:
        _log(f"Setup error: {e}")
        return False


async def setup_imgenv_async(progress_cb=None) -> bool:
    """Non-blocking wrapper — runs setup in a thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: setup_imgenv(progress_cb))


# ── Model download ────────────────────────────────────────────────────────────

def download_model(model_id: str, progress_cb=None) -> bool:
    """
    Download a diffusers model snapshot into _MODEL_DIR using huggingface_hub.
    Skips if already present. Returns True on success.
    """
    def _log(msg: str):
        log.info(msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    if not is_imgenv_ready():
        _log("Image venv not ready — run setup first.")
        return False

    if is_model_downloaded(model_id):
        _log(f"Model '{model_id}' already downloaded — skipping.")
        return True

    _log(f"Downloading model '{model_id}' — this may take several minutes…")

    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from huggingface_hub import snapshot_download\n"
        f"model_id  = {json.dumps(model_id)}\n"
        f"model_dir = Path({json.dumps(str(_MODEL_DIR))}) / model_id.replace('/', '--')\n"
        "model_dir.mkdir(parents=True, exist_ok=True)\n"
        "print(f'Downloading {model_id}…', flush=True)\n"
        "snapshot_download(\n"
        "    repo_id=model_id,\n"
        "    local_dir=str(model_dir),\n"
        "    local_dir_use_symlinks=False,\n"
        "    ignore_patterns=['*.msgpack', '*.h5', 'flax_model*'],\n"
        ")\n"
        "print('DOWNLOAD_COMPLETE', flush=True)\n"
    )

    try:
        proc = subprocess.Popen(
            [_venv_python(), "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            _log(line.rstrip())
        proc.wait()
        if proc.returncode == 0:
            _log(f"✅ Model '{model_id}' downloaded.")
            return True
        _log(f"Model download failed with exit code {proc.returncode}")
        return False
    except Exception as e:
        _log(f"Model download error: {e}")
        return False


async def download_model_async(model_id: str, progress_cb=None) -> bool:
    """Non-blocking wrapper — runs download in a thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: download_model(model_id, progress_cb))


# ── Image generation ──────────────────────────────────────────────────────────

async def generate_image(
    prompt: str,
    model_id: str,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    guidance_scale: float = 7.5,
    seed: int = -1,
) -> Optional[str]:
    """
    Generate an image via the imgenv subprocess worker.
    Returns a base64-encoded PNG string, or None on failure.
    The image exists only in memory — never written to disk.
    """
    if not is_imgenv_ready():
        log.error("Image venv not ready.")
        return None

    if not is_model_downloaded(model_id):
        log.error(f"Model '{model_id}' not downloaded.")
        return None

    safe_name  = model_id.replace("/", "--")
    model_path = str(_MODEL_DIR / safe_name)

    payload = json.dumps({
        "prompt":          prompt,
        "model_path":      model_path,
        "negative_prompt": negative_prompt,
        "width":           width,
        "height":          height,
        "steps":           steps,
        "guidance_scale":  guidance_scale,
        "seed":            seed,
    })

    try:
        proc = await asyncio.create_subprocess_exec(
            _venv_python(), str(_WORKER),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(payload.encode()),
            timeout=300,
        )

        if proc.returncode != 0:
            log.error(f"Image worker error: {stderr.decode(errors='replace')[:400]}")
            return None

        result = json.loads(stdout.decode())
        if result.get("ok"):
            log.info("Image generated successfully (in-memory, not saved to disk)")
            return result["b64"]
        log.error(f"Image worker returned error: {result.get('error')}")
        return None

    except asyncio.TimeoutError:
        log.error("Image generation timed out (5 min)")
        try:
            proc.kill()
        except Exception:
            pass
        return None
    except Exception as e:
        log.error(f"Image generation exception: {e}")
        return None
