"""Executor adapter package scaffold."""

from .hosted import HostedExecutor
from .acpx import AcpxExecutor, AcpxExecutorSession
from .codex import CodexExecutor, CodexExecutorSession
from .mock import MockExecutor, MockExecutorConfig, MockExecutorSession
from .hermes import HermesExecutor, HermesExecutorSession

__all__ = [
    "HostedExecutor",
    "AcpxExecutor",
    "AcpxExecutorSession",
    "CodexExecutor",
    "CodexExecutorSession",
    "MockExecutor",
    "MockExecutorConfig",
    "MockExecutorSession",
    "HermesExecutor",
    "HermesExecutorSession",
]
