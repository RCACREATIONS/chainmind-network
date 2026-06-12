"""
crypto.py — Symmetric encryption for task prompts and results at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography library.
The key is loaded from config.yaml → privacy.encryption_key.

If no key is configured, data is stored as plain text and a warning is logged.
This keeps the node functional even without encryption configured, but
production deployments should always set a key.

Add to config.yaml:
    privacy:
      encrypt_tasks: true
      encryption_key: "your-fernet-key-here"   # generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
      mask_prompts_in_dashboard: true           # show [encrypted] instead of prompt text in UI
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("crypto")

_fernet = None
_enabled = False


def init_crypto(cfg: dict) -> None:
    """Call once at startup with the full config dict."""
    global _fernet, _enabled

    privacy = cfg.get("privacy", {})
    if not privacy.get("encrypt_tasks", False):
        log.info("Task encryption disabled (privacy.encrypt_tasks = false)")
        return

    key = privacy.get("encryption_key", "").strip()
    if not key:
        log.warning(
            "privacy.encrypt_tasks is true but no encryption_key set — "
            "tasks will be stored as plain text. "
            "Generate a key with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
        return

    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(key.encode())
        _enabled = True
        log.info("Task encryption enabled (AES-128-CBC via Fernet)")
    except Exception as e:
        log.error(f"Failed to initialize encryption: {e} — falling back to plain text")


def encrypt(text: str) -> str:
    """Encrypt a string. Returns the encrypted value (still a string, base64-encoded).
    If encryption is not enabled, returns the original text unchanged."""
    if not _enabled or not _fernet or not text:
        return text
    try:
        return _fernet.encrypt(text.encode()).decode()
    except Exception as e:
        log.error(f"Encryption failed: {e}")
        return text


def decrypt(text: str) -> str:
    """Decrypt a string. Returns the original plaintext.
    If encryption is not enabled or the text is not encrypted, returns as-is."""
    if not _enabled or not _fernet or not text:
        return text
    try:
        return _fernet.decrypt(text.encode()).decode()
    except Exception:
        # Not encrypted (legacy data or plain text) — return as-is
        return text


def is_enabled() -> bool:
    return _enabled


def mask_prompt(prompt: str, max_chars: int = 0) -> str:
    """Return a privacy-safe version of a prompt for display in dashboards/logs.
    Shows only token count, not content."""
    if not prompt:
        return ""
    word_count = len(prompt.split())
    char_count = len(prompt)
    return f"[encrypted · ~{word_count} words · {char_count} chars]"
