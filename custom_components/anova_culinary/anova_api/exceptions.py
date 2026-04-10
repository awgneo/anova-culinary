"""Exceptions for the Anova API library."""

class AnovaException(Exception):
    """Base exception for Anova API."""
    pass

class AnovaAuthError(AnovaException):
    """Raised when authentication fails (invalid PAT)."""
    pass

class AnovaConnectionError(AnovaException):
    """Raised when the WebSocket connection fails."""
    pass

class AnovaTimeoutError(AnovaException):
    """Raised when a command times out."""
    pass

class AnovaCommandError(AnovaException):
    """Raised when the device returns an error for a command."""
    pass
