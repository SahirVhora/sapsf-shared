# ADR-0003 — Local-token Auth: Header-First, Query-String Deprecated

| Field      | Value                                                          |
|------------|----------------------------------------------------------------|
| Status     | Accepted, in deprecation window                                |
| Date       | 2026-07-25                                                     |
| Owner      | sapsf platform                                                 |
| Closes     | audit-finding R-006 (legacy `?token=` channel on local Flask) |
| Removal    | 2026-10-25                                                     |

## Context

The sapsf portfolio's local Flask surfaces historically accepted the
`?token=...` query-string channel as a fallback when an authentication header
was not provided. This was once useful because shell scripts had trouble
passing headers and curl users naturally reach for `--data-urlencode`.

With the move to 12-factor share-nothing deploys and the proliferation of
cross-tool log scrapers, query-string tokens are now a probe target:

* They appear in reverse-proxy access logs and process listings.
* They are cached in browser history and corporate proxy caches.
* They survive into the URL bar and leak via shared screenshots.

## Decision

Move HTTP-token-gated sapsf local Flask surfaces to header-only. New
write-path surfaces use the shared helper
`sapsf_shared.flask_base.require_local_token` - header-only,
with 403 responses for client authentication failures. A missing server-side
token configuration returns 503. For legacy surfaces still accepting `?token=` (notably
`sf-object-sync/web_ui/app.py`) we add a single `app.logger.warning`
per request so operators see probe traffic in observability.

Local credential-management Flask surfaces (encrypted-at-rest secrets,
session CSRF on every POST) are out of scope: they have no HTTP token
channel to deprecate. See "Applicability by surface type" below.

A regression pin at `sf-object-sync/tests/test_web_ui_auth.py` freezes
the current deprecation behaviour: header works, query works but warns,
wrong/missing returns 401.

## Deprecation timeline

| Phase                | Date       | Surface state                                                                                  |
|----------------------|------------|------------------------------------------------------------------------------------------------|
| Now                  | 2026-07-25 | Header primary. `?token=` accepted, ONE warning log per request. Tests pin behaviour.          |
| Removal candidate    | 2026-10-25 | `?token=` returns 401 with no warning. Test's fallback case flips to a permanent 401 pin.      |
| Post-removal cleanup | 2026-11-25 | Query-string branch removed from `_require_token`; only `X-Auth-Token` and the header fallback. |

If a critical operator cannot migrate by 2026-10-25, file the blocker at
`_shared/docs/DECISIONS_pending_owner_approval.md` with the specific
caller URL and rolling-impact estimate.

## Operator action

By **2026-10-25**, every script and pocket-reference doc that hits an
HTTP-token-gated local sapsf Flask surface (see the table below) must
switch from `?token=...` to the surface's header: `X-Auth-Token` for
sf-object-sync and `X-Report-Token` for report endpoints. After that
date, **sf-object-sync** returns 401 for the `?token=` channel with no
warning; silent breakage is the failure mode for stragglers. The
back-compat reader `check_local_token` (used by `sf-config-compare{,ec}`
and `sf-metadata-vault`) keeps emitting its existing warning log past
the cutover on read-only report paths - the warning stays on by design.

**Pre-cutover sweep (mandatory by 2026-10-25):**
Run these fixed-string greps (no regex, copy-paste safe):

  ```
  grep -rn --include='*.py' -F 'request.args.get("token' sapsf/
  grep -rn --include='*.py' -F 'request.args.get("_token' sapsf/
  grep -rn --include='*.py' -F 'legacy_query_arg' sapsf/
  ```

Together they must identify only the two implementation files in the next
bullet (test files may also pin this behavior). If they surface another
implementation file, the deprecation list is incomplete and
the cutover cannot proceed without an ADR amendment. The `-F` flag
keeps the patterns literal so an operator can paste them blind on
2026-10-25 and trust the output.

**Files to edit on 2026-10-25:**
* `sapsf/sf-object-sync/web_ui/app.py` -- drop the legacy branch in
  `_require_token`; the regression pin
  `tests/test_web_ui_auth.py::test_query_token_falls_back_and_logs_deprecation`
  flips to a permanent 401 invariant.
