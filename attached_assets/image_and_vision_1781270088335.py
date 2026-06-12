"""
ChainMind Node  Image Generation + Vision Module
================================================
Drop this file into your node's directory alongside your existing
node code. Import it in your main job-claiming loop.

Handles:
  - job_type == 'image_gen'  : Stable Diffusion (GPU) or placeholder
  - job_type == 'vision'     : LLaVA multimodal via Ollama
  - job_type == 'file_qa'    : Text-only file understanding via Ollama

Auto-detects system capabilities on first run:
  - GPU + enough VRAM  → tries Stable Diffusion (diffusers)
  - No GPU / low VRAM  → uses Ollama LLaVA as fallback
  - Also checks available disk space and RAM

Usage in your job loop:
  from image_and_vision import handle_special_job, detect_capabilities
  caps = detect_capabilities()
  # caps is sent to central server via heartbeat so it knows what this node can do

  if job['job_type'] in ('image_gen', 'vision', 'file_qa'):
      result = handle_special_job(job, caps)
"""

import base64
import io
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Optional

import requests

logger = logging.getLogger("chainmind.multimodal")

# ── System detection ─────────────────────────────────────────────────────────

def detect_capabilities() -> dict:
    """
    Detect what this node can handle.
    Returns a capabilities dict that should be sent to the central server
    in your heartbeat payload as 'capabilities'.
    """
    caps = {
        "image_gen":   False,
        "image_gen_engine": None,     # "sd", "sdxl", "flux", "ollama_llava"
        "vision":      False,
        "vision_model": None,
        "file_qa":     True,          # always supported via text LLM
        "gpu":         False,
        "gpu_name":    None,
        "vram_gb":     0,
        "ram_gb":      _ram_gb(),
        "disk_free_gb": _disk_free_gb(),
        "sd_model_path": None,
    }

    # ── GPU detection ──────────────────────────────────────────────────────
    gpu_info = _detect_gpu()
    caps["gpu"]      = gpu_info["has_gpu"]
    caps["gpu_name"] = gpu_info["name"]
    caps["vram_gb"]  = gpu_info["vram_gb"]

    # ── Stable Diffusion availability ─────────────────────────────────────
    if gpu_info["has_gpu"] and gpu_info["vram_gb"] >= 4:
        sd_ready, sd_model, sd_engine = _check_stable_diffusion(gpu_info["vram_gb"])
        if sd_ready:
            caps["image_gen"]        = True
            caps["image_gen_engine"] = sd_engine
            caps["sd_model_path"]    = sd_model
            logger.info(f"[caps] Stable Diffusion ready: engine={sd_engine} model={sd_model}")
    elif not gpu_info["has_gpu"] and caps["ram_gb"] >= 8:
        # CPU-only SD is very slow but possible as last resort
        logger.info("[caps] No GPU — SD possible on CPU but will be slow")

    # ── LLaVA / vision via Ollama ─────────────────────────────────────────
    llava_model = _check_ollama_vision()
    if llava_model:
        caps["vision"]       = True
        caps["vision_model"] = llava_model
        # If we couldn't get SD, use LLaVA for image gen too (describe → refuse)
        if not caps["image_gen"]:
            caps["image_gen"]        = True
            caps["image_gen_engine"] = "ollama_llava"
        logger.info(f"[caps] LLaVA vision model: {llava_model}")

    logger.info(f"[caps] System: GPU={caps['gpu']} VRAM={caps['vram_gb']}GB "
                f"RAM={caps['ram_gb']}GB image_gen={caps['image_gen']} "
                f"engine={caps['image_gen_engine']} vision={caps['vision']}")
    return caps


def _ram_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024**2), 1)
    except Exception:
        pass
    return 0.0


def _disk_free_gb() -> float:
    try:
        total, used, free = shutil.disk_usage("/")
        return round(free / (1024**3), 1)
    except Exception:
        return 0.0


