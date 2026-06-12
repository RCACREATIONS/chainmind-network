"""Orchestrator — splits tasks across the peer network and merges results."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import Any

import httpx

from .db import get_online_peers, update_peer_task_stats


class Orchestrator:
    def __init__(self, con: sqlite3.Connection, cfg: dict, node_id: str):
        self.con = con
        self.cfg = cfg
        self.node_id = node_id
        self._http = httpx.AsyncClient(timeout=120.0)

    async def close(self):
        await self._http.aclose()

    def best_peers(self, count: int = 2) -> list[dict]:
        """Return up to `count` online peers sorted by reputation."""
        peers = get_online_peers(self.con)
        return peers[:count]

    async def route_to_peer(self, peer: dict, prompt: str, model: str | None) -> dict:
        """Send an inference task to a peer and wait for the result."""
        url = peer["url"].rstrip("/")
        try:
            # Submit task
            payload: dict = {"prompt": prompt}
            if model:
                payload["model"] = model
            r = await self._http.post(f"{url}/infer", json=payload, timeout=10)
            r.raise_for_status()
            task_id = r.json()["task_id"]

            # Poll for result (max 5 minutes)
            for _ in range(300):
                await asyncio.sleep(1)
                tr = await self._http.get(f"{url}/tasks/{task_id}", timeout=5)
                t = tr.json()
                if t.get("status") in ("done", "error"):
                    iq = (t.get("tokens_in", 0) + t.get("tokens_out", 0)) * 0.001
                    update_peer_task_stats(self.con, peer["id"], iq, t["status"] == "done")
                    return t
            return {"status": "timeout", "result": "Peer timed out"}
        except Exception as e:
            update_peer_task_stats(self.con, peer["id"], 0, False)
            return {"status": "error", "result": str(e)}

    async def split_and_merge(self, prompt: str, model: str | None) -> dict:
        """
        Split a prompt into sub-tasks, farm them to available peers,
        and merge the results. Falls back to local if no peers available.
        """
        peers = self.best_peers(2)
        if not peers:
            return {"routed_to": "local", "peers_used": []}

        # Split strategy: first half to peer 0, second half to peer 1 (if available)
        words = prompt.split()
        mid = len(words) // 2

        if len(peers) >= 2 and len(words) > 10:
            part1 = " ".join(words[:mid])
            part2 = " ".join(words[mid:])
            task1 = asyncio.create_task(self.route_to_peer(peers[0], part1, model))
            task2 = asyncio.create_task(self.route_to_peer(peers[1], part2, model))
            r1, r2 = await asyncio.gather(task1, task2)
            merged = self._merge(r1.get("result", ""), r2.get("result", ""))
            return {
                "result": merged,
                "routed_to": "split",
                "peers_used": [peers[0]["url"], peers[1]["url"]],
                "tokens_in": r1.get("tokens_in", 0) + r2.get("tokens_in", 0),
                "tokens_out": r1.get("tokens_out", 0) + r2.get("tokens_out", 0),
            }
        else:
            # Route entire task to best peer
            r = await self.route_to_peer(peers[0], prompt, model)
            return {
                "result": r.get("result", ""),
                "routed_to": "peer",
                "peers_used": [peers[0]["url"]],
                "tokens_in": r.get("tokens_in", 0),
                "tokens_out": r.get("tokens_out", 0),
            }

    def _merge(self, part1: str, part2: str) -> str:
        """Merge two partial results into a coherent response."""
        if not part1.strip():
            return part2
        if not part2.strip():
            return part1
        # Simple concatenation with a joining phrase
        p1 = part1.rstrip()
        p2 = part2.lstrip()
        if p1.endswith(".") or p1.endswith("!") or p1.endswith("?"):
            return f"{p1} {p2}"
        return f"{p1}. {p2}"
