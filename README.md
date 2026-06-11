# sapsf-shared

**Shared Python SDK for SAP SuccessFactors tools.**

A single, well-tested library that extracts the common patterns repeated across every SAP SF tool in your workspace: OData HTTP client, authentication, config loading, logging, utilities, and Flask boilerplate.

## Why this exists

Every SAP SF tool in your workspace reimplements:
- OData v2 HTTP client with retries and pagination
- Basic Auth / OAuth2 / Certificate auth handling
- Keyring vs file-based credential storage
- Config loader (YAML/JSON with env var substitution)
- Coloured logging setup
- Flask CSRF, error handlers, health endpoint

`sapsf-shared` consolidates all of this into one package. When you fix a bug in the auth layer, it's fixed everywhere.

## Installation

```bash
cd sapsf/_shared
pip install -e ".[dev,flask]"
```

## Quick Start

### 1. Connect to SAP SuccessFactors

```python
from sapsf_shared import AuthConfig, SFClient

config = AuthConfig(
    base_url="https://api4.successfactors.com/odata/v2",
    username="admin@companyId",
    password="secret",
    company_id="companyId",
    auth_type="basic",
)

with SFClient(config) as client:
    # Fetch all departments
    depts = client.get("FODepartment")
    print(f"Found {len(depts)} departments")

    # Fetch with filter and pagination
    positions = client.get(
        "Position",
        filter_expr="cust_Country eq 'GBR'",
        select=["code", "externalName", "cust_JobFunction"],
        expand=["cust_JobFunction"],
    )
```

### 2. OAuth 2.0

```python
config = AuthConfig(
    base_url="https://api4.successfactors.com/odata/v2",
    auth_type="oauth2",
    client_id="my_client_id",
    client_secret="my_secret",
    company_id="companyId",
)
with SFClient(config) as client:
    ok, msg = client.test_connection()
    print(ok, msg)
```

### 3. Secure credential storage

```python
from sapsf_shared.auth import CredentialStore

store = CredentialStore(service="my_tool")
store.set("prd:password", "secret123")
pwd = store.get("prd:password")
```

Automatically uses OS keyring when available; falls back to a chmod-600 JSON file on headless systems.

### 4. Config from YAML

```python
from sapsf_shared.config import load_config

cfg = load_config("config.yaml")
# Supports ${ENV_VAR} substitution inside the YAML file
```

### 5. Flask base app

```python
from sapsf_shared.flask_base import create_app

app = create_app(__name__, log_dir="logs", enable_csrf=True)

@app.route("/")
def index():
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(port=5050)
```

Comes with built-in:
- `/api/health` endpoint
- CSRF token generation + validation
- JSON error handlers (400, 403, 404, 500)
- CORS preflight support
- Rotating file logging

## API Reference

### `SFClient`

| Method | Description |
|--------|-------------|
| `get(entity_set, **kwargs)` | Fetch all records with auto-pagination |
| `get_entity_by_code(entity_set, external_code, **kwargs)` | Filter by externalCode |
| `post(entity_set, payload)` | Create a record |
| `patch(entity_set, payload)` | Update a record |
| `delete(entity_set, key)` | Delete a record |
| `test_connection()` | Quick connectivity probe |
| `entity_exists(entity_set, external_code)` | Check existence |

### `AuthConfig`

Dataclass that normalises auth settings across all your tools. Fields: `base_url`, `company_id`, `auth_type`, `username`, `password`, `client_id`, `client_secret`, `token_url`, `cert_path`, `key_path`, `timeout_sec`.

### `SFEnvConfig`

Loads configuration from environment variables with the standard `SF_*` prefix:

```bash
export SF_BASE_URL=https://api4.successfactors.com/odata/v2
export SF_USERNAME=admin
export SF_PASSWORD=secret
export SF_COMPANY_ID=companyId
```

```python
cfg = SFEnvConfig.from_env()
```

### `CredentialStore`

Keyring-backed secret storage with automatic fallback to a local `.secrets.json` file (chmod 600). Use `store.clear_alias(alias)` to delete all secrets for a tenant.

### Utilities

| Function | Description |
|----------|-------------|
| `parse_sf_date(raw)` | Parse `/Date(millis)/` and ISO formats |
| `is_active_today(record)` | Check effective dating + status |
| `flatten_record(record)` | Flatten nested OData for CSV export |
| `build_odata_filter(dict)` | Build `$filter` strings from dicts |

## Development

```bash
pip install -e ".[dev,flask]"
pytest -v                  # 13 tests
mypy src/sapsf_shared      # Type checking
ruff check src tests       # Linting
ruff format src tests      # Formatting
```

## Roadmap

- [ ] Vectorised batch operations (`upsert_many`, `delete_many`)
- [ ] Connection pooling tuning
- [ ] Async support (httpx-based client)
- [ ] SAP SF API v4 support

## License

MIT

## Adoption status

| Tool | Status |
|---|---|
| sf-config-compare | Adopted - `parse_sf_date` via `sapsf_shared.utils` |
| sf-position-integrity-checker | Next - client/pagination migration pending tenant testing |
| sf-object-sync | Planned |

Depend on it from any tool:

```
sapsf-shared @ git+https://github.com/SahirVhora/sapsf-shared
```
