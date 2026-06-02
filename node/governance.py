"""Governance — on-chain voting simulation for protocol proposals.

Rules from the IntelliChain whitepaper:
  - 5% of total supply must participate for a vote to be valid
  - 67% supermajority required to pass
  - IQ holders vote; founders hold 10% (meaningful but not controlling)
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any


TOTAL_IQ_SUPPLY = 1_000_000_000.0  # Simulated genesis supply
QUORUM_PCT = 0.05                   # 5% participation required
SUPERMAJORITY = 0.67                # 67% yes votes required


def init_governance(con: sqlite3.Connection):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS proposals (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            description TEXT,
            proposer    TEXT,
            status      TEXT DEFAULT 'active',
            yes_votes   REAL DEFAULT 0.0,
            no_votes    REAL DEFAULT 0.0,
            abstain     REAL DEFAULT 0.0,
            created_at  REAL,
            ends_at     REAL
        );

        CREATE TABLE IF NOT EXISTS votes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id TEXT,
            voter_id    TEXT,
            vote        TEXT,
            weight      REAL,
            ts          REAL
        );
    """)
    con.commit()

    # Seed with default proposals if none exist
    count = con.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    if count == 0:
        _seed_proposals(con)


def _seed_proposals(con: sqlite3.Connection):
    proposals = [
        {
            "id": str(uuid.uuid4()),
            "title": "IQP-001: Set base IQ reward rate to 0.001 per token",
            "description": "Proposal to fix the base IQ reward rate at 0.001 IQ per token processed. "
                           "This establishes the initial token economy for Phase 1 testnet.",
            "proposer": "genesis",
            "duration_days": 7,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "IQP-002: Enable peer task splitting by default",
            "description": "Allow the orchestrator to split tasks across peer nodes automatically "
                           "when 2+ peers are online, to improve network utilization.",
            "proposer": "genesis",
            "duration_days": 7,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "IQP-003: Increase reputation decay for offline nodes",
            "description": "Nodes that go offline unexpectedly lose -3 reputation per hour of absence "
                           "instead of -1, to incentivize higher uptime.",
            "proposer": "genesis",
            "duration_days": 7,
        },
    ]
    for p in proposals:
        now = time.time()
        con.execute("""
            INSERT OR IGNORE INTO proposals
            (id, title, description, proposer, status, created_at, ends_at)
            VALUES (?,?,?,?,'active',?,?)
        """, (p["id"], p["title"], p["description"], p["proposer"],
              now, now + p["duration_days"] * 86400))
    con.commit()


def get_proposals(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute("SELECT * FROM proposals ORDER BY created_at DESC").fetchall()
    proposals = [dict(r) for r in rows]
    for p in proposals:
        total = p["yes_votes"] + p["no_votes"] + p["abstain"]
        p["total_votes"] = total
        p["participation_pct"] = round(total / TOTAL_IQ_SUPPLY * 100, 4)
        p["yes_pct"] = round(p["yes_votes"] / total * 100, 1) if total > 0 else 0
        p["no_pct"] = round(p["no_votes"] / total * 100, 1) if total > 0 else 0
        p["quorum_met"] = total >= TOTAL_IQ_SUPPLY * QUORUM_PCT
        p["passed"] = p["quorum_met"] and (p["yes_votes"] / total >= SUPERMAJORITY if total > 0 else False)
        p["time_remaining_h"] = max(0, round((p["ends_at"] - time.time()) / 3600, 1))
        # Close expired proposals
        if p["ends_at"] < time.time() and p["status"] == "active":
            new_status = "passed" if p["passed"] else "rejected"
            con.execute("UPDATE proposals SET status=? WHERE id=?", (new_status, p["id"]))
            con.commit()
            p["status"] = new_status
    return proposals


def cast_vote(con: sqlite3.Connection, proposal_id: str, voter_id: str,
              vote: str, iq_weight: float) -> dict[str, Any]:
    """Cast a vote. vote must be 'yes', 'no', or 'abstain'."""
    if vote not in ("yes", "no", "abstain"):
        return {"error": "Vote must be 'yes', 'no', or 'abstain'"}

    # Check proposal exists and is active
    row = con.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    if not row:
        return {"error": "Proposal not found"}
    if dict(row)["status"] != "active":
        return {"error": "Proposal is no longer active"}

    # Check if already voted
    existing = con.execute(
        "SELECT id FROM votes WHERE proposal_id=? AND voter_id=?",
        (proposal_id, voter_id)
    ).fetchone()
    if existing:
        return {"error": "Already voted on this proposal"}

    # Record vote
    con.execute(
        "INSERT INTO votes (proposal_id, voter_id, vote, weight, ts) VALUES (?,?,?,?,?)",
        (proposal_id, voter_id, vote, iq_weight, time.time()),
    )
    col = {"yes": "yes_votes", "no": "no_votes", "abstain": "abstain"}.get(vote)
    if col:
        con.execute(f"UPDATE proposals SET {col}={col}+? WHERE id=?", (iq_weight, proposal_id))
    con.commit()

    return {"success": True, "proposal_id": proposal_id, "vote": vote, "weight": iq_weight}


def create_proposal(con: sqlite3.Connection, title: str, description: str,
                    proposer: str, duration_days: int = 7) -> dict[str, Any]:
    now = time.time()
    proposal_id = str(uuid.uuid4())
    con.execute("""
        INSERT INTO proposals (id, title, description, proposer, status, created_at, ends_at)
        VALUES (?,?,?,?,'active',?,?)
    """, (proposal_id, title, description, proposer, now, now + duration_days * 86400))
    con.commit()
    return {"id": proposal_id, "title": title, "status": "active"}
