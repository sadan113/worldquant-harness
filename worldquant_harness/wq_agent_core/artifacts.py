"""Compatibility JSONL exports for canonical WQ agent events."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifact_io import append_jsonl
from .domain import AgentEvent, EventType


class JsonlArtifactObserver:
    """Export newly committed events to the legacy operational artifacts."""

    def __init__(self, paths: dict[str, Path]) -> None:
        self.paths = paths

    def on_event(self, event: AgentEvent, record: dict[str, Any] | None = None) -> None:
        append_jsonl(self.paths["agent_events"], event.to_dict())
        if record is None:
            return
        exported = {
            **record,
            "event_id": event.event_id,
            "run_id": event.run_id,
            "attempt_uid": event.attempt_uid,
            "candidate_uid": event.candidate_uid,
        }
        target = self._target(event)
        if target:
            append_jsonl(target, exported)

    def _target(self, event: AgentEvent) -> Path | None:
        if event.event_type in {
            EventType.VALIDATION_REJECTED.value,
            EventType.SIMULATION_SUCCEEDED.value,
            EventType.SIMULATION_FAILED.value,
        }:
            return self.paths["simulation_results"]
        if event.stage == "check" and event.event_type in {
            EventType.CHECK_SUCCEEDED.value,
            EventType.CHECK_BLOCKED.value,
        }:
            return self.paths["check_results"]
        if event.event_type in {
            EventType.SUBMIT_SUCCEEDED.value,
            EventType.SUBMIT_FAILED.value,
            EventType.SUBMISSION_PENDING.value,
            EventType.ACTIVE_CONFIRMED.value,
        }:
            return self.paths["submit_results"]
        return None
