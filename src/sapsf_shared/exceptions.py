"""Exception hierarchy for sapsf-shared.

All errors inherit from SFError for easy catching across tools.
"""


class SFError(Exception):
    """Base exception for all SAP SF SDK errors."""

    def __init__(self, message: str, *, details: str | None = None) -> None:
        super().__init__(message)
        self.details = details


class SFConfigError(SFError):
    """Raised when configuration is missing or invalid."""


class SFClientError(SFError):
    """Raised when an OData API call fails unrecoverably."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str = "",
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.url = url


class AuthError(SFError):
    """Raised when authentication cannot be established."""
