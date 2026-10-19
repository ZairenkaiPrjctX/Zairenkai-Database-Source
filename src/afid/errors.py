"""Error types. Every CLI failure maps to one of these and to an exit code."""

from __future__ import annotations


class AfidError(Exception):
    """Base class. `exit_code` is what the CLI returns for this error."""

    exit_code = 1


class ConfigError(AfidError):
    exit_code = 2


class ValidationError(AfidError):
    exit_code = 3


class ToolMissingError(AfidError):
    """A required external tool is not installed."""

    exit_code = 4

    def __init__(self, tool: str, purpose: str, install_hint: str) -> None:
        super().__init__(f"required tool '{tool}' not found ({purpose}). Install: {install_hint}")
        self.tool = tool


class UnsafeArchiveError(AfidError):
    """Archive member would escape the extraction root, or limits were exceeded."""

    exit_code = 5


class CorruptArchiveError(AfidError):
    exit_code = 11


class UnsupportedFormatError(AfidError):
    exit_code = 6


class ProviderError(AfidError):
    exit_code = 7


class CapabilityError(ProviderError):
    """The provider does not support the requested operation."""

    exit_code = 8


class PolicyViolationError(AfidError):
    exit_code = 9


class NotFoundError(AfidError):
    exit_code = 10


class ResourceError(AfidError):
    """Not enough disk, inodes or memory for the requested work, or a budget was exceeded."""

    exit_code = 13
