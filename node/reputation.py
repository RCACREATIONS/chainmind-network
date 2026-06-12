"""Reputation system — compute and expose node tiers and scores."""

from __future__ import annotations

import sqlite3
import time
from typing import Any


TIER_THRESHOLDS = [
    ("enterprise", 5000),
    ("pro",        1000),
    ("standard",   200),
    ("micro",      50),
    ("nano",       0),
]

TIER_LABELS = {
    "nano":       "🔵 Nano",
    "micro":      "🟢 Micro",
    "standard":   "🟡 Standard",
    "pro":        "🟠 Pro",
    "enterprise": "🔴 Enterprise",
}

TIER_MULTIPLIERS = {
    "nano": 1, "micro": 3, "standard": 8, "pro": 20, "enterprise": 50
}

TIER_HARDWARE = {
    "nano":       "Raspberry Pi / Phone",
    "micro":      "Laptop / Old PC",
    "standard":   "Gaming PC (GPU)",
    "pro":        "Multi-GPU Workstation",
    "enterprise": "Server Rack",
}


def compute_tier(tasks_done: int) -> str:
    for tier, threshold in TIER_THRESHOLDS:
        if tasks_done >= threshold:
            return tier
    return "nano"


def score_summary(con: sqlite3.Connection, node_id: str | None = None) -> dict[str, Any]:
    """Return a reputation summary for the local node."""
    row = con.execute("SELECT * FROM node_stats WHERE id=1").fetchone()
    if not row:
        return {}
    stats = dict(row)
    tasks = stats.get("total_tasks", 0)
    tier = compute_tier(tasks)

    uptime_s = int(time.time() - (stats.get("uptime_start") or time.time()))
    h, rem = divmod(uptime_s, 3600)
    m = rem // 60

    # Reputation score: starts at 100, +2 per task
    rep_score = min(1000.0, 100.0 + tasks * 2.0)

    return {
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "tier_hardware": TIER_HARDWARE[tier],
        "iq_multiplier": TIER_MULTIPLIERS[tier],
        "reputation_score": round(rep_score, 2),
        "tasks_done": tasks,
        "total_tokens": stats.get("total_tokens", 0),
        "iq_earned": round(stats.get("iq_earned", 0.0), 6),
        "uptime": f"{h}h {m}m",
        "uptime_seconds": uptime_s,
    }


def next_tier_info(current_tier: str, tasks_done: int) -> dict[str, Any]:
    """How many tasks until the next tier."""
    tier_order = ["nano", "micro", "standard", "pro", "enterprise"]
    idx = tier_order.index(current_tier)
    if idx == len(tier_order) - 1:
        return {"next_tier": None, "tasks_needed": 0}
    next_t = tier_order[idx + 1]
    threshold = dict(reversed(TIER_THRESHOLDS))[next_t]
    return {
        "next_tier": next_t,
        "next_tier_label": TIER_LABELS[next_t],
        "tasks_needed": max(0, threshold - tasks_done),
        "progress_pct": min(100, int(tasks_done / threshold * 100)) if threshold else 100,
    }
