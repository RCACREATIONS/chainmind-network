"""SQLite database — tasks, stats, peers, reputation, tokens, leaderboard."""

import sqlite3
import time
from pathlib import Path
from typing import Any

# Crypto is imported lazily so db.py works even before init_crypto() is called.
# All encrypt/decrypt calls are safe no-ops if crypto is not initialised.
from . import crypto as _crypto


def _conn(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db(db_path: str) -> sqlite3.Connection:
    con = _conn(db_path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          TEXT PRIMARY KEY,
            prompt      TEXT NOT NULL,
            model       TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            result      TEXT,
            tokens_in   INTEGER DEFAULT 0,
            tokens_out  INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            routed_to   TEXT DEFAULT 'local',
            created_at  REAL NOT NULL,
            finished_at REAL
        );

        CREATE TABLE IF NOT EXISTS node_stats (
            id              INTEGER PRIMARY KEY CHECK (id = 1),
            total_tasks     INTEGER DEFAULT 0,
            total_tokens    INTEGER DEFAULT 0,
            iq_earned       REAL    DEFAULT 0.0,
            uptime_start    REAL    NOT NULL,
            last_heartbeat  REAL
        );

        CREATE TABLE IF NOT EXISTS peers (
            id              TEXT PRIMARY KEY,
            url             TEXT NOT NULL UNIQUE,
            name            TEXT DEFAULT '',
            tier            TEXT DEFAULT 'nano',
            reputation      REAL DEFAULT 100.0,
            iq_earned       REAL DEFAULT 0.0,
            tasks_done      INTEGER DEFAULT 0,
            last_seen       REAL,
            status          TEXT DEFAULT 'unknown',
            models          TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS reputation_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            peer_id     TEXT,
            event_type  TEXT,
            delta       REAL,
            reason      TEXT,
            ts          REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS token_ledger (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            peer_id     TEXT,
            amount      REAL,
            reason      TEXT,
            ts          REAL NOT NULL
        );

        INSERT OR IGNORE INTO node_stats (id, uptime_start) VALUES (1, unixepoch());
    """)
    con.commit()
    return con


# ── Tasks ─────────────────────────────────────────────────────────────────────

def insert_task(con, task_id, prompt, model, routed_to="local"):
    con.execute(
        "INSERT INTO tasks (id, prompt, model, status, routed_to, created_at) VALUES (?,?,?,'pending',?,?)",
        (task_id, _crypto.encrypt(prompt), model, routed_to, time.time()),
    )
    con.commit()


def update_task(con, task_id, status, result="", tokens_in=0, tokens_out=0, duration_ms=0):
    con.execute(
        "UPDATE tasks SET status=?, result=?, tokens_in=?, tokens_out=?, duration_ms=?, finished_at=? WHERE id=?",
        (status, _crypto.encrypt(result), tokens_in, tokens_out, duration_ms, time.time(), task_id),
    )
    if status == "done":
        tier = _get_local_tier(con)
        from pathlib import Path
        import yaml
        cfg_path = Path(__file__).parent.parent / "config.yaml"
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        multiplier = cfg.get("tokens", {}).get("tier_multipliers", {}).get(tier, 1)
        base = cfg.get("tokens", {}).get("base_rate", 0.001)
        iq = round((tokens_in + tokens_out) * base * multiplier, 6)
        con.execute(
            "UPDATE node_stats SET total_tasks=total_tasks+1, total_tokens=total_tokens+?, iq_earned=iq_earned+?, last_heartbeat=? WHERE id=1",
            (tokens_in + tokens_out, iq, time.time()),
        )
    con.commit()


def _get_local_tier(con) -> str:
    stats = get_stats(con)
    tasks = stats.get("total_tasks", 0)
    if tasks < 10:
        return "nano"
    elif tasks < 100:
        return "micro"
    elif tasks < 1000:
        return "standard"
    elif tasks < 5000:
        return "pro"
    return "enterprise"


def get_stats(con) -> dict[str, Any]:
    row = con.execute("SELECT * FROM node_stats WHERE id=1").fetchone()
    return dict(row) if row else {}


def get_recent_tasks(con, limit=20) -> list[dict]:
    rows = con.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    tasks = []
    for r in rows:
        t = dict(r)
        # Decrypt result for internal use; mask prompt for privacy in dashboard
        t["result"] = _crypto.decrypt(t.get("result") or "")
        t["prompt"] = _crypto.mask_prompt(t.get("prompt") or "") if _crypto.is_enabled() else (t.get("prompt") or "")
        tasks.append(t)
    return tasks


def get_task(con, task_id) -> dict | None:
    row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        return None
    t = dict(row)
    # Decrypt both prompt and result when fetching a specific task (used for inference result delivery)
    t["result"] = _crypto.decrypt(t.get("result") or "")
    t["prompt"] = _crypto.decrypt(t.get("prompt") or "")
    return t


# ── Peers ─────────────────────────────────────────────────────────────────────

def upsert_peer(con, peer_id, url, name="", tier="nano", models=""):
    con.execute("""
        INSERT INTO peers (id, url, name, tier, models, last_seen, status)
        VALUES (?,?,?,?,?,?,'online')
        ON CONFLICT(id) DO UPDATE SET
            url=excluded.url, name=excluded.name, tier=excluded.tier,
            models=excluded.models, last_seen=excluded.last_seen, status='online'
    """, (peer_id, url, name, tier, models, time.time()))
    con.commit()


def update_peer_status(con, peer_id, status):
    con.execute("UPDATE peers SET status=?, last_seen=? WHERE id=?", (status, time.time(), peer_id))
    con.commit()


def get_peers(con) -> list[dict]:
    rows = con.execute("SELECT * FROM peers ORDER BY reputation DESC").fetchall()
    return [dict(r) for r in rows]


def get_online_peers(con) -> list[dict]:
    cutoff = time.time() - 120
    rows = con.execute(
        "SELECT * FROM peers WHERE status='online' AND last_seen > ? ORDER BY reputation DESC",
        (cutoff,)
    ).fetchall()
    return [dict(r) for r in rows]


def remove_peer(con, peer_id):
    con.execute("DELETE FROM peers WHERE id=?", (peer_id,))
    con.commit()


# ── Reputation ────────────────────────────────────────────────────────────────

def adjust_reputation(con, peer_id, delta, reason=""):
    con.execute("UPDATE peers SET reputation=MAX(0,MIN(1000,reputation+?)) WHERE id=?", (delta, peer_id))
    con.execute("INSERT INTO reputation_events (peer_id,event_type,delta,reason,ts) VALUES (?,?,?,?,?)",
                (peer_id, "adjustment", delta, reason, time.time()))
    con.commit()


def update_peer_task_stats(con, peer_id, iq_delta, success=True):
    con.execute(
        "UPDATE peers SET tasks_done=tasks_done+1, iq_earned=iq_earned+? WHERE id=?",
        (iq_delta, peer_id)
    )
    delta = 2.0 if success else -5.0
    adjust_reputation(con, peer_id, delta, "task_result")
    con.commit()


# ── Leaderboard ───────────────────────────────────────────────────────────────

def get_leaderboard(con) -> list[dict]:
    rows = con.execute("""
        SELECT id, name, url, tier, reputation, iq_earned, tasks_done, status, last_seen
        FROM peers ORDER BY iq_earned DESC LIMIT 50
    """).fetchall()
    return [dict(r) for r in rows]
