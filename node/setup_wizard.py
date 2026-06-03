"""
setup_wizard.py — ChainMind first-run configuration wizard.
Called automatically by start.sh / start.bat if config.yaml is missing
key node settings (name, api_token etc).
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
from pathlib import Path
from typing import Optional

import yaml

# ── Config path — works both frozen (PyInstaller) and plain Python ──────────
if os.environ.get("CHAINMIND_CONFIG"):
    _cfg_path = Path(os.environ["CHAINMIND_CONFIG"])
elif getattr(sys, "frozen", False):
    _cfg_path = Path(sys.executable).parent / "config.yaml"
else:
    _cfg_path = Path(__file__).parent.parent / "config.yaml"

# Full default config — always written so ALL keys exist after first run.
# Users edit config.yaml; the wizard only overrides what it asks about.
_DEFAULT_CONFIG: dict = {
    "node": {
        "name": "chainmind-node-1",
        "host": "0.0.0.0",
        "port": 8000,
        "api_token": "",
        "public_url": "",
    },
    "network": {
        "heartbeat_interval": 30,
        "discovery_interval": 60,
        "max_peers": 50,
        "bootstrap_peers": [],
    },
    "ollama": {
        "host": "http://localhost",
        "port": 11434,
    },
    "dashboard": {
        "port": 8501,
    },
    "database": {
        "path": "data/node.db",
    },
    "tokens": {
        "base_rate": 0.001,
        "tier_multipliers": {
            "nano": 1,
            "micro": 3,
            "standard": 8,
            "pro": 20,
            "enterprise": 50,
        },
    },
    "central": {
        "enabled": True,
        "url": "https://chainmind.com.ng",
        "node_secret": "",
        "poll_interval": 3,
        "heartbeat_interval": 30,
    },
    "privacy": {
        "encrypt_tasks": True,
        "mask_prompts_in_dashboard": True,
    },
    "models": {
        "tiny": [
            {"name": "qwen2:0.5b",  "label": "Qwen2 0.5B — Fastest, any machine", "ram_gb": 1.0, "disk_gb": 0.4},
            {"name": "tinyllama",   "label": "TinyLlama 1.1B — Good for low-RAM",   "ram_gb": 2.0, "disk_gb": 0.6},
            {"name": "phi3:mini",   "label": "Phi-3 Mini 3.8B — Best tiny quality", "ram_gb": 4.0, "disk_gb": 2.3},
        ],
        "small": [
            {"name": "llama3.2:1b", "label": "Llama3.2 1B — Very fast",                  "ram_gb": 2.0, "disk_gb": 1.3},
            {"name": "llama3.2:3b", "label": "Llama3.2 3B — Recommended for 8GB RAM",    "ram_gb": 4.0, "disk_gb": 2.0},
            {"name": "gemma2:2b",   "label": "Gemma2 2B — Google's small model",          "ram_gb": 4.0, "disk_gb": 1.6},
        ],
        "medium": [
            {"name": "mistral",      "label": "Mistral 7B — Best balance",                   "ram_gb": 8.0,  "disk_gb": 4.1},
            {"name": "llama3.1:8b",  "label": "Llama3.1 8B — Recommended for 16GB RAM",      "ram_gb": 10.0, "disk_gb": 4.7},
            {"name": "gemma2:9b",    "label": "Gemma2 9B — Google's medium model",            "ram_gb": 12.0, "disk_gb": 5.4},
        ],
        "large": [
            {"name": "llama3.1:70b", "label": "Llama3.1 70B — Server-grade only",   "ram_gb": 48.0, "disk_gb": 40.0},
            {"name": "mixtral:8x7b", "label": "Mixtral 8x7B — Expert mixture",       "ram_gb": 32.0, "disk_gb": 26.0},
            {"name": "qwen2:72b",    "label": "Qwen2 72B — Maximum quality",          "ram_gb": 48.0, "disk_gb": 41.0},
        ],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively. Base keys not in override are kept."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _prompt(msg: str, default: str = "", required: bool = True) -> str:
    """Prompt the user; return default on empty input."""
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"{msg}{suffix}: ").strip()
        if val:
            return val
        if default:
            return default
        if not required:
            return ""
        print("  ⚠  This field is required.")


def _prompt_yn(msg: str, default: bool = True) -> bool:
    yn = "Y/n" if default else "y/N"
    val = input(f"{msg} [{yn}]: ").strip().lower()
    if not val:
        return default
    return val.startswith("y")


def _get_local_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "my-chainmind-node"


def run_wizard(cfg: dict) -> dict:
    """Run the interactive setup wizard and return the updated config dict."""

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   ChainMind Node — First-Run Setup Wizard    ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("This wizard configures your node. You can edit config.yaml later.")
    print()

    node_cfg = cfg.setdefault("node", {})
    central_cfg = cfg.setdefault("central", {})

    # ── Node name ────────────────────────────────────────────
    default_name = node_cfg.get("name", "") or f"{_get_local_hostname()}-node"
    print("1/5  Node Name")
    print("     This is shown in the network directory and your web dashboard.")
    node_name = _prompt("     Node name", default=default_name)
    node_cfg["name"] = node_name
    print()

    # ── Node port ─────────────────────────────────────────────
    print("2/5  API Port")
    print("     The port this node listens on (default 8000).")
    port_str = _prompt("     Port", default=str(node_cfg.get("port", 8000)))
    try:
        node_cfg["port"] = int(port_str)
    except ValueError:
        node_cfg["port"] = 8000
    print()

    # ── Public URL ────────────────────────────────────────────
    print("3/5  Public URL  (optional)")
    print("     If this node is accessible from the internet, enter its public URL.")
    print("     Leave blank to let the node auto-detect your public IP.")
    pub_url = _prompt("     Public URL (e.g. http://203.0.113.1:8000)", required=False)
    node_cfg["public_url"] = pub_url
    print()

    # ── API token ─────────────────────────────────────────────
    print("4/5  Node API Token")
    existing_token = node_cfg.get("api_token", "")
    if existing_token:
        print(f"     An API token already exists: {existing_token[:12]}…")
        regen = _prompt_yn("     Regenerate it?", default=False)
        if regen:
            node_cfg["api_token"] = secrets.token_hex(24)
            print(f"     ✅ New token: {node_cfg['api_token']}")
        else:
            print("     Keeping existing token.")
    else:
        node_cfg["api_token"] = secrets.token_hex(24)
        print(f"     ✅ Generated token: {node_cfg['api_token']}")
    print()

    # ── Central server / web account link ────────────────────
    print("5/5  ChainMind Central Server")
    central_url = central_cfg.get("url", "https://chainmind.com.ng")
    print(f"     Central server: {central_url}")
    enabled = _prompt_yn("     Connect to central server (recommended)?", default=True)
    central_cfg["enabled"] = enabled
    central_cfg["url"] = central_url

    if enabled:
        secret = central_cfg.get("node_secret", "")
        if not secret:
            print()
            print("     ⚠  You need a node_secret from the central server.")
            print("     Find it in your ChainMind web account → Node Settings → copy the NODE_SECRET.")
            secret = _prompt("     node_secret (from config.php on the central server)", required=False)
            central_cfg["node_secret"] = secret
        else:
            print(f"     node_secret: {'•' * 12} (already set)")

        # Optionally link to web account now
        print()
        link_now = _prompt_yn("     Link this node to your web account now?", default=True)
        if link_now:
            print()
            print("     Steps:")
            print("     1. Open https://chainmind.com.ng/dashboard/node-settings.php")
            print("     2. Copy the 10-minute pairing token shown on that page.")
            link_token = _prompt("     Paste pairing token here (or press Enter to skip)", required=False)
            if link_token:
                # Store the pending token — central_client will send it on first heartbeat
                cfg.setdefault("_pending_link_token", link_token)
                print("     ✅ Token saved — your node will link automatically on first start.")
            else:
                print("     Skipped. You can link later from Node Settings → Link Web Account.")
    print()

    # ── Summary ───────────────────────────────────────────────
    print("═══════════════════════════════════════════════")
    print(f"  Node Name : {node_cfg['name']}")
    print(f"  API Port  : {node_cfg['port']}")
    print(f"  Public URL: {node_cfg.get('public_url') or '(auto-detect)'}")
    print(f"  Central   : {'✅ Enabled' if enabled else '❌ Disabled'}")
    print("═══════════════════════════════════════════════")
    print()
    print("Config saved to config.yaml. Starting node…")
    print()

    return cfg


def maybe_run_wizard() -> dict:
    """Load config.yaml; run wizard if node.name is the generic default or missing."""
    if _cfg_path.exists():
        with open(_cfg_path) as f:
            saved = yaml.safe_load(f) or {}
    else:
        saved = {}

    # Always deep-merge with defaults so new config keys are present even on
    # existing installs that were created by an older wizard version.
    cfg = _deep_merge(_DEFAULT_CONFIG, saved)

    node_name = cfg.get("node", {}).get("name", "")
    needs_setup = (
        not node_name
        or node_name in ("chainmind-node-1", "my-chainmind-node")
    )

    # Force wizard with env var (used by install scripts)
    if os.environ.get("CHAINMIND_SETUP") == "1":
        needs_setup = True

    if needs_setup:
        cfg = run_wizard(cfg)
        # Save updated config
        with open(_cfg_path, "w") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return cfg


if __name__ == "__main__":
    maybe_run_wizard()
