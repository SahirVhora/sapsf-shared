"""Tests for sapsf_shared.client."""

import json
from unittest.mock import MagicMock, patch

import pytest

from sapsf_shared.auth import AuthConfig
from sapsf_shared.client import SFClient
from sapsf_shared.exceptions import SFClientError


@pytest.fixture
def auth_config():
    return AuthConfig(
        base_url="https://api.example.com",
        username="user",
        password="pass",
        auth_type="basic",
    )


class TestSFClientInit:
    def test_init(self, auth_config):
        client = SFClient(auth_config, default_top=50)
        # SFClient normalises base_url to append /odata/v2 (unless already
        # present) so downstream code can hit the OData endpoint directly.
        assert client.base_url == "https://api.example.com/odata/v2"
        assert client.default_top == 50
        assert client.config == auth_config

    def test_trailing_slash_removed(self, auth_config):
        auth_config.base_url = "https://api.example.com/"
        client = SFClient(auth_config)
        assert client.base_url == "https://api.example.com/odata/v2"

    def test_existing_odata_path_preserved(self, auth_config):
        # If the user already supplies an /odata path we keep it as-is
        # rather than appending /odata/v2 a second time.
        auth_config.base_url = "https://api.example.com/odata/v2/"
        client = SFClient(auth_config)
        assert client.base_url == "https://api.example.com/odata/v2"


class TestUrlHelper:
    def test_url(self, auth_config):
        client = SFClient(auth_config)
        # _url("Users") is appended to the (already /odata/v2) base_url.
        assert client._url("Users") == "https://api.example.com/odata/v2/Users"


class TestRequestWithRetry:
    @patch("sapsf_shared.client.requests.Session.request")
    def test_success_no_retry(self, mock_request, auth_config):
        mock_request.return_value.status_code = 200
        client = SFClient(auth_config)
        resp = client._request_with_retry("GET", "https://api.example.com/Users")
        assert resp.status_code == 200
        mock_request.assert_called_once()

    @patch("sapsf_shared.client.requests.Session.request")
    def test_retry_on_429(self, mock_request, auth_config):
        bad = MagicMock()
        bad.status_code = 429
        good = MagicMock()
        good.status_code = 200
        mock_request.side_effect = [bad, good]

        client = SFClient(auth_config)
        resp = client._request_with_retry("GET", "https://api.example.com/Users")
        assert resp.status_code == 200
        assert mock_request.call_count == 2

    @patch("sapsf_shared.client.requests.Session.request")
    def test_all_retries_exhausted(self, mock_request, auth_config):
        bad = MagicMock()
        bad.status_code = 503
        mock_request.return_value = bad

        client = SFClient(auth_config)
        resp = client._request_with_retry("GET", "https://api.example.com/Users")
        # After 3 retries, returns the last response
        assert resp.status_code == 503
        assert mock_request.call_count == 3


class TestCheckResponse:
    def test_401_raises(self, auth_config):
        client = SFClient(auth_config)
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        with pytest.raises(SFClientError) as exc:
            client._check_response(resp, "https://api.example.com/Users")
        assert exc.value.status_code == 401
        assert "Authentication failed" in str(exc.value)

    def test_403_raises(self, auth_config):
        client = SFClient(auth_config)
        resp = MagicMock()
        resp.status_code = 403
        resp.text = "Forbidden"
        with pytest.raises(SFClientError) as exc:
            client._check_response(resp, "https://api.example.com/Users")
        assert exc.value.status_code == 403

    def test_500_raises(self, auth_config):
        client = SFClient(auth_config)
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Server Error"
        with pytest.raises(SFClientError) as exc:
            client._check_response(resp, "https://api.example.com/Users")
        assert exc.value.status_code == 500

    def test_invalid_json_raises(self, auth_config):
        client = SFClient(auth_config)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = json.JSONDecodeError("bad", "", 0)
        resp.text = "not json"
        with pytest.raises(SFClientError) as exc:
            client._check_response(resp, "https://api.example.com/Users")
        assert "Non-JSON response" in str(exc.value)

    def test_valid_json(self, auth_config):
        client = SFClient(auth_config)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"d": {"results": []}}
        result = client._check_response(resp, "https://api.example.com/Users")
        assert result == {"d": {"results": []}}


class TestGet:
    @patch("sapsf_shared.client.requests.Session.request")
    def test_get_with_params(self, mock_request, auth_config):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"d": {"results": [{"id": "1"}]}}

        client = SFClient(auth_config)
        results = client.get("Users", select=["userId"], filter_expr="status eq 'A'")
        assert len(results) == 1
        assert results[0]["id"] == "1"
        call_kwargs = mock_request.call_args[1]
        assert "params" in call_kwargs
        assert call_kwargs["params"]["$select"] == "userId"
        assert call_kwargs["params"]["$filter"] == "status eq 'A'"


