"""API key generation and verification.

Keys are shown to the user once at creation and never stored in the clear; the
registry keeps only a SHA-256 hash, so a database leak does not expose usable
credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

KEY_PREFIX = "tir_live_"


def generate_key() -> str:
    """A fresh API key. Returned once to the caller; only its hash is stored."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def key_looks_valid(key: str) -> bool:
    return key.startswith(KEY_PREFIX) and len(key) > len(KEY_PREFIX) + 20


def admin_token_ok(presented: str, configured: str) -> bool:
    """Constant-time admin token check. A blank configured token means the admin
    API is disabled (no token can ever match)."""
    if not configured or not presented:
        return False
    return hmac.compare_digest(presented, configured)
