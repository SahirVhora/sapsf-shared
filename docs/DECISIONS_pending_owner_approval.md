# DECISIONS pending owner approval (cross-repo)

Per `sapsf/CLAUDE.md` archival rule: items in this file are awaiting an
explicit decision from the owner before any delete / archive / major rewrite
action is taken. Companion to `sapsf/PORTFOLIO_OPERATING_MODEL.md` and
`sapsf/SECURITY.md`.

Last reviewed: 2026-07-25 (sapsf portfolio audit review)

---

## 1. Workshop triplet canonical path

**Repos involved:** `sf-workshop-advisor/`, `sap-workshop-advisor/`,
`sap-integration-workshop-advisor/`

**Audit observation:** Three single-file HTML apps with overlapping content.
A canonical version should be chosen; near-duplicates archived.

**Why it is pending:** Each workshop advisor targets a slightly different
audience (SF-only, SAP general, SAP integration). The "canonical" version is
a product decision, not an engineering one.

**Options for the owner:**
1. Mark `sf-workshop-advisor/` canonical; archive `sap-workshop-advisor/` and
   `sap-integration-workshop-advisor/` with redirects.
2. Keep all three; document the audience split in each README.
3. Merge under a shared `sapsf-workshops/` umbrella with per-audience
   subdirs.

**Owner decision needed before:** any archive or merge action.

---

## 2. sf-position-integrity-checker archival

**Repo involved:** `sf_position_integrity_checker/` (with the underscore; the
directory `sf-position-integrity-checker/` is the live component)

**Audit observation:** Two near-duplicate repos exist. The active one is the
hyphenated one; the underscore variant is kept for historical reasons.

**Why it is pending:** Owner may still be receiving references from older
clients / partner docs to the underscore name.

**Options for the owner:**
1. Archive `sf_position_integrity_checker/` with a redirect README pointing
   to the hyphenated variant.
2. Keep both; tag the underscore variant "frozen as of 2026-07-25".
3. Rename the live repo to match the underscore form.

**Owner decision needed before:** any rename or archive action.

---

## 3. sf-scope archival

**Repo involved:** `sf-scope-prep/` (the active component) and the
historical `sf-scope/`

**Audit observation:** `sf-scope/app.py` historically used `exec()` to run
`.pyc`-derived bytecode, which is unsafe. Replaced with a
`NotImplementedError` shim on 2026-07-25 (commit pending). The repo is
effectively retired.

**Why it is pending:** Owner wants to confirm no production deploy ever
relied on `exec_pyc`.

**Options for the owner:**
1. Archive `sf-scope/` now (no production usage confirmed).
2. Keep as reference for the audit trail; add an ARCHIVED.md marker only.
3. Re-implement `exec_pyc` using constrained, vetted patterns and resume.

**Owner decision needed before:** archive or rewrite.

---

## 4. sf_workflow_monitor archival

**Repo involved:** `sf_workflow_monitor/` (underscored, with
`.secrets.json`)

**Audit observation:** Project lifecycle unclear; secret-scanning flagged a
leaked credential on 2026-07-25 (now scrubbed). No recent commits; no
active CI.

**Why it is pending:** Owner needs to confirm whether the project is
retired, frozen, or in low-priority maintenance.

**Options for the owner:**
1. Archive repo now (tool superseded by sf-rule-tester + sf-cutover-planner).
2. Resume maintenance; reassign an owner.
3. Mark as "frozen / read-only" and add an ARCHIVED.md marker.

**Owner decision needed before:** any archive / resume action.

---

## How to record a decision

When the owner decides on any item above, add a dated note under the
item with:
- Option chosen
- Rationale (one sentence)
- Any constraints from the decision that future audits must respect

Then act on the decision. Update this file as items are resolved.

## How to add a new pending decision

Append a new section at the bottom with the same shape (repos involved,
audit observation, why pending, options, owner action needed before).
