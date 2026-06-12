"""
ChainMind Node  Job Loop Integration Patch
==========================================
This shows exactly how to integrate the new image/vision/file_qa handling
into your existing node job-claiming loop.

Find your existing job claim loop in the node client and apply the changes
marked with  ADD  and  MODIFY  comments below.

Your existing flow is probably:
  1. POST /api/node/claim-job.php  → get a job
  2. Run inference via Ollama
  3. POST /api/node/submit-result.php  → submit result

This patch adds:
  - Reporting capabilities in heartbeat
  - Routing special job types to image_and_vision.py handlers
"""

import json
import logging
import os
import time

import requests

from image_and_vision import detect_capabilities, ensure_vision_model, handle_special_job

logger = logging.getLogger("chainmind.node")

# ── ADD: Detect capabilities once at startup ─────────────────────────────────

def startup_capability_check(config: dict) -> dict:
    """
    Call this ONCE when your node starts up.
    Returns capabilities dict to include in heartbeats.

    config: your existing node config dict (with central_url, node_id, node_secret)
    """
    logger.info("[startup] Detecting node capabilities...")
    caps = detect_capabilities()

    # If no vision model, try to pull one automatically
    if not caps["vision"]:
        caps = ensure_vision_model(caps)

    logger.info(f"[startup] Capabilities: image_gen={caps['image_gen']} "
                f"engine={caps.get('image_gen_engine')} vision={caps['vision']}")
    return caps


# ── MODIFY: Add capabilities to your heartbeat payload ───────────────────────

def send_heartbeat(config: dict, caps: dict, models: list[str]) -> bool:
    """
    Modified heartbeat that reports capabilities.
    Replace your existing heartbeat function with this pattern.
    """
    payload = {
        "models":       models,
        # ADD these three fields:
        "capabilities": json.dumps(list(filter(None, [
            "image_gen"  if caps.get("image_gen")  else None,
            "vision"     if caps.get("vision")     else None,
            "file_qa",   # always supported
            f"engine:{caps.get('image_gen_engine', 'none')}",
        ]))),
        "vram_gb":      caps.get("vram_gb", 0),
        "gpu_name":     caps.get("gpu_name", ""),
    }

    try:
        resp = requests.post(
            f"{config['central_url']}/api/node/heartbeat.php",
            json=payload,
            headers={
                "X-Node-Id":     config["node_id"],
                "X-Node-Secret": config["node_secret"],
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"[heartbeat] Failed: {e}")
        return False


# ── MODIFY: Extended job claim → route → submit ───────────────────────────────

def run_job_loop(config: dict, caps: dict):
    """
    Your main job polling loop — updated to handle special job types.

    Replace / adapt your existing loop with this pattern.
    The key addition is checking job['job_type'] before running Ollama.
    """
    central_url  = config["central_url"]
    node_id      = config["node_id"]
    node_secret  = config["node_secret"]
    poll_interval = config.get("poll_interval_seconds", 3)

    headers = {
        "X-Node-Id":     node_id,
        "X-Node-Secret": node_secret,
        "Content-Type":  "application/json",
    }

    logger.info("[loop] Starting job loop...")

    while True:
        try:
            # ── 1. Claim a job ────────────────────────────────────────────
            resp = requests.post(
                f"{central_url}/api/node/claim-job.php",
                headers=headers,
                timeout=10,
            )

            if resp.status_code != 200:
                time.sleep(poll_interval)
                continue

            data = resp.json()
            job  = data.get("job")

            if not job:
                time.sleep(poll_interval)
                continue

            job_id   = job["id"]
            job_type = job.get("job_type", "text")

            logger.info(f"[loop] Claimed job {job_id} type={job_type}")

            # ── 2. Route to correct handler ──────────────────────────────
            if job_type in ("image_gen", "vision", "file_qa"):
                # NEW: use image_and_vision handlers
                outcome = handle_special_job(job, caps)

            else:
                # EXISTING: standard text inference via Ollama
                outcome = run_ollama_inference(job, config)

            # ── 3. Submit result ─────────────────────────────────────────
            submit_payload = {
                "job_id":      job_id,
                "status":      outcome["status"],
                "result":      outcome["result"],
                "tokens_in":   outcome.get("tokens_in", 0),
                "tokens_out":  outcome.get("tokens_out", 0),
                "duration_ms": outcome.get("duration_ms", 0),
            }

            # NEW: include result_images if present
            if outcome.get("result_images"):
                submit_payload["result_images"] = outcome["result_images"]

            requests.post(
                f"{central_url}/api/node/submit-result.php",
                json=submit_payload,
                headers=headers,
                timeout=30,
            )

        except KeyboardInterrupt:
            logger.info("[loop] Stopped by user")
            break
        except Exception as e:
            logger.error(f"[loop] Error: {e}")
            time.sleep(poll_interval * 2)


def run_ollama_inference(job: dict, config: dict) -> dict:
    """
    Your existing Ollama text inference — kept unchanged.
    This is a reference implementation; replace with your actual code.
    """
    t_start = time.time()
    prompt  = job.get("prompt", "")
    model   = job.get("model") or config.get("default_model", "mistral")
    system  = job.get("system_prompt", "")

    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": full_prompt, "stream": False},
            timeout=90,
        )
        resp.raise_for_status()
        data       = resp.json()
        result     = data.get("response", "")
        tokens_in  = data.get("prompt_eval_count", len(full_prompt.split()))
        tokens_out = data.get("eval_count", len(result.split()))

        return {
            "status":      "done",
            "result":      result,
            "result_images": None,
            "tokens_in":   tokens_in,
            "tokens_out":  tokens_out,
            "duration_ms": int((time.time() - t_start) * 1000),
        }

    except Exception as e:
        return {
            "status":      "error",
            "result":      str(e),
            "result_images": None,
            "tokens_in":   0,
            "tokens_out":  0,
            "duration_ms": int((time.time() - t_start) * 1000),
        }


# ── Example startup ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Load your existing config (adapt path to your node's config.yaml / config.json)
    import yaml  # or json
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Startup capability detection (runs once)
    caps = startup_capability_check(config)

    # Run job loop
    run_job_loop(config, caps)
