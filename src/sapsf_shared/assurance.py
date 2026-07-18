"""Common engagement, findings, actions, and evidence contract.

The contract is deliberately small, dependency-free, and safe for portfolio-wide
JSON exchange. It carries references and aggregate evidence, not employee data.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

ASSURANCE_SCHEMA = "sapsf-assurance/v1"
SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
FINDING_STATUSES = frozenset({"open", "accepted", "in_progress", "resolved", "false_positive"})
ACTION_STATUSES = frozenset({"open", "in_progress", "blocked", "completed", "cancelled"})
PRIORITIES = frozenset({"critical", "high", "medium", "low"})
SUMMARY_STATUSES = frozenset({"pass", "attention_required", "blocked", "incomplete"})
EVIDENCE_CLASSIFICATIONS = frozenset({"public", "internal", "confidential", "restricted"})

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "employee_name",
        "person_name",
        "email",
        "phone",
        "national_id",
        "bank_account",
        "iban",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AssuranceValidationError(ValueError):
    """Raised when a portfolio assurance document violates the contract."""


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssuranceValidationError(f"{path} must be an object")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise AssuranceValidationError(f"{path} must be an array")
    return value


def _require_fields(value: dict[str, Any], required: set[str], path: str) -> None:
    missing = sorted(required - value.keys())
    if missing:
        raise AssuranceValidationError(f"{path} missing required field(s): {', '.join(missing)}")


def _check_no_sensitive_fields(value: Any, path: str = "document") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS:
                raise AssuranceValidationError(f"{path}.{key} is a sensitive field and is forbidden")
            _check_no_sensitive_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_no_sensitive_fields(child, f"{path}[{index}]")


def _unique_ids(items: list[Any], section: str) -> set[str]:
    identifiers: list[str] = []
    for index, raw in enumerate(items):
        item = _require_mapping(raw, f"{section}[{index}]")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise AssuranceValidationError(f"{section}[{index}].id must be a non-empty string")
        identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        raise AssuranceValidationError(f"{section} contains a duplicate id")
    return set(identifiers)


def _check_references(refs: Any, known: set[str], path: str) -> None:
    for reference in _require_list(refs, path):
        if reference not in known:
            raise AssuranceValidationError(f"{path} contains unknown reference {reference}")


def validate_assurance_document(document: dict[str, Any]) -> None:
    """Validate one ``sapsf-assurance/v1`` exchange document.

    The validator fails closed on unknown severities/statuses, broken references,
    duplicate IDs, obvious credential/PII fields, and raw tenant identifiers.
    """
    root = _require_mapping(document, "document")
    required_sections = {"schema", "engagement", "run", "summary", "findings", "actions", "evidence"}
    _require_fields(root, required_sections, "document")
    if root["schema"] != ASSURANCE_SCHEMA:
        raise AssuranceValidationError(f"schema must be {ASSURANCE_SCHEMA}")
    _check_no_sensitive_fields(root)

    engagement = _require_mapping(root["engagement"], "engagement")
    _require_fields(engagement, {"id", "name", "client_alias", "countries", "modules", "stage"}, "engagement")
    if not engagement["client_alias"] or "@" in str(engagement["client_alias"]):
        raise AssuranceValidationError("engagement.client_alias must be a non-personal alias")
    _require_list(engagement["countries"], "engagement.countries")
    _require_list(engagement["modules"], "engagement.modules")

    run = _require_mapping(root["run"], "run")
    _require_fields(run, {"id", "tool", "tool_version", "generated_at", "mode", "scope"}, "run")
    _require_mapping(run["scope"], "run.scope")
    tenant = run.get("tenant")
    if tenant is not None and "***masked***" not in str(tenant):
        raise AssuranceValidationError("run.tenant must be explicitly masked")
    try:
        datetime.fromisoformat(str(run["generated_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssuranceValidationError("run.generated_at must be ISO 8601") from exc

    summary = _require_mapping(root["summary"], "summary")
    _require_fields(summary, {"status", "records_assessed", "findings", "by_severity"}, "summary")
    if summary["status"] not in SUMMARY_STATUSES:
        raise AssuranceValidationError("summary.status is not canonical")
    if not isinstance(summary["records_assessed"], int) or summary["records_assessed"] < 0:
        raise AssuranceValidationError("summary.records_assessed must be a non-negative integer")
    by_severity = _require_mapping(summary["by_severity"], "summary.by_severity")
    if any(key not in SEVERITIES for key in by_severity):
        raise AssuranceValidationError("summary.by_severity contains a noncanonical severity")

    findings = _require_list(root["findings"], "findings")
    actions = _require_list(root["actions"], "actions")
    evidence = _require_list(root["evidence"], "evidence")
    finding_ids = _unique_ids(findings, "findings")
    action_ids = _unique_ids(actions, "actions")
    evidence_ids = _unique_ids(evidence, "evidence")

    if summary["findings"] != len(findings):
        raise AssuranceValidationError("summary.findings does not match findings length")

    for index, raw in enumerate(findings):
        finding = _require_mapping(raw, f"findings[{index}]")
        _require_fields(
            finding,
            {
                "id",
                "rule_id",
                "severity",
                "status",
                "category",
                "title",
                "description",
                "object_type",
                "object_ref",
                "evidence_refs",
                "action_refs",
            },
            f"findings[{index}]",
        )
        if finding["severity"] not in SEVERITIES:
            raise AssuranceValidationError(f"findings[{index}].severity is not canonical")
        if finding["status"] not in FINDING_STATUSES:
            raise AssuranceValidationError(f"findings[{index}].status is not canonical")
        _check_references(finding["evidence_refs"], evidence_ids, f"findings[{index}].evidence_refs")
        _check_references(finding["action_refs"], action_ids, f"findings[{index}].action_refs")

    for index, raw in enumerate(actions):
        action = _require_mapping(raw, f"actions[{index}]")
        _require_fields(action, {"id", "title", "owner_role", "priority", "status", "finding_refs"}, f"actions[{index}]")
        if action["priority"] not in PRIORITIES:
            raise AssuranceValidationError(f"actions[{index}].priority is not canonical")
        if action["status"] not in ACTION_STATUSES:
            raise AssuranceValidationError(f"actions[{index}].status is not canonical")
        _check_references(action["finding_refs"], finding_ids, f"actions[{index}].finding_refs")

    for index, raw in enumerate(evidence):
        item = _require_mapping(raw, f"evidence[{index}]")
        _require_fields(item, {"id", "type", "description", "classification", "source", "generated_at"}, f"evidence[{index}]")
        if item["classification"] not in EVIDENCE_CLASSIFICATIONS:
            raise AssuranceValidationError(f"evidence[{index}].classification is not canonical")
        digest = item.get("sha256")
        if digest is not None and not _SHA256_RE.fullmatch(str(digest)):
            raise AssuranceValidationError(f"evidence[{index}].sha256 must be a lowercase SHA-256 digest")


def new_assurance_document(
    *,
    engagement_id: str,
    engagement_name: str,
    client_alias: str,
    run_id: str,
    tool: str,
    tool_version: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Create a valid empty assurance document for a tool run."""
    timestamp = generated_at or datetime.now(UTC)
    return {
        "schema": ASSURANCE_SCHEMA,
        "engagement": {
            "id": engagement_id,
            "name": engagement_name,
            "client_alias": client_alias,
            "countries": [],
            "modules": [],
            "stage": "discovery",
        },
        "run": {
            "id": run_id,
            "tool": tool,
            "tool_version": tool_version,
            "generated_at": timestamp.isoformat(),
            "mode": "local",
            "scope": {},
        },
        "summary": {
            "status": "incomplete",
            "records_assessed": 0,
            "findings": 0,
            "by_severity": {},
        },
        "findings": [],
        "actions": [],
        "evidence": [],
    }
