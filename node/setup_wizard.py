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

REGISTER_URL = "https://chainmind.com.ng/api/node/register.php"
PAIR_URL     = "https://chainmind.com.ng/api/node/pair.php"

# Full default config — always written so ALL keys exist after first run.
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
        "encryption_key": "",
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


def _prompt_password(msg: str) -> str:
    """Prompt for a password, hiding input if possible."""
    try:
        import getpass
        return getpass.getpass(f"{msg}: ").strip()
    except Exception:
        return input(f"{msg}: ").strip()


def _get_local_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "my-chainmind-node"


def _generate_encryption_key() -> str:
    """Generate a Fernet-compatible encryption key locally."""
    try:
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()
    except ImportError:
        import base64
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def activate_node_with_token(token: str) -> dict:
    """
    Pair this node with a ChainMind web account using a short-lived pairing token.
    The token is generated on chainmind.com.ng/dashboard/node-settings.php.

    Returns dict with keys: node_secret, node_id, username
    Raises ValueError on bad/expired token, ConnectionError on network failure.
    """
    try:
        import httpx
        resp = httpx.post(
            PAIR_URL,
            json={"token": token.strip()},
            timeout=15,
            follow_redirects=True,
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            return data
        raise ValueError(data.get("error", f"Server returned {resp.status_code}"))
    except ValueError:
        raise
    except Exception as exc:
        raise ConnectionError(f"Could not reach {PAIR_URL}: {exc}") from exc


def activate_node(email: str, password: str, node_name: str = "") -> Optional[dict]:
    """
    Call the ChainMind central server to register / re-activate this node.

    Returns dict with keys: node_secret, node_id, username
    Returns None on failure (network error, wrong credentials, server down).
    """
    try:
        import httpx
        payload: dict = {"email": email, "password": password}
        if node_name:
            payload["node_name"] = node_name
        resp = httpx.post(
            REGISTER_URL,
            json=payload,
            timeout=15,
            follow_redirects=True,
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            return data
        raise ValueError(data.get("error", f"Server returned {resp.status_code}"))
    except ValueError:
        raise
    except Exception as exc:
        raise ConnectionError(f"Could not reach {REGISTER_URL}: {exc}") from exc


def run_wizard(cfg: dict) -> dict:
    """Run the interactive setup wizard and return the updated config dict."""

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   ChainMind Node — First-Run Setup Wizard    ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("This wizard configures your node. You can edit config.yaml later.")
    print()

    node_cfg    = cfg.setdefault("node", {})
    central_cfg = cfg.setdefault("central", {})
    privacy_cfg = cfg.setdefault("privacy", {})

    # ── 1. Node name ─────────────────────────────────────────
    default_name = node_cfg.get("name", "") or f"{_get_local_hostname()}-node"
    print("1/4  Node Name")
    print("     This is shown in the network directory and your web dashboard.")
    node_name = _prompt("     Node name", default=default_name)
    node_cfg["name"] = node_name
    print()

    # ── 2. Node port ─────────────────────────────────────────
    print("2/4  API Port")
    print("     The port this node listens on (default 8000).")
    port_str = _prompt("     Port", default=str(node_cfg.get("port", 8000)))
    try:
        node_cfg["port"] = int(port_str)
    except ValueError:
        node_cfg["port"] = 8000
    print()

    # ── 3. Public URL ────────────────────────────────────────
    print("3/4  Public URL  (optional)")
    print("     If this node is accessible from the internet, enter its public URL.")
    print("     Leave blank to let the node auto-detect your public IP.")
    pub_url = _prompt("     Public URL (e.g. http://203.0.113.1:8000)", required=False)
    node_cfg["public_url"] = pub_url
    print()

    # ── 4. Connect to ChainMind Network ─────────────────────
    print("4/4  Connect to ChainMind Network")
    print("     Log in to chainmind.com.ng to register your node and get")
    print("     a node secret.  Your password is never stored on this machine.")
    print()

    already_activated = bool(central_cfg.get("node_secret", "").strip())
    if already_activated:
        print("     ✅  This node is already connected to the network.")
        reactivate = _prompt_yn("     Re-activate (re-link to your account)?", default=False)
        if not reactivate:
            print()
            _finalize_local_secrets(node_cfg, privacy_cfg)
            return _print_summary(cfg)

    # Try automatic login (up to 3 attempts)
    for attempt in range(1, 4):
        print(f"     ChainMind account login{' (attempt ' + str(attempt) + '/3)' if attempt > 1 else ''}:")
        email    = _prompt("     Email")
        password = _prompt_password("     Password")
        print()
        print("     Connecting to chainmind.com.ng…")
        try:
            result = activate_node(email, password, node_name=node_cfg.get("name", ""))
            # Write node_secret received from server
            central_cfg["enabled"]     = True
            central_cfg["url"]         = "https://chainmind.com.ng"
            central_cfg["node_secret"] = result["node_secret"]
            # Write node_id to data/ for gossip protocol
            _write_node_id(result["node_id"])
            # Generate local-only secrets
            _finalize_local_secrets(node_cfg, privacy_cfg)
            print(f"     ✅  Connected!  Welcome, {result['username']}.")
            print(f"     Node ID: {result['node_id'][:8]}…")
            print()
            break
        except ValueError as e:
            print(f"     ❌  {e}")
            if attempt == 3:
                print()
                print("     Too many failed attempts. Skipping — you can reconnect later")
                print("     from Settings → Reconnect Account in the dashboard.")
                central_cfg["enabled"] = False
                _finalize_local_secrets(node_cfg, privacy_cfg)
            else:
                print()
        except ConnectionError as e:
            print(f"     ⚠   {e}")
            print("     Cannot reach chainmind.com.ng — check your internet connection.")
            print("     You can reconnect later from Settings → Reconnect Account in the dashboard.")
            central_cfg["enabled"] = False
            _finalize_local_secrets(node_cfg, privacy_cfg)
            break

    return _print_summary(cfg)


def _finalize_local_secrets(node_cfg: dict, privacy_cfg: dict) -> None:
    """Generate / refresh local-only secrets (api_token, encryption_key)."""
    # API token: generated locally, never leaves this machine
    if not node_cfg.get("api_token", "").strip():
        node_cfg["api_token"] = secrets.token_hex(24)

    # Encryption key: generated locally, never sent anywhere
    if not privacy_cfg.get("encryption_key", "").strip():
        privacy_cfg["encryption_key"] = _generate_encryption_key()
        privacy_cfg["encrypt_tasks"]  = True


def _write_node_id(node_id: str) -> None:
    """Persist the server-assigned node_id to data/node_id.txt."""
    try:
        data_dir = _cfg_path.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "node_id.txt").write_text(node_id)
    except Exception:
        pass  # non-fatal; node will generate one if missing


def _fallback_manual_secret(central_cfg: dict) -> None:
    """Ask the user to manually paste a node_secret from the web dashboard."""
    print("     Manual activation:")
    print("     1. Open https://chainmind.com.ng/dashboard/node-settings.php")
    print("     2. Copy the NODE_SECRET shown there.")
    secret = _prompt("     Paste NODE_SECRET here (or press Enter to skip)", required=False)
    central_cfg["node_secret"] = secret
    central_cfg["enabled"]     = bool(secret)
    if not secret:
        print("     Skipped — you can activate later from the Settings page.")


def _print_summary(cfg: dict) -> dict:
    node_cfg    = cfg.get("node", {})
    central_cfg = cfg.get("central", {})
    connected   = central_cfg.get("enabled") and bool(central_cfg.get("node_secret", ""))
    print("═══════════════════════════════════════════════")
    print(f"  Node Name : {node_cfg.get('name', '—')}")
    print(f"  API Port  : {node_cfg.get('port', 8000)}")
    print(f"  Public URL: {node_cfg.get('public_url') or '(auto-detect)'}")
    print(f"  Network   : {'✅ Connected' if connected else '❌ Not connected'}")
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

    cfg = _deep_merge(_DEFAULT_CONFIG, saved)

    node_name  = cfg.get("node", {}).get("name", "")
    needs_setup = (
        not node_name
        or node_name in ("chainmind-node-1", "my-chainmind-node")
    )

    if os.environ.get("CHAINMIND_SETUP") == "1":
        needs_setup = True

    if os.environ.get("CHAINMIND_NO_SETUP") == "1" and _cfg_path.exists():
        needs_setup = False

    if needs_setup:
        cfg = run_wizard(cfg)
        with open(_cfg_path, "w") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return cfg


if __name__ == "__main__":
    maybe_run_wizard()
