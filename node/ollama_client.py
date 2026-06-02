"""Async wrapper around Ollama's local HTTP API (port 11434)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

import httpx


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
