"""Ad copy generation — uses the node's local Ollama model."""

from __future__ import annotations

import json
import logging

log = logging.getLogger("motion_ads.script_gen")


async def generate_ad_script(
    ollama_client,
    model: str,
    business_name: str,
    product: str,
    offer: str,
    tone: str,
) -> dict:
    """
    Generates ad copy JSON via the local LLM.
    Returns a dict with keys: hook, body, cta, image_query, sfx_moments.
    Falls back to sane defaults if the model returns malformed JSON.
    """
    prompt = f"""Generate ad copy for a short promotional video. Return ONLY valid JSON,
no markdown, no preamble. Format:
{{"hook": "...", "body": "...", "cta": "...", "image_query": "...", "sfx_moments": ["whoosh","pop","chime"]}}

Business: {business_name}
Product/offer: {product} - {offer}
Tone: {tone}
"""
    try:
        resp = await ollama_client.generate(model=model, prompt=prompt)
        content = resp.get("response", "").strip()
        content = content.strip("```json").strip("```").strip()
        return json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        log.warning(f"Ad script generation fallback triggered: {e}")
        return {
            "hook": f"{business_name} has something for you",
            "body": f"{product} — {offer}",
            "cta": "Order now",
            "image_query": product,
            "sfx_moments": ["whoosh", "pop", "chime"],
        }
