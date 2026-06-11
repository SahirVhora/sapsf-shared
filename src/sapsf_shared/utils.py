"""Utility helpers used across SAP SuccessFactors tools.

These functions handle common OData data transformations without
pulling in heavy dependencies.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any

_SF_DATE_RE = re.compile(r"/Date\((-?\d+)\)/")
_ACTIVE_STATUSES = {"ACTIVE", "A", "1", "TRUE", "true", "active"}


def parse_sf_date(raw: Any) -> date | None:
    """Parse a SuccessFactors date string to a Python date.

    Handles:
      - /Date(1234567890000)/   (SF epoch milliseconds)
      - ISO 8601 strings (e.g. 2024-01-15T00:00:00Z)
      - Plain YYYY-MM-DD strings
    """
    if raw is None:
        return None
    raw_str = str(raw).strip()
    if not raw_str:
        return None

    # Try /Date(millis)/ pattern
    m = _SF_DATE_RE.match(raw_str)
    if m:
        ts_ms = int(m.group(1))
        return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date()

    # Try ISO 8601 with timezone
    try:
        clean = raw_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.date()
    except (ValueError, TypeError):
        pass

    # Try plain date string
    try:
        return datetime.strptime(raw_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        pass

    return None


def is_active_today(item: dict[str, Any], today: date | None = None) -> bool:
    """Check if an OData record is active today based on status and effective dates.

    Looks at common SF fields:
      - status / cust_status
      - startDate / effectiveStartDate / validFrom
      - endDate / effectiveEndDate / validTo
    """
    if today is None:
        today = date.today()

    # Check status field
    status = item.get("status") or item.get("cust_status")
    if status is not None and str(status).strip().upper() not in _ACTIVE_STATUSES:
        return False

    # Check date boundaries
    start = (
        parse_sf_date(item.get("startDate"))
        or parse_sf_date(item.get("effectiveStartDate"))
        or parse_sf_date(item.get("validFrom"))
    )
    end = (
        parse_sf_date(item.get("endDate"))
        or parse_sf_date(item.get("effectiveEndDate"))
        or parse_sf_date(item.get("validTo"))
    )

    if start and start > today:
        return False
    return not (end and end < today)


def flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested OData objects for CSV / tabular output.

    Rules:
      - Skip __metadata and __deferred keys
      - Inline single objects as "nav_prop_subkey"
      - Serialize collections as JSON strings
      - Convert datetime objects to ISO strings
    """
    flat: dict[str, Any] = {}
    for key, value in record.items():
        if key.startswith("__") or key == "metadata" or key == "deferred":
            continue
        if isinstance(value, dict):
            if "__deferred" in value:
                continue
            if "results" in value:
                flat[key] = json.dumps(value["results"], default=str)
            else:
                for sub_key, sub_val in value.items():
                    if not sub_key.startswith("__"):
                        flat[f"{key}_{sub_key}"] = sub_val
        elif isinstance(value, list):
            flat[key] = json.dumps(value, default=str)
        elif isinstance(value, (datetime, date)):
            flat[key] = value.isoformat()
        else:
            flat[key] = value
    return flat


def build_odata_filter(
    filters: dict[str, Any],
    *,
    operator: str = "eq",
    combiner: str = "and",
) -> str | None:
    """Build a simple OData $filter string from a dict of field → value pairs.

    Args:
        filters: e.g. {"cust_Country": "GBR", "status": "A"}
        operator: Comparison operator (eq, ne, gt, lt, ge, le)
        combiner: How to join multiple conditions (and / or)

    Returns:
        OData filter string or None if filters is empty.
    """
    if not filters:
        return None
    parts: list[str] = []
    for field, value in filters.items():
        if isinstance(value, str):
            parts.append(f"{field} {operator} '{value}'")
        else:
            parts.append(f"{field} {operator} {value}")
    return f" {combiner} ".join(parts)
