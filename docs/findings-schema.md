# SF Compass Suite - Findings Schema (v1)

> Compatibility format. New portfolio integrations should emit the broader [`sapsf-assurance/v1`](assurance-exchange-v1.md) contract, which includes engagement context, actions and evidence. Existing findings-only emitters remain supported during migration.

A common JSON format for analysis findings, so every scanner in the suite
(sf-config-debt-radar, sf-position-integrity-checker, sf-config-compare, ...)
can emit results that any other tool (the sf-compass dashboard, AI agents via
MCP, future trend tooling) can consume without tool-specific parsing.

Schema identifier: `sf-compass-findings/v1`

## Top-level document

```json
{
  "schema": "sf-compass-findings/v1",
  "tool": "sf-position-integrity-checker",
  "tool_version": "1.4.0",
  "generated_at": "2026-06-11T14:32:00",
  "tenant": "https://***masked***.successfactors.eu",
  "scope": {
    "country": "CAN",
    "as_of_date": "2026-06-11"
  },
  "summary": {
    "total_records": 1240,
    "findings": 37,
    "by_severity": { "high": 4, "medium": 21, "low": 12 }
  },
  "findings": []
}
```

| Field | Required | Notes |
|---|---|---|
| `schema` | yes | Always `sf-compass-findings/v1` |
| `tool` | yes | Repo name of the emitting tool |
| `tool_version` | yes | Version string of the emitting tool |
| `generated_at` | yes | ISO 8601 local timestamp |
| `tenant` | no | Masked tenant URL only - never the raw subdomain |
| `scope` | no | Tool-specific run parameters (country, module, object types) |
| `summary` | yes | Counts; `by_severity` keys are lowercase severities |
| `findings` | yes | Array of finding objects, may be empty |

## Finding object

```json
{
  "id": "POS-014",
  "severity": "high",
  "category": "Org Assignment",
  "object_type": "Position",
  "object_id": "POS_10023",
  "field": "costCenter",
  "message": "Cost centre is inactive as of the as-of date",
  "details": {}
}
```

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Stable rule/check identifier within the tool |
| `severity` | yes | One of `critical`, `high`, `medium`, `low`, `info` (lowercase) |
| `category` | yes | Tool-defined grouping label |
| `object_type` | yes | e.g. `Position`, `Picklist`, `ObjectDefinition`, `BusinessRule` |
| `object_id` | yes | External code / ID of the affected record |
| `field` | no | Affected field name, if applicable |
| `message` | yes | Plain-English description of the finding |
| `details` | no | Free-form object for tool-specific extras |

## Rules

- Severities are normalised to lowercase. Map tool-native scales onto
  critical/high/medium/low/info before emitting.
- Never include employee personal data in `message` or `details`. IDs and
  codes only.
- Always mask tenant URLs (`***masked***` subdomain convention, see
  `sapsf_shared.utils`).
- Emitters write the file alongside their other reports as
  `<tool>_findings_<datestamp>.json`.

## Current emitters

- `sf-position-integrity-checker` - `write_findings_json` in `reporters.py`
  (also exposed via its MCP server tool `sf_validate_positions`)
- `sf-config-debt-radar` - `build_findings_v1` in `cli.py`, written as
  `config_debt_findings.json` on every scan

## Consumers

- `sf-compass` - [Tenant Findings Viewer](https://sahirvhora.github.io/sf-compass/findings.html)
  loads any number of v1 files into one combined, filterable view

Planned emitter: sf-config-compare.
