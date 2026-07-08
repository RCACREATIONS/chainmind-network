"""Async wrapper around Ollama's local HTTP API (port 11434)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

import httpx

log = logging.getLogger("ollama_client")


def strip_latest_tag(name: str) -> str:
    """Strip a trailing ':latest' tag — Ollama treats a bare model name as
    implicitly tagged ':latest', so "tinyllama" and "tinyllama:latest" refer
    to the same model. This is the single shared normalizer: use it anywhere
    two model names need to be compared for equivalence."""
    return name[: -len(":latest")] if name.endswith(":latest") else name


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=None)

    async def is_running(self) -> bool:
        try:
            r = await self._http.get(f"{self.base_url}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    async def list_local_models(self) -> list[dict]:
        try:
            r = await self._http.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            return r.json().get("models", [])
        except Exception:
            return []

    async def resolve_model(self, preferred: str | None) -> str:
        """
        Return the best model name to actually run with, given what's pulled locally.

        Single source of truth for model-fallback logic — used by every caller
        (job-queue jobs, motion-ad jobs, and the live /ws/infer chat endpoint)
        so none of them can silently skip it and hit a raw 404 again.

        Priority:
          1. preferred — if it exists locally (exact match, or matches ignoring an
             implicit ":latest" tag), use it exactly.
          2. First locally-pulled model — if preferred isn't pulled, log a warning
             and fall back rather than failing the request.
          3. "tinyllama" — if nothing is pulled at all (the request will still 404,
             but generate()/generate_stream() will raise a clear message).
        """
        models      = await self.list_local_models()
        local_names = [m.get("name", "") for m in models]

        def _matches(name: str) -> str | None:
            if name in local_names:
                return name
            bare = strip_latest_tag(name)
            for local in local_names:
                if strip_latest_tag(local) == bare:
                    return local
            return None

        resolved_exact = _matches(preferred) if preferred else None
        if resolved_exact:
            return resolved_exact

        if preferred and local_names:
            fallback = local_names[0]
            log.warning(
                f"Requested model '{preferred}' is not pulled locally — "
                f"falling back to '{fallback}'. "
                f"Pull it anytime with:  ollama pull {preferred}"
            )
            return fallback

        if local_names:
            return local_names[0]

        log.error(
            "No models are pulled in Ollama. "
            "Pull at least one:  ollama pull tinyllama"
        )
        return preferred or "tinyllama"

    async def pull_model(self, model_name: str) -> AsyncIterator[dict]:
        """Stream pull progress events."""
        async with self._http.stream(
            "POST",
            f"{self.base_url}/api/pull",
            json={"name": model_name, "stream": True},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    yield json.loads(line)

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        stream: bool = False,
    ) -> dict:
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
        }
        if system:
            payload["system"] = system

        start = time.monotonic()
        r = await self._http.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=300,
        )
        if r.status_code == 404:
            raise ValueError(
                f"Model '{model}' is not pulled in your local Ollama. "
                f"Pull it first: ollama pull {model}"
            )
        r.raise_for_status()
        data = r.json()
        data["_duration_ms"] = int((time.monotonic() - start) * 1000)
        return data

    async def generate_stream(
        self, model: str, prompt: str, system: str = ""
    ) -> AsyncIterator[str]:
        """Yield text chunks as they stream from Ollama."""
        payload = {"model": model, "prompt": prompt, "stream": True}
        if system:
            payload["system"] = system

        async with self._http.stream(
            "POST", f"{self.base_url}/api/generate", json=payload
        ) as resp:
            if resp.status_code == 404:
                raise ValueError(
                    f"Model '{model}' is not pulled in your local Ollama. "
                    f"Pull it first: ollama pull {model}"
                )
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    chunk = json.loads(line)
                    if chunk.get("response"):
                        yield chunk["response"]
                    if chunk.get("done"):
                        break

    async def delete_model(self, model_name: str) -> bool:
        try:
            r = await self._http.delete(
                f"{self.base_url}/api/delete",
                json={"name": model_name},
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    async def close(self):
        await self._http.aclose()
