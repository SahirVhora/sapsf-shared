"""Standalone retry-with-backoff wrapper for plain `requests` calls.

`SFClient` (client.py) already retries on 429/5xx internally, but it's built
around an entity-set-based OData API (`client.get("JobInfo")`), which doesn't
fit every call site -- e.g. a raw `$metadata` XML fetch, or a hand-rolled
pagination loop that predates SFClient. Those call sites still want the same
retry policy without adopting the whole SFClient API.

This module exposes that policy as a plain function so any caller doing
`requests.get(...)` directly can opt in with a one-line change:

    from sapsf_shared.retry import get_with_retry
    resp = get_with_retry(url, headers=headers, auth=auth, timeout=60)

Reuses the exact same constants as SFClient (RETRY_STATUS_CODES, MAX_RETRIES,
BACKOFF_SECONDS) so behavior is consistent across every tool built on this SDK.

Calls reuse a per-thread keep-alive session so paginated pulls do not pay a
new TCP/TLS handshake per page. That session refuses cookies: callers pass
their own credentials per call, and two tenants can share one API host, so a
server session cookie from one caller must never ride along with another.
Callers that manage their own session can pass ``session=``.
"""

from __future__ import annotations

import logging
import threading
import time
from http.cookiejar import DefaultCookiePolicy
from typing import Any

import requests

from sapsf_shared.client import MAX_RETRIES, RETRY_STATUS_CODES, retry_wait_seconds

logger = logging.getLogger(__name__)

_local = threading.local()


def _thread_session() -> requests.Session:
    """Return this thread's cookie-less keep-alive session."""
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        session.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))
        _local.session = session
    return session


def get_with_retry(
    url: str, *, session: requests.Session | None = None, **kwargs: Any
) -> requests.Response:
    """GET *url* with the shared retry-on-429/5xx policy.

    Retries transient failures (429, 500, 502, 503, 504, and network errors)
    up to MAX_RETRIES times with exponential backoff. Non-retryable responses
    (2xx, 4xx other than 429, etc.) are returned immediately so callers can
    keep using `resp.raise_for_status()` as before.

    On final exhaustion of retries against a persistent network error, the
    last exception is re-raised. On final exhaustion against a persistent
    retryable status code, the last (still-bad) response is returned so the
    caller's own error handling (raise_for_status / status checks) applies.
    """
    last_exc: Exception | None = None
    resp: requests.Response | None = None
    # Credentialed calls must never forward auth across redirects. Callers may
    # inspect a 3xx response and decide on an explicitly revalidated URL.
    kwargs["allow_redirects"] = False
    # Bound stalled connections while preserving a caller's explicit timeout.
    timeout = kwargs.pop("timeout", 60)
    http = session or _thread_session()

    for attempt in range(MAX_RETRIES):
        try:
            resp = http.get(url, timeout=timeout, **kwargs)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            wait = retry_wait_seconds(None, attempt)
            logger.warning(
                "Request error on %s (attempt %d/%d): %s - retrying in %ds",
                url,
                attempt + 1,
                MAX_RETRIES,
                exc,
                wait,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
            continue

        if resp.status_code not in RETRY_STATUS_CODES:
            return resp

        last_exc = None
        wait = retry_wait_seconds(resp, attempt)
        logger.warning(
            "HTTP %s from %s (attempt %d/%d) - retrying in %ds",
            resp.status_code,
            url,
            attempt + 1,
            MAX_RETRIES,
            wait,
        )
        if attempt < MAX_RETRIES - 1:
            time.sleep(wait)

    if resp is None and last_exc is not None:
        raise last_exc
    return resp
