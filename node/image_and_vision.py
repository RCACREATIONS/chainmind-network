"""
ChainMind Node — Image Generation + Vision Module
==================================================
Handles three new job types routed from central_client:
  - image_gen : Stable Diffusion (GPU) or LLaVA description fallback
  - vision    : LLaVA multimodal understanding via Ollama
  - file_qa   : Text-only file/document Q&A via Ollama

Async-native: blocking SD operations are run in a thread executor so
they never block the FastAPI/asyncio event loop.

GPU detection re-uses system_check.get_system_info() so there is a
single source of truth for hardware facts across the node.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import subprocess
import sys
import time
from typing import Optional

import httpx

from .system_check import get_system_info

log = logging.getLogger("chainmind.multimodal")

# ── Ollama base URL (overridden by central_client when constructed) ──────────
_OLLAMA_BASE = "http://localhost:11434"

VISION_MODEL_CANDIDATES = [
    "llava", "llava:7b", "llava:13b", "llava:34b",
    "bakllava", "llama3.2-vision", "llama3.2-vision:11b",
    "moondream", "minicpm-v",
]

# Module-level SD pipeline cache — keyed by model_id so we load once per model
_sd_pipeline_cache: dict[str, object] = {}
_sd_cache_lock = asyncio.Lock()


# ── Capabilities detection ────────────────────────────────────────────────────

async def detect_capabilities(ollama_base: str = _OLLAMA_BASE) -> dict:
    """
    Detect what this node can handle for multimodal jobs.
    Re-uses system_check hardware info so GPU data is consistent everywhere.
    Returns a capabilities dict included in every heartbeat.
    """
    global _OLLAMA_BASE
    _OLLAMA_BASE = ollama_base

    sys_info = await asyncio.to_thread(get_system_info)

    caps: dict = {
        "image_gen":         False,
        "image_gen_engine":  None,
        "vision":            False,
        "vision_model":      None,
        "file_qa":           True,
        "gpu":               sys_info.get("has_gpu", False),
        "gpu_name":          sys_info.get("gpu_name", None),
        "vram_gb":           sys_info.get("gpu_vram_gb", 0.0),
        "ram_gb":            sys_info.get("ram_gb", 0.0),
        "disk_free_gb":      sys_info.get("disk_free_gb", 0.0),
        "sd_model_id":       None,
    }

    vram = caps["vram_gb"]

    # ── Stable Diffusion check (non-blocking) ─────────────────────────────────
    if caps["gpu"] and vram >= 4:
        sd_ready, model_id, engine = await asyncio.to_thread(
            _check_stable_diffusion, vram
        )
        if sd_ready:
            caps["image_gen"]        = True
            caps["image_gen_engine"] = engine
            caps["sd_model_id"]      = model_id
            log.info(f"[caps] SD ready: engine={engine} model={model_id}")

    # ── LLaVA / vision via Ollama ─────────────────────────────────────────────
    llava_model = await _find_ollama_vision_model(ollama_base)
    if llava_model:
        caps["vision"]       = True
        caps["vision_model"] = llava_model
        if not caps["image_gen"]:
            caps["image_gen"]        = True
            caps["image_gen_engine"] = "ollama_llava"
        log.info(f"[caps] Vision model: {llava_model}")

    log.info(
        f"[caps] GPU={caps['gpu']} VRAM={vram}GB RAM={caps['ram_gb']}GB "
        f"image_gen={caps['image_gen']}({caps['image_gen_engine']}) "
        f"vision={caps['vision']}({caps['vision_model']})"
    )
    return caps


async def ensure_vision_model(caps: dict, ollama_base: str = _OLLAMA_BASE) -> dict:
    """
    If no vision model is present, pull llava:7b from Ollama automatically.
    Called once at startup if caps['vision'] is False.
    """
    if caps.get("vision"):
        return caps

    log.info("[vision] No vision model — pulling llava:7b (this may take a while)…")
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(
                f"{ollama_base}/api/pull",
                json={"name": "llava:7b", "stream": False},
            )
            if r.status_code == 200:
                caps["vision"]       = True
                caps["vision_model"] = "llava:7b"
                if not caps.get("image_gen"):
                    caps["image_gen"]        = True
                    caps["image_gen_engine"] = "ollama_llava"
                log.info("[vision] llava:7b pulled successfully")
            else:
                log.warning(f"[vision] Pull returned HTTP {r.status_code}")
    except Exception as exc:
        log.warning(f"[vision] Could not pull llava:7b: {exc}")

    return caps


# ── Main async job dispatcher ─────────────────────────────────────────────────

async def handle_special_job(
    job: dict,
    caps: dict,
    ollama_base: str = _OLLAMA_BASE,
) -> dict:
    """
    Async entry point for image_gen / vision / file_qa jobs.

    Args:
        job:        Job dict from claim-job (id, job_type, prompt, model, image_params …)
        caps:       Capabilities dict from detect_capabilities()
        ollama_base: Ollama URL (default localhost:11434)

    Returns:
        dict: result, result_images, tokens_in, tokens_out, duration_ms, status
    """
    job_type = job.get("job_type", "text")
    t_start  = time.monotonic()

    if job_type == "image_gen":
        return await _handle_image_gen(job, caps, t_start, ollama_base)
    if job_type == "vision":
        return await _handle_vision(job, caps, t_start, ollama_base)
    if job_type == "file_qa":
        return await _handle_file_qa(job, t_start, ollama_base)

    return _err(f"Unknown job_type: {job_type}", t_start)


# ── Image generation ──────────────────────────────────────────────────────────

async def _handle_image_gen(
    job: dict, caps: dict, t_start: float, ollama_base: str
) -> dict:
    engine  = caps.get("image_gen_engine")
    prompt  = job.get("prompt", "")
    params  = _parse_image_params(job.get("image_params"))

    negative = params.get("negative_prompt", "")
    size     = params.get("size", "512x512")
    steps    = int(params.get("steps", 20))
    guidance = float(params.get("guidance_scale", 7.5))
    seed     = int(params.get("seed", -1))

    try:
        w, h = [int(x) for x in size.split("x")]
    except Exception:
        w, h = 512, 512

    if engine in ("sd14", "sd15", "sdxl", "sd_tiny"):
        return await asyncio.to_thread(
            _generate_with_diffusers,
            prompt, negative, caps["sd_model_id"],
            w, h, steps, guidance, seed, t_start,
        )

    if engine == "ollama_llava":
        vision_model = caps.get("vision_model", "llava")
        llava_prompt = (
            f"Describe in rich, vivid detail what this image would look like: {prompt}"
        )
        result = await _ollama_generate(
            vision_model, llava_prompt, images=[], ollama_base=ollama_base
        )
        return {
            "status": "done",
            "result": result or (
                "[Image Generation via LLaVA — GPU with Stable Diffusion required "
                "for actual image output. This node describes the requested image "
                "instead.]\n\nPrompt: " + prompt
            ),
            "result_images": None,
            "tokens_in": len(prompt.split()),
            "tokens_out": len((result or "").split()),
            "duration_ms": _ms(t_start),
        }

    return _err("This node does not support image generation.", t_start)


async def _handle_vision(
    job: dict, caps: dict, t_start: float, ollama_base: str
) -> dict:
    prompt = job.get("prompt", "")
    images_b64: list[str] = []

    params = _parse_image_params(job.get("image_params"))
    for img in params.get("images", []):
        data = img.get("data", "") if isinstance(img, dict) else img
        if data:
            images_b64.append(data)

    model = caps.get("vision_model") or job.get("model") or "llava"

    if not images_b64:
        return await _handle_file_qa(job, t_start, ollama_base)

    if not caps.get("vision"):
        return _err("No vision model available on this node.", t_start)

    log.info(f"[vision] {model} on {len(images_b64)} image(s)…")
    result = await _ollama_generate(model, prompt, images=images_b64, ollama_base=ollama_base)

    if result is None:
        return _err(f"Vision model '{model}' failed to respond.", t_start)

    return {
        "status": "done",
        "result": result,
        "result_images": None,
        "tokens_in":  len(prompt.split()),
        "tokens_out": len(result.split()),
        "duration_ms": _ms(t_start),
    }


async def _handle_file_qa(job: dict, t_start: float, ollama_base: str) -> dict:
    prompt = job.get("prompt", "")
    model  = job.get("model") or "mistral"

    log.info(f"[file_qa] {model} on file content…")
    result = await _ollama_generate(model, prompt, images=[], ollama_base=ollama_base)

    if result is None:
        return _err(f"Model '{model}' is not available on this node.", t_start)

    return {
        "status": "done",
        "result": result,
        "result_images": None,
        "tokens_in":  len(prompt.split()),
        "tokens_out": len(result.split()),
        "duration_ms": _ms(t_start),
    }


# ── Stable Diffusion (runs in thread) ────────────────────────────────────────

def _check_stable_diffusion(vram_gb: float) -> tuple[bool, Optional[str], Optional[str]]:
    """Check diffusers availability and select model for VRAM. Runs in thread."""
    try:
        import torch       # noqa
        import diffusers   # noqa
    except ImportError:
        log.info("[sd] diffusers/torch not installed — skipping")
        return False, None, None

    if vram_gb >= 10:
        return True, "stabilityai/stable-diffusion-xl-base-1.0", "sdxl"
    if vram_gb >= 6:
        return True, "runwayml/stable-diffusion-v1-5",           "sd15"
    if vram_gb >= 4:
        return True, "CompVis/stable-diffusion-v1-4",            "sd14"
    return True, "nota-ai/bk-sdm-small",                         "sd_tiny"


def _generate_with_diffusers(
    prompt: str,
    negative_prompt: str,
    model_id: str,
    width: int,
    height: int,
    steps: int,
    guidance_scale: float,
    seed: int,
    t_start: float,
) -> dict:
    """Run Stable Diffusion in a thread. Uses module-level cache to avoid reloading."""
    try:
        import torch
        from diffusers import StableDiffusionPipeline, DiffusionPipeline

        pipe = _sd_pipeline_cache.get(model_id)
        if pipe is None:
            log.info(f"[sd] Loading {model_id}…")
            device = (
                "cuda" if torch.cuda.is_available()
                else "mps"  if torch.backends.mps.is_available()
                else "cpu"
            )
            dtype = torch.float16 if device in ("cuda", "mps") else torch.float32
            PipeClass = (
                DiffusionPipeline if "xl" in model_id.lower()
                else StableDiffusionPipeline
            )
            pipe = PipeClass.from_pretrained(
                model_id,
                torch_dtype=dtype,
                safety_checker=None,
                requires_safety_checker=False,
            ).to(device)

            for opt in ("enable_attention_slicing", "enable_vae_slicing",
                        "enable_model_cpu_offload"):
                try:
                    getattr(pipe, opt)()
                except Exception:
                    pass

            _sd_pipeline_cache[model_id] = pipe
            log.info(f"[sd] Pipeline ready on {device}")
        else:
            device = next(pipe.unet.parameters()).device.type

        generator = None
        if seed >= 0:
            import torch as _t
            generator = _t.Generator(device=device).manual_seed(seed)

        log.info(f"[sd] Generating {width}x{height} ({steps} steps)…")
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
        elapsed = time.monotonic() - t_start
        log.info(f"[sd] Done in {elapsed:.1f}s")

        return {
            "status": "done",
            "result": f"[Image generated — {width}x{height}px, {steps} steps, {elapsed:.1f}s]",
            "result_images": [b64],
            "tokens_in": 0, "tokens_out": 0,
            "duration_ms": int(elapsed * 1000),
        }

    except Exception as exc:
        log.error(f"[sd] Generation failed: {exc}")
        return _err(f"Image generation failed: {exc}", t_start)


# ── Ollama helpers ────────────────────────────────────────────────────────────

async def _find_ollama_vision_model(ollama_base: str) -> Optional[str]:
    """Return the first vision model name found in Ollama, or None."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{ollama_base}/api/tags")
            if r.status_code == 200:
                installed = [m["name"] for m in r.json().get("models", [])]
                for candidate in VISION_MODEL_CANDIDATES:
                    for installed_name in installed:
                        if candidate.split(":")[0] in installed_name.lower():
                            return installed_name
    except Exception:
        pass
    return None


async def _ollama_generate(
    model: str,
    prompt: str,
    images: list[str],
    ollama_base: str = _OLLAMA_BASE,
    timeout: float = 180.0,
) -> Optional[str]:
    """Async Ollama /api/generate call with optional image support."""
    payload: dict = {"model": model, "prompt": prompt, "stream": False}
    if images:
        payload["images"] = images

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{ollama_base}/api/generate", json=payload)
            r.raise_for_status()
            return r.json().get("response", "")
    except Exception as exc:
        log.error(f"[ollama] {model} failed: {exc}")
        return None


# ── Utilities ─────────────────────────────────────────────────────────────────

def _parse_image_params(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _ms(t_start: float) -> int:
    return int((time.monotonic() - t_start) * 1000)


def _err(msg: str, t_start: float) -> dict:
    return {
        "status": "error",
        "result": msg,
        "result_images": None,
        "tokens_in": 0, "tokens_out": 0,
        "duration_ms": _ms(t_start),
    }
