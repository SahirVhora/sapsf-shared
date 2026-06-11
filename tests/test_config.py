"""Tests for sapsf_shared.config."""

import json
from pathlib import Path

import pytest

from sapsf_shared.config import SFEnvConfig, load_config, load_json, load_yaml
from sapsf_shared.exceptions import SFConfigError


class TestLoadYaml:
    def test_load_yaml(self, tmp_path: Path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("base_url: https://api.example.com\nusername: u\n")
        result = load_yaml(cfg_path)
        assert result["base_url"] == "https://api.example.com"
        assert result["username"] == "u"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(SFConfigError) as exc:
            load_yaml(tmp_path / "missing.yaml")
        assert "not found" in str(exc.value).lower()

    def test_env_substitution(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MY_VAR", "resolved_value")
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("secret: ${MY_VAR}\n")
        result = load_yaml(cfg_path)
        assert result["secret"] == "resolved_value"


class TestLoadJson:
    def test_load_json(self, tmp_path: Path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"base_url": "https://api.example.com"}))
        result = load_json(cfg_path)
        assert result["base_url"] == "https://api.example.com"

    def test_invalid_json_raises(self, tmp_path: Path):
        cfg_path = tmp_path / "bad.json"
        cfg_path.write_text("not json")
        with pytest.raises(SFConfigError):
            load_json(cfg_path)


class TestLoadConfig:
    def test_auto_detects_json(self, tmp_path: Path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"key": "val"}))
        result = load_config(cfg_path)
        assert result["key"] == "val"

    def test_auto_detects_yaml(self, tmp_path: Path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("key: val\n")
        result = load_config(cfg_path)
        assert result["key"] == "val"

    def test_unsupported_extension_raises(self, tmp_path: Path):
        cfg_path = tmp_path / "config.txt"
        cfg_path.write_text("a=b")
        with pytest.raises(SFConfigError) as exc:
            load_config(cfg_path)
        assert "Unsupported" in str(exc.value)


class TestSFEnvConfig:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("SF_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("SF_USERNAME", "user")
        monkeypatch.setenv("SF_PASSWORD", "pass")
        cfg = SFEnvConfig.from_env()
        assert cfg.base_url == "https://api.example.com"
        assert cfg.username == "user"
        assert cfg.password == "pass"
        assert cfg.auth_type == "basic"
        assert cfg.timeout_sec == 30

    def test_from_env_with_prefix(self, monkeypatch):
        monkeypatch.setenv("MYAPP_BASE_URL", "https://api.example.com")
        cfg = SFEnvConfig.from_env(prefix="MYAPP")
        assert cfg.base_url == "https://api.example.com"

    def test_from_env_legacy_instance_id(self, monkeypatch):
        monkeypatch.setenv("SF_INSTANCE_ID", "MYCO")
        cfg = SFEnvConfig.from_env()
        assert cfg.company_id == "MYCO"

    def test_validate_missing_base_url_raises(self):
        cfg = SFEnvConfig()
        with pytest.raises(SFConfigError) as exc:
            cfg.validate()
        assert "base_url" in str(exc.value)

    def test_validate_invalid_base_url_raises(self):
        cfg = SFEnvConfig(base_url="ftp://example.com")
        with pytest.raises(SFConfigError) as exc:
            cfg.validate()
        assert "https://" in str(exc.value)

    def test_to_auth_config(self, monkeypatch):
        monkeypatch.setenv("SF_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("SF_USERNAME", "user")
        monkeypatch.setenv("SF_PASSWORD", "pass")
        env_cfg = SFEnvConfig.from_env()
        auth_cfg = env_cfg.to_auth_config()
        assert auth_cfg.base_url == "https://api.example.com"
        assert auth_cfg.username == "user"
        assert auth_cfg.password == "pass"
