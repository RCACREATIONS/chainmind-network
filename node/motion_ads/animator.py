"""
Ken Burns animator — builds a 3-scene 1080×1920 video ad using moviepy.
Scene 1: Hook text + product image (slow zoom in)
Scene 2: Body text + product image (slow zoom out)
Scene 3: CTA text on brand color background + optional logo
SFX and voiceover are composited over the scenes.
"""

from __future__ import annotations

import logging
import os

import numpy as np
from PIL import Image

log = logging.getLogger("motion_ads.animator")

SCENE_DURATION = 3.5  # seconds per scene


def build_ad_video(
    image_paths: list[str],
    hook: str,
    body: str,
    cta: str,
    brand_color: str,
    logo_path: str | None,
    voiceover_path: str | None,
    sfx_paths: dict,
    output_path: str,
    size: tuple[int, int] = (1080, 1920),
) -> str:
    """
    Render and write the video. Returns output_path.
    sfx_paths: {"scene1": path|None, "scene2": path|None, "scene3": path|None}
    """
    from moviepy.editor import (
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        TextClip,
        concatenate_videoclips,
    )

    clips: list = []
    audio_layers: list = []
    t_cursor = 0.0

    def _scene(image_path: str, text: str, zoom_start: float, zoom_end: float, sfx_key: str):
        nonlocal t_cursor

        bg = (
            ImageClip(image_path)
            .set_duration(SCENE_DURATION)
            .resize(height=size[1])
            .resize(
                lambda t: zoom_start + (zoom_end - zoom_start) * (t / SCENE_DURATION)
            )
            .set_position("center")
        )

        txt = (
            TextClip(
                text,
                fontsize=70,
                color="white",
                font="Arial-Bold",
                size=(size[0] - 100, None),
                method="caption",
            )
            .set_duration(SCENE_DURATION)
            .set_position(("center", 0.75), relative=True)
        )

        sfx = sfx_paths.get(sfx_key)
        if sfx and os.path.exists(sfx):
            try:
                audio_layers.append(
                    AudioFileClip(sfx).set_start(t_cursor).volumex(0.6)
                )
            except Exception as e:
                log.warning(f"Could not load SFX {sfx}: {e}")

        t_cursor += SCENE_DURATION
        return (
            CompositeVideoClip([bg, txt], size=size).set_duration(SCENE_DURATION)
        )

    clips.append(_scene(image_paths[0], hook, 1.0, 1.15, "scene1"))

    img2 = image_paths[1] if len(image_paths) > 1 else image_paths[0]
    clips.append(_scene(img2, body, 1.15, 1.0, "scene2"))

    rgb = _parse_color(brand_color)
    solid = Image.new("RGB", size, rgb)
    layers: list = [
        ImageClip(np.array(solid)).set_duration(SCENE_DURATION)
    ]

    if logo_path and os.path.exists(logo_path):
        try:
            layers.append(
                ImageClip(logo_path)
                .set_duration(SCENE_DURATION)
                .resize(width=size[0] // 3)
                .set_position(("center", 0.35), relative=True)
            )
        except Exception as e:
            log.warning(f"Could not load logo {logo_path}: {e}")

    layers.append(
        TextClip(
            cta,
            fontsize=70,
            color="white",
            font="Arial-Bold",
            size=(size[0] - 100, None),
            method="caption",
        )
        .set_duration(SCENE_DURATION)
        .set_position(("center", 0.7), relative=True)
    )

    sfx3 = sfx_paths.get("scene3")
    if sfx3 and os.path.exists(sfx3):
        try:
            audio_layers.append(
                AudioFileClip(sfx3).set_start(t_cursor).volumex(0.6)
            )
        except Exception as e:
            log.warning(f"Could not load SFX scene3 {sfx3}: {e}")

    clips.append(CompositeVideoClip(layers, size=size).set_duration(SCENE_DURATION))

    final = concatenate_videoclips(clips, method="compose")

    audio_tracks = list(audio_layers)
    if voiceover_path and os.path.exists(voiceover_path):
        try:
            audio_tracks.append(AudioFileClip(voiceover_path).volumex(1.0))
        except Exception as e:
            log.warning(f"Could not load voiceover {voiceover_path}: {e}")

    if audio_tracks:
        final = final.set_audio(CompositeAudioClip(audio_tracks))

    final.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac",
                          logger=None)
    log.info(f"Ad video written to {output_path}")
    return output_path


def _parse_color(hex_color: str) -> tuple[int, int, int]:
    """Parse a hex color string like '#7C3AED' into an (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except Exception:
        return (124, 58, 237)
