"""Local Persistent Caching for Volleymetrics MCP using diskcache & platformdirs.

Caches historical match play-by-play, box scores, and DVW exports for 7+ days (expire=604800)
and live/season schedule and team endpoints for 15 minutes (expire=900) to protect
user accounts and minimize redundant requests across LLM tool loops.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional
import diskcache
import platformdirs

logger = logging.getLogger(__name__)

# TTL Policies in Seconds
TTL_HISTORICAL_MATCH: int = 604800  # 7 Days
TTL_SCHEDULE_TEAM: int = 900        # 15 Minutes


def get_cache_directory() -> Path:
    """Determine the optimal cache directory respecting OS conventions and sandbox constraints."""
    custom_dir = os.getenv("VOLLEYMETRICS_CACHE_DIR")
    if custom_dir:
        p = Path(custom_dir).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    # Standard OS user cache directory
    try:
        user_cache = Path(platformdirs.user_cache_dir("volleymetrics-mcp")) / "cache"
        user_cache.mkdir(parents=True, exist_ok=True)
        return user_cache
    except (PermissionError, OSError):
        # Fallback to project root .cache for sandboxed or containerized environments
        project_cache = Path(__file__).resolve().parents[2] / ".cache" / "volleymetrics_mcp"
        project_cache.mkdir(parents=True, exist_ok=True)
        return project_cache


_CACHE_INSTANCE: Optional[diskcache.Cache] = None


def get_cache() -> diskcache.Cache:
    """Retrieve or initialize the global diskcache.Cache singleton instance."""
    global _CACHE_INSTANCE
    if _CACHE_INSTANCE is None:
        cache_dir = get_cache_directory()
        _CACHE_INSTANCE = diskcache.Cache(str(cache_dir))
    return _CACHE_INSTANCE


def compute_cache_key(prefix: str, payload: Any) -> str:
    """Generate a deterministic SHA-256 cache key for an endpoint and its parameters."""
    if isinstance(payload, (dict, list)):
        payload_str = json.dumps(payload, sort_keys=True, default=str)
    else:
        payload_str = str(payload)

    hashed = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{hashed}"


def get_cached_response(key: str) -> Optional[Any]:
    """Retrieve an item from the persistent cache if still valid."""
    try:
        cache = get_cache()
        return cache.get(key)
    except Exception as exc:
        logger.debug(f"Cache get failed for key '{key}': {exc}")
        return None


def set_cached_response(key: str, value: Any, expire: int = TTL_HISTORICAL_MATCH) -> None:
    """Store an item in the persistent cache with a specified expiration (TTL in seconds)."""
    try:
        cache = get_cache()
        cache.set(key, value, expire=expire)
    except Exception as exc:
        logger.debug(f"Cache set failed for key '{key}': {exc}")


def clear_all_cache() -> None:
    """Clear all cached entries."""
    global _CACHE_INSTANCE
    try:
        if _CACHE_INSTANCE is not None:
            _CACHE_INSTANCE.clear()
        else:
            cache = get_cache()
            cache.clear()
    except Exception as exc:
        logger.debug(f"Cache clear failed: {exc}")
