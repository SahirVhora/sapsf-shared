"""sapsf-shared — Shared Python SDK for SAP SuccessFactors tools."""

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
from sapsf_shared.exceptions import SFClientError, SFConfigError, SFError
from sapsf_shared.logging_config import setup_logging
from sapsf_shared.utils import (
    build_odata_filter,
    flatten_record,
    is_active_today,
    odata_escape,
    parse_sf_date,
)

__all__ = [
    "AuthConfig",
    "AuthError",
    "BasicAuth",
    "CertificateAuth",
    "CredentialStore",
    "OAuth2Auth",
    "SFClient",
    "SFEnvConfig",
    "SFClientError",
    "SFConfigError",
    "SFError",
    "build_auth_headers",
    "build_odata_filter",
    "build_requests_auth",
    "flatten_record",
    "is_active_today",
    "load_config",
    "load_yaml",
    "odata_escape",
    "parse_sf_date",
    "setup_logging",
]
