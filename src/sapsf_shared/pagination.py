"""Trusted-origin URL policy for credentialed OData pagination."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from sapsf_shared.exceptions import SFClientError


def _effective_port(parsed) -> int | None:
    if parsed.port is not None:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None


def trusted_pagination_url(base_url: str, candidate: str, current_url: str) -> str:
    """Resolve and validate an OData next-link against the configured service origin.

    Credentialed pagination may remain on the same scheme, host, effective port
    and service path only. Userinfo and fragments are always rejected.
    """
    if not isinstance(candidate, str) or not candidate.strip():
        raise SFClientError("Invalid OData pagination URL")

    resolved = urljoin(current_url, candidate.strip())
    base = urlparse(base_url)
    parsed = urlparse(resolved)

    if parsed.username or parsed.password or parsed.fragment:
        raise SFClientError("Rejected unsafe OData pagination URL")

    base_origin = (base.scheme.lower(), (base.hostname or "").lower(), _effective_port(base))
    next_origin = (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        _effective_port(parsed),
    )
    if next_origin != base_origin:
        raise SFClientError("Rejected cross-origin OData pagination URL")

    service_path = base.path.rstrip("/")
    if service_path and parsed.path != service_path and not parsed.path.startswith(
        service_path + "/"
    ):
        raise SFClientError("Rejected OData pagination URL outside the configured service path")

    return resolved
