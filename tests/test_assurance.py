"""Tests for the portfolio-wide assurance engagement contract."""

import copy
from datetime import UTC, datetime

import pytest

from sapsf_shared.assurance import (
    ASSURANCE_SCHEMA,
    AssuranceValidationError,
    new_assurance_document,
    validate_assurance_document,
)


def valid_document():
    return {
        "schema": ASSURANCE_SCHEMA,
        "engagement": {
            "id": "ENG-001",
            "name": "Migration Assurance",
            "client_alias": "CLIENT-A",
            "programme": "EC migration",
            "countries": ["GBR", "IND"],
            "modules": ["Employee Central"],
            "stage": "rehearsal",
        },
        "run": {
            "id": "RUN-001",
            "tool": "migration-tool",
            "tool_version": "1.0.0",
            "generated_at": "2026-07-18T12:00:00+00:00",
            "as_of_date": "2026-07-18",
            "mode": "local",
            "scope": {"country": "GBR", "object_types": ["EmpJob"]},
        },
        "summary": {
            "status": "attention_required",
            "records_assessed": 1000,
            "findings": 1,
            "by_severity": {"high": 1},
        },
        "findings": [
            {
                "id": "F-001",
                "rule_id": "MAP-001",
                "severity": "high",
                "status": "open",
                "category": "mapping",
                "title": "Required target field is unmapped",
                "description": "A required target field needs an approved source rule.",
                "object_type": "EmpJob",
                "object_ref": "FIELD:company",
                "evidence_refs": ["E-001"],
                "action_refs": ["A-001"],
            }
        ],
        "actions": [
            {
                "id": "A-001",
                "title": "Approve company mapping",
                "owner_role": "Data Lead",
                "priority": "high",
                "status": "open",
                "finding_refs": ["F-001"],
            }
        ],
        "evidence": [
            {
                "id": "E-001",
                "type": "validation_summary",
                "description": "Deterministic mapping validation output",
                "classification": "confidential",
                "source": "migration-tool",
                "sha256": "a" * 64,
                "generated_at": "2026-07-18T12:00:00+00:00",
            }
        ],
    }


def test_valid_complete_document_passes():
    validate_assurance_document(valid_document())


def test_factory_creates_valid_minimal_document():
    document = new_assurance_document(
        engagement_id="ENG-002",
        engagement_name="Configuration Assurance",
        client_alias="CLIENT-B",
        run_id="RUN-002",
        tool="sf-config-compare",
        tool_version="2.0.0",
        generated_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )

    validate_assurance_document(document)
    assert document["schema"] == ASSURANCE_SCHEMA
    assert document["findings"] == []
    assert document["actions"] == []
    assert document["evidence"] == []


@pytest.mark.parametrize(
    "missing", ["schema", "engagement", "run", "summary", "findings", "actions", "evidence"]
)
def test_rejects_missing_top_level_contract_sections(missing):
    document = valid_document()
    del document[missing]

    with pytest.raises(AssuranceValidationError, match=missing):
        validate_assurance_document(document)


@pytest.mark.parametrize("severity", ["urgent", "P1", "HIGH"])
def test_rejects_noncanonical_severity(severity):
    document = valid_document()
    document["findings"][0]["severity"] = severity

    with pytest.raises(AssuranceValidationError, match="severity"):
        validate_assurance_document(document)


def test_rejects_broken_finding_evidence_reference():
    document = valid_document()
    document["findings"][0]["evidence_refs"] = ["E-MISSING"]

    with pytest.raises(AssuranceValidationError, match="E-MISSING"):
        validate_assurance_document(document)


def test_rejects_broken_action_finding_reference():
    document = valid_document()
    document["actions"][0]["finding_refs"] = ["F-MISSING"]

    with pytest.raises(AssuranceValidationError, match="F-MISSING"):
        validate_assurance_document(document)


@pytest.mark.parametrize(
    "sensitive_key",
    [
        "password",
        "access_token",
        "client_secret",
        "employee_name",
        "email",
        "national_id",
        "bank_account",
    ],
)
def test_rejects_sensitive_fields_anywhere_in_document(sensitive_key):
    document = valid_document()
    document["findings"][0]["details"] = {sensitive_key: "must-not-be-here"}

    with pytest.raises(AssuranceValidationError, match="sensitive"):
        validate_assurance_document(document)


def test_rejects_unmasked_tenant_identifier():
    document = valid_document()
    document["run"]["tenant"] = "https://api55.sapsf.eu"

    with pytest.raises(AssuranceValidationError, match="tenant"):
        validate_assurance_document(document)


def test_accepts_explicitly_masked_tenant_identifier():
    document = valid_document()
    document["run"]["tenant"] = "https://***masked***.sapsf.eu"

    validate_assurance_document(document)


def test_rejects_duplicate_ids():
    document = valid_document()
    document["findings"].append(copy.deepcopy(document["findings"][0]))
    document["summary"]["findings"] = 2

    with pytest.raises(AssuranceValidationError, match="duplicate"):
        validate_assurance_document(document)


def test_rejects_summary_finding_count_mismatch():
    document = valid_document()
    document["summary"]["findings"] = 2

    with pytest.raises(AssuranceValidationError, match="summary"):
        validate_assurance_document(document)
