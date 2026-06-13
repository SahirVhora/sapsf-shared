# Changelog

All notable changes to `sapsf-shared` are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-06-13

### Security
- **Fix OData injection in `$filter` builders.** `SFClient.get_entity_by_code()`
  and `build_odata_filter()` interpolated values into OData `$filter`
  expressions without escaping single quotes, allowing query manipulation and
  breaking on benign values (e.g. `O'Brien`). Added `odata_escape()` (doubles
  `'` per the OData v2 spec) and applied it at both call sites. Users on 0.1.0
  should upgrade.

### Added
- `odata_escape()` helper, exported from the package root.

### Changed
- Tests run from a clean checkout without an editable install
  (`pythonpath = ["src"]` in the pytest config).

## [0.1.0] - 2026-06-11

### Added
- Initial release: OData v2 `SFClient`, `AuthConfig` (basic / OAuth2 /
  certificate), `CredentialStore` (keyring with chmod-600 fallback), config
  loading, Flask base, and reporting utilities.
