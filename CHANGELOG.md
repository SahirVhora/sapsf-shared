# Changelog

All notable changes to `sapsf-shared` are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-08-23

### Added
- Versioned assurance and engagement-pack schemas, validation helpers, and
  synthetic examples for exchanging aggregate evidence between tools.
- RBP permission catalogue, role and assignment models, and permission scan
  reporting.
- Tenant snapshot storage, comparison helpers, audit logging, trusted
  pagination validation, retry helpers, and the `sf` command-line entry point.
- Header-first local-token controls and lazy top-level access to Flask helpers.

### Security
- **Fix OData injection in `$filter` builders.** `SFClient.get_entity_by_code()`
  and `build_odata_filter()` interpolated values into OData `$filter`
  expressions without escaping single quotes, allowing query manipulation and
  breaking on benign values (e.g. `O'Brien`). Added `odata_escape()` (doubles
  `'` per the OData v2 spec) and applied it at both call sites. Users on 0.1.0
  should upgrade.
- Prevent ambiguous write retries, constrain pagination URLs to the configured
  tenant, enforce CORS/CSRF and local-token boundaries, redact credentials from
  logs, use timing-safe token comparison, and create fallback credential files
  atomically with mode `0600`.

### Changed
- Add connection pooling, OAuth token caching, streamed iteration, structured
  SuccessFactors error handling, and explicit transient-read retry semantics.
- Parse XML through `defusedxml` and expose the new APIs from the package root
  without importing Flask for non-web consumers.
- Tests run from a clean checkout without an editable install.

## [0.1.0] - 2026-06-11

### Added
- Initial release: OData v2 `SFClient`, `AuthConfig` (basic / OAuth2 /
  certificate), `CredentialStore` (keyring with chmod-600 fallback), config
  loading, Flask base, and reporting utilities.
