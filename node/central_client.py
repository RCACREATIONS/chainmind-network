"""
central_client.py — ChainMind Central Server integration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from .db import insert_task, update_task, get_stats
from .image_and_vision import detect_capabilities, ensure_vision_model, handle_special_job

log = logging.getLogger("central_client")

_IP_SERVICES = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
]


class CentralClient:
    def __init__(self, cfg: dict, node_id: str, node_name: str, ollama_client, con):
        self.cfg          = cfg  # keep full cfg for pending link token etc.
        self.central_cfg  = cfg.get("central", {})
        self.enabled      = self.central_cfg.get("enabled", False)
        self.base_url     = self.central_cfg.get("url", "https://chainmind.com.ng").rstrip("/")
        self.secret       = self.central_cfg.get("node_secret", "")
        self.poll_ivl     = self.central_cfg.get("poll_interval", 3)
        self.hb_ivl       = self.central_cfg.get("heartbeat_interval", 30)
        self.node_cfg     = cfg.get("node", {})
        self.token_cfg    = cfg.get("tokens", {})

        self.node_id      = node_id
        self.node_name    = node_name
        self.ollama       = ollama_client
        self.con          = con

        self._jobs_done      = 0
        self._iq_earned      = 0.0
        self._reputation     = 100.0
        self._running        = False
        self._public_ip      = None
        self._secret_invalid = False  # set True on 403 — prompts user to reconnect
        self._capabilities: dict = {}  # populated at startup by _detect_capabilities()

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5, read=90, write=10, pool=5),
            headers={
                "X-Node-Secret": self.secret   or "",
                "X-Node-Id":     self.node_id  or "",
                "Content-Type":  "application/json",
            },
        )

    @property
    def public_url(self):
        override = self.node_cfg.get("public_url", "").strip()
        if override:
            return override
        if self._public_ip:
            port = self.node_cfg.get("port", 8000)
            return f"http://{self._public_ip}:{port}"
        return None

    async def _detect_public_ip(self):
        if self.node_cfg.get("public_url", "").strip():
            log.info(f"Using configured public_url: {self.node_cfg['public_url']}")
            return None
        async with httpx.AsyncClient(timeout=5) as tmp:
            for url in _IP_SERVICES:
                try:
                    r = await tmp.get(url, headers={"Accept": "text/plain"})
                    ip = r.text.strip()
                    if ip and 4 <= len(ip) <= 45:
                        log.info(f"Detected public IP: {ip} (via {url})")
                        return ip
                except Exception as e:
                    log.debug(f"IP detection failed for {url}: {e}")
        log.warning("Could not detect public IP — heartbeat will use localhost URL")
        return None

    async def start(self):
        if not self.enabled:
            log.info("Central client disabled.")
            return
        if not self.secret:
            log.warning("central.node_secret is empty — central server integration won't work")
            return

        # ── Seed in-memory counters from local DB so heartbeat sends correct totals
        # even after a restart (previously these started at 0 every time).
        try:
            db_stats = get_stats(self.con)
            self._iq_earned  = float(db_stats.get("iq_earned",  0.0))
            self._jobs_done  = int(db_stats.get("total_tasks", 0))
            self._reputation = float(db_stats.get("reputation_score", 100.0))
            log.info(
                f"Seeded from DB — IQ: {self._iq_earned:.6f}, "
                f"jobs: {self._jobs_done}, rep: {self._reputation:.1f}"
            )
        except Exception as e:
            log.warning(f"Could not seed counters from DB: {e}")

        # ── Detect multimodal capabilities once at startup ────────────────────
        ollama_base = f"{self._ollama.base_url}" if hasattr(self._ollama, "base_url") \
                      else "http://localhost:11434"
        try:
            self._capabilities = await detect_capabilities(ollama_base)
            # Auto-pull llava:7b if no vision model is available
            if not self._capabilities.get("vision"):
                self._capabilities = await ensure_vision_model(
                    self._capabilities, ollama_base
                )
        except Exception as exc:
            log.warning(f"Capability detection failed: {exc}")
            self._capabilities = {"file_qa": True}

        self._public_ip = await self._detect_public_ip()
        log.info(f"Central client starting — connecting to {self.base_url}")
        log.info(f"Node public URL: {self.public_url or '(localhost fallback)'}")
        self._running = True

        # Send first heartbeat immediately so the node is registered before we try to link
        await self._send_heartbeat()

        # Check for a pending link token from the setup wizard
        pending_token = self.cfg.get("_pending_link_token", "")
        if pending_token:
            await self._complete_account_link(pending_token)

        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        await self._http.aclose()

    @property
    def secret_invalid(self) -> bool:
        return self._secret_invalid

    async def _heartbeat_loop(self):
        await self._send_heartbeat()
        while self._running and not self._secret_invalid:
            await asyncio.sleep(self.hb_ivl)
            await self._send_heartbeat()

    async def _send_heartbeat(self):
        try:
            # Always read fresh totals from DB — in-memory counters may lag after restart
            try:
                db_stats = get_stats(self.con)
                db_iq   = float(db_stats.get("iq_earned",  self._iq_earned))
                db_jobs = int(db_stats.get("total_tasks",  self._jobs_done))
                db_rep  = float(db_stats.get("reputation_score", self._reputation))
                # Use whichever is higher (DB is ground truth; in-memory catches mid-session)
                self._iq_earned  = max(self._iq_earned,  db_iq)
                self._jobs_done  = max(self._jobs_done,  db_jobs)
                self._reputation = max(self._reputation, db_rep)
            except Exception:
                pass  # fall through to in-memory values

            models = await self.ollama.list_local_models()
            model_names = [m.get("name", "") for m in models]
            tier = self._compute_tier()
            node_url = self.public_url or self._self_url()
            caps = self._capabilities

            # Build capabilities list for the server
            cap_list = list(filter(None, [
                "image_gen" if caps.get("image_gen")  else None,
                "vision"    if caps.get("vision")     else None,
                "file_qa",
                f"engine:{caps.get('image_gen_engine', 'none')}",
            ]))

            payload = {
                "name":         self.node_name,
                "url":          node_url,
                "tier":         tier,
                "models":       model_names,
                "jobs_done":    self._jobs_done,
                "iq_earned":    round(self._iq_earned, 6),
                "reputation":   round(self._reputation, 2),
                "capabilities": json.dumps(cap_list),
                "vram_gb":      caps.get("vram_gb", 0),
                "gpu_name":     caps.get("gpu_name", "") or "",
            }
            r = await self._http.post(f"{self.base_url}/api/node/heartbeat.php", json=payload)
            if r.status_code == 200:
                data = r.json()
                net = data.get("network", {})
                log.debug(f"Heartbeat OK — {net.get('online_nodes')} nodes online")
            elif r.status_code == 403:
                self._secret_invalid = True
                self._running = False
                log.error(
                    "Heartbeat rejected with 403 Invalid node secret. "
                    "Go to ⚙️ Settings → Reconnect Account in the dashboard to fix this."
                )
            else:
                log.warning(f"Heartbeat returned {r.status_code}: {r.text[:200]}")
        except Exception as e:
            log.warning(f"Heartbeat failed: {e}")

    async def _poll_loop(self):
        while self._running and not self._secret_invalid:
            try:
                await self._poll_once()
            except Exception as e:
                log.warning(f"Poll error: {e}")
            await asyncio.sleep(self.poll_ivl)

    async def _poll_once(self):
        r = await self._http.get(f"{self.base_url}/api/node/claim-job.php")

        # ===== PATCH 1: CREDIT HANDLING =====
        if r.status_code == 402:
            try:
                err = r.json().get("error", "Insufficient credits")
            except Exception:
                err = "Insufficient credits"

            log.warning(f"claim-job: 402 {err} — pausing 60s before retry")
            await asyncio.sleep(60)
            return

        if r.status_code != 200:
            log.warning(f"claim-job: HTTP {r.status_code}")
            return
        # ====================================

        data = r.json()
        job = data.get("job")
        if not job:
            return

        job_id   = job["id"]
        job_type = job.get("job_type", "text")
        prompt   = job.get("prompt", "")
        model    = job.get("model") or None
        system   = job.get("system_prompt", "")

        log.info(f"Claimed job {job_id[:8]}… type={job_type} model={model or 'auto'}")

        if job_type in ("image_gen", "vision", "file_qa"):
            await self._run_multimodal_job(job)
        else:
            await self._run_job(job_id, prompt, model, system)

    async def _run_multimodal_job(self, job: dict):
        """Handle image_gen / vision / file_qa jobs via image_and_vision module."""
        job_id = job["id"]
        prompt = job.get("prompt", "")
        ollama_base = getattr(self.ollama, "base_url", "http://localhost:11434")

        insert_task(self.con, job_id, prompt, job.get("model") or "auto", routed_to="central")

        try:
            outcome = await handle_special_job(job, self._capabilities, ollama_base)
        except Exception as exc:
            log.error(f"Multimodal job {job_id[:8]}… error: {exc}")
            outcome = {
                "status": "error",
                "result": str(exc),
                "result_images": None,
                "tokens_in": 0, "tokens_out": 0,
                "duration_ms": 0,
            }

        update_task(
            self.con, job_id, outcome["status"],
            result=outcome["result"],
            tokens_in=outcome.get("tokens_in", 0),
            tokens_out=outcome.get("tokens_out", 0),
            duration_ms=outcome.get("duration_ms", 0),
        )

        try:
            payload: dict = {
                "job_id":      job_id,
                "status":      outcome["status"],
                "result":      outcome["result"],
                "tokens_in":   outcome.get("tokens_in", 0),
                "tokens_out":  outcome.get("tokens_out", 0),
                "duration_ms": outcome.get("duration_ms", 0),
            }
            if outcome.get("result_images"):
                payload["result_images"] = outcome["result_images"]

            r = await self._http.post(
                f"{self.base_url}/api/node/submit-result.php",
                json=payload,
            )
            if r.status_code == 200:
                resp_data = r.json()
                iq_delta  = resp_data.get("iq_earned", 0.0)
                rep_delta = resp_data.get("rep_delta", 0.0)
                self._jobs_done  += 1
                self._iq_earned  += iq_delta
                self._reputation  = max(0, min(1000, self._reputation + rep_delta))
                log.info(
                    f"Multimodal job {job_id[:8]}… done "
                    f"status={outcome['status']} IQ+{iq_delta:.6f}"
                )
            else:
                log.warning(f"submit-result returned {r.status_code}: {r.text[:200]}")
        except Exception as exc:
            log.error(f"Failed to submit multimodal result for {job_id[:8]}: {exc}")

    async def _run_job(self, job_id: str, prompt: str, model, system: str):
        start  = time.monotonic()
        status = "error"
        result = ""
        tokens_in  = 0
        tokens_out = 0

        insert_task(self.con, job_id, prompt, model or "auto", routed_to="central")

        try:
            if not model:
                models = await self.ollama.list_local_models()
                model = models[0]["name"] if models else "tinyllama"

            resp       = await self.ollama.generate(model=model, prompt=prompt, system=system or "")
            result     = resp.get("response", "")
            tokens_in  = resp.get("prompt_eval_count", 0)
            tokens_out = resp.get("eval_count", 0)
            status     = "done"

            log.info(f"Job {job_id[:8]}… done — {tokens_out} tokens out")

        except Exception as e:
            result = f"Node error: {e}"
            log.error(f"Job {job_id[:8]}… failed: {e}")

        duration_ms = int((time.monotonic() - start) * 1000)

        update_task(
            self.con,
            job_id,
            status,
            result=result,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=duration_ms
        )

        try:
            payload = {
                "job_id":      job_id,
                "status":      status,
                "result":      result,
                "tokens_in":   tokens_in,
                "tokens_out":  tokens_out,
                "duration_ms": duration_ms,
            }

            r = await self._http.post(
                f"{self.base_url}/api/node/submit-result.php",
                json=payload
            )

            if r.status_code == 200:
                resp_data = r.json()
                iq_delta  = resp_data.get("iq_earned", 0.0)
                rep_delta = resp_data.get("rep_delta", 0.0)

                self._jobs_done += 1
                self._iq_earned += iq_delta
                self._reputation = max(0, min(1000, self._reputation + rep_delta))

                # ===== PATCH 2: IQ LOGGING =====
                if iq_delta > 0:
                    log.info(
                        f"IQ earned: +{iq_delta:.6f}  |  session total: {self._iq_earned:.6f}  "
                        f"|  view earnings: {self.base_url}/dashboard/node-earnings.php"
                    )
                else:
                    log.debug(f"Result accepted — IQ +{iq_delta:.4f}, rep {rep_delta:+.1f}")
                # =================================

            else:
                log.warning(f"submit-result returned {r.status_code}: {r.text[:200]}")

        except Exception as e:
            log.error(f"Failed to submit result for job {job_id[:8]}: {e}")

    @property
    def capabilities(self) -> dict:
        """Current multimodal capabilities dict (populated at startup)."""
        return self._capabilities

    def _self_url(self) -> str:
        port = self.node_cfg.get("port", 8000)
        return f"http://localhost:{port}"

    async def _complete_account_link(self, token: str):
        """Send the pending link token to the central server to pair this node with a web account."""
        try:
            r = await self._link_request(token)
            if r.status_code == 200:
                text = r.text.strip()
                data = r.json() if text else {}
                email = data.get("user_email", "")
                log.info(f"✅ Node linked to web account: {email}")
                log.info(f"   View your earnings at: {self.base_url}/dashboard/node-earnings.php")
                self._clear_pending_link_token()
            else:
                text = r.text.strip() if r.text else ""
                try:
                    err = r.json().get("error", text[:120]) if text else f"HTTP {r.status_code}"
                except Exception:
                    err = text[:120] or f"HTTP {r.status_code}"
                log.warning(f"Account link failed ({r.status_code}): {err}")
                log.warning("Generate a new token from the web dashboard and try again.")
        except Exception as e:
            log.warning(f"Account link request failed: {e}")

    async def _link_request(self, token: str):
        """Send link token — tries PUT first, falls back to POST if server blocks PUT."""
        url = f"{self.base_url}/api/node/link.php"
        try:
            r = await self._http.request("PUT", url, json={"link_token": token})
            if r.status_code not in (403, 405):
                return r
            log.debug(f"PUT blocked ({r.status_code}), retrying as POST+action")
        except Exception:
            pass
        # Fallback: POST with action field (for proxies/hosts that block PUT)
        return await self._http.post(url, json={"link_token": token, "action": "link_node"})

    def _clear_pending_link_token(self):
        """Remove _pending_link_token from config.yaml after successful link."""
        try:
            from pathlib import Path
            import yaml as _yaml
            cfg_path = Path(__file__).parent.parent / "config.yaml"
            with open(cfg_path) as f:
                raw = _yaml.safe_load(f) or {}
            raw.pop("_pending_link_token", None)
            with open(cfg_path, "w") as f:
                _yaml.safe_dump(raw, f, default_flow_style=False, sort_keys=False)
        except Exception as e:
            log.debug(f"Could not clear pending link token from config: {e}")

    async def link_account(self, token: str) -> dict:
        """Public method — called from node dashboard UI to link account."""
        try:
            r = await self._link_request(token)
            text = r.text.strip() if r.text else ""
            if not text:
                return {"ok": False, "error": f"Server returned empty response (HTTP {r.status_code})"}
            try:
                data = r.json()
            except Exception:
                return {"ok": False, "error": f"Server returned invalid response (HTTP {r.status_code}): {text[:120]}"}
            if r.status_code == 200:
                self._clear_pending_link_token()
                return {"ok": True, "user_email": data.get("user_email", "")}
            return {"ok": False, "error": data.get("error", f"Server error {r.status_code}")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def request_withdrawal(self, iq_amount: float, method: str, wallet: str = "", bank: str = "", account: str = "") -> dict:
        """Submit a withdrawal request to the central server."""
        payload = {"iq_amount": iq_amount, "method": method}
        if method == "crypto":
            payload["wallet"] = wallet
        else:
            payload["bank"] = bank
            payload["account"] = account
        try:
            r = await self._http.post(f"{self.base_url}/api/node/withdraw.php", json=payload)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def get_earnings_info(self) -> dict:
        """Fetch current node earnings from central server (node-authenticated endpoint)."""
        try:
            r = await self._http.get(f"{self.base_url}/api/node/node-earnings.php")
            if r.status_code == 200:
                text = r.text.strip()
                if not text:
                    log.debug("node-earnings: empty response body")
                    return {}
                try:
                    data = r.json()
                except Exception as json_err:
                    log.warning(f"node-earnings: invalid JSON — {json_err} — body: {text[:120]}")
                    return {}
                return data.get("node") or {}
            else:
                log.debug(f"node-earnings: HTTP {r.status_code}")
        except Exception as e:
            log.debug(f"node-earnings: request failed — {e}")
        return {}

    def _compute_tier(self) -> str:
        jobs = self._jobs_done
        if jobs >= 5000: return "enterprise"
        if jobs >= 1000: return "pro"
        if jobs >= 200:  return "standard"
        if jobs >= 50:   return "micro"
        return "nano"