"""Unit tests for caching, token bucket rate limiting, and exponential retry handling."""

import asyncio
import time
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from volleymetrics_mcp.cache import (
    clear_all_cache,
    compute_cache_key,
    get_cached_response,
    set_cached_response,
)
from volleymetrics_mcp.rate_limiter import AsyncTokenBucket, execute_with_retry


def test_cache_set_and_get():
    """Verify storing and retrieving values from disk cache."""
    key = compute_cache_key("test_box_score", {"match_id": "123", "team": "A"})
    set_cached_response(key, {"kills": 45, "hitting_pct": 0.320}, expire=60)

    val = get_cached_response(key)
    assert val is not None
    assert val["kills"] == 45
    assert val["hitting_pct"] == 0.320

    clear_all_cache()
    assert get_cached_response(key) is None


@pytest.mark.asyncio
async def test_token_bucket_rate_limiter():
    """Verify AsyncTokenBucket throttles excessive burst requests."""
    # 5 requests per second, capacity 2
    limiter = AsyncTokenBucket(rate=5.0, capacity=2.0)

    start = time.monotonic()
    # First 2 requests should be instantaneous (within capacity)
    await limiter.acquire()
    await limiter.acquire()
    burst_elapsed = time.monotonic() - start
    assert burst_elapsed < 0.1

    # Third request must wait for new token (~0.2s)
    await limiter.acquire()
    total_elapsed = time.monotonic() - start
    assert total_elapsed >= 0.15


@pytest.mark.asyncio
async def test_execute_with_retry_on_429():
    """Verify execute_with_retry retries on HTTP 429 and succeeds on subsequent try."""
    call_count = 0

    async def mock_call():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, request=httpx.Request("GET", "https://api.volleymetrics.hudl.com/portal/teams"))
        return httpx.Response(200, json={"status": "ok"}, request=httpx.Request("GET", "https://api.volleymetrics.hudl.com/portal/teams"))

    limiter = AsyncTokenBucket(rate=100.0, capacity=100.0)
    resp = await execute_with_retry(mock_call, max_retries=2, base_backoff=0.01, rate_limiter=limiter)

    assert resp.status_code == 200
    assert call_count == 2
