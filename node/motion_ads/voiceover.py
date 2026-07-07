"""Text-to-speech voiceover generation using edge-tts (Microsoft Edge TTS, free)."""

from __future__ import annotations

import logging

log = logging.getLogger("motion_ads.voiceover")

DEFAULT_VOICE = "en-US-JennyNeural"


async def generate_voiceover(
    text: str,
    output_path: str,
    voice: str = DEFAULT_VOICE,
) -> str:
    """
    Generate a voiceover MP3 from text using edge-tts.
    Returns output_path on success.
    Raises on failure — caller should handle gracefully.
    """
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)
    log.debug(f"Voiceover saved to {output_path}")
    return output_path
