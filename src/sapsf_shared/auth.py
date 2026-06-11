"""Authentication layer for SAP SuccessFactors OData APIs.

Supports three auth methods:
  - basic:       HTTP Basic Auth (username + password)
  - oauth2:      OAuth 2.0 client credentials grant
  - certificate: Mutual TLS with client cert + private key

Credential storage uses the OS keyring when available; falls back to a
local chmod-600 JSON file on headless systems (WSL, CI, etc.).
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from requests.auth import AuthBase, HTTPBasicAuth

from sapsf_shared.exceptions import AuthError

logger = logging.getLogger(__name__)

_DEFAULT_KEYRING_SERVICE = "sapsf_shared"


def _detect_keyring(service: str) -> bool:
    """Probe whether a keyring backend is functional."""
    try:
        import keyring as _keyring

        _keyring.get_password(service, "__probe__")
        return True
    except Exception:
        return False


class CredentialStore:
    """Secure credential storage with keyring fallback to a local JSON file.

    Usage:
        store = CredentialStore(service="my_tool")
        store.set("prd:password", "secret123")
        pwd = store.get("prd:password")
    """

    def __init__(
        self,
        *,
        service: str = _DEFAULT_KEYRING_SERVICE,
        fallback_path: Path | None = None,
    ) -> None:
        self.service = service
        self._use_keyring = _detect_keyring(service)
        if not self._use_keyring:
            logger.warning(
                "No keyring backend available; using local fallback file "
                "(chmod 600 applied)."
            )
        self._fallback = fallback_path or (
            Path(__file__).parent.parent.parent / ".secrets.json"
        )

    # ------------------------------------------------------------------
    # Internal file helpers
    # ------------------------------------------------------------------

    def _file_load(self) -> dict[str, str]:
        if self._fallback.exists():
            try:
                return json.loads(self._fallback.read_text())
            except Exception:
                return {}
        return {}

    def _file_save(self, data: dict[str, str]) -> None:
        tmp = Path(str(self._fallback) + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self._fallback)
        try:
            os.chmod(self._fallback, 0o600)
        except OSError as exc:
            logger.warning("chmod 600 on %s failed: %s", self._fallback, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, key: str, value: str) -> None:
        """Persist *value* under *key*."""
        if self._use_keyring:
            import keyring as _keyring

            _keyring.set_password(self.service, key, value)
        else:
            data = self._file_load()
            data[key] = value
            self._file_save(data)

    def get(self, key: str) -> str | None:
        """Retrieve the value for *key* or None."""
        if self._use_keyring:
            import keyring as _keyring

            return _keyring.get_password(self.service, key)
        return self._file_load().get(key)

    def delete(self, key: str) -> None:
        """Remove *key* from storage."""
        if self._use_keyring:
            import keyring as _keyring

            with contextlib.suppress(Exception):
                _keyring.delete_password(self.service, key)
        else:
            data = self._file_load()
            data.pop(key, None)
            self._file_save(data)

    def clear_alias(self, alias: str) -> None:
        """Delete all keys scoped to *alias*."""
        for suffix in ("password", "client_secret"):
            self.delete(f"{alias}:{suffix}")


# ── OAuth bearer auth ─────────────────────────────────────────────────────

class _BearerAuth(AuthBase):
    """Attaches an OAuth 2.0 Bearer token to every request."""

    def __init__(self, token: str) -> None:
        self._token = token

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        r.headers["Authorization"] = f"Bearer {self._token}"
        return r


# ── Auth config dataclass ─────────────────────────────────────────────────

@dataclass
class AuthConfig:
    """Immutable authentication configuration for a single SF tenant.

    Fields map cleanly onto the form fields used across your Flask UIs.
    """

    base_url: str
    company_id: str = ""
    auth_type: str = "basic"  # basic | oauth2 | certificate
    username: str = ""
    password: str = ""
    client_id: str = ""
    client_secret: str = ""
    token_url: str = ""
    cert_path: str = ""
    key_path: str = ""
    timeout_sec: int = 30

    # Optional store for persisting / retrieving secrets
    store: CredentialStore = field(default_factory=CredentialStore)

    # ── Validation ─────────────────────────────────────────────────────

    def validate(self) -> None:
        """Raise AuthError if required fields are missing."""
        if not self.base_url.startswith(("https://", "http://")):
            raise AuthError(
                "base_url must start with https:// or http://",
                details=f"got: {self.base_url}",
            )

        if self.auth_type == "basic":
            if not self.username:
                raise AuthError("username is required for basic auth")
            if not self.password:
                raise AuthError("password is required for basic auth")

        elif self.auth_type == "oauth2":
            if not self.client_id:
                raise AuthError("client_id is required for OAuth 2.0")
            if not self.client_secret:
                raise AuthError("client_secret is required for OAuth 2.0")
            if not self.company_id:
                raise AuthError("company_id is required for OAuth 2.0")
            if not self.token_url:
                # Auto-derive from base_url
                parsed = urllib.parse.urlparse(self.base_url)
                self.token_url = f"{parsed.scheme}://{parsed.netloc}/oauth/token"
                logger.debug("Auto-derived token_url: %s", self.token_url)

        elif self.auth_type == "certificate":
            if not self.cert_path or not Path(self.cert_path).is_file():
                raise AuthError(
                    f"cert_path does not exist: {self.cert_path}"
                )
            if not self.key_path or not Path(self.key_path).is_file():
                raise AuthError(
                    f"key_path does not exist: {self.key_path}"
                )
        else:
            raise AuthError(
                f"Unknown auth_type '{self.auth_type}'. "
                "Must be one of: basic, oauth2, certificate"
            )

    # ── Persistence helpers (store / load via keyring/file) ────────────

    def save_secrets(self) -> None:
        """Persist password or client_secret for this config's base_url."""
        alias = self._alias()
        if self.auth_type == "basic" and self.password:
            self.store.set(f"{alias}:password", self.password)
        elif self.auth_type == "oauth2" and self.client_secret:
            self.store.set(f"{alias}:client_secret", self.client_secret)

    def load_secrets(self) -> None:
        """Hydrate password / client_secret from the credential store."""
        alias = self._alias()
        if self.auth_type == "basic":
            stored = self.store.get(f"{alias}:password")
            if stored:
                self.password = stored
        elif self.auth_type == "oauth2":
            stored = self.store.get(f"{alias}:client_secret")
            if stored:
                self.client_secret = stored

    def _alias(self) -> str:
        """Derive a short alias from base_url for keyring keys."""
        parsed = urllib.parse.urlparse(self.base_url)
        return parsed.netloc.replace(":", "_")


