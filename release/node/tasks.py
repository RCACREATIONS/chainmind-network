"""Task processing — async queue, local inference, peer routing."""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from typing import Any

from .db import insert_task, update_task, get_task
from .ollama_client import OllamaClient


class TaskProcessor:
    def __init__(self, con: sqlite3.Connection, ollama: OllamaClient, default_model: str):
        self.con = con
        self.ollama = ollama
        self.default_model = default_model
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._running = False
        self.orchestrator = None  # injected after init

    async def enqueue(self, prompt: str, model: str | None = None, use_network: bool = False) -> str:
        task_id = str(uuid.uuid4())
        chosen = model or self.default_model
        routed_to = "local"
        insert_task(self.con, task_id, prompt, chosen, routed_to)
        await self._queue.put({"id": task_id, "prompt": prompt, "model": chosen, "use_network": use_network})
        return task_id

    async def start(self):
        self._running = True
        asyncio.create_task(self._worker())

    async def stop(self):
        self._running = False

    async def _worker(self):
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            task_id = item["id"]
            use_network = item.get("use_network", False)

            try:
                update_task(self.con, task_id, "running")

                # Try to route via network if requested and orchestrator is available
                if use_network and self.orchestrator:
                    net_result = await self.orchestrator.split_and_merge(item["prompt"], item["model"])
                    if net_result.get("result"):
                        update_task(
                            self.con, task_id, "done",
                            result=net_result["result"],
                            tokens_in=net_result.get("tokens_in", 0),
                            tokens_out=net_result.get("tokens_out", 0),
                        )
                        self._queue.task_done()
                        continue

                # Local inference
                result = await self.ollama.generate(model=item["model"], prompt=item["prompt"])
                update_task(
                    self.con, task_id, "done",
                    result=result.get("response", ""),
                    tokens_in=result.get("prompt_eval_count", 0),
                    tokens_out=result.get("eval_count", 0),
                    duration_ms=result.get("_duration_ms", 0),
                )
            except Exception as exc:
                update_task(self.con, task_id, "error", result=str(exc))
            finally:
                self._queue.task_done()

    def status(self) -> dict[str, Any]:
        return {"queue_depth": self._queue.qsize(), "worker_running": self._running}
