"""
vision.py — ChainMind Vision (LLaVA) Engine

Manages a separate Python venv (data/visionenv/) with transformers + torch.
Runs vision inference as a subprocess so heavy ML never loads into the main process.

Job flow:
  1. central_client._poll_once() receives job_type='vision'
  2. Calls run_vision(prompt, image_b64) -> answer text
  3. Text answer is submitted to submit-result.php as the 'result' field
  4. Input image is processed entirely in memory — never written to disk

Tier rules:
  - Standard / Pro / Enterprise + GPU detected → auto-download on startup
  - Nano / Micro / any tier without GPU         → Settings toggle only
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger("vision")

# ── Paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT     = Path(__file__).parent.parent
_DATA_DIR      = _REPO_ROOT / "data"
_VENV_DIR      = _DATA_DIR / "visionenv"
_MODEL_DIR     = _DATA_DIR / "visionmodels"
_READY_FILE    = _DATA_DIR / "visionenv_ready.flag"
_WORKER        = Path(__file__).parent / "_visionworker.py"

# Tiers that auto-download IF a GPU is present
AUTO_GPU_TIERS = {"standard", "pro", "enterprise"}

# ── Model map ─────────────────────────────────────────────────────────────────
# (model_id, min_vram_gb, cpu_ok, label)
# GPU models (standard / pro / enterprise)
_GPU_MODEL_ID    = "llava-hf/llava-1.5-7b-hf"
_GPU_MODEL_LABEL = "LLaVA 1.5 7B"
_GPU_MIN_VRAM    = 6.0

# CPU / small-device model (nano / micro / no GPU)
_CPU_MODEL_ID    = "vikhyatk/moondream2"
_CPU_MODEL_LABEL = "Moondream 2 (CPU)"

# Packages installed in the dedicated vision venv
_VISION_PACKAGES = [
    "torch",
    "transformers>=4.40",
    "accelerate>=0.30",
    "safetensors>=0.4",
    "huggingface_hub>=0.23",
    "Pillow>=10.0",
    "einops>=0.7",
]


def _venv_python() -> str:
    if platform.system() == "Windows":
        return str(_VENV_DIR / "Scripts" / "python.exe")
    return str(_VENV_DIR / "bin" / "python")


def _venv_pip() -> str:
    if platform.system() == "Windows":
        return str(_VENV_DIR / "Scripts" / "pip.exe")
    return str(_VENV_DIR / "bin" / "pip")


def is_visionenv_ready() -> bool:
    return _READY_FILE.exists() and Path(_venv_python()).exists()


def is_model_downloaded(model_id: str) -> bool:
    safe = model_id.replace("/", "--")
    p    = _MODEL_DIR / safe
    return p.exists() and any(p.iterdir())


def should_auto_enable(tier: str, hw: dict) -> bool:
    """Return True if this tier+hardware should auto-download the GPU vision model."""
    return tier in AUTO_GPU_TIERS and hw.get("has_gpu", False) and hw.get("gpu_vram_gb", 0) >= _GPU_MIN_VRAM


def get_vision_model_for_hw(hw: dict) -> tuple[str, str]:
    """
    Return (model_id, label) based on hardware.
    GPU with enough VRAM → LLaVA 7B; otherwise → Moondream2 (CPU).
    """
    if hw.get("has_gpu") and hw.get("gpu_vram_gb", 0) >= _GPU_MIN_VRAM:
        return _GPU_MODEL_ID, _GPU_MODEL_LABEL
    return _CPU_MODEL_ID, _CPU_MODEL_LABEL


# ── Venv setup ────────────────────────────────────────────────────────────────

def setup_visionenv(progress_cb=None) -> bool:
    def _log(msg):
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
            _log("Creating vision virtual environment…")
            subprocess.run(
                [sys.executable, "-m", "venv", str(_VENV_DIR)],
                check=True, capture_output=True,
            )
            _log("Virtual environment created.")

        _log("Upgrading pip in vision venv…")
        subprocess.run(
            [_venv_python(), "-m", "pip", "install", "--upgrade", "pip"],
            check=True, capture_output=True,
        )

        total = len(_VISION_PACKAGES)
        for i, pkg in enumerate(_VISION_PACKAGES, 1):
            _log(f"  [{i}/{total}] Installing {pkg}…")
            subprocess.run(
                [_venv_pip(), "install", pkg, "--quiet"],
                check=True, capture_output=True,
            )

        _READY_FILE.write_text("ready")
        _log("✅ Vision environment ready.")
        return True

    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else ""
        _log(f"Setup failed: {stderr[:400]}")
        return False
    except Exception as e:
        _log(f"Setup error: {e}")
        return False


async def setup_visionenv_async(progress_cb=None) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: setup_visionenv(progress_cb))


# ── Model download ────────────────────────────────────────────────────────────

def download_model(model_id: str, progress_cb=None) -> bool:
    def _log(msg):
        log.info(msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    if not is_visionenv_ready():
        _log("Vision venv not ready — run setup first.")
        return False

    if is_model_downloaded(model_id):
        _log(f"Model '{model_id}' already downloaded.")
        return True

    _log(f"Downloading vision model '{model_id}'…")

    script = (
        "from huggingface_hub import snapshot_download\n"
        "from pathlib import Path\n"
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
            _log(f"✅ Vision model '{model_id}' downloaded.")
            return True
        _log(f"Download failed (exit {proc.returncode})")
        return False
    except Exception as e:
        _log(f"Download error: {e}")
        return False


async def download_model_async(model_id: str, progress_cb=None) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: download_model(model_id, progress_cb))


# ── Vision inference ──────────────────────────────────────────────────────────

async def run_vision(
    prompt: str,
    image_b64: str,
    model_id: str,
    max_new_tokens: int = 512,
) -> Optional[str]:
    """
    Run vision inference via the visionenv subprocess worker.
    prompt     — the question / instruction
    image_b64  — base64-encoded image (PNG or JPEG)
    Returns the model's text answer, or None on failure.
    """
    if not is_visionenv_ready():
        log.error("Vision venv not ready.")
        return None

    if not is_model_downloaded(model_id):
        log.error(f"Vision model '{model_id}' not downloaded.")
        return None

    safe_name  = model_id.replace("/", "--")
    model_path = str(_MODEL_DIR / safe_name)

    payload = json.dumps({
        "prompt":         prompt,
        "image_b64":      image_b64,
        "model_path":     model_path,
        "model_id":       model_id,
        "max_new_tokens": max_new_tokens,
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
            log.error(f"Vision worker error: {stderr.decode(errors='replace')[:400]}")
            return None

        result = json.loads(stdout.decode())
        if result.get("ok"):
            return result["text"]
        log.error(f"Vision worker error: {result.get('error')}")
        return None

    except asyncio.TimeoutError:
        log.error("Vision inference timed out (5 min)")
        try:
            proc.kill()
        except Exception:
            pass
        return None
    except Exception as e:
        log.error(f"Vision inference exception: {e}")
        return None
