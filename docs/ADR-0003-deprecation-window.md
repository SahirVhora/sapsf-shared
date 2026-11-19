# ADR-0003 — Local-token Auth: Header-Only

| Field      | Value                                                          |
|------------|----------------------------------------------------------------|
| Status     | Accepted and implemented                                       |
| Date       | 2026-07-25                                                     |
| Owner      | sapsf platform                                                 |
| Closes     | audit-finding R-006 (legacy `?token=` channel on local Flask) |
| Removal    | 2026-08-31                                                     |

## Context

The sapsf portfolio's local Flask surfaces historically accepted the
`?token=...` query-string channel as a fallback when an authentication header
was not provided.

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
token configuration returns 503. The compatibility helper
`check_local_token` retains its documented open-when-unconfigured behaviour
for existing read-only routes, but rejects query-string credentials.

Local credential-management Flask surfaces (encrypted-at-rest secrets,
session CSRF on every POST) are out of scope: they have no HTTP token
channel to deprecate. See "Applicability by surface type" below.

A regression pin in `_shared/tests/test_flask_base.py` verifies that both
shared helpers reject `?token=` and only accept the configured header.

## Operator action

Every script and pocket-reference document that calls an HTTP-token-gated
local Flask surface must use `X-Auth-Token` for sf-object-sync and
`X-Report-Token` for report endpoints. Requests containing `?token=` are
rejected and logged. Local credential-management surfaces remain unaffected
because they do not expose an HTTP token channel.

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
| `sf-object-sync` (`web_ui/app.py`) | local `_require_token` | header only | `require_local_token` (header-only) |
| `sf-config-compare` (`app.py`) | `check_local_token` | header only | preserves caller-defined denial status |
| `sf-config-compare-ec` (`app.py` + `core/api.py`) | `check_local_token` | header only | preserves caller-defined denial status |
| `sf-metadata-vault` (`app.py`) | `check_local_token` | header only | preserves caller-defined denial status |

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
* **Read paths** (report endpoints) may stay on `check_local_token` when
  they intentionally remain open without a configured token. It accepts only
  the configured header and logs rejected query-string attempts.
* New shared Flask blueprints default to `require_local_token`; only fall
  back to `check_local_token` when the endpoint is read-only and its
  open-when-unconfigured behaviour is required.
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
