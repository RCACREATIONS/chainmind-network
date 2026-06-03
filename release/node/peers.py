"""Peer discovery — gossip protocol over HTTP + central server directory.

Each node:
  1. Has a unique node_id (UUID saved to data/node_id.txt)
  2. Announces itself to bootstrap peers and discovered peers
  3. Asks peers for their peer lists (gossip)
  4. Broadcasts heartbeats every N seconds
  5. Fetches peer list from central server on startup and periodically
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

from .db import upsert_peer, update_peer_status, get_peers, get_online_peers


def load_node_id(data_dir: str) -> str:
    id_file = Path(data_dir) / "node_id.txt"
    if id_file.exists():
        return id_file.read_text().strip()
    node_id = str(uuid.uuid4())
    id_file.parent.mkdir(parents=True, exist_ok=True)
    id_file.write_text(node_id)
    return node_id


class PeerManager:
    def __init__(self, con: sqlite3.Connection, cfg: dict, node_id: str, self_url: str, node_name: str):
        self.con = con
        self.cfg = cfg
        self.node_id = node_id
        self.self_url = self_url
        self.node_name = node_name
        self.net_cfg = cfg.get("network", {})
        self.central_cfg = cfg.get("central", {})
        self._http = httpx.AsyncClient(timeout=8.0)
        self._running = False

    def _self_info(self, local_models: list = None) -> dict:
        return {
            "id": self.node_id,
            "url": self.self_url,
            "name": self.node_name,
            "tier": "micro",
            "models": json.dumps([m.get("name", "") for m in (local_models or [])]),
        }

    def _central_headers(self) -> dict:
        return {
            "X-Node-Secret": self.central_cfg.get("node_secret", ""),
            "X-Node-Id": self.node_id,
            "Content-Type": "application/json",
        }

    def _central_enabled(self) -> bool:
        return (
            self.central_cfg.get("enabled", False)
            and bool(self.central_cfg.get("node_secret", ""))
            and bool(self.central_cfg.get("url", ""))
        )

    async def start(self, get_models_fn=None):
        self._get_models = get_models_fn
        self._running = True
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._discovery_loop())
        # Announce to bootstrap peers immediately
        asyncio.create_task(self._announce_to_bootstrap())
        # Fetch peers from central server immediately on startup
        if self._central_enabled():
            asyncio.create_task(self._fetch_peers_from_central())
            # BUG FIX: _central_discovery_loop was defined but never started.
            asyncio.create_task(self._central_discovery_loop())

    async def stop(self):
        self._running = False
        await self._http.aclose()

    # ── Central server peer discovery ─────────────────────────────────────────

    async def _fetch_peers_from_central(self):
        """Pull the online node list from the central server and connect to them."""
        central_url = self.central_cfg.get("url", "").rstrip("/")
        if not central_url:
            return
        try:
            r = await self._http.get(
                f"{central_url}/api/node/peers.php",
                headers=self._central_headers(),
                timeout=10,
            )
            if r.status_code != 200:
                return

            data = r.json()
            peers = data.get("peers", [])
            max_peers = self.net_cfg.get("max_peers", 50)
            current = len(get_peers(self.con))
            new_count = 0

            for p in peers:
                if current >= max_peers:
                    break
                peer_id  = p.get("id")
                peer_url = p.get("url", "").strip()
                if not peer_id or not peer_url:
                    continue
                if peer_id == self.node_id:
                    continue
                # Add to local DB if not already known
                existing = get_peers(self.con)
                if not any(ep["id"] == peer_id for ep in existing):
                    upsert_peer(self.con, peer_id, peer_url,
                                p.get("name", ""), p.get("tier", "nano"))
                    asyncio.create_task(self._announce_to(peer_url))
                    current += 1
                    new_count += 1

            if new_count:
                import logging
                logging.getLogger("peers").info(
                    f"Central discovery: found {new_count} new peer(s) from {central_url}"
                )
        except Exception as e:
            import logging
            logging.getLogger("peers").debug(f"Central peer fetch failed: {e}")

    async def _central_discovery_loop(self):
        """Re-fetch peers from central server every discovery_interval seconds."""
        interval = self.net_cfg.get("discovery_interval", 60)
        while self._running:
            await asyncio.sleep(interval)
            if self._central_enabled():
                await self._fetch_peers_from_central()

    # ── Bootstrap & gossip ────────────────────────────────────────────────────

    async def _announce_to_bootstrap(self):
        for peer_url in self.net_cfg.get("bootstrap_peers", []):
            await self._announce_to(peer_url.rstrip("/"))

    async def _heartbeat_loop(self):
        interval = self.net_cfg.get("heartbeat_interval", 30)
        while self._running:
            await asyncio.sleep(interval)
            peers = get_peers(self.con)
            for peer in peers:
                asyncio.create_task(self._ping_peer(peer))

    async def _discovery_loop(self):
        interval = self.net_cfg.get("discovery_interval", 60)
        while self._running:
            await asyncio.sleep(interval)
            # Gossip from local peers
            peers = get_online_peers(self.con)
            for peer in peers:
                asyncio.create_task(self._fetch_peers_from(peer["url"]))
            # NOTE: central re-fetch is handled by _central_discovery_loop;
            # no need to also call it here to avoid duplicate requests.

    async def _ping_peer(self, peer: dict):
        url = peer["url"].rstrip("/")
        try:
            info = self._self_info()
            r = await self._http.post(f"{url}/network/announce", json=info, timeout=5)
            if r.status_code == 200:
                update_peer_status(self.con, peer["id"], "online")
            else:
                update_peer_status(self.con, peer["id"], "degraded")
        except Exception:
            update_peer_status(self.con, peer["id"], "offline")

    async def _announce_to(self, url: str):
        try:
            info = self._self_info()
            r = await self._http.post(f"{url}/network/announce", json=info, timeout=5)
            if r.status_code == 200:
                data = r.json()
                peer_id = data.get("node_id") or data.get("id")
                peer_name = data.get("name", "")
                if peer_id and peer_id != self.node_id:
                    upsert_peer(self.con, peer_id, url, peer_name)
                    # Immediately fetch their peer list
                    asyncio.create_task(self._fetch_peers_from(url))
        except Exception:
            pass

    async def _fetch_peers_from(self, url: str):
        try:
            r = await self._http.get(f"{url.rstrip('/')}/network/peers", timeout=5)
            if r.status_code != 200:
                return
            peers = r.json().get("peers", [])
            max_peers = self.net_cfg.get("max_peers", 50)
            current = len(get_peers(self.con))
            for p in peers:
                if current >= max_peers:
                    break
                peer_id = p.get("id")
                peer_url = p.get("url")
                if peer_id and peer_url and peer_id != self.node_id:
                    if not any(ep["id"] == peer_id for ep in get_peers(self.con)):
                        upsert_peer(self.con, peer_id, peer_url, p.get("name", ""))
                        asyncio.create_task(self._announce_to(peer_url))
                        current += 1
        except Exception:
            pass

    async def connect_to_peer(self, url: str) -> dict:
        """Manually connect to a specific peer URL."""
        url = url.rstrip("/")
        await self._announce_to(url)
        peers = get_peers(self.con)
        match = next((p for p in peers if p["url"] == url), None)
        return match or {"error": "Could not connect to peer"}

    async def get_central_peers(self) -> list[dict]:
        """Fetch current online peers from central server for display in dashboard.

        Called by the node API at GET /network/central_peers so the dashboard
        can proxy through the node (which already holds the node_secret) rather
        than exposing the secret to the browser.
        """
        if not self._central_enabled():
            return []
        central_url = self.central_cfg.get("url", "").rstrip("/")
        try:
            r = await self._http.get(
                f"{central_url}/api/node/peers.php",
                headers=self._central_headers(),
                timeout=8,
            )
            if r.status_code == 200:
                return r.json().get("peers", [])
        except Exception:
            pass
        return []