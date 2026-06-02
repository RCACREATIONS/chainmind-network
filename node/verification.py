"""PoUI — Proof of Useful Intelligence verification engine.

Layer 1: Deterministic task auto-verification (math, code, factual lookups).
Layer 2: Consensus ranking across multiple peer responses.
"""

from __future__ import annotations

import ast
import math
import re
import sqlite3
import time
from typing import Any


# ── Layer 1 — Deterministic Verification ──────────────────────────────────────

def detect_task_type(prompt: str) -> str:
    """Classify a prompt as 'math', 'code', 'factual', or 'open'."""
    p = prompt.lower().strip()
    if re.search(r"[\d\s\+\-\*\/\^\(\)]+[=\?]", p):
        return "math"
    if any(k in p for k in ("write a", "code", "function", "def ", "class ", "script", "program")):
        return "code"
    if any(k in p for k in ("what is", "who is", "when was", "where is", "how many", "capital of")):
        return "factual"
    return "open"


def verify_math(prompt: str, result: str) -> dict[str, Any]:
    """Try to verify a math answer deterministically."""
    # Extract numbers from prompt
    numbers = re.findall(r"-?\d+\.?\d*", prompt)
    operators = re.findall(r"[\+\-\*\/\^]", prompt)
    result_nums = re.findall(r"-?\d+\.?\d*", result)

    if not numbers or not result_nums:
        return {"verified": False, "method": "math", "confidence": 0.0, "reason": "Could not parse"}

    # Simple expression evaluation attempt
    try:
        # Build expression from detected numbers and operators
        expr = prompt
        for pattern in [r"[a-zA-Z\?\.\,\!]", r"\s+"]:
            expr = re.sub(pattern, " ", expr)
        expr = expr.strip()
        # Safety: only allow math characters
        if re.fullmatch(r"[\d\s\+\-\*\/\.\(\)\^]+", expr):
            expr = expr.replace("^", "**")
            expected = eval(expr, {"__builtins__": {}})  # noqa: S307
            answer = float(result_nums[0])
            correct = abs(expected - answer) < 0.01
            return {
                "verified": True, "passed": correct,
                "method": "math", "confidence": 1.0 if correct else 0.0,
                "expected": str(expected), "got": str(answer),
            }
    except Exception:
        pass

    return {"verified": False, "method": "math", "confidence": 0.5, "reason": "Expression too complex"}


def verify_code(prompt: str, result: str) -> dict[str, Any]:
    """Check if a code response is syntactically valid Python."""
    # Extract code blocks
    code_blocks = re.findall(r"```(?:python)?\n?([\s\S]*?)```", result)
    code = code_blocks[0] if code_blocks else result

    try:
        ast.parse(code)
        return {"verified": True, "passed": True, "method": "code", "confidence": 0.7,
                "reason": "Valid Python syntax"}
    except SyntaxError as e:
        return {"verified": True, "passed": False, "method": "code", "confidence": 0.3,
                "reason": f"Syntax error: {e}"}


def verify_response(prompt: str, result: str) -> dict[str, Any]:
    """Run Layer 1 verification on a task response."""
    task_type = detect_task_type(prompt)

    if task_type == "math":
        v = verify_math(prompt, result)
    elif task_type == "code":
        v = verify_code(prompt, result)
    else:
        # Open tasks — can't auto-verify, pass to consensus
        return {
            "verified": False, "task_type": "open",
            "method": "none", "confidence": 0.5,
            "reason": "Open task — requires consensus ranking",
        }

    v["task_type"] = task_type
    return v


# ── Layer 2 — Consensus Ranking ───────────────────────────────────────────────

def similarity_score(text_a: str, text_b: str) -> float:
    """Simple token overlap similarity (0.0–1.0) — no heavy dependencies."""
    if not text_a or not text_b:
        return 0.0
    tokens_a = set(text_a.lower().split())
    tokens_b = set(text_b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)  # Jaccard similarity


def consensus_rank(responses: list[dict]) -> dict[str, Any]:
    """
    Given N peer responses, rank them by consensus similarity.
    Returns the winner and reputation deltas for each peer.
    """
    if not responses:
        return {"winner": None, "scores": [], "deltas": {}}

    texts = [r.get("result", "") for r in responses]
    n = len(texts)

    # Compute pairwise similarity for each response vs all others
    scores = []
    for i, text in enumerate(texts):
        total_sim = sum(
            similarity_score(text, texts[j]) for j in range(n) if j != i
        )
        avg_sim = total_sim / max(n - 1, 1)
        scores.append({"index": i, "peer_id": responses[i].get("peer_id"), "score": avg_sim})

    scores.sort(key=lambda x: x["score"], reverse=True)

    # Winner is the response most similar to all others (consensus center)
    winner_idx = scores[0]["index"]
    winner = responses[winner_idx]

    # Reputation deltas: agree with consensus = +1, outlier = -2
    deltas: dict = {}
    median_score = scores[len(scores) // 2]["score"] if scores else 0.5
    for s in scores:
        peer_id = s["peer_id"]
        if not peer_id:
            continue
        if s["score"] >= median_score:
            deltas[peer_id] = +1.0
        else:
            deltas[peer_id] = -2.0

    return {
        "winner": winner,
        "winner_text": winner.get("result", ""),
        "scores": scores,
        "deltas": deltas,
        "method": "consensus",
    }


# ── Layer 3 — Spot Check (flagging) ───────────────────────────────────────────

def should_spot_check(task_id: str) -> bool:
    """Probabilistic: 0.1% of tasks flagged for human review."""
    import hashlib
    digest = hashlib.sha256(task_id.encode()).hexdigest()
    value = int(digest[:4], 16) / 0xFFFF
    return value < 0.001  # 0.1%


def record_verification(con: sqlite3.Connection, task_id: str, result: dict):
    """Store verification result in DB."""
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS verifications (
                task_id     TEXT PRIMARY KEY,
                method      TEXT,
                passed      INTEGER,
                confidence  REAL,
                reason      TEXT,
                spot_check  INTEGER DEFAULT 0,
                ts          REAL
            )
        """)
        con.execute(
            "INSERT OR REPLACE INTO verifications VALUES (?,?,?,?,?,?,?)",
            (
                task_id,
                result.get("method", "none"),
                1 if result.get("passed") else 0,
                result.get("confidence", 0.5),
                result.get("reason", ""),
                1 if should_spot_check(task_id) else 0,
                time.time(),
            ),
        )
        con.commit()
    except Exception:
        pass
