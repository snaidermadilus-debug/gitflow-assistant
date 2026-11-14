"""Service-level exceptions mapped to CLI exit codes by the interface layer."""

from __future__ import annotations


class ServiceError(RuntimeError):
    """Base class for service errors."""

    exit_code = 1


class UsageError(ServiceError):
    """Missing or contradictory arguments (e.g. non-interactive without required options)."""

    exit_code = 2


class ProjectRequired(ServiceError):
    """No project was selected or the path is not a git repository."""

    exit_code = 4


class SecurityBlocked(ServiceError):
    """Publication blocked by security findings."""

    exit_code = 6


class RemoteOperationFailed(ServiceError):
    """Network, authentication or rejection errors talking to a remote."""

    exit_code = 7


class Cancelled(ServiceError):
    """The user cancelled the operation."""

    exit_code = 5
