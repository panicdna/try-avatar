#!/usr/bin/env python3
"""Shared HTTP error types and default base URL for backup_avatar.py and restore_avatar.py.

Both scripts talk to the same Agent Factory API over urllib and need the same
reached-the-server-but-got-an-error vs never-reached-the-server distinction. Keep that
vocabulary here so it doesn't drift into two near-identical copies.
"""

from __future__ import annotations

DEFAULT_BASE_URL = "https://agent.samsungds.net:3355/api/v1/agent"


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: bytes) -> None:
        super().__init__(f"{method} {path} -> {status}")
        self.method = method
        self.path = path
        self.status = status
        self.body = body


class NetworkError(RuntimeError):
    """A request never reached the server (connection refused, DNS failure, timeout, ...)."""

    def __init__(self, method: str, path: str, cause: BaseException) -> None:
        super().__init__(f"{method} {path} failed: {cause}")
        self.method = method
        self.path = path
        self.cause = cause
