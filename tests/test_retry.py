"""Tests for sapsf_shared.retry.get_with_retry.

Covers the three failure modes SF integrations hit in the field: throttling
(429), transient server errors (5xx), and connection-level failures (timeouts
/ resets) -- plus confirming non-retryable responses (2xx, 4xx other than
429) pass through on the first attempt with no delay.

Mocking style mirrors TestRequestWithRetry in test_client.py: patch
`requests.get` directly with MagicMock responses / side_effect sequences,
rather than pulling in an extra HTTP-mocking dependency.
"""

from unittest.mock import MagicMock, patch

import requests

from sapsf_shared.client import MAX_RETRIES
from sapsf_shared.retry import get_with_retry


@patch("sapsf_shared.retry.requests.get")
def test_success_on_first_attempt_no_sleep(mock_get):
    mock_get.return_value = MagicMock(status_code=200)

    with patch("sapsf_shared.retry.time.sleep") as mock_sleep:
        resp = get_with_retry("https://example.com/thing")

    assert resp.status_code == 200
    mock_sleep.assert_not_called()
    mock_get.assert_called_once()
    assert mock_get.call_args.kwargs["allow_redirects"] is False


@patch("sapsf_shared.retry.requests.get")
def test_caller_cannot_enable_redirects_for_credentialed_retry(mock_get):
    mock_get.return_value = MagicMock(status_code=302)

    get_with_retry("https://example.com/thing", allow_redirects=True)

    assert mock_get.call_args.kwargs["allow_redirects"] is False


@patch("sapsf_shared.retry.requests.get")
def test_non_retryable_4xx_passes_through_immediately(mock_get):
    mock_get.return_value = MagicMock(status_code=404)

    with patch("sapsf_shared.retry.time.sleep") as mock_sleep:
        resp = get_with_retry("https://example.com/thing")

    assert resp.status_code == 404
    mock_sleep.assert_not_called()
    mock_get.assert_called_once()


@patch("sapsf_shared.retry.requests.get")
def test_retries_on_429_then_succeeds(mock_get):
    bad = MagicMock(status_code=429)
    good = MagicMock(status_code=200)
    mock_get.side_effect = [bad, good]

    with patch("sapsf_shared.retry.time.sleep") as mock_sleep:
        resp = get_with_retry("https://example.com/thing")

    assert resp.status_code == 200
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1)  # first backoff step


@patch("sapsf_shared.retry.requests.get")
def test_exhausts_retries_on_persistent_5xx_returns_last_response(mock_get):
    mock_get.return_value = MagicMock(status_code=503)

    with patch("sapsf_shared.retry.time.sleep"):
        resp = get_with_retry("https://example.com/thing")

    assert resp.status_code == 503
    assert mock_get.call_count == MAX_RETRIES


@patch("sapsf_shared.retry.requests.get")
def test_connection_error_is_retried_then_raised_if_persistent(mock_get):
    mock_get.side_effect = requests.exceptions.ConnectionError("boom")

    with patch("sapsf_shared.retry.time.sleep"):
        try:
            get_with_retry("https://example.com/thing")
            raised = False
        except requests.exceptions.ConnectionError:
            raised = True

    assert raised is True
    assert mock_get.call_count == MAX_RETRIES


@patch("sapsf_shared.retry.requests.get")
def test_connection_error_then_recovers(mock_get):
    mock_get.side_effect = [
        requests.exceptions.ConnectionError("boom"),
        MagicMock(status_code=200),
    ]

    with patch("sapsf_shared.retry.time.sleep"):
        resp = get_with_retry("https://example.com/thing")

    assert resp.status_code == 200
    assert mock_get.call_count == 2
