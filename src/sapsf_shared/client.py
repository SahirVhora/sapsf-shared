"""OData v2 HTTP client for SAP SuccessFactors.

Features:
  - requests.Session with configurable auth (Basic, OAuth, Certificate)
  - 3 retries with exponential back-off on 429 and 5xx
  - Automatic OData __next pagination
  - Configurable per-request timeout
  - Context-manager support for automatic cleanup
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from sapsf_shared.auth import AuthConfig, build_requests_auth
from sapsf_shared.exceptions import AmbiguousWriteError, SFClientError
from sapsf_shared.utils import odata_escape

logger = logging.getLogger(__name__)

# HTTP status codes that trigger a retry
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_RETRIES = 3
BACKOFF_SECONDS = (1, 2, 4)
RETRYABLE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class SFClient:
    """Thin OData v2 client bound to ONE SuccessFactors tenant.

    Usage:
        config = AuthConfig(base_url="https://api.sapsf.com", username="...", password="...")
        with SFClient(config) as client:
            records = client.get_entity_by_code("FODepartment", "IT")
    """

    def __init__(
        self,
        auth_config: AuthConfig,
        *,
        default_top: int = 100,
        json_indent: int | None = None,
        pool_connections: int = 10,
        pool_maxsize: int = 20,
    ) -> None:
        self.config = auth_config
        raw_url = auth_config.base_url.rstrip("/")
        # Auto-append /odata/v2 if the URL doesn't already include an OData path
        if "/odata" not in raw_url.lower():
            self.base_url = f"{raw_url}/odata/v2"
        else:
            self.base_url = raw_url
        self.default_top = default_top
        self.json_indent = json_indent

        auth_obj, cert = build_requests_auth(auth_config)

        self._session = requests.Session()
        self._session.auth = auth_obj  # type: ignore[assignment]
        if cert:
            self._session.cert = cert
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        # Connection pooling for reuse across requests
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=0,  # we handle retries ourselves
        )
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _url(self, entity_set: str) -> str:
        return f"{self.base_url}/{entity_set}"

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Execute a request, retrying transient failures only for safe methods.

        A failed write response is ambiguous: the server may have committed the
        mutation before the response was lost. Replaying it here could create a
        duplicate, so callers must reconcile target state instead.
        """
        method = method.upper()
        may_retry = method in RETRYABLE_METHODS
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.request(method, url, timeout=self.config.timeout_sec, **kwargs)
                if resp.status_code not in RETRY_STATUS_CODES:
                    return resp
                if not may_retry:
                    raise AmbiguousWriteError(
                        f"{method} outcome is unknown after HTTP {resp.status_code}; "
                        "reconcile target state before retrying",
                        method=method,
                        status_code=resp.status_code,
                        body=resp.text[:2000],
                        url=url,
                    )
                wait = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                logger.warning(
                    "HTTP %s from %s (attempt %d/%d) - retrying in %ds",
                    resp.status_code,
                    url,
                    attempt + 1,
                    MAX_RETRIES,
                    wait,
                )
                last_exc = None
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait)
            except AmbiguousWriteError:
                raise
            except requests.exceptions.RequestException as exc:
                if not may_retry:
                    raise AmbiguousWriteError(
                        f"{method} outcome is unknown after a network error; "
                        "reconcile target state before retrying",
                        method=method,
                        url=url,
                    ) from exc
                wait = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                logger.warning(
                    "Request error on %s (attempt %d/%d): %s - retrying in %ds",
                    url,
                    attempt + 1,
                    MAX_RETRIES,
                    exc,
                    wait,
                )
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait)

        if last_exc:
            raise SFClientError(
                f"Request failed after {MAX_RETRIES} attempts: {last_exc}",
                url=url,
            )
        # All retries exhausted, return the last (still bad) response
        return resp

    def _check_response(self, resp: requests.Response, url: str) -> dict[str, Any]:
        """Parse JSON, handle auth errors, and return the OData payload dict."""
        if resp.status_code == 401:
            raise SFClientError(
                "Authentication failed - check username, password, and company_id",
                status_code=401,
                url=url,
            )
        if resp.status_code == 403:
            raise SFClientError(
                "Access denied - check API user permissions",
                status_code=403,
                url=url,
            )
        if resp.status_code >= 400:
            body = resp.text[:2000]
            raise SFClientError(
                f"HTTP {resp.status_code} from {url}",
                status_code=resp.status_code,
                body=body,
                url=url,
            )
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise SFClientError(
                f"Non-JSON response from {url}: {exc}",
                body=resp.text[:500],
                url=url,
            ) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        entity_set: str,
        *,
        top: int | None = None,
        skip: int = 0,
        select: list[str] | None = None,
        expand: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all records for *entity_set* with automatic pagination.

        Args:
            entity_set: OData entity set name (e.g. "FODepartment")
            top: Max records per page (default: self.default_top)
            skip: Initial $skip value
            select: Fields to $select
            expand: Navigation properties to $expand
            filter_expr: OData $filter expression
            orderby: OData $orderby expression
            params: Any additional query parameters

        Returns:
            Flat list of record dicts from d.results across all pages.
        """
        url = self._url(entity_set)
        query: dict[str, str] = {
            "$format": "json",
            "$top": str(top or self.default_top),
            "$skip": str(skip),
        }
        if select:
            query["$select"] = ",".join(select)
        if expand:
            query["$expand"] = ",".join(expand)
        if filter_expr:
            query["$filter"] = filter_expr
        if orderby:
            query["$orderby"] = orderby
        if params:
            query.update(params)

        return self._paginate(url, query)

    def get_iter(
        self,
        entity_set: str,
        *,
        top: int | None = None,
        skip: int = 0,
        select: list[str] | None = None,
        expand: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        params: dict[str, str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield records one at a time with constant memory.

        Identical to get() but returns a generator instead of loading
        all pages into a single list. Use this for large datasets
        (500k+ records) to avoid O(n) memory.

        Args:
            entity_set: OData entity set name
            top: Max records per page
            skip: Initial $skip value
            select: Fields to $select
            expand: Navigation properties to $expand
            filter_expr: OData $filter expression
            orderby: OData $orderby expression
            params: Any additional query parameters

        Yields:
            One record dict at a time.
        """
        url = self._url(entity_set)
        query: dict[str, str] = {
            "$format": "json",
            "$top": str(top or self.default_top),
            "$skip": str(skip),
        }
        if select:
            query["$select"] = ",".join(select)
        if expand:
            query["$expand"] = ",".join(expand)
        if filter_expr:
            query["$filter"] = filter_expr
        if orderby:
            query["$orderby"] = orderby
        if params:
            query.update(params)

        next_url: str | None = url
        first_call = True
        while next_url:
            resp = self._request_with_retry(
                "GET",
                next_url,
                params=query if first_call else None,
            )
            first_call = False
            payload = self._check_response(resp, next_url or url)
            data = payload.get("d", {})
            yield from data.get("results", [])
            next_url = data.get("__next")

    def get_entity_by_code(
        self,
        entity_set: str,
        external_code: str,
        *,
        expand: str | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all records where externalCode = *external_code*.

        Args:
            expand: comma-separated navigation properties to $expand
            extra_params: additional OData query params to merge in
        """
        url = self._url(entity_set)
        params: dict[str, str] = {
            "$filter": f"externalCode eq '{odata_escape(external_code)}'",
            "$format": "json",
            "$top": str(self.default_top),
        }
        if expand:
            params["$expand"] = expand
        if extra_params:
            params.update(extra_params)
        return self._paginate(url, params)

    def _paginate(
        self,
        url: str,
        params: dict[str, str] | None,
    ) -> list[dict[str, Any]]:
        """Follow OData __next links until exhausted."""
        results: list[dict[str, Any]] = []
        next_url: str | None = url
        first_call = True

        while next_url:
            resp = self._request_with_retry(
                "GET",
                next_url,
                params=params if first_call else None,
            )
            first_call = False
            payload = self._check_response(resp, next_url or url)
            data = payload.get("d", {})
            batch = data.get("results", [])
            results.extend(batch)

            next_url = data.get("__next")
            logger.debug(
                "GET %s → %d records (total so far: %d)%s",
                next_url or url,
                len(batch),
                len(results),
                " [has next]" if next_url else "",
            )

        return results

    def post(
        self,
        entity_set: str,
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        """POST *payload* to *entity_set*.

        Returns (http_status_code, response_body_dict).
        Raises SFClientError on network / parsing failures only.
        """
        url = self._url(entity_set)
        logger.debug(
            "POST %s payload=%s",
            url,
            json.dumps(payload, indent=self.json_indent)[:500],
        )
        resp = self._request_with_retry("POST", url, json=payload)
        body = self._check_response(resp, url)
        return resp.status_code, body

    def patch(
        self,
        entity_set: str,
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        """PATCH (upsert) *payload* to *entity_set*.

        Returns (http_status_code, response_body_dict).
        """
        url = self._url(entity_set)
        logger.debug("PATCH %s payload=%s", url, json.dumps(payload)[:500])
        resp = self._request_with_retry("PATCH", url, json=payload)
        body = self._check_response(resp, url)
        return resp.status_code, body

    def delete(
        self,
        entity_set: str,
        key: str,
    ) -> int:
        """DELETE a record by key. Returns HTTP status code."""
        url = f"{self._url(entity_set)}('{odata_escape(key)}')"
        resp = self._request_with_retry("DELETE", url)
        return resp.status_code

    def entity_exists(
        self,
        entity_set: str,
        external_code: str,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Check whether an active record exists in *entity_set*.

        Returns (exists: bool, first_record: dict | None).
        The caller should apply effective-dating logic to select the active record.
        """
        records = self.get_entity_by_code(entity_set, external_code)
        if not records:
            return False, None
        return True, records[0]

    def test_connection(self) -> tuple[bool, str]:
        """Quick connectivity check. Returns (ok, message).

        On failure, includes the SF error body so the user can see WHY
        (e.g. "[LGN0015]Authentication failed" vs "Connection refused").
        Body is trimmed to 200 chars to keep the message UI-friendly.
        """
        try:
            # Use User/$count - returns a simple JSON number, avoids
            # Accept header issues with the XML-only $metadata endpoint
            url = f"{self.base_url}/User/$count"
            resp = self._request_with_retry("GET", url)
            if resp.status_code == 200:
                return True, "Connected successfully"
            if resp.status_code == 404:
                # Some tenants don't expose User; try $metadata as fallback
                url = f"{self.base_url}/$metadata"
                resp = self._request_with_retry("GET", url)
                if resp.status_code in (200, 201):
                    return True, "Connected successfully"
            body = self._extract_error_body(resp)
            if body:
                return False, f"HTTP {resp.status_code} - {body}"
            return False, f"HTTP {resp.status_code}"
        except SFClientError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"Connection error: {exc}"

    @staticmethod
    def _extract_error_body(resp) -> str:
        """Pull a short, UI-friendly error message out of a failed response.

        SuccessFactors returns XML like:
          <error xmlns="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
            <code>LGN0015</code>
            <message xml:lang="en">Authentication failed...</message>
          </error>
        We want "[CODE] message" so the user can both identify the error
        (LGN0015) and read the human explanation. For non-XML bodies,
        fall back to the raw text.
        """
        try:
            raw = (resp.text or "").strip()
            if not raw:
                return ""
            code = ""
            message = ""
            code_m = re.search(r"<code[^>]*>(.*?)</code>", raw, re.S | re.I)
            if code_m:
                code = code_m.group(1).strip()
            msg_m = re.search(r"<message[^>]*>(.*?)</message>", raw, re.S | re.I)
            if msg_m:
                message = re.sub(r"\s+", " ", msg_m.group(1)).strip()
            if code and message:
                return f"[{code}] {message}"[:240]
            if message:
                return message[:200]
            if code:
                return f"[{code}]"[:200]
            # Plain text body (no XML structure)
            return re.sub(r"\s+", " ", raw).strip()[:200]
        except Exception as exc:
            logger.warning("Failed to extract error body: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> SFClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
