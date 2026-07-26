"""sapsf-shared - Shared Python SDK for SAP SuccessFactors tools.

Note on top-level imports: the Flask helpers (``check_local_token``,
``require_local_token``) live in ``sapsf_shared.flask_base`` which imports
``flask``. They are NOT imported eagerly here; instead they are exposed
through PEP 562 module-level ``__getattr__`` so consumers reaching only for
auth-/config- side helpers do not pay the Flask import cost. They remain
findable via ``from sapsf_shared import require_local_token`` per ADR-0003.
"""

from typing import Any

from sapsf_shared.assurance import (
    ASSURANCE_SCHEMA,
    AssuranceValidationError,
    new_assurance_document,
    validate_assurance_document,
)
from sapsf_shared.audit import audit, audit_log
from sapsf_shared.auth import (
    AuthConfig,
    AuthError,
    BasicAuth,
    CertificateAuth,
    CredentialStore,
    OAuth2Auth,
    build_auth_headers,
    build_requests_auth,
)
from sapsf_shared.client import SFClient
from sapsf_shared.config import SFEnvConfig, load_config, load_yaml
from sapsf_shared.exceptions import AmbiguousWriteError, SFClientError, SFConfigError, SFError
from sapsf_shared.logging_config import CredentialRedactionFilter, setup_logging
from sapsf_shared.pagination import trusted_pagination_url
from sapsf_shared.permissions import (
    PermissionAnalyzer,
    PermissionCatalogue,
    PermissionRole,
    PermissionScanReport,
    UserRoleAssignment,
)
from sapsf_shared.retry import get_with_retry
from sapsf_shared.snapshot import (
    SnapshotDiff,
    SnapshotRef,
    SnapshotStore,
    parse_only,
)
from sapsf_shared.utils import (
    build_odata_filter,
    flatten_record,
    is_active_today,
    odata_escape,
    parse_sf_date,
)

# Lazy-imported Flask helpers: the sapsf_shared.flask_base module pulls in
# ``flask``. We expose them through the top-level namespace (findable via
# ``from sapsf_shared import require_local_token``) but defer the actual
# import so consumers that only need auth-/config- side helpers don't pay
# the Flask import cost. ``__getattr__`` is the PEP 562 mechanism for
# module-level lazy attribute resolution.
_LAZY_ATTRS = frozenset({"check_local_token", "require_local_token"})


def __getattr__(name: str) -> Any:  # pragma: no cover - introspection helper
    if name in _LAZY_ATTRS:
        from sapsf_shared import flask_base

        return getattr(flask_base, name)
    raise AttributeError(f"module 'sapsf_shared' has no attribute {name!r}")


def __dir__() -> list[str]:  # pragma: no cover - introspection helper
    return sorted(set(globals()) | set(__all__) | _LAZY_ATTRS)


__all__ = [
    "ASSURANCE_SCHEMA",
    "AssuranceValidationError",
    "audit",
    "audit_log",
    "AmbiguousWriteError",
    "AuthConfig",
    "AuthError",
    "BasicAuth",
    "CertificateAuth",
    "CredentialStore",
    "CredentialRedactionFilter",
    "OAuth2Auth",
    "PermissionAnalyzer",
    "PermissionCatalogue",
    "PermissionRole",
    "PermissionScanReport",
    "SFClient",
    "SFEnvConfig",
    "SFClientError",
    "SFConfigError",
    "SFError",
    "SnapshotDiff",
    "SnapshotRef",
    "SnapshotStore",
    "UserRoleAssignment",
    "build_auth_headers",
    "build_odata_filter",
    "build_requests_auth",
    "flatten_record",
    "get_with_retry",
    "is_active_today",
    "load_config",
    "load_yaml",
    "new_assurance_document",
    "odata_escape",
    "parse_sf_date",
    "parse_only",
    "setup_logging",
    "trusted_pagination_url",
    "validate_assurance_document",
]