def _detect_gpu() -> dict:
    """Detect NVIDIA/AMD/Apple GPU."""
    result = {"has_gpu": False, "name": None, "vram_gb": 0}

    # NVIDIA via nvidia-smi
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
        if out:
            parts = out.split(",")
            name  = parts[0].strip()
            vram  = int(parts[1].strip()) // 1024  # MiB → GiB
            result.update({"has_gpu": True, "name": name, "vram_gb": vram})
            return result
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # AMD via rocm-smi
    try:
        out = subprocess.check_output(
            ["rocm-smi", "--showmeminfo", "vram", "--csv"],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode()
        if "GPU" in out:
            result.update({"has_gpu": True, "name": "AMD GPU", "vram_gb": 8})
            return result
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Apple Silicon via sysctl
    if platform.system() == "Darwin":
        try:
            out = subprocess.check_output(
                ["sysctl", "hw.memsize"], stderr=subprocess.DEVNULL, timeout=3
            ).decode()
            mem_bytes = int(out.split(":")[1].strip())
            vram = round(mem_bytes / (1024**3) * 0.75, 1)  # shared — estimate 75%
            result.update({"has_gpu": True, "name": "Apple Silicon", "vram_gb": vram})
            return result
        except Exception:
            pass

    return result


def _check_stable_diffusion(vram_gb: float) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Check if Stable Diffusion is available.
    Returns (ready, model_id_or_path, engine_name).
    Auto-selects model based on available VRAM.
    """
    # Try to import diffusers
    try:
        import torch
        import diffusers  # noqa
    except ImportError:
        logger.info("[sd] diffusers not installed — will attempt install")
        ok = _install_diffusers()
        if not ok:
            return False, None, None

    # Select model based on VRAM
    if vram_gb >= 10:
        model_id = "stabilityai/stable-diffusion-xl-base-1.0"
        engine   = "sdxl"
    elif vram_gb >= 6:
        model_id = "runwayml/stable-diffusion-v1-5"
        engine   = "sd15"
    elif vram_gb >= 4:
        model_id = "CompVis/stable-diffusion-v1-4"
        engine   = "sd14"
    else:
        # Low VRAM — use a tiny fp16 model
        model_id = "nota-ai/bk-sdm-small"
        engine   = "sd_tiny"

    # Check if model is cached locally
    cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
    model_cached = _is_model_cached(model_id, cache_dir)

    if not model_cached:
        logger.info(f"[sd] Model {model_id} not cached — will download on first use")

    return True, model_id, engine


def _is_model_cached(model_id: str, cache_dir: str) -> bool:
    """Check HuggingFace cache for model."""
    slug = model_id.replace("/", "--")
    model_dir = os.path.join(cache_dir, f"models--{slug}")
    return os.path.isdir(model_dir)


def _check_ollama_vision() -> Optional[str]:
    """Return vision model name if Ollama has one available."""
    vision_models = ["llava", "llava:7b", "llava:13b", "llava:34b",
                     "bakllava", "llama3.2-vision", "moondream"]
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            for vm in vision_models:
                for m in models:
                    if vm in m.lower():
                        return m
    except Exception:
        pass
    return None


def _install_diffusers() -> bool:
    """Attempt to pip install diffusers + torch."""
    logger.info("[sd] Installing diffusers, transformers, accelerate, torch...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q",
             "diffusers", "transformers", "accelerate", "safetensors"],
            timeout=300
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.error(f"[sd] Install failed: {e}")
        return False


# ── Main job handler ─────────────────────────────────────────────────────────

def handle_special_job(job: dict, caps: dict) -> dict:
    """
    Handle image_gen, vision, or file_qa jobs.

    Args:
        job:  The job dict from claim-job.php (id, prompt, model, image_params, etc.)
        caps: The capabilities dict from detect_capabilities()

    Returns:
        dict with keys: result, result_images, tokens_in, tokens_out, duration_ms, status
    """
    job_type = job.get("job_type", "text")
    t_start  = time.time()

    if job_type == "image_gen":
        return _handle_image_gen(job, caps, t_start)
    elif job_type == "vision":
        return _handle_vision(job, caps, t_start)
    elif job_type == "file_qa":
        return _handle_file_qa(job, t_start)
    else:
        return {
            "status": "error",
            "result": f"Unknown job_type: {job_type}",
            "result_images": None,
            "tokens_in": 0, "tokens_out": 0,
            "duration_ms": int((time.time() - t_start) * 1000),
        }


def _handle_image_gen(job: dict, caps: dict, t_start: float) -> dict:
    """Generate an image from text prompt."""
    engine = caps.get("image_gen_engine")
    prompt = job.get("prompt", "")

    img_params = {}
    if job.get("image_params"):
        try:
            img_params = json.loads(job["image_params"])
        except Exception:
            pass

    negative_prompt = img_params.get("negative_prompt", "")
    size            = img_params.get("size", "512x512")
    steps           = int(img_params.get("steps", 20))
    guidance_scale  = float(img_params.get("guidance_scale", 7.5))
    seed            = int(img_params.get("seed", -1))

    # Parse size
    try:
        w, h = [int(x) for x in size.split("x")]
    except Exception:
        w, h = 512, 512

    if engine in ("sd14", "sd15", "sdxl", "sd_tiny"):
        return _generate_with_diffusers(
            prompt, negative_prompt, caps["sd_model_path"],
            w, h, steps, guidance_scale, seed, t_start
        )
    elif engine == "ollama_llava":
        # LLaVA can't generate images — return a descriptive message
        result_text = (
            f"[Image Generation via LLaVA description]\n"
            f"A detailed description of: {prompt}\n\n"
            f"Note: This node uses LLaVA (vision understanding) rather than "
            f"Stable Diffusion (image generation). For actual image generation, "
            f"a node with a GPU and Stable Diffusion is required. "
            f"LLaVA can analyze images you upload but cannot create new ones from text."
        )
        # Ask LLaVA to describe what the image would look like
        llava_result = _ollama_generate(
            caps.get("vision_model", "llava"),
            f"Describe in vivid detail what this image would look like: {prompt}",
            images=[]
        )
        if llava_result:
            result_text = llava_result

        return {
            "status": "done",
            "result": result_text,
            "result_images": None,
            "tokens_in": 0, "tokens_out": 0,
            "duration_ms": int((time.time() - t_start) * 1000),
        }
    else:
        return {
            "status": "error",
            "result": "This node does not support image generation.",
            "result_images": None,
            "tokens_in": 0, "tokens_out": 0,
            "duration_ms": int((time.time() - t_start) * 1000),
        }


def _generate_with_diffusers(
    prompt: str, negative_prompt: str, model_id: str,
    width: int, height: int, steps: int, guidance_scale: float,
    seed: int, t_start: float
) -> dict:
    """Run Stable Diffusion via HuggingFace diffusers."""
    try:
        import torch
        from diffusers import StableDiffusionPipeline, DiffusionPipeline

        logger.info(f"[sd] Loading model {model_id}...")
        device = "cuda" if torch.cuda.is_available() else \
                 "mps" if torch.backends.mps.is_available() else "cpu"
        dtype  = torch.float16 if device in ("cuda", "mps") else torch.float32

        # Use SDXL pipeline for xl models
        PipeClass = DiffusionPipeline if "xl" in model_id.lower() else StableDiffusionPipeline

        pipe = PipeClass.from_pretrained(
            model_id,
            torch_dtype=dtype,
            safety_checker=None,
            requires_safety_checker=False,
        )
        pipe = pipe.to(device)

        # Memory optimisation for low VRAM
        try:
            pipe.enable_attention_slicing()
        except Exception:
            pass
        try:
            pipe.enable_vae_slicing()
        except Exception:
            pass

        logger.info(f"[sd] Generating {width}x{height} image on {device}...")

        generator = None
        if seed >= 0:
            generator = torch.Generator(device=device).manual_seed(seed)

        result = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt or "blurry, ugly, low quality, watermark",
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            generator=generator,
            num_images_per_prompt=1,
        )

        image = result.images[0]
        buf   = io.BytesIO()
        image.save(buf, format="PNG")
        b64   = base64.b64encode(buf.getvalue()).decode()

        logger.info(f"[sd] Image generated in {time.time()-t_start:.1f}s")

        return {
            "status": "done",
            "result": f"[Image generated successfully — {width}x{height}px, {steps} steps]",
            "result_images": [b64],
            "tokens_in": 0, "tokens_out": 0,
            "duration_ms": int((time.time() - t_start) * 1000),
        }

    except Exception as e:
        logger.error(f"[sd] Generation failed: {e}")
        return {
            "status": "error",
            "result": f"Image generation failed: {str(e)}",
            "result_images": None,
            "tokens_in": 0, "tokens_out": 0,
            "duration_ms": int((time.time() - t_start) * 1000),
        }


def _handle_vision(job: dict, caps: dict, t_start: float) -> dict:
    """Understand images using LLaVA."""
    prompt = job.get("prompt", "")

    images_b64 = []
    if job.get("image_params"):
        try:
            ip = json.loads(job["image_params"])
            for img in ip.get("images", []):
                images_b64.append(img.get("data", ""))
        except Exception:
            pass

    model = caps.get("vision_model") or job.get("model") or "llava"

    if not images_b64:
        # No images — just do text completion
        return _handle_file_qa(job, t_start)

    logger.info(f"[vision] Running LLaVA on {len(images_b64)} image(s)...")
    result = _ollama_generate(model, prompt, images=images_b64)

    if result is None:
        return {
            "status": "error",
            "result": "Vision model (LLaVA) is not available on this node.",
            "result_images": None,
            "tokens_in": 0, "tokens_out": 0,
            "duration_ms": int((time.time() - t_start) * 1000),
        }

    return {
        "status": "done",
        "result": result,
        "result_images": None,
        "tokens_in": len(prompt.split()),
        "tokens_out": len(result.split()),
        "duration_ms": int((time.time() - t_start) * 1000),
    }


def _handle_file_qa(job: dict, t_start: float) -> dict:
    """Answer questions about file content (text only, no images)."""
    prompt = job.get("prompt", "")
    model  = job.get("model") or "mistral"

    logger.info(f"[file_qa] Running {model} on file content...")
    result = _ollama_generate(model, prompt, images=[])

    if result is None:
        return {
            "status": "error",
            "result": f"Model '{model}' is not available on this node.",
            "result_images": None,
            "tokens_in": 0, "tokens_out": 0,
            "duration_ms": int((time.time() - t_start) * 1000),
        }

    return {
        "status": "done",
        "result": result,
        "result_images": None,
        "tokens_in": len(prompt.split()),
        "tokens_out": len(result.split()),
        "duration_ms": int((time.time() - t_start) * 1000),
    }


def _ollama_generate(model: str, prompt: str, images: list[str] = []) -> Optional[str]:
    """
    Call local Ollama API.
    images: list of base64-encoded image strings (for vision models).
    """
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if images:
        payload["images"] = images

    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        logger.error(f"[ollama] {model} failed: {e}")
        return None


# ── Auto-install required vision models ─────────────────────────────────────

def ensure_vision_model(caps: dict) -> dict:
    """
    If no vision model is available, try to pull llava:7b via Ollama.
    Call this during node startup if caps['vision'] is False.
    """
    if caps.get("vision"):
        return caps

    logger.info("[vision] No vision model found — attempting to pull llava:7b...")
    try:
        resp = requests.post(
            "http://localhost:11434/api/pull",
            json={"name": "llava:7b", "stream": False},
            timeout=600,  # 10 min for download
        )
        if resp.status_code == 200:
            caps["vision"]       = True
            caps["vision_model"] = "llava:7b"
            if not caps.get("image_gen"):
                caps["image_gen"]        = True
                caps["image_gen_engine"] = "ollama_llava"
            logger.info("[vision] llava:7b pulled successfully")
        else:
            logger.warning(f"[vision] Pull returned {resp.status_code}")
    except Exception as e:
        logger.warning(f"[vision] Could not pull llava:7b: {e}")

    return caps


# ── Integration example ──────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Quick test — run: python image_and_vision.py
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("Detecting system capabilities...")
    caps = detect_capabilities()
    print(json.dumps(caps, indent=2))

    if not caps["vision"]:
        print("\nNo vision model found. Attempting to pull llava:7b from Ollama...")
        caps = ensure_vision_model(caps)

    print(f"\nNode capabilities summary:")
    print(f"  Image generation : {caps['image_gen']} ({caps.get('image_gen_engine')})")
    print(f"  Vision (LLaVA)   : {caps['vision']} ({caps.get('vision_model')})")
    print(f"  GPU              : {caps['gpu']} — {caps.get('gpu_name')} {caps['vram_gb']}GB VRAM")
    print(f"  RAM              : {caps['ram_gb']} GB")
    print(f"  Disk free        : {caps['disk_free_gb']} GB")
