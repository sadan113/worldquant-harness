"""Typed identities, events, and execution results for the WQ agent core."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ..expression_parser import normalize_expression
from ..wq_efficiency import candidate_uid as build_candidate_uid
from ..wq_efficiency import normalized_efficiency_settings, settings_hash
from ..wq_failure_memory import expression_hash

SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def stable_hash(value: Any, *, length: int = 32) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


@dataclass(frozen=True)
class RunScope:
    """Tenant and platform dimensions that isolate candidates and memory."""

    user_id: str | None = None
    account: str = "primary"
    region: str = "USA"
    universe: str = "TOP3000"
    delay: int = 1

    def __post_init__(self) -> None:
        if self.user_id:
            try:
                uuid.UUID(str(self.user_id))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"user_id must be a valid UUID, got {self.user_id!r}") from exc

    @property
    def owner_key(self) -> str:
        return f"user:{self.user_id}" if self.user_id else "local"

    @property
    def scope_key(self) -> str:
        return stable_hash(
            {
                "owner_key": self.owner_key,
                "account": self.account,
                "region": self.region.upper(),
                "universe": self.universe.upper(),
                "delay": int(self.delay),
            }
        )

    @classmethod
    def from_settings(
        cls,
        settings: dict[str, Any] | None,
        *,
        user_id: str | None = None,
    ) -> RunScope:
        normalized = normalized_efficiency_settings(settings)
        return cls(
            user_id=user_id,
            account=str(normalized["account"]),
            region=str(normalized["region"]),
            universe=str(normalized["universe"]),
            delay=int(normalized["delay"]),
        )


@dataclass(frozen=True)
class EffectiveSettings:
    account: str = "primary"
    region: str = "USA"
    universe: str = "TOP3000"
    delay: int = 1
    decay: int = 0
    neutralization: str = "SUBINDUSTRY"
    truncation: float = 0.08
    max_trade: str = "OFF"
    max_position: str = "OFF"

    @classmethod
    def from_mapping(cls, settings: dict[str, Any] | None) -> EffectiveSettings:
        normalized = normalized_efficiency_settings(settings)
        return cls(
            account=str(normalized["account"]),
            region=str(normalized["region"]),
            universe=str(normalized["universe"]),
            delay=int(normalized["delay"]),
            decay=int(normalized["decay"]),
            neutralization=str(normalized["neutralization"]),
            truncation=float(normalized["truncation"]),
            max_trade=str(normalized["maxTrade"]),
            max_position=str(normalized["maxPosition"]),
        )

    def to_platform_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "region": self.region,
            "universe": self.universe,
            "delay": self.delay,
            "decay": self.decay,
            "neutralization": self.neutralization,
            "truncation": self.truncation,
            "maxTrade": self.max_trade,
            "maxPosition": self.max_position,
        }


@dataclass(frozen=True)
class CandidateIdentity:
    expression: str
    expression_normalized: str
    expression_hash: str
    settings: EffectiveSettings
    settings_hash: str
    candidate_uid: str

    @classmethod
    def create(cls, expression: str, settings: EffectiveSettings) -> CandidateIdentity:
        text = str(expression or "").strip()
        settings_dict = settings.to_platform_dict()
        return cls(
            expression=text,
            expression_normalized=normalize_expression(text),
            expression_hash=expression_hash(text),
            settings=settings,
            settings_hash=settings_hash(settings_dict),
            candidate_uid=build_candidate_uid(text, settings_dict),
        )


def attempt_uid(run_id: str, candidate_uid: str, attempt_no: int = 1) -> str:
    return stable_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": str(run_id),
            "candidate_uid": str(candidate_uid),
            "attempt_no": int(attempt_no),
        }
    )


class EventType(str, Enum):
    CANDIDATE_CREATED = "candidate_created"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_REJECTED = "validation_rejected"
    SIMULATION_STARTED = "simulation_started"
    SIMULATION_SUCCEEDED = "simulation_succeeded"
    SIMULATION_FAILED = "simulation_failed"
    CHECK_STARTED = "check_started"
    CHECK_SUCCEEDED = "check_succeeded"
    CHECK_BLOCKED = "check_blocked"
    READY = "ready"
    SUBMIT_STARTED = "submit_started"
    SUBMIT_SUCCEEDED = "submit_succeeded"
    SUBMIT_FAILED = "submit_failed"
    SUBMISSION_PENDING = "submission_pending"
    ACTIVE_CONFIRMED = "active_confirmed"
    ARTIFACT_IMPORTED = "artifact_imported"


TERMINAL_EVENT_TYPES = {
    EventType.VALIDATION_REJECTED.value,
    EventType.SIMULATION_FAILED.value,
    EventType.CHECK_BLOCKED.value,
    EventType.READY.value,
    EventType.SUBMIT_FAILED.value,
    EventType.SUBMISSION_PENDING.value,
    EventType.SUBMIT_SUCCEEDED.value,
    EventType.ACTIVE_CONFIRMED.value,
}


@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    event_type: str
    occurred_at: str
    run_id: str
    attempt_uid: str
    candidate_uid: str
    scope_key: str
    owner_key: str
    account: str
    region: str
    universe: str
    delay: int
    stage: str
    payload: dict[str, Any] = field(default_factory=dict)
    alpha_id: str | None = None
    user_id: str | None = None
    source_artifact: str | None = None
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        event_type: EventType | str,
        *,
        run_id: str,
        attempt_uid: str,
        candidate: CandidateIdentity,
        scope: RunScope,
        stage: str,
        payload: dict[str, Any] | None = None,
        alpha_id: str | None = None,
        source_artifact: str | None = None,
        event_key: str | None = None,
        occurred_at: str | None = None,
    ) -> AgentEvent:
        event_value = event_type.value if isinstance(event_type, EventType) else str(event_type)
        identity = event_key or f"{attempt_uid}:{event_value}"
        return cls(
            event_id=stable_hash({"schema_version": SCHEMA_VERSION, "event_key": identity}, length=48),
            event_type=event_value,
            occurred_at=occurred_at or utc_now(),
            run_id=str(run_id),
            attempt_uid=str(attempt_uid),
            candidate_uid=candidate.candidate_uid,
            scope_key=scope.scope_key,
            owner_key=scope.owner_key,
            user_id=scope.user_id,
            account=scope.account,
            region=scope.region,
            universe=scope.universe,
            delay=scope.delay,
            alpha_id=str(alpha_id) if alpha_id else None,
            stage=str(stage),
            payload=dict(payload or {}),
            source_artifact=source_artifact,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionPolicy:
    self_correlation_cutoff: float = 0.70
    submit_enabled: bool = False
    check_polls: int = 4
    check_interval: int = 10
    max_submit_retries: int = 1


@dataclass
class ExecutionResult:
    status: str
    candidate: CandidateIdentity
    attempt_uid: str
    alpha_id: str | None = None
    simulation_row: dict[str, Any] | None = None
    check_row: dict[str, Any] | None = None
    submit_row: dict[str, Any] | None = None
    resumed: bool = False
    reason: str | None = None

    @property
    def active(self) -> bool:
        return self.status == "ACTIVE"

    @property
    def ready(self) -> bool:
        return self.status == "READY"
