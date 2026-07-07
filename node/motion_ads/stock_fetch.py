"""Free stock image fetching — Openverse API (no key) with Wikimedia fallback."""

from __future__ import annotations

import os
import time

import requests

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "stock_cache")
_CACHE_TTL = 86400  # 24h


def search_openverse(query: str, per_page: int = 6) -> list[dict]:
    try:
        resp = requests.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": per_page, "license_type": "commercial"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

        def _rank(r):
            return 0 if r.get("license") in ("cc0", "pdm") else 1

        results.sort(key=_rank)
        return [
            {
                "url": r["url"],
                "license": r.get("license", "unknown"),
                "needs_attribution": r.get("license") not in ("cc0", "pdm"),
                "creator": r.get("creator", ""),
                "source": r.get("foreign_landing_url", ""),
            }
            for r in results
            if r.get("url")
        ]
    except Exception:
        return []


def search_wikimedia(query: str, per_page: int = 6) -> list[dict]:
    try:
        resp = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:bitmap {query}",
                "gsrlimit": per_page,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
            },
            headers={"User-Agent": "ChainMindMotionAds/1.0 (chainmind.com.ng)"},
            timeout=10,
        )
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        out = []
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("url"):
                out.append(
                    {
                        "url": info["url"],
                        "license": "wikimedia",
                        "needs_attribution": True,
                        "creator": "Wikimedia Commons",
                        "source": info.get("descriptionurl", ""),
                    }
                )
        return out
    except Exception:
        return []


def download_image(url: str, dest_path: str) -> str:
    resp = requests.get(
        url,
        timeout=15,
        headers={"User-Agent": "ChainMindMotionAds/1.0"},
    )
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)
    return dest_path


def _cache_key(query: str) -> str:
    import hashlib
    return hashlib.md5(query.encode()).hexdigest()


def fetch_and_prepare_stock_image(query: str, workdir: str) -> dict:
    """
    Returns {"path": <bg-removed PNG path>, "needs_attribution": bool, "creator": str}

    Tries a 24-hour on-disk cache keyed by query hash before hitting the network.
    """
    from .bg_remover import remove_background

    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache_key = _cache_key(query)
    cached_png = os.path.join(_CACHE_DIR, f"{cache_key}.png")
    cached_meta = os.path.join(_CACHE_DIR, f"{cache_key}.meta")

    if os.path.exists(cached_png) and os.path.exists(cached_meta):
        age = time.time() - os.path.getmtime(cached_png)
        if age < _CACHE_TTL:
            import json
            with open(cached_meta) as f:
                meta = json.load(f)
            import shutil
            dst = os.path.join(workdir, "stock_clean.png")
            shutil.copy2(cached_png, dst)
            meta["path"] = dst
            return meta

    results = search_openverse(query) or search_wikimedia(query)
    if not results:
        raise ValueError(f"No free stock image found for query: {query!r}")

    best = results[0]
    raw_path = os.path.join(workdir, "stock_raw.jpg")
    download_image(best["url"], raw_path)

    clean_path = os.path.join(workdir, "stock_clean.png")
    try:
        remove_background(raw_path, clean_path)
    except Exception:
        import shutil
        shutil.copy2(raw_path, clean_path)

    meta = {
        "path": clean_path,
        "needs_attribution": best["needs_attribution"],
        "creator": best.get("creator", ""),
    }

    try:
        import shutil, json as _json
        shutil.copy2(clean_path, cached_png)
        save_meta = dict(meta)
        save_meta.pop("path", None)
        with open(cached_meta, "w") as f:
            _json.dump(save_meta, f)
    except Exception:
        pass

    return meta
