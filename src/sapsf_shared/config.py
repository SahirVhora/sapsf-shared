"""Configuration loader for SAP SuccessFactors tools.

Supports:
  - YAML config files (with env-var substitution ${VAR_NAME})
  - JSON config files
  - Environment variable overrides
  - Typed dataclass for IDE autocomplete
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sapsf_shared.auth import AuthConfig
from sapsf_shared.exceptions import SFConfigError

_ENV_RE = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(value: Any) -> Any:
    """Recursively replace ${VAR_NAME} with os.environ values."""
    if isinstance(value, str):

        def _replacer(m: re.Match[str]) -> str:
            var_name = m.group(1)
            env_val = os.environ.get(var_name, "")
            return env_val

        return _ENV_RE.sub(_replacer, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML file and resolve ${ENV_VAR} placeholders."""
    p = Path(path)
    if not p.exists():
        raise SFConfigError(f"Config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text())
    except Exception as exc:
        raise SFConfigError(f"Failed to parse YAML {p}: {exc}") from exc
    if raw is None:
        return {}
    return _resolve_env_vars(raw)


def load_json(path: str | Path) -> dict[str, Any]:
    """Load a JSON file and resolve ${ENV_VAR} placeholders."""
    p = Path(path)
    if not p.exists():
        raise SFConfigError(f"Config file not found: {p}")
    try:
        raw = json.loads(p.read_text())
    except Exception as exc:
        raise SFConfigError(f"Failed to parse JSON {p}: {exc}") from exc
    return _resolve_env_vars(raw)


def load_config(path: str | Path) -> dict[str, Any]:
    """Auto-detect format from extension (.yaml / .yml / .json) and load."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return load_yaml(p)
    if suffix == ".json":
        return load_json(p)
    raise SFConfigError(f"Unsupported config format: {suffix}. Use .yaml or .json")


# ── Typed dataclass for common SF tool config ───────────────────────────


@dataclass
class SFEnvConfig:
    """Configuration shaped like the env-var patterns used across your tools.

    Example .env mapping:
        SF_BASE_URL     → base_url
        SF_USERNAME     → username
        SF_PASSWORD     → password
        SF_COMPANY_ID   → company_id
    """

    base_url: str = ""
    username: str = ""
    password: str = ""
    company_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    token_url: str = ""
    cert_path: str = ""
    key_path: str = ""
    auth_type: str = "basic"
    timeout_sec: int = 30

    @classmethod
    def from_env(cls, prefix: str = "SF") -> SFEnvConfig:
        """Build from environment variables with optional prefix.

        Looks for SF_BASE_URL, SF_USERNAME, etc.
        Also checks legacy names: SF_INSTANCE_ID → company_id.
        """
        return cls(
            base_url=os.environ.get(f"{prefix}_BASE_URL", ""),
            username=os.environ.get(f"{prefix}_USERNAME", ""),
            password=os.environ.get(f"{prefix}_PASSWORD", ""),
            company_id=os.environ.get(
                f"{prefix}_COMPANY_ID",
                os.environ.get(f"{prefix}_INSTANCE_ID", ""),
            ),
            client_id=os.environ.get(f"{prefix}_CLIENT_ID", ""),
            client_secret=os.environ.get(f"{prefix}_CLIENT_SECRET", ""),
            token_url=os.environ.get(f"{prefix}_TOKEN_URL", ""),
            cert_path=os.environ.get(f"{prefix}_CERT_PATH", ""),
            key_path=os.environ.get(f"{prefix}_KEY_PATH", ""),
            auth_type=os.environ.get(f"{prefix}_AUTH_TYPE", "basic").lower(),
            timeout_sec=int(os.environ.get(f"{prefix}_TIMEOUT_SEC", "30")),
        )

    def validate(self) -> None:
        """Raise SFConfigError if required fields are missing."""
        if not self.base_url:
            raise SFConfigError("base_url is required (set SF_BASE_URL)")
        if not self.base_url.startswith(("https://", "http://")):
            raise SFConfigError(
                f"base_url must start with https:// or http:// - got: {self.base_url}"
            )

    def to_auth_config(self) -> AuthConfig:
        """Convert to an AuthConfig for use with SFClient."""
        from sapsf_shared.auth import AuthConfig

        return AuthConfig(
            base_url=self.base_url,
            company_id=self.company_id,
            auth_type=self.auth_type,
            username=self.username,
            password=self.password,
            client_id=self.client_id,
            client_secret=self.client_secret,
            token_url=self.token_url,
            cert_path=self.cert_path,
            key_path=self.key_path,
            timeout_sec=self.timeout_sec,
        )
