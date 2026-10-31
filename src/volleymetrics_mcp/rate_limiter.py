"""Async Token Bucket Rate Limiter and Retry Handler for Volleymetrics MCP.

Defends against aggressive LLM tool loops that could trigger Volleymetrics
rate limits or CloudFront/Envoy WAF security blocks. Enforces a maximum request rate
(default: 2 requests/second) and jittered exponential backoff on HTTP 429/5xx.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Awaitable, Callable, Optional, TypeVar
import httpx

T = TypeVar("T")


class AsyncTokenBucket:
    """Thread-safe and asyncio-safe token bucket rate limiter.
    
    Attributes:
        rate: Maximum number of requests allowed per second.
        capacity: Maximum burst capacity of the token bucket.
    """

    def __init__(self, rate: float = 2.0, capacity: float = 2.0) -> None:
        self.rate = max(0.1, float(rate))
        self.capacity = max(1.0, float(capacity))
        self._tokens = self.capacity
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available to perform an HTTP request."""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_update
                self._last_update = now

                # Add new tokens generated over elapsed time
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                # Calculate sleep duration needed for at least 1 token
                deficit = 1.0 - self._tokens
                sleep_time = deficit / self.rate
                await asyncio.sleep(sleep_time)


# Global default rate limiter: 2 requests/second
DEFAULT_RATE_LIMITER = AsyncTokenBucket(rate=2.0, capacity=2.0)


async def execute_with_retry(
    func: Callable[[], Awaitable[httpx.Response]],
    max_retries: int = 3,
    base_backoff: float = 1.0,
    max_backoff: float = 10.0,
    rate_limiter: Optional[AsyncTokenBucket] = None,
) -> httpx.Response:
    """Execute an async HTTP request function with rate limiting and exponential backoff retry.
    
    Retries on:
    - HTTP 429 (Too Many Requests / Rate Limit Exceeded)
    - HTTP 500, 502, 503, 504 (Server Errors)
    - Transient network errors (httpx.ConnectError, httpx.ReadTimeout)
    
    Args:
        func: Async zero-argument callable returning an httpx.Response.
        max_retries: Maximum number of retry attempts (default: 3).
        base_backoff: Initial backoff duration in seconds (default: 1.0).
        max_backoff: Maximum backoff cap in seconds (default: 10.0).
        rate_limiter: Optional AsyncTokenBucket instance (defaults to DEFAULT_RATE_LIMITER).
        
    Returns:
        The successful or final httpx.Response.
        
    Raises:
        httpx.RequestError: If retries are exhausted on network errors.
    """
    limiter = rate_limiter or DEFAULT_RATE_LIMITER
    attempt = 0

    while True:
        await limiter.acquire()

        try:
            response = await func()

            # Success or client errors that should not be retried (e.g. 400, 401, 403, 404)
            if response.status_code not in (429, 500, 502, 503, 504):
                return response

            # If reached max retries, return final response
            if attempt >= max_retries:
                return response

        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError):
            if attempt >= max_retries:
                raise

        attempt += 1

        # Exponential backoff with full jitter: random uniform between 0 and min(max_backoff, base * 2^attempt)
        backoff_cap = min(max_backoff, base_backoff * (2 ** (attempt - 1)))
        sleep_duration = random.uniform(0.5 * backoff_cap, backoff_cap)
        await asyncio.sleep(sleep_duration)
