"""Security regression tests for trusted OData pagination."""

from unittest.mock import MagicMock, patch

import pytest

from sapsf_shared.auth import AuthConfig
from sapsf_shared.client import SFClient
from sapsf_shared.exceptions import SFClientError


@pytest.fixture
def client():
    return SFClient(
        AuthConfig(
            base_url="https://api.example.com/odata/v2",
            username="user",
            password="pass",
            auth_type="basic",
        )
    )


def _page(results, next_url=None):
    response = MagicMock()
    response.status_code = 200
    data = {"results": results}
    if next_url is not None:
        data["__next"] = next_url
    response.json.return_value = {"d": data}
    return response


class TestTrustedPagination:
    @patch("sapsf_shared.client.requests.Session.request")
    def test_accepts_same_origin_absolute_next_link(self, request, client):
        request.side_effect = [
            _page([{"id": "1"}], "https://api.example.com/odata/v2/User?$skiptoken=abc"),
            _page([{"id": "2"}]),
        ]

        assert [row["id"] for row in client.get("User")] == ["1", "2"]

    @patch("sapsf_shared.client.requests.Session.request")
    def test_accepts_relative_next_link_and_resolves_it_on_tenant(self, request, client):
        request.side_effect = [
            _page([{"id": "1"}], "/odata/v2/User?$skiptoken=abc"),
            _page([{"id": "2"}]),
        ]

        assert [row["id"] for row in client.get("User")] == ["1", "2"]
        assert (
            request.call_args_list[1].args[1]
            == "https://api.example.com/odata/v2/User?$skiptoken=abc"
        )

    @pytest.mark.parametrize(
        "next_url",
        [
            "https://attacker.example/collect",
            "http://api.example.com/odata/v2/User?$skiptoken=abc",
            "https://api.example.com.evil.test/odata/v2/User",
            "https://user:pass@api.example.com/odata/v2/User",
            "https://api.example.com/private/path",
            "//attacker.example/collect",
        ],
    )
    @patch("sapsf_shared.client.requests.Session.request")
    def test_rejects_untrusted_next_link_before_second_request(self, request, next_url, client):
        request.side_effect = [
            _page([{"id": "1"}], next_url),
            AssertionError("untrusted pagination URL was requested"),
        ]

        with pytest.raises(SFClientError, match="pagination"):
            client.get("User")

        request.assert_called_once()

    @patch("sapsf_shared.client.requests.Session.request")
    def test_rejects_pagination_cycle(self, request, client):
        repeated = "https://api.example.com/odata/v2/User?$skiptoken=abc"
        request.side_effect = [_page([{"id": "1"}], repeated), _page([{"id": "2"}], repeated)]

        with pytest.raises(SFClientError, match="cycle"):
            client.get("User")

        assert request.call_count == 2

    @patch("sapsf_shared.client.requests.Session.request")
    def test_get_iter_applies_same_origin_guard(self, request, client):
        request.return_value = _page([{"id": "1"}], "https://attacker.example/collect")

        with pytest.raises(SFClientError, match="pagination"):
            list(client.get_iter("User"))

        request.assert_called_once()

    @patch("sapsf_shared.client.requests.Session.request")
    def test_credentialed_requests_disable_redirects(self, request, client):
        request.return_value = _page([])

        client.get("User")

        assert request.call_args.kwargs["allow_redirects"] is False

    @patch("sapsf_shared.client.requests.Session.request")
    def test_redirect_response_fails_closed(self, request, client):
        response = MagicMock()
        response.status_code = 302
        response.headers = {"Location": "https://attacker.example/collect"}
        response.text = ""
        request.return_value = response

        with pytest.raises(SFClientError, match="redirect"):
            client.get("User")
