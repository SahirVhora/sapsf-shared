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


class AmbiguousWriteError(SFClientError):
    """Raised when a write may have succeeded but no definitive response was received.

    Retrying such a request automatically could duplicate a create or apply a
    mutation twice. Callers should reconcile the target state before deciding
    whether to retry.
    """

    def __init__(
        self,
        message: str,
        *,
        method: str,
        status_code: int | None = None,
        body: str = "",
        url: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, body=body, url=url)
        self.method = method


class AuthError(SFError):
    """Raised when authentication cannot be established."""
