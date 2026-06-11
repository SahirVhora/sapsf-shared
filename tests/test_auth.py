"""Tests for sapsf_shared.auth."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from sapsf_shared.auth import (
    AuthConfig,
    BasicAuth,
    CertificateAuth,
    CredentialStore,
    OAuth2Auth,
    _BearerAuth,
    build_auth_headers,
    build_requests_auth,
)
from sapsf_shared.exceptions import AuthError


class TestCredentialStore:
    def test_inits_without_keyring(self, tmp_path):
        store = CredentialStore(fallback_path=tmp_path / "secrets.json")
        assert store.service == "sapsf_shared"
        assert not store._use_keyring

    def test_file_save_and_load(self, tmp_path):
        store = CredentialStore(fallback_path=tmp_path / "secrets.json")
        store.set("key1", "val1")
        assert store.get("key1") == "val1"
        store.delete("key1")
        assert store.get("key1") is None

    def test_clear_alias(self, tmp_path):
        store = CredentialStore(fallback_path=tmp_path / "secrets.json")
        store.set("example.com:password", "pwd")
        store.set("example.com:client_secret", "sec")
        store.clear_alias("example.com")
        assert store.get("example.com:password") is None
        assert store.get("example.com:client_secret") is None


class TestBearerAuth:
    def test_applies_header(self):
        auth = _BearerAuth("mytoken")
        req = MagicMock()
        req.headers = {}
        result = auth(req)
        assert result.headers["Authorization"] == "Bearer mytoken"


class TestAuthConfig:
    def test_basic_validation(self):
        cfg = AuthConfig(
            base_url="https://api.example.com",
            username="user",
            password="pass",
            auth_type="basic",
        )
        cfg.validate()
        assert cfg.auth_type == "basic"

    def test_basic_missing_username_raises(self):
        cfg = AuthConfig(base_url="https://api.example.com", auth_type="basic")
        with pytest.raises(AuthError) as exc:
            cfg.validate()
        assert "username" in str(exc.value)

    def test_basic_missing_password_raises(self):
        cfg = AuthConfig(
            base_url="https://api.example.com", username="u", auth_type="basic"
        )
        with pytest.raises(AuthError) as exc:
            cfg.validate()
        assert "password" in str(exc.value)

    def test_oauth_auto_derives_token_url(self):
        cfg = AuthConfig(
            base_url="https://api.example.com",
            auth_type="oauth2",
            client_id="cid",
            client_secret="sec",
            company_id="MYCO",
        )
        cfg.validate()
        assert cfg.token_url == "https://api.example.com/oauth/token"

    def test_oauth_missing_company_id_raises(self):
        cfg = AuthConfig(
            base_url="https://api.example.com",
            auth_type="oauth2",
            client_id="cid",
            client_secret="sec",
        )
        with pytest.raises(AuthError) as exc:
            cfg.validate()
        assert "company_id" in str(exc.value)

    def test_certificate_missing_cert_raises(self):
        cfg = AuthConfig(
            base_url="https://api.example.com",
            auth_type="certificate",
        )
        with pytest.raises(AuthError) as exc:
            cfg.validate()
        assert "cert_path" in str(exc.value)

    def test_unknown_auth_type_raises(self):
        cfg = AuthConfig(
            base_url="https://api.example.com", auth_type="unknown"
        )
        with pytest.raises(AuthError) as exc:
            cfg.validate()
        assert "Unknown auth_type" in str(exc.value)

    def test_invalid_base_url_raises(self):
        cfg = AuthConfig(base_url="ftp://example.com")
        with pytest.raises(AuthError) as exc:
            cfg.validate()
        assert "base_url" in str(exc.value)

    def test_alias_from_base_url(self):
        cfg = AuthConfig(base_url="https://api.example.com:443")
        assert cfg._alias() == "api.example.com_443"

    def test_save_and_load_secrets(self, tmp_path):
        cfg = AuthConfig(
            base_url="https://api.example.com",
            username="u",
            password="secret",
            auth_type="basic",
            store=CredentialStore(fallback_path=tmp_path / "secrets.json"),
        )
        cfg.save_secrets()
        cfg2 = AuthConfig(
            base_url="https://api.example.com",
            username="u",
            auth_type="basic",
            store=CredentialStore(fallback_path=tmp_path / "secrets.json"),
        )
        cfg2.load_secrets()
        assert cfg2.password == "secret"


class TestBasicAuthBuilder:
    def test_build_with_company_id(self):
        cfg = AuthConfig(
            base_url="https://api.example.com",
            username="user",
            password="pass",
            company_id="MYCO",
            auth_type="basic",
        )
        auth = BasicAuth.build(cfg)
        assert auth.username == "user@MYCO"

    def test_build_without_company_id(self):
        cfg = AuthConfig(
            base_url="https://api.example.com",
            username="user@MYCO",
            password="pass",
            auth_type="basic",
        )
        auth = BasicAuth.build(cfg)
        assert auth.username == "user@MYCO"


class TestOAuth2Auth:
    @patch("sapsf_shared.auth.urllib.request.urlopen")
    def test_fetch_token_success(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = json.dumps(
            {"access_token": "tok123"}
        ).encode()
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda *a: None
        mock_urlopen.return_value.read = resp.read

        cfg = AuthConfig(
            base_url="https://api.example.com",
            auth_type="oauth2",
            client_id="cid",
            client_secret="sec",
            company_id="MYCO",
            token_url="https://api.example.com/oauth/token",
        )
        token = OAuth2Auth.fetch_token(cfg)
        assert token == "tok123"

    @patch("sapsf_shared.auth.urllib.request.urlopen")
    def test_fetch_token_missing_token_raises(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = json.dumps({"error": "invalid"}).encode()
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda *a: None
        mock_urlopen.return_value.read = resp.read

        cfg = AuthConfig(
            base_url="https://api.example.com",
            auth_type="oauth2",
            client_id="cid",
            client_secret="sec",
            company_id="MYCO",
            token_url="https://api.example.com/oauth/token",
        )
        with pytest.raises(AuthError) as exc:
            OAuth2Auth.fetch_token(cfg)
        assert "access_token" in str(exc.value)

    @patch("sapsf_shared.auth.urllib.request.urlopen")
    def test_build_returns_bearer_auth(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = json.dumps(
            {"access_token": "tok123"}
        ).encode()
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda *a: None
        mock_urlopen.return_value.read = resp.read

        cfg = AuthConfig(
            base_url="https://api.example.com",
            auth_type="oauth2",
            client_id="cid",
            client_secret="sec",
            company_id="MYCO",
            token_url="https://api.example.com/oauth/token",
        )
        auth = OAuth2Auth.build(cfg)
        assert isinstance(auth, _BearerAuth)


class TestCertificateAuth:
    def test_build_returns_tuple(self, tmp_path):
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("cert")
        key.write_text("key")
        cfg = AuthConfig(
            base_url="https://api.example.com",
            auth_type="certificate",
            cert_path=str(cert),
            key_path=str(key),
        )
        result = CertificateAuth.build(cfg)
        assert result == (str(cert), str(key))


class TestBuildRequestsAuth:
    def test_basic(self):
        cfg = AuthConfig(
            base_url="https://api.example.com",
            username="u",
            password="p",
            auth_type="basic",
        )
        auth, cert = build_requests_auth(cfg)
        assert auth is not None
        assert cert is None

    def test_oauth2(self):
        with patch("sapsf_shared.auth.urllib.request.urlopen") as mock_urlopen:
            resp = MagicMock()
            resp.read.return_value = json.dumps(
                {"access_token": "tok123"}
            ).encode()
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda *a: None
            mock_urlopen.return_value.read = resp.read

            cfg = AuthConfig(
                base_url="https://api.example.com",
                auth_type="oauth2",
                client_id="cid",
                client_secret="sec",
                company_id="MYCO",
                token_url="https://api.example.com/oauth/token",
            )
            auth, cert = build_requests_auth(cfg)
            assert isinstance(auth, _BearerAuth)
            assert cert is None

    def test_certificate(self, tmp_path):
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("cert")
        key.write_text("key")
        cfg = AuthConfig(
            base_url="https://api.example.com",
            auth_type="certificate",
            cert_path=str(cert),
            key_path=str(key),
        )
        auth, cert_tuple = build_requests_auth(cfg)
        assert auth is None
        assert cert_tuple == (str(cert), str(key))

    def test_unknown_raises(self):
        cfg = AuthConfig(
            base_url="https://api.example.com", auth_type="unknown"
        )
        with pytest.raises(AuthError):
            build_requests_auth(cfg)


class TestBuildAuthHeaders:
    def test_basic(self):
        cfg = AuthConfig(
            base_url="https://api.example.com",
            username="user",
            password="pass",
            auth_type="basic",
        )
        headers = build_auth_headers(cfg)
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")

    def test_basic_with_company_id(self):
        cfg = AuthConfig(
            base_url="https://api.example.com",
            username="user",
            password="pass",
            company_id="MYCO",
            auth_type="basic",
        )
        headers = build_auth_headers(cfg)
        decoded = base64.b64decode(headers["Authorization"].split()[1])
        assert decoded == b"user@MYCO:pass"

    @patch("sapsf_shared.auth.urllib.request.urlopen")
    def test_oauth2(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = json.dumps(
            {"access_token": "tok123"}
        ).encode()
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda *a: None
        mock_urlopen.return_value.read = resp.read

        cfg = AuthConfig(
            base_url="https://api.example.com",
            auth_type="oauth2",
            client_id="cid",
            client_secret="sec",
            company_id="MYCO",
            token_url="https://api.example.com/oauth/token",
        )
        headers = build_auth_headers(cfg)
        assert headers["Authorization"] == "Bearer tok123"
