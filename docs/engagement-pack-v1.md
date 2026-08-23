# SAP SuccessFactors Engagement Pack v1

Schema identifier: `sapsf-engagement-pack/v1`

The engagement pack combines validated `sapsf-assurance/v1` run documents into
one local, decision-oriented G0-G4 view. SF Compass builds the pack entirely in
the browser; source files and generated output are not uploaded.

## Decision rules

1. Every input must share the same engagement ID and non-personal client alias.
2. Only the latest timestamped run for each canonical tool drives the current
   gate decision. Superseded runs remain in the pack as history.
3. A required tool without SHA-256 evidence is `incomplete`, even if its run
   claims `pass`.
4. Open critical findings, blocked run summaries, and blocked actions produce a
   `blocked` gate. Open high findings produce `attention_required`.
5. G0 and G4 pass only when a human checkbox and a non-personal ticket or
   document reference are both present.
6. Optional Position Management and digital-twin controls become required only
   when selected as in scope.
7. `records_assessed` is the latest migration population. The sum of every
   current control run is reported separately as `control_assessments`, because
   the same business record may be assessed by several tools.
8. The pack is decision support. It never grants a production approval or
   replaces the accountable programme authority.

## Gate mapping

| Gate | Machine controls | Human control |
|---|---|---|
| G0 Scope accepted | none | scope approval reference |
| G1 Mapping approved | `migration-tool`, `sf-config-compare-ec` | programme decision process |
| G2 Load candidate accepted | `sf-ec-hcm-validator`, plus Position Integrity when in scope | programme decision process |
| G3 Go/no-go recommendation | `sf-change-ledger`, `sf-cutover-planner`, plus digital twin when in scope | accountable go/no-go decision |
| G4 Evidence closed | none | hypercare closure reference |

## Safe use

- Load only `sapsf-assurance/v1` metadata documents, never raw extracts or
  detailed client workbooks.
- Use aliases and ticket references rather than names or email addresses.
- Keep the exported pack in the approved engagement evidence repository.
- Treat a `proceed` recommendation as evidence completeness, not autonomous
  authorisation.

Canonical implementation: `sf-compass/engagement-pack.mjs`
JSON Schema: `schemas/sapsf-engagement-pack-v1.schema.json`
