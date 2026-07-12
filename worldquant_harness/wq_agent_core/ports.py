"""Ports used by the canonical WQ execution engine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from .domain import AgentEvent, CandidateIdentity, EffectiveSettings, RunScope


class PlatformGateway(Protocol):
    def simulate(
        self,
        expression: str,
        settings: EffectiveSettings,
        *,
        tag: str | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict[str, Any]: ...

    def check(self, alpha_id: str, *, max_polls: int, interval: int) -> dict[str, Any]: ...

    def submit(self, alpha_id: str) -> dict[str, Any]: ...

    def status(self, alpha_id: str) -> dict[str, Any]: ...


class AgentRepository(Protocol):
    def append(self, event: AgentEvent, candidate: CandidateIdentity) -> bool: ...

    def append_many(self, items: list[tuple[AgentEvent, CandidateIdentity]]) -> int: ...

    def events_for_attempt(self, attempt_uid: str) -> list[dict[str, Any]]: ...

    def query_memory(
        self,
        scope: RunScope,
        *,
        limit: int = 50,
        failure_kinds: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...


class ExecutionObserver(Protocol):
    def on_event(self, event: AgentEvent, record: dict[str, Any] | None = None) -> None: ...
