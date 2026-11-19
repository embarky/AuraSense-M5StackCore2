"""
security.py — Request authentication, rate limiting and client-IP helpers.
"AuraSense: See the air you breathe."

Authentication
--------------
Every endpoint except ``GET /health`` requires the shared secret configured as
``AURASENSE_API_KEY`` (environment variable) or ``api_key`` (config.json).
Clients send it in the ``X-API-Key`` header. If no key is configured the
backend runs in *open dev mode* and logs a warning at startup — never deploy
it that way on a public IP.

Rate limiting
-------------
A small in-process sliding-window limiter protects the endpoints that call
paid LLM / TTS APIs. It is per client IP and per route. Because the backend
runs as a single gunicorn worker (see Dockerfile), in-process state is shared
by every request.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import threading
import time
from collections import defaultdict, deque
from functools import wraps
from typing import Callable, Optional

from flask import current_app, jsonify, request

log = logging.getLogger(__name__)


# ── Client IP ─────────────────────────────────────────────────────────────────

def get_public_client_ip() -> Optional[str]:
    """
    Return the caller's public IP address, or ``None`` if it is private.

    Takes the first hop of ``X-Forwarded-For`` when behind a reverse proxy.
    Private, loopback and link-local addresses (e.g. the Docker bridge network)
    are discarded so that geolocation falls back to the configured city.
    """
    raw = request.headers.get("X-Forwarded-For", request.remote_addr) or ""
    candidate = raw.split(",")[0].strip()
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return None
    return str(ip)


def get_device_id() -> str:
    """Identify the calling device (used to keep per-device conversation history)."""
    device_id = (request.headers.get("X-Device-Id") or "default").strip()
    return device_id[:64] or "default"


# ── API key ───────────────────────────────────────────────────────────────────

def require_api_key(view: Callable) -> Callable:
    """Reject the request with 401 unless it carries the configured API key."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        expected = current_app.config.get("API_KEY") or ""
        if expected:
            provided = request.headers.get("X-API-Key", "")
            if not hmac.compare_digest(provided.encode(), expected.encode()):
                log.warning("Rejected unauthenticated request to %s", request.path)
                return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)

    return wrapper


# ── Rate limiting ─────────────────────────────────────────────────────────────

class RateLimiter:
    """Thread-safe sliding-window limiter keyed by (client, route)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: tuple[str, str], limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window_s:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limit(limit: int, per_seconds: float = 60.0) -> Callable:
    """Allow at most ``limit`` calls per ``per_seconds`` per client and route."""

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args, **kwargs):
            client = request.remote_addr or "unknown"
            if not limiter.allow((client, request.path), limit, per_seconds):
                log.warning("Rate limit hit on %s by %s", request.path, client)
                return jsonify({"error": "rate limit exceeded"}), 429
            return view(*args, **kwargs)

        return wrapper

    return decorator
