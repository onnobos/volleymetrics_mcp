"""Secure credential storage and read-only policy enforcement for Volleymetrics MCP.

Stores Volleymetrics session tokens in the OS-native secure credential store
(macOS Keychain, Linux SecretService, Windows Credential Manager) and enforces
strict read-only data access to prevent accidental mutations.
"""

from __future__ import annotations

import logging
from typing import Optional
import keyring
from keyring.errors import KeyringError

logger = logging.getLogger(__name__)

SERVICE_NAME = "volleymetrics-mcp"
KEY_TOKEN = "session_token"
KEY_TEAM_ID = "active_team_id"


class VolleymetricsSecurityError(Exception):
    """Raised when an operation violates the strict read-only security policy."""


def assert_read_only(method: str, path: str) -> None:
    """Enforce strict read-only policy.
    
    Permits GET requests universally.
    Permits POST exclusively for read-like query payloads (e.g., matchStats query,
    report requests, DVW generation, or OAuth token exchange).
    Blocks PUT, DELETE, and PATCH unconditionally.
    """
    m = method.upper().strip()
    if m == "GET" or m == "HEAD" or m == "OPTIONS":
        return

    # Authorized read-like query or token endpoints
    allowed_post_prefixes = [
        "oauth/token",
        "/acct/oauth/token",
        "matchStats",
        "/stats/matchStats",
        "dvws/generate",
        "/dvw/dvws/generate",
        "logging/reports/request",
    ]

    clean_path = path.lower()
    if m == "POST" and any(p.lower() in clean_path for p in allowed_post_prefixes):
        return

    raise VolleymetricsSecurityError(
        f"Read-Only Policy Enforced: Mutating operation {method} on '{path}' is strictly prohibited."
    )


def save_secure_session(token: str, team_id: Optional[str] = None) -> bool:
    """Save session token and optional active team ID to the OS secure keyring.
    
    Args:
        token: The active Bearer JWT token or cookie string.
        team_id: Optional active Volleymetrics team ID.
        
    Returns:
        True if successfully saved to keyring, False otherwise.
    """
    saved = False
    try:
        keyring.set_password(SERVICE_NAME, KEY_TOKEN, token.strip())
        if team_id:
            keyring.set_password(SERVICE_NAME, KEY_TEAM_ID, str(team_id).strip())
        saved = True
    except (KeyringError, Exception) as exc:
        logger.debug(f"Keyring storage unavailable ({exc}), will use file/env fallback.")

    return saved


def get_secure_token() -> Optional[str]:
    """Retrieve the cached Volleymetrics session token from OS keyring."""
    try:
        val = keyring.get_password(SERVICE_NAME, KEY_TOKEN)
        if val and val.strip():
            return val.strip()
    except (KeyringError, Exception) as exc:
        logger.debug(f"Keyring read error: {exc}")
    return None


def get_secure_team_id() -> Optional[str]:
    """Retrieve the cached Volleymetrics team ID from OS keyring."""
    try:
        val = keyring.get_password(SERVICE_NAME, KEY_TEAM_ID)
        if val and val.strip():
            return val.strip()
    except (KeyringError, Exception) as exc:
        logger.debug(f"Keyring read error: {exc}")
    return None


def clear_secure_session() -> bool:
    """Clear credentials stored in OS keyring."""
    cleared = True
    try:
        keyring.delete_password(SERVICE_NAME, KEY_TOKEN)
    except Exception:
        cleared = False
    try:
        keyring.delete_password(SERVICE_NAME, KEY_TEAM_ID)
    except Exception:
        pass
    return cleared
