"""Exceptions for the Anova API library."""


class AnovaException(Exception):
    """Base exception for Anova API."""


class AnovaAuthError(AnovaException):
    """Raised when authentication fails (wrong credentials or a revoked sign-in)."""


class AnovaConnectionError(AnovaException):
    """Raised when Anova's cloud can't be reached or the WebSocket isn't connected."""


class AnovaTimeoutError(AnovaException):
    """Raised when a command gets no response in time."""


class AnovaCommandError(AnovaException):
    """Raised when the device rejects a command."""


class AnovaValidationError(AnovaException):
    """Raised when a setting is outside what the device accepts (see the limits modules)."""
