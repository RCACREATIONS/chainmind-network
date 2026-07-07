"""Sound effect fetching — downloads from chainmind.com.ng/assets/sfx/ and caches locally."""

from __future__ import annotations

import os
import random

import requests

SFX_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "sfx_cache")
MANIFEST_URL = "https://chainmind.com.ng/api/sfx-manifest.php"

_manifest_cache: dict | None = None


def get_manifest() -> dict:
    global _manifest_cache
    if _manifest_cache is None:
        try:
            resp = requests.get(MANIFEST_URL, timeout=10)
            resp.raise_for_status()
            _manifest_cache = resp.json().get("categories", {})
        except Exception:
            _manifest_cache = {}
    return _manifest_cache


def get_sfx(category: str) -> str | None:
    """
    Returns a local file path to a sound effect in the given category,
    downloading + caching it if not already present.
    Returns None if the category has no files — the animator skips the audio layer.
    """
    try:
        manifest = get_manifest()
        options = manifest.get(category, [])
        if not options:
            return None

        choice = random.choice(options)
        os.makedirs(SFX_CACHE_DIR, exist_ok=True)
        local_path = os.path.join(SFX_CACHE_DIR, f"{category}_{choice['name']}")

        if not os.path.exists(local_path):
            resp = requests.get(choice["url"], timeout=15)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(resp.content)

        return local_path
    except Exception:
        return None