# ── Auth builder classes ──────────────────────────────────────────────────

class BasicAuth:
    """Builds an HTTPBasicAuth instance + headers from an AuthConfig."""

    @staticmethod
    def build(config: AuthConfig) -> HTTPBasicAuth:
        config.validate()
        # SuccessFactors convention: username@company_id
        if config.company_id and "@" not in config.username:
            user = f"{config.username}@{config.company_id}"
        else:
            user = config.username
        logger.debug("Building BasicAuth for user=%s", user.split("@")[0])
        return HTTPBasicAuth(user, config.password)


class OAuth2Auth:
    """Fetches an OAuth 2.0 access token via client-credentials grant."""

    @staticmethod
    def fetch_token(config: AuthConfig) -> str:
        config.validate()
        payload = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "company_id": config.company_id,
            }
        ).encode()

        req = urllib.request.Request(
            config.token_url, data=payload, method="POST"
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, timeout=config.timeout_sec) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise AuthError(
                f"OAuth token request failed: HTTP {exc.code}",
                details=body,
            ) from exc
        except Exception as exc:
            raise AuthError(f"OAuth token request failed: {exc}") from exc

        token = data.get("access_token")
        if not token:
            raise AuthError(
                "OAuth response missing access_token",
                details=str(data)[:500],
            )
        logger.debug("OAuth token obtained from %s", config.token_url)
        return token

    @staticmethod
    def build(config: AuthConfig) -> _BearerAuth:
        token = OAuth2Auth.fetch_token(config)
        return _BearerAuth(token)


class CertificateAuth:
    """Validates that cert/key files exist. The actual cert tuple is
    passed directly to requests.Session.cert."""

    @staticmethod
    def build(config: AuthConfig) -> tuple[str, str]:
        config.validate()
        return (config.cert_path, config.key_path)


# ── Unified auth builder ──────────────────────────────────────────────────

def build_requests_auth(config: AuthConfig) -> tuple[Any, Any]:
    """Return (auth_object, cert_tuple) compatible with requests.Session.

    For basic  → (HTTPBasicAuth, None)
    For oauth2 → (_BearerAuth, None)
    For cert   → (None, (cert_path, key_path))
    """
    if config.auth_type == "basic":
        return BasicAuth.build(config), None
    elif config.auth_type == "oauth2":
        return OAuth2Auth.build(config), None
    elif config.auth_type == "certificate":
        return None, CertificateAuth.build(config)
    else:
        raise AuthError(f"Unsupported auth_type: {config.auth_type}")


def build_auth_headers(config: AuthConfig) -> dict[str, str]:
    """Return a dict of Authorization headers for urllib-based callers.

    This is used by tools that prefer urllib over requests (e.g. sf-audit).
    """
    if config.auth_type == "basic":
        config.validate()
        if config.company_id and "@" not in config.username:
            credential_str = f"{config.username}@{config.company_id}:{config.password}"
        else:
            credential_str = f"{config.username}:{config.password}"
        encoded = base64.b64encode(credential_str.encode("utf-8")).decode("utf-8")
        return {"Authorization": f"Basic {encoded}"}

    elif config.auth_type == "oauth2":
        token = OAuth2Auth.fetch_token(config)
        return {"Authorization": f"Bearer {token}"}

    else:
        raise AuthError(
            f"build_auth_headers does not support auth_type={config.auth_type}"
        )
