"""Exception classes for entity intelligence services."""


class GPTConfigError(Exception):
    """Raised when GPT configuration is missing or invalid."""
    pass


class GPTServiceError(Exception):
    """Raised when GPT API call fails."""
    pass


class GoogleSearchError(Exception):
    """Raised when Google search fails."""
    pass


class SOSDataError(Exception):
    """Raised when SOS data retrieval fails."""
    pass

