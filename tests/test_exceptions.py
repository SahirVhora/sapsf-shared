"""Tests for sapsf_shared.exceptions."""


from sapsf_shared.exceptions import (
    AuthError,
    SFClientError,
    SFConfigError,
    SFError,
)


class TestSFError:
    def test_message(self):
        exc = SFError("Something went wrong")
        assert str(exc) == "Something went wrong"
        assert exc.details is None

    def test_message_with_details(self):
        exc = SFError("Auth failed", details="Invalid credentials")
        assert str(exc) == "Auth failed"
        assert exc.details == "Invalid credentials"

    def test_inheritance(self):
        assert issubclass(SFConfigError, SFError)
        assert issubclass(AuthError, SFError)
        assert issubclass(SFClientError, SFError)


class TestSFClientError:
    def test_status_code(self):
        exc = SFClientError("Not found", status_code=404)
        assert exc.status_code == 404
        assert str(exc) == "Not found"

    def test_url(self):
        exc = SFClientError("Failed", status_code=500, url="https://api.example.com")
        assert exc.url == "https://api.example.com"

    def test_body(self):
        exc = SFClientError("Error", body="Internal server error")
        assert exc.body == "Internal server error"


class TestSFConfigError:
    def test_message(self):
        exc = SFConfigError("Missing base_url")
        assert str(exc) == "Missing base_url"


class TestAuthError:
    def test_message(self):
        exc = AuthError("Invalid credentials")
        assert str(exc) == "Invalid credentials"
