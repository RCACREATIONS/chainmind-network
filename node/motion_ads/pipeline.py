"""
Full motion-ad pipeline orchestrator.
Coordinates: script gen → image fetch → bg removal → voiceover → sfx → render.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

log = logging.getLogger("motion_ads.pipeline")


async def run_pipeline(
    ollama_client,
    model: str,
    params: dict,
    user_image_paths: list[str] | None,
) -> str:
    """
    Run the full motion-ad pipeline.
    Returns the path to the rendered .mp4 file.

    params keys: business_name, product, offer, tone, brand_color, logo_path, job_id
    """
    from .animator import build_ad_video
    from .bg_remover import remove_background
    from .script_gen import generate_ad_script
    from .sfx_fetch import get_sfx
    from .stock_fetch import fetch_and_prepare_stock_image
    from .voiceover import generate_voiceover

    job_id = params.get("job_id", str(uuid.uuid4()))
    workdir = os.path.join("data", "motion_ads", job_id)
    os.makedirs(workdir, exist_ok=True)

    log.info(f"[{job_id[:8]}] Generating ad script…")
    copy = await generate_ad_script(
        ollama_client,
        model,
        params["business_name"],
        params["product"],
        params["offer"],
        params.get("tone", "friendly"),
    )
    log.info(f"[{job_id[:8]}] Script: hook={copy['hook'][:40]!r}")

    image_paths: list[str] = []

    if user_image_paths:
        log.info(f"[{job_id[:8]}] Removing backgrounds from {len(user_image_paths)} user images…")
        for i, path in enumerate(user_image_paths):
            clean = os.path.join(workdir, f"user_clean_{i}.png")
            try:
                await asyncio.to_thread(remove_background, path, clean)
            except Exception as e:
                log.warning(f"bg removal failed for {path}: {e} — using original")
                clean = path
            image_paths.append(clean)
    else:
        log.info(f"[{job_id[:8]}] Fetching stock image for {copy['image_query']!r}…")
        stock = await asyncio.to_thread(
            fetch_and_prepare_stock_image, copy["image_query"], workdir
        )
        image_paths.append(stock["path"])
        if stock["needs_attribution"]:
            log.info(f"[{job_id[:8]}] Attribution required: {stock['creator']}")

    voice_path = os.path.join(workdir, "voiceover.mp3")
    voice_text = f"{copy['hook']}. {copy['body']}. {copy['cta']}."
    log.info(f"[{job_id[:8]}] Generating voiceover…")
    try:
        await generate_voiceover(voice_text, voice_path)
    except Exception as e:
        log.warning(f"[{job_id[:8]}] Voiceover failed: {e} — video will have no voice")
        voice_path = None  # type: ignore[assignment]

    moments = copy.get("sfx_moments", ["whoosh", "pop", "chime"])
    log.info(f"[{job_id[:8]}] Fetching SFX: {moments}…")
    sfx_paths = {
        "scene1": await asyncio.to_thread(get_sfx, moments[0] if moments else "whoosh"),
        "scene2": await asyncio.to_thread(get_sfx, moments[1] if len(moments) > 1 else "pop"),
        "scene3": await asyncio.to_thread(get_sfx, moments[2] if len(moments) > 2 else "chime"),
    }

    output_path = os.path.join(workdir, "ad.mp4")
    log.info(f"[{job_id[:8]}] Rendering video…")
    await asyncio.to_thread(
        build_ad_video,
        image_paths=image_paths,
        hook=copy["hook"],
        body=copy["body"],
        cta=copy["cta"],
        brand_color=params.get("brand_color", "#7C3AED"),
        logo_path=params.get("logo_path"),
        voiceover_path=voice_path,
        sfx_paths=sfx_paths,
        output_path=output_path,
    )

    log.info(f"[{job_id[:8]}] Pipeline complete → {output_path}")
    return output_path