* `sapsf/_shared/src/sapsf_shared/flask_base.py` -- decide on the
  future of `check_local_token`'s `?token=` fallback per the
  write-path-vs-read-path rule in the Compliance section. This ADR
  does not force removal here; reviewers must choose per surface.

Local credential-management surfaces (see second table) are
unaffected by ADR-0003 -- they do not have an HTTP token channel.

## Applicability by surface type

ADR-0003 governs HTTP-token-gated Flask surfaces that accept an
`X-Auth-Token` / `?token=` channel. Local credential-management Flask
surfaces (CRUD on stored secrets, scenario packs, manifest review)
use a different model -- encrypted credentials-at-rest plus session
CSRF -- and are **not** covered by ADR-0003. Mixing them here would
mislead the next maintainer.

### HTTP-token-gated surfaces (ADR-0003 applies)

| Tool | Helper used | Channel accepted today | Migration target |
|------|-------------|------------------------|------------------|
| `sf-object-sync` (`web_ui/app.py`) | local `_require_token` | header + query (warn) | `require_local_token` (header-only) |
| `sf-config-compare` (`app.py`) | `check_local_token` | header + query | preserves caller-defined denial status |
| `sf-config-compare-ec` (`app.py` + `core/api.py`) | `check_local_token` | header + query | preserves caller-defined denial status |
| `sf-metadata-vault` (`app.py`) | `check_local_token` | header + query | preserves caller-defined denial status |

### Local credential-management surfaces (ADR-0003 does not apply)

| Tool | Auth model | Credentials at rest | Notes |
|------|------------|---------------------|-------|
| `sf-rule-tester` (`webapp/app.py`) | Session cookie + CSRF token; outbound SF passwords stored in `webapp/auth.py` | OS keyring (preferred) or `chmod 600` `.secrets.json` fallback | Loopback bind only (`127.0.0.1:5060`); enforced in `webapp/app.py:main()`. No inbound `X-Auth-Token` / `?token=` channel. `webapp/auth.py` is a credential **store**, not a request gate. |
| `sf-transport-pilot` (`src/sftp/webui/app.py`) | Per-tenant credentials encrypted `SecretBox` (libsodium) into SQLite; session CSRF on every POST | SQLite ciphertext + `data/.sftp_secret.key` per secret | Loopback bind enforced at the CLI in `src/sftp/cli.py` (`ui` command); the webui factory itself does not bind. CSRF is the write-protection gate -- a separate concern from any HTTP token. No `X-Auth-Token` / `?token=`. |

The migration target column above is informational -- rows marked
"preserves caller-defined denial status" are intentionally on the back-compat reader
because all are read-only report endpoints. Write-path gates
(`<tool>/<write-route>`) on those tools should adopt
`require_local_token` ahead of the 2026-10-25 cutover.

## Compliance

* **Write paths** MUST use `require_local_token` (header-only, with 403 for
  client authentication failures and 503 for missing server configuration).
  `sf-object-sync`'s local `_require_token` is
  grandfathered through the 2026-10-25 cutover window only -- see
  Operator action for the exact cutover rules. Emitting `?token=` to
  any other hardened write surface after the cutover returns 401; no
  new code path should accept the channel through a back-compat
  reader.
* **Read paths** (report endpoints) may stay on `check_local_token` for
  back-compat reads, provided every rejection emits an
  `app.logger.warning` with `path=` and `remote=` so SOC can grep probe
  traffic. `check_local_token` is not "banned"; it is the deliberate
  reader helper, distinct from the writer helper.
* New shared Flask blueprints default to `require_local_token`; only fall
  back to `check_local_token` when the endpoint is read-only and the
  regression pin covers both channels.
* When `WEB_UI_TOKEN` is unset, `_require_token` short-circuits open.
  Loopback binding is enforced **per tool**:
  - `sf-object-sync` (Table 1) -- env-override via `HOST`
    (`os.getenv("HOST", "127.0.0.1")`); soft default, NOT validator-
    enforced. Operators must not override `HOST` on a public network.
  - `sf-rule-tester` (Table 2) -- hardcoded
    `app.run(host="127.0.0.1", port=5060)` in `webapp/app.py:main()`.
  - `sf-transport-pilot` (Table 2) -- enforced at the CLI in
    `src/sftp/cli.py` (`ui` command validator: rejects any host not in
    `{"127.0.0.1", "localhost", "::1"}`).
