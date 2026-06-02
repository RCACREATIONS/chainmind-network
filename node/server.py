"""FastAPI node server — Phase 1 complete with all endpoints."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .db import (
    init_db, get_stats, get_recent_tasks, get_task,
    upsert_peer, get_peers, get_online_peers, get_leaderboard,
    remove_peer,
)
from .ollama_client import OllamaClient
from .tasks import TaskProcessor
from .peers import PeerManager, load_node_id
from .orchestrator import Orchestrator
from .reputation import score_summary, next_tier_info
from .system_check import get_system_info, get_tier_for_system, filter_models_for_system
from .verification import verify_response, record_verification, consensus_rank
from .governance import init_governance, get_proposals, cast_vote, create_proposal
from .central_client import CentralClient
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, Request as FARequest

# ── Node API auth ──────────────────────────────────────────────────────────────
# Protected endpoints require: Authorization: Bearer <node.api_token>
# If api_token is empty in config.yaml, localhost access is always allowed.
_bearer = HTTPBearer(auto_error=False)

def _get_api_token() -> str:
    return NODE_CFG.get("api_token", "")

async def require_auth(
    req: FARequest,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    token = _get_api_token()
    if not token:
        return  # no token configured, open (localhost only recommended)
    if creds and creds.credentials == token:
        return
    from fastapi import HTTPException
    raise HTTPException(status_code=401, detail="Invalid or missing node API token")

# ── Config ────────────────────────────────────────────────────────────────────
_cfg_path = Path(__file__).parent.parent / "config.yaml"
with open(_cfg_path) as f:
    CFG: dict[str, Any] = yaml.safe_load(f)

NODE_CFG  = CFG["node"]
OLLAMA_URL = f"{CFG['ollama']['host']}:{CFG['ollama']['port']}"
DB_PATH   = str(Path(__file__).parent.parent / CFG["database"]["path"])
DATA_DIR  = str(Path(__file__).parent.parent / "data")
CATALOG   = CFG.get("models", {})

NODE_ID  = load_node_id(DATA_DIR)
SELF_URL = f"http://localhost:{NODE_CFG['port']}"

ollama    = OllamaClient(OLLAMA_URL)
con       = init_db(DB_PATH)
processor: TaskProcessor | None = None
peer_mgr:  PeerManager   | None = None
orch:      Orchestrator   | None = None
central:   CentralClient  | None = None

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global processor, peer_mgr, orch, central

    init_governance(con)

    models = await ollama.list_local_models()
    default = models[0]["name"] if models else "tinyllama"

    orch = Orchestrator(con, CFG, NODE_ID)
    processor = TaskProcessor(con, ollama, default)
    processor.orchestrator = orch
    await processor.start()

    peer_mgr = PeerManager(con, CFG, NODE_ID, SELF_URL, NODE_CFG["name"])
    await peer_mgr.start(get_models_fn=ollama.list_local_models)

    central = CentralClient(CFG, NODE_ID, NODE_CFG["name"], ollama, con)
    await central.start()

    yield

    await central.stop()
    await processor.stop()
    await peer_mgr.stop()
    await orch.close()
    await ollama.close()


app = FastAPI(title="IntelliChain Node", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# ── Pydantic models ───────────────────────────────────────────────────────────
class InferRequest(BaseModel):
    prompt: str
    model: str | None = None
    system: str = ""
    use_network: bool = False

class PullRequest(BaseModel):
    model: str

class ConnectRequest(BaseModel):
    url: str

class AnnounceRequest(BaseModel):
    id: str
    url: str
    name: str = ""
    tier: str = "nano"
    models: str = ""

class ConsensusRequest(BaseModel):
    responses: list[dict]

class VoteRequest(BaseModel):
    proposal_id: str
    vote: str
    iq_weight: float = 0.0

class ProposeRequest(BaseModel):
    title: str
    description: str = ""
    duration_days: int = 7

# ── Health & Stats ────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    ollama_ok = await ollama.is_running()
    return {
        "status": "ok",
        "node_id": NODE_ID[:8] + "...",   # truncated — full ID never exposed publicly
        "node": NODE_CFG["name"],
        "ollama": ollama_ok,
        "timestamp": time.time(),
        "version": "1.0.0",
    }

@app.get("/stats")
async def stats(_auth=Depends(require_auth)):
    s = get_stats(con)
    s["queue"] = processor.status() if processor else {}
    s["node_id"] = NODE_ID
    s["node_name"] = NODE_CFG["name"]
    rep = score_summary(con, NODE_ID)
    tasks = rep.get("tasks_done", 0)
    tier = rep.get("tier", "nano")
    nxt = next_tier_info(tier, tasks)
    s["reputation"] = {**rep, **nxt}
    s["peers_online"] = len(get_online_peers(con))
    return s

# ── System / Hardware ─────────────────────────────────────────────────────────
@app.get("/system")
async def system_info():
    hw = get_system_info()
    tier = get_tier_for_system(hw)
    compat = filter_models_for_system(CATALOG, hw)
    return {
        "hardware": hw,
        "recommended_tier": tier,
        "compatible_models": compat,
    }

# ── Models ────────────────────────────────────────────────────────────────────
@app.get("/models")
async def list_models():
    local = await ollama.list_local_models()
    hw = get_system_info()
    compat = filter_models_for_system(CATALOG, hw)
    return {"local": local, "catalog": CATALOG, "compatible": compat}

@app.post("/models/pull")
async def pull_model(req: PullRequest):
    async def _pull():
        async for _ in ollama.pull_model(req.model):
            pass
    asyncio.create_task(_pull())
    return {"status": "pulling", "model": req.model}

@app.delete("/models/{model_name:path}")
async def delete_model(model_name: str):
    ok = await ollama.delete_model(model_name)
    if not ok:
        raise HTTPException(404, f"Model '{model_name}' not found")
    return {"deleted": model_name}

# ── Inference ─────────────────────────────────────────────────────────────────
@app.post("/infer")
async def infer(req: InferRequest, _auth=Depends(require_auth)):
    if not processor:
        raise HTTPException(503, "Node not ready")
    task_id = await processor.enqueue(req.prompt, req.model, req.use_network)
    return {"task_id": task_id, "status": "queued"}

@app.post("/infer/verify")
async def infer_and_verify(req: InferRequest, _auth=Depends(require_auth)):
    """Submit task, wait for completion, run PoUI Layer 1 verification inline."""
    if not processor:
        raise HTTPException(503, "Node not ready")

    task_id = await processor.enqueue(req.prompt, req.model, req.use_network)

    # Wait for result (max 5 min)
    for _ in range(300):
        await asyncio.sleep(1)
        t = get_task(con, task_id)
        if t and t.get("status") in ("done", "error"):
            break

    result = t.get("result", "") if t else ""
    v = verify_response(req.prompt, result)
    if t:
        record_verification(con, task_id, v)

    return {
        **(t or {}),
        "verification": v,
    }

@app.get("/tasks")
async def list_tasks(limit: int = 50, _auth=Depends(require_auth)):
    return get_recent_tasks(con, limit)

@app.get("/tasks/{task_id}")
async def task_status(task_id: str, _auth=Depends(require_auth)):
    t = get_task(con, task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    return t

# ── Consensus / PoUI Layer 2 ──────────────────────────────────────────────────
@app.post("/consensus/rank")
async def consensus_ranking(req: ConsensusRequest):
    result = consensus_rank(req.responses)
    return result

# ── Network / Peer Discovery ──────────────────────────────────────────────────
@app.post("/network/announce")
async def network_announce(req: AnnounceRequest):
    if req.id != NODE_ID:
        upsert_peer(con, req.id, req.url, req.name, req.tier, req.models)
    return {
        "id": NODE_ID, "node_id": NODE_ID,   # full ID needed for gossip protocol
        "name": NODE_CFG["name"], "status": "ok",
        # url intentionally omitted — nodes should not advertise localhost URL
    }

@app.get("/network/peers")
async def network_peers():
    peers = get_peers(con)
    return {
        "peers": [{"id":p["id"][:8]+"...","name":p["name"],"tier":p["tier"]} for p in peers],
        "self": {"id":NODE_ID[:8]+"...","name":NODE_CFG["name"]},
    }

@app.get("/network/status")
async def network_status(_auth=Depends(require_auth)):
    all_peers = get_peers(con)
    online    = get_online_peers(con)
    # Include the detected public URL so the dashboard can display it
    pub_url   = central.public_url if central else None
    return {
        "node_id":    NODE_ID,
        "node_name":  NODE_CFG["name"],
        "self_url":   SELF_URL,
        "public_url": pub_url,
        "total_peers":  len(all_peers),
        "online_peers": len(online),
        "peers": all_peers,
    }

@app.post("/network/connect")
async def network_connect(req: ConnectRequest):
    if not peer_mgr:
        raise HTTPException(503, "Peer manager not ready")
    result = await peer_mgr.connect_to_peer(req.url)
    return result

@app.get("/network/central_peers")
async def network_central_peers():
    """Proxy the central server's peer directory through the node.
    The dashboard calls this so the node_secret is never exposed to the browser.
    """
    if not peer_mgr:
        raise HTTPException(503, "Peer manager not ready")
    peers = await peer_mgr.get_central_peers()
    return peers

@app.delete("/network/peers/{peer_id}")
async def network_remove_peer(peer_id: str):
    remove_peer(con, peer_id)
    return {"removed": peer_id}

# ── Reputation & Leaderboard ──────────────────────────────────────────────────
@app.get("/reputation")
async def reputation(_auth=Depends(require_auth)):
    rep = score_summary(con, NODE_ID)
    tasks = rep.get("tasks_done", 0)
    tier  = rep.get("tier", "nano")
    nxt   = next_tier_info(tier, tasks)
    return {**rep, **nxt}

@app.get("/leaderboard")
async def leaderboard(_auth=Depends(require_auth)):
    board = get_leaderboard(con)
    local = score_summary(con, NODE_ID)
    tasks = local.get("tasks_done", 0)
    tier  = local.get("tier", "nano")
    nxt   = next_tier_info(tier, tasks)
    return {"leaderboard": board, "local_node": {**local, **nxt}, "node_id": NODE_ID}

# ── Governance ────────────────────────────────────────────────────────────────
@app.get("/governance/proposals")
async def gov_proposals(_auth=Depends(require_auth)):
    proposals = get_proposals(con)
    return {"proposals": proposals}

@app.post("/governance/vote")
async def gov_vote(req: VoteRequest, _auth=Depends(require_auth)):
    # Use caller's IQ balance if weight not provided
    if req.iq_weight <= 0:
        rep = score_summary(con, NODE_ID)
        req.iq_weight = rep.get("iq_earned", 0.0)
    return cast_vote(con, req.proposal_id, NODE_ID, req.vote, req.iq_weight)

@app.post("/governance/propose")
async def gov_propose(req: ProposeRequest, _auth=Depends(require_auth)):
    rep = score_summary(con, NODE_ID)
    iq  = rep.get("iq_earned", 0.0)
    if iq < 1.0:
        raise HTTPException(403, "You need at least 1.0 IQ to create a proposal")
    return create_proposal(con, req.title, req.description, NODE_ID, req.duration_days)

# ── WebSocket: streaming inference ────────────────────────────────────────────
@app.websocket("/ws/infer")
async def ws_infer(ws: WebSocket):
    await ws.accept()
    try:
        data   = json.loads(await ws.receive_text())
        prompt = data.get("prompt", "")
        model  = data.get("model") or (
            (await ollama.list_local_models() or [{"name":"tinyllama"}])[0]["name"]
        )
        system = data.get("system", "")
        async for chunk in ollama.generate_stream(model, prompt, system):
            await ws.send_text(json.dumps({"chunk": chunk}))
        await ws.send_text(json.dumps({"done": True}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await ws.send_text(json.dumps({"error": str(e)}))
    finally:
        await ws.close()

@app.websocket("/ws/pull")
async def ws_pull(ws: WebSocket, model: str = "tinyllama"):
    await ws.accept()
    try:
        async for event in ollama.pull_model(model):
            await ws.send_text(json.dumps(event))
            if event.get("status") == "success":
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await ws.send_text(json.dumps({"error": str(e)}))
    finally:
        await ws.close()

# ── Account Linking & Billing endpoints (for node dashboard) ──────────────────

class LinkRequest(BaseModel):
    token: str

class WithdrawRequest(BaseModel):
    iq_amount: float
    method: str = "crypto"
    wallet: str = ""
    bank: str = ""
    account: str = ""

@app.post("/account/link")
async def account_link(req: LinkRequest, _auth=Depends(require_auth)):
    """Link this node to a ChainMind web account using a pairing token."""
    if not central:
        return {"ok": False, "error": "Central client not running"}
    result = await central.link_account(req.token.strip())
    return result

@app.post("/account/withdraw")
async def account_withdraw(req: WithdrawRequest, _auth=Depends(require_auth)):
    """Submit a withdrawal request to the central server."""
    if not central:
        return {"error": "Central client not running"}
    result = await central.request_withdrawal(
        req.iq_amount, req.method, req.wallet, req.bank, req.account
    )
    return result

@app.get("/account/earnings")
async def account_earnings(_auth=Depends(require_auth)):
    """Fetch live earnings data from the central server for this node."""
    if not central:
        return {"error": "Central client not running"}
    data = await central.get_earnings_info()
    return {"earnings": data}