class TestPagination:
    @patch("sapsf_shared.client.requests.Session.request")
    def test_single_page(self, mock_request, auth_config):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"d": {"results": [{"id": "1"}, {"id": "2"}]}}

        client = SFClient(auth_config)
        results = client.get("Users")
        assert len(results) == 2

    @patch("sapsf_shared.client.requests.Session.request")
    def test_follows_next_link(self, mock_request, auth_config):
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "d": {
                "results": [{"id": "1"}],
                "__next": "https://api.example.com/Users?$skip=1",
            }
        }
        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {"d": {"results": [{"id": "2"}]}}

        mock_request.side_effect = [page1, page2]
        client = SFClient(auth_config)
        results = client.get("Users")
        assert len(results) == 2
        assert results[0]["id"] == "1"
        assert results[1]["id"] == "2"


class TestGetEntityByCode:
    @patch("sapsf_shared.client.requests.Session.request")
    def test_get_entity_by_code(self, mock_request, auth_config):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"d": {"results": [{"externalCode": "IT"}]}}

        client = SFClient(auth_config)
        results = client.get_entity_by_code("FODepartment", "IT", expand="parent")
        assert len(results) == 1
        call_kwargs = mock_request.call_args[1]
        assert "parent" in call_kwargs["params"]["$expand"]


class TestPost:
    @patch("sapsf_shared.client.requests.Session.request")
    def test_post(self, mock_request, auth_config):
        mock_request.return_value.status_code = 201
        mock_request.return_value.json.return_value = {"d": {"userId": "2"}}

        client = SFClient(auth_config)
        status, body = client.post("Users", {"userId": "2", "firstName": "Alice"})
        assert status == 201
        assert body["d"]["userId"] == "2"


class TestPatch:
    @patch("sapsf_shared.client.requests.Session.request")
    def test_patch(self, mock_request, auth_config):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {}

        client = SFClient(auth_config)
        status, body = client.patch("Users", {"firstName": "Bob"})
        assert status == 200


class TestDelete:
    @patch("sapsf_shared.client.requests.Session.request")
    def test_delete(self, mock_request, auth_config):
        mock_request.return_value.status_code = 204

        client = SFClient(auth_config)
        status = client.delete("Users", "2")
        assert status == 204
        call_args = mock_request.call_args
        assert call_args[0][0] == "DELETE"
        assert "('2')" in call_args[0][1]


class TestEntityExists:
    @patch("sapsf_shared.client.requests.Session.request")
    def test_exists(self, mock_request, auth_config):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"d": {"results": [{"externalCode": "IT"}]}}

        client = SFClient(auth_config)
        exists, record = client.entity_exists("FODepartment", "IT")
        assert exists is True
        assert record["externalCode"] == "IT"

    @patch("sapsf_shared.client.requests.Session.request")
    def test_not_exists(self, mock_request, auth_config):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"d": {"results": []}}

        client = SFClient(auth_config)
        exists, record = client.entity_exists("FODepartment", "HR")
        assert exists is False
        assert record is None


class TestTestConnection:
    @patch("sapsf_shared.client.requests.Session.request")
    def test_success(self, mock_request, auth_config):
        mock_request.return_value.status_code = 200
        client = SFClient(auth_config)
        ok, msg = client.test_connection()
        assert ok is True
        assert "Connected" in msg

    @patch("sapsf_shared.client.requests.Session.request")
    def test_failure(self, mock_request, auth_config):
        mock_request.return_value.status_code = 500
        mock_request.return_value.text = ""
        client = SFClient(auth_config)
        ok, msg = client.test_connection()
        assert ok is False
        assert "HTTP 500" in msg

    @patch("sapsf_shared.client.requests.Session.request")
    def test_failure_includes_sf_error_body(self, mock_request, auth_config):
        """SF returns XML like <error><message>[LGN0015] auth failed</message></error>.
        The message should be surfaced, not swallowed."""
        mock_request.return_value.status_code = 401
        mock_request.return_value.text = (
            '<error xmlns="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
            "<code>LGN0015</code>"
            "<message xml:lang=\"en\">Authentication failed. You have entered an incorrect username or password.</message>"
            "</error>"
        )
        client = SFClient(auth_config)
        ok, msg = client.test_connection()
        assert ok is False
        assert "HTTP 401" in msg
        assert "LGN0015" in msg
        assert "Authentication failed" in msg

    @patch("sapsf_shared.client.requests.Session.request")
    def test_failure_plain_text_body(self, mock_request, auth_config):
        mock_request.return_value.status_code = 502
        mock_request.return_value.text = "Bad Gateway"
        client = SFClient(auth_config)
        ok, msg = client.test_connection()
        assert ok is False
        assert "HTTP 502" in msg
        assert "Bad Gateway" in msg

    @patch("sapsf_shared.client.requests.Session.request")
    def test_failure_truncates_long_body(self, mock_request, auth_config):
        mock_request.return_value.status_code = 500
        mock_request.return_value.text = "x" * 5000
        client = SFClient(auth_config)
        ok, msg = client.test_connection()
        assert ok is False
        assert "HTTP 500" in msg
        assert len(msg) < 260  # 240 char combined + "HTTP 500 - " prefix


class TestContextManager:
    def test_enter_exit(self, auth_config):
        with SFClient(auth_config) as client:
            assert client._session is not None
        # After exit, session should be closed (no error means success)
