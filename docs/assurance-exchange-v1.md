# SAP SuccessFactors Assurance Exchange v1

Schema identifier: `sapsf-assurance/v1`

This is the common portfolio contract for an engagement, one deterministic tool run, its findings, remediation actions and supporting evidence. It supersedes the findings-only `sf-compass-findings/v1` format for new integrations. Existing v1 findings emitters can continue while adapters are added.

## Canonical artifacts

- Runtime validator: `src/sapsf_shared/assurance.py`
- JSON Schema: `schemas/sapsf-assurance-v1.schema.json`
- Safe example: `examples/sapsf-assurance-v1.example.json`
- Tests: `tests/test_assurance.py`

## Design rules

1. One document represents one tool run within one engagement.
2. Findings use stable rule IDs and canonical lowercase severities.
3. Findings reference evidence and actions by ID. Broken references are invalid.
4. Evidence records describe and hash an artifact. They do not embed the artifact.
5. Tenant identifiers must be explicitly masked.
6. Employee PII, credentials and tokens are forbidden anywhere in the exchange document.
7. Raw client evidence stays in the approved local/client repository. The exchange document carries only safe metadata and relative references.
8. IDs remain stable across reruns where the underlying issue is the same. A tool-specific fingerprint can be used to generate the finding ID.

## Required sections

- `engagement`: client alias, programme, countries, modules and lifecycle stage.
- `run`: emitting tool, version, timestamp, mode and scope.
- `summary`: gate status and aggregate counts.
- `findings`: deterministic observations with rule, severity and status.
- `actions`: owned remediation or decision items.
- `evidence`: metadata, classification and optional SHA-256 for supporting artifacts.

## Adoption sequence

1. `migration_tool` and `sf-validator`: mapping and load-gate findings.
2. `sf-position-integrity-checker`: position and Job Information integrity findings.
3. `sf-config-compare-ec`: source/target readiness findings and worklist actions.
4. `sf-change-ledger`: snapshot-change findings and CAB evidence.
5. `sf-config-debt-radar`: current-state debt findings.
6. `sf-release-update`/`sf-impact-brief`: vendor change and release-test actions.
7. SF Compass: aggregate documents into engagement and executive views.

## Python usage

```python
from sapsf_shared.assurance import new_assurance_document, validate_assurance_document

document = new_assurance_document(
    engagement_id="ENG-001",
    engagement_name="Migration Assurance",
    client_alias="CLIENT-A",
    run_id="RUN-001",
    tool="migration-tool",
    tool_version="1.0.0",
)
# Populate findings, actions and evidence, then update summary counts.
validate_assurance_document(document)
```

Validation is dependency-free and adds cross-reference, duplicate-ID, tenant-mask and sensitive-key checks that JSON Schema alone cannot enforce.
