"""Event repositories and deterministic projections for the WQ agent core."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from ..async_utils import run_coro_sync
from ..models import WQAgentEvent, WQCandidateState, WQMemoryItem
from ..record_utils import first_float
from ..wq_failure_taxonomy import audit_root_cause, canonical_failure_kind
from .domain import AgentEvent, CandidateIdentity, EffectiveSettings, EventType, RunScope, stable_hash

EVENT_STATUS = {
    EventType.CANDIDATE_CREATED.value: "candidate",
    EventType.VALIDATION_PASSED.value: "validated",
    EventType.VALIDATION_REJECTED.value: "validation_failed",
    EventType.SIMULATION_STARTED.value: "simulating",
    EventType.SIMULATION_SUCCEEDED.value: "simulated",
    EventType.SIMULATION_FAILED.value: "simulation_failed",
    EventType.CHECK_STARTED.value: "checking",
    EventType.CHECK_SUCCEEDED.value: "checked",
    EventType.CHECK_BLOCKED.value: "blocked",
    EventType.READY.value: "ready",
    EventType.SUBMIT_STARTED.value: "submitting",
    EventType.SUBMIT_SUCCEEDED.value: "active",
    EventType.SUBMIT_FAILED.value: "submit_failed",
    EventType.SUBMISSION_PENDING.value: "submission_pending",
    EventType.ACTIVE_CONFIRMED.value: "active",
    EventType.ARTIFACT_IMPORTED.value: "imported",
}

MEMORY_EVENTS = {
    EventType.VALIDATION_REJECTED.value,
    EventType.SIMULATION_FAILED.value,
    EventType.CHECK_BLOCKED.value,
    EventType.READY.value,
    EventType.SUBMIT_FAILED.value,
    EventType.SUBMISSION_PENDING.value,
    EventType.SUBMIT_SUCCEEDED.value,
    EventType.ACTIVE_CONFIRMED.value,
}

EVIDENCE_CONFIDENCE = {
    "platform_submit": 1.0,
    "platform_check": 0.95,
    "simulation": 0.85,
    "local_validation": 0.75,
    "artifact_import": 0.70,
    "forum": 0.35,
    "heuristic": 0.25,
}


class InMemoryAgentRepository:
    """Test repository with the same event idempotency contract as SQL."""

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.candidates: dict[tuple[str, str], dict[str, Any]] = {}
        self.memories: dict[tuple[str, str], dict[str, Any]] = {}

    def append(self, event: AgentEvent, candidate: CandidateIdentity) -> bool:
        if event.event_id in self.events:
            return False
        row = event.to_dict()
        self.events[event.event_id] = row
        key = (event.scope_key, event.candidate_uid)
        current = self.candidates.get(key, {})
        self.candidates[key] = _project_candidate_dict(current, event, candidate)
        memory = _memory_spec(event)
        if memory:
            memory_key = (event.scope_key, memory["memory_key"])
            existing = self.memories.get(memory_key)
            self.memories[memory_key] = _merge_memory_dict(existing, event, memory)
            for other_key, other in self.memories.items():
                if other_key == memory_key:
                    continue
                if (
                    other_key[0] == event.scope_key
                    and other.get("subject_key") == memory["subject_key"]
                    and other.get("memory_kind") == memory["memory_kind"]
                    and other.get("polarity") != memory["polarity"]
                    and other.get("state") == "active"
                ):
                    other["contradiction_count"] = int(other.get("contradiction_count") or 0) + 1
                    if memory["evidence_class"] == "platform_submit" and memory["polarity"] == "positive":
                        other["state"] = "superseded"
        return True

    def events_for_attempt(self, attempt_uid: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.events.values() if row.get("attempt_uid") == attempt_uid]

    def append_many(self, items: list[tuple[AgentEvent, CandidateIdentity]]) -> int:
        return sum(self.append(event, candidate) for event, candidate in items)

    def query_memory(
        self,
        scope: RunScope,
        *,
        limit: int = 50,
        failure_kinds: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        wanted = set(failure_kinds or [])
        rows = [
            dict(row)
            for (scope_key, _), row in self.memories.items()
            if scope_key == scope.scope_key
            and row.get("state") == "active"
            and (not wanted or row.get("failure_kind") in wanted)
        ]
        rows.sort(key=_memory_sort_key, reverse=True)
        return rows[: max(0, limit)]


class SqlAgentRepository:
    """Synchronous facade over the async SQLAlchemy event repository."""

    def append(self, event: AgentEvent, candidate: CandidateIdentity) -> bool:
        result = run_coro_sync(
            _append_with_db(event, candidate),
            timeout=30,
            timeout_message="timed out writing WQ agent event",
        )
        return bool(result)

    def events_for_attempt(self, attempt_uid: str) -> list[dict[str, Any]]:
        result = run_coro_sync(
            _events_for_attempt_with_db(attempt_uid),
            timeout=30,
            timeout_message="timed out reading WQ agent events",
        )
        return list(result or [])

    def append_many(self, items: list[tuple[AgentEvent, CandidateIdentity]]) -> int:
        result = run_coro_sync(
            _append_many_with_db(items),
            timeout=120,
            timeout_message="timed out writing WQ agent event batch",
        )
        return int(result or 0)

    def query_memory(
        self,
        scope: RunScope,
        *,
        limit: int = 50,
        failure_kinds: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        result = run_coro_sync(
            _query_memory_with_db(scope, limit=limit, failure_kinds=failure_kinds),
            timeout=30,
            timeout_message="timed out reading WQ memory projection",
        )
        return list(result or [])

    def rebuild_projections(self) -> dict[str, int]:
        result = run_coro_sync(
            _rebuild_projections_with_db(),
            timeout=300,
            timeout_message="timed out rebuilding WQ agent projections",
        )
        return dict(result or {})


async def _append_with_db(event: AgentEvent, candidate: CandidateIdentity) -> bool:
    from ..db import _get_session_factory, init_db

    await init_db()
    factory = _get_session_factory()
    async with factory() as session:
        try:
            if await session.get(WQAgentEvent, event.event_id) is not None:
                return False
            session.add(_event_model(event))
            await _project_candidate(session, event, candidate)
            await _project_memory(session, event)
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False
        except Exception:
            await session.rollback()
            raise


async def _events_for_attempt_with_db(attempt_uid: str) -> list[dict[str, Any]]:
    from ..db import _get_session_factory, init_db

    await init_db()
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(WQAgentEvent)
            .where(WQAgentEvent.attempt_uid == str(attempt_uid))
            .order_by(WQAgentEvent.occurred_at.asc(), WQAgentEvent.created_at.asc())
        )
        return [_event_row(row) for row in result.scalars().all()]


async def _append_many_with_db(items: list[tuple[AgentEvent, CandidateIdentity]]) -> int:
    from ..db import _get_session_factory, init_db

    if not items:
        return 0
    await init_db()
    unique: dict[str, tuple[AgentEvent, CandidateIdentity]] = {}
    for event, candidate in items:
        unique[event.event_id] = (event, candidate)
    factory = _get_session_factory()
    async with factory() as session:
        existing_result = await session.execute(
            select(WQAgentEvent.event_id).where(WQAgentEvent.event_id.in_(list(unique)))
        )
        existing = set(existing_result.scalars().all())
        pending_items = [pair for event_id, pair in unique.items() if event_id not in existing]
        scope_keys = {event.scope_key for event, _ in pending_items}
        candidate_uids = {event.candidate_uid for event, _ in pending_items}
        candidate_cache: dict[tuple[str, str], WQCandidateState] = {}
        memory_cache: dict[tuple[str, str], WQMemoryItem] = {}
        subject_memory_cache: dict[tuple[str, str, str], list[WQMemoryItem]] = {}
        if scope_keys and candidate_uids:
            candidate_result = await session.execute(
                select(WQCandidateState).where(
                    WQCandidateState.scope_key.in_(scope_keys),
                    WQCandidateState.candidate_uid.in_(candidate_uids),
                )
            )
            for state in candidate_result.scalars().all():
                candidate_cache[(state.scope_key, state.candidate_uid)] = state
            memory_result = await session.execute(
                select(WQMemoryItem).where(
                    WQMemoryItem.scope_key.in_(scope_keys),
                    WQMemoryItem.subject_key.in_(candidate_uids),
                )
            )
            for memory in memory_result.scalars().all():
                memory_cache[(memory.scope_key, memory.memory_key)] = memory
                subject_memory_cache.setdefault(
                    (memory.scope_key, memory.subject_key, memory.memory_kind),
                    [],
                ).append(memory)
        inserted = 0
        try:
            for event_id, (event, candidate) in unique.items():
                if event_id in existing:
                    continue
                session.add(_event_model(event))
                await _project_candidate(session, event, candidate, cache=candidate_cache)
                await _project_memory(
                    session,
                    event,
                    memory_cache=memory_cache,
                    subject_memory_cache=subject_memory_cache,
                )
                inserted += 1
            await session.commit()
            return inserted
        except Exception:
            await session.rollback()
            raise


async def _query_memory_with_db(
    scope: RunScope,
    *,
    limit: int,
    failure_kinds: list[str] | None,
) -> list[dict[str, Any]]:
    from ..db import _get_session_factory, init_db

    await init_db()
    stmt = select(WQMemoryItem).where(
        WQMemoryItem.scope_key == scope.scope_key,
        WQMemoryItem.state == "active",
    )
    if failure_kinds:
        stmt = stmt.where(WQMemoryItem.failure_kind.in_(list(failure_kinds)))
    stmt = stmt.order_by(
        WQMemoryItem.confidence.desc(),
        WQMemoryItem.support_count.desc(),
        WQMemoryItem.last_seen_at.desc(),
    ).limit(max(1, limit))
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(stmt)
        return [_memory_row(row) for row in result.scalars().all()]


async def _rebuild_projections_with_db() -> dict[str, int]:
    from ..db import _get_session_factory, init_db

    await init_db()
    factory = _get_session_factory()
    async with factory() as session:
        state_result = await session.execute(select(WQCandidateState))
        identity_by_key = {
            (state.scope_key, state.candidate_uid): CandidateIdentity.create(
                state.expression,
                _effective_settings(state.effective_settings, state),
            )
            for state in state_result.scalars().all()
        }
        event_result = await session.execute(
            select(WQAgentEvent).order_by(WQAgentEvent.occurred_at.asc(), WQAgentEvent.created_at.asc())
        )
        event_models = list(event_result.scalars().all())
        await session.execute(delete(WQMemoryItem))
        await session.execute(delete(WQCandidateState))
        candidate_cache: dict[tuple[str, str], WQCandidateState] = {}
        memory_cache: dict[tuple[str, str], WQMemoryItem] = {}
        subject_memory_cache: dict[tuple[str, str, str], list[WQMemoryItem]] = {}
        skipped = 0
        for model in event_models:
            event = AgentEvent(**_event_row(model))
            candidate = identity_by_key.get((event.scope_key, event.candidate_uid)) or _candidate_from_event(event)
            if candidate is None:
                skipped += 1
                continue
            await _project_candidate(session, event, candidate, cache=candidate_cache)
            await _project_memory(
                session,
                event,
                memory_cache=memory_cache,
                subject_memory_cache=subject_memory_cache,
            )
        await session.commit()
        return {
            "events_replayed": len(event_models) - skipped,
            "events_skipped": skipped,
            "candidate_states": len(candidate_cache),
            "memory_items": len(memory_cache),
        }


def _event_model(event: AgentEvent) -> WQAgentEvent:
    return WQAgentEvent(
        event_id=event.event_id,
        schema_version=event.schema_version,
        event_type=event.event_type,
        occurred_at=_parse_time(event.occurred_at),
        run_id=event.run_id,
        attempt_uid=event.attempt_uid,
        candidate_uid=event.candidate_uid,
        scope_key=event.scope_key,
        owner_key=event.owner_key,
        user_id=_uuid_or_none(event.user_id),
        account=event.account,
        region=event.region,
        universe=event.universe,
        delay=event.delay,
        alpha_id=event.alpha_id,
        stage=event.stage,
        payload=event.payload,
        source_artifact=event.source_artifact,
    )


async def _project_candidate(
    session: Any,
    event: AgentEvent,
    candidate: CandidateIdentity,
    *,
    cache: dict[tuple[str, str], WQCandidateState] | None = None,
) -> None:
    key = (event.scope_key, event.candidate_uid)
    if cache is None:
        result = await session.execute(
            select(WQCandidateState).where(
                WQCandidateState.scope_key == event.scope_key,
                WQCandidateState.candidate_uid == event.candidate_uid,
            ).limit(1)
        )
        state = result.scalar_one_or_none()
    else:
        state = cache.get(key)
    if state is None:
        state = WQCandidateState(
            scope_key=event.scope_key,
            owner_key=event.owner_key,
            user_id=_uuid_or_none(event.user_id),
            account=event.account,
            region=event.region,
            universe=event.universe,
            delay=event.delay,
            candidate_uid=event.candidate_uid,
            expression=candidate.expression,
            expression_normalized=candidate.expression_normalized,
            expression_hash=candidate.expression_hash,
            settings_hash=candidate.settings_hash,
            effective_settings=candidate.settings.to_platform_dict(),
            run_id=event.run_id,
            attempt_uid=event.attempt_uid,
            lifecycle_status="candidate",
            revision=0,
            metrics={},
            correlation={},
            failure={},
            source_meta={},
            latest_event_id=event.event_id,
        )
        session.add(state)
        if cache is not None:
            cache[key] = state
    _apply_event_to_state(state, event)


def _apply_event_to_state(state: WQCandidateState, event: AgentEvent) -> None:
    record = _event_record(event)
    state.latest_event_id = event.event_id
    state.revision = int(state.revision or 0) + 1
    next_status = EVENT_STATUS.get(event.event_type, state.lifecycle_status)
    apply_outcome = state.lifecycle_status != "active" or next_status == "active"
    if apply_outcome:
        state.run_id = event.run_id
        state.attempt_uid = event.attempt_uid
        state.lifecycle_status = next_status
        if event.alpha_id:
            state.alpha_id = event.alpha_id
        metrics = _metrics(record)
        if metrics:
            state.metrics = {**(state.metrics or {}), **metrics}
        correlation = _correlation(record)
        if correlation:
            state.correlation = {**(state.correlation or {}), **correlation}
        failure = _failure(record, event.event_type)
        if failure:
            state.failure = failure
        elif next_status in {"active", "ready"}:
            state.failure = {}
    source_meta = dict(state.source_meta or {})
    for key in (
        "tag",
        "source",
        "source_family",
        "field_signature",
        "provenance",
        "mutation_strategy",
        "rationale",
        "expected_low_corr_reason",
        "parent_alpha_ids",
        "source_run_id",
        "forum_evidence",
        "repair_evidence",
        "risk_flags",
    ):
        if event.payload.get(key) not in (None, "", [], {}):
            source_meta[key] = event.payload[key]
    state.source_meta = source_meta
    state.updated_at = _parse_time(event.occurred_at)


async def _project_memory(
    session: Any,
    event: AgentEvent,
    *,
    memory_cache: dict[tuple[str, str], WQMemoryItem] | None = None,
    subject_memory_cache: dict[tuple[str, str, str], list[WQMemoryItem]] | None = None,
) -> None:
    spec = _memory_spec(event)
    if not spec:
        return
    memory_key = (event.scope_key, spec["memory_key"])
    subject_key = (event.scope_key, spec["subject_key"], spec["memory_kind"])
    if memory_cache is None:
        result = await session.execute(
            select(WQMemoryItem).where(
                WQMemoryItem.scope_key == event.scope_key,
                WQMemoryItem.memory_key == spec["memory_key"],
            ).limit(1)
        )
        memory = result.scalar_one_or_none()
    else:
        memory = memory_cache.get(memory_key)
    occurred_at = _parse_time(event.occurred_at)
    if memory is None:
        memory = WQMemoryItem(
            memory_id=stable_hash({"scope_key": event.scope_key, "memory_key": spec["memory_key"]}, length=48),
            scope_key=event.scope_key,
            owner_key=event.owner_key,
            user_id=_uuid_or_none(event.user_id),
            account=event.account,
            region=event.region,
            universe=event.universe,
            delay=event.delay,
            memory_key=spec["memory_key"],
            memory_kind=spec["memory_kind"],
            subject_key=spec["subject_key"],
            candidate_uid=event.candidate_uid,
            failure_kind=spec["failure_kind"],
            severity=spec["severity"],
            evidence_class=spec["evidence_class"],
            polarity=spec["polarity"],
            confidence=spec["confidence"],
            support_count=1,
            contradiction_count=0,
            state="active",
            payload=spec["payload"],
            evidence_event_ids=[event.event_id],
            first_seen_at=occurred_at,
            last_seen_at=occurred_at,
        )
        session.add(memory)
        if memory_cache is not None:
            memory_cache[memory_key] = memory
        if subject_memory_cache is not None:
            subject_memory_cache.setdefault(subject_key, []).append(memory)
    else:
        previous_confidence = float(memory.confidence or 0.0)
        memory.support_count = int(memory.support_count or 0) + 1
        memory.confidence = max(float(memory.confidence or 0.0), float(spec["confidence"]))
        if float(spec["confidence"]) >= previous_confidence:
            memory.evidence_class = spec["evidence_class"]
        memory.last_seen_at = occurred_at
        memory.payload = spec["payload"]
        evidence = list(memory.evidence_event_ids or [])
        if event.event_id not in evidence:
            evidence.append(event.event_id)
        memory.evidence_event_ids = evidence[-50:]
        memory.state = "active"

    if subject_memory_cache is None:
        contradictions = await session.execute(
            select(WQMemoryItem).where(
                WQMemoryItem.scope_key == event.scope_key,
                WQMemoryItem.subject_key == spec["subject_key"],
                WQMemoryItem.memory_kind == spec["memory_kind"],
                WQMemoryItem.polarity != spec["polarity"],
                WQMemoryItem.state == "active",
            )
        )
        other_memories = contradictions.scalars().all()
    else:
        other_memories = subject_memory_cache.get(subject_key, [])
    for other in other_memories:
        if other.polarity == spec["polarity"] or other.state != "active":
            continue
        other.contradiction_count = int(other.contradiction_count or 0) + 1
        if spec["evidence_class"] == "platform_submit" and spec["polarity"] == "positive":
            other.state = "superseded"


def _memory_spec(event: AgentEvent) -> dict[str, Any] | None:
    if event.event_type not in MEMORY_EVENTS:
        return None
    record = _event_record(event)
    positive = event.event_type in {
        EventType.READY.value,
        EventType.SUBMIT_SUCCEEDED.value,
        EventType.ACTIVE_CONFIRMED.value,
    }
    failure_kind = "active" if event.event_type in {
        EventType.SUBMIT_SUCCEEDED.value,
        EventType.ACTIVE_CONFIRMED.value,
    } else "ready" if event.event_type == EventType.READY.value else _projected_failure_kind(record, event.event_type)
    evidence_class = _evidence_class(event)
    memory_kind = "candidate_outcome"
    subject_key = event.candidate_uid
    return {
        "memory_key": f"{memory_kind}:{subject_key}:{failure_kind}",
        "memory_kind": memory_kind,
        "subject_key": subject_key,
        "failure_kind": failure_kind,
        "severity": "positive" if positive else "block" if "correlation" in failure_kind else "penalize",
        "evidence_class": evidence_class,
        "polarity": "positive" if positive else "negative",
        "confidence": EVIDENCE_CONFIDENCE[evidence_class],
        "payload": {
            "event_type": event.event_type,
            "alpha_id": event.alpha_id,
            "record": record,
            "run_id": event.run_id,
            "source_artifact": event.source_artifact,
        },
    }


def _evidence_class(event: AgentEvent) -> str:
    override = str(event.payload.get("evidence_class_override") or "")
    if override in EVIDENCE_CONFIDENCE:
        return override
    event_type = event.event_type
    if event_type in {EventType.SUBMIT_SUCCEEDED.value, EventType.ACTIVE_CONFIRMED.value, EventType.SUBMIT_FAILED.value}:
        return "platform_submit"
    if event_type in {EventType.CHECK_BLOCKED.value, EventType.READY.value, EventType.SUBMISSION_PENDING.value}:
        return "platform_check"
    if event_type == EventType.SIMULATION_FAILED.value:
        return "simulation"
    if event_type == EventType.VALIDATION_REJECTED.value:
        return "local_validation"
    return "artifact_import"


def _project_candidate_dict(current: dict[str, Any], event: AgentEvent, candidate: CandidateIdentity) -> dict[str, Any]:
    out = dict(current)
    next_status = EVENT_STATUS.get(event.event_type, out.get("lifecycle_status", "candidate"))
    apply_outcome = out.get("lifecycle_status") != "active" or next_status == "active"
    out.update({
        "scope_key": event.scope_key,
        "candidate_uid": event.candidate_uid,
        "expression": candidate.expression,
        "settings": candidate.settings.to_platform_dict(),
        "latest_event_id": event.event_id,
        "revision": int(out.get("revision") or 0) + 1,
    })
    if apply_outcome:
        out.update({
            "run_id": event.run_id,
            "attempt_uid": event.attempt_uid,
            "alpha_id": event.alpha_id or out.get("alpha_id"),
            "lifecycle_status": next_status,
        })
        record = _event_record(event)
        out["metrics"] = {**(out.get("metrics") or {}), **_metrics(record)}
        out["correlation"] = {**(out.get("correlation") or {}), **_correlation(record)}
        failure = _failure(record, event.event_type)
        if failure:
            out["failure"] = failure
        elif next_status in {"active", "ready"}:
            out["failure"] = {}
    source_meta = dict(out.get("source_meta") or {})
    for key in (
        "tag",
        "source",
        "source_family",
        "field_signature",
        "provenance",
        "mutation_strategy",
        "rationale",
        "expected_low_corr_reason",
        "parent_alpha_ids",
        "source_run_id",
        "forum_evidence",
        "repair_evidence",
        "risk_flags",
    ):
        if event.payload.get(key) not in (None, "", [], {}):
            source_meta[key] = event.payload[key]
    out["source_meta"] = source_meta
    return out


def _merge_memory_dict(existing: dict[str, Any] | None, event: AgentEvent, spec: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return {
            **spec,
            "scope_key": event.scope_key,
            "candidate_uid": event.candidate_uid,
            "support_count": 1,
            "contradiction_count": 0,
            "state": "active",
            "evidence_event_ids": [event.event_id],
            "last_seen_at": event.occurred_at,
        }
    out = dict(existing)
    out["support_count"] = int(out.get("support_count") or 0) + 1
    previous_confidence = float(out.get("confidence") or 0.0)
    out["confidence"] = max(previous_confidence, float(spec["confidence"]))
    if float(spec["confidence"]) >= previous_confidence:
        out["evidence_class"] = spec["evidence_class"]
    out["payload"] = spec["payload"]
    out["last_seen_at"] = event.occurred_at
    out["evidence_event_ids"] = list(dict.fromkeys([*(out.get("evidence_event_ids") or []), event.event_id]))[-50:]
    return out


def _event_record(event: AgentEvent) -> dict[str, Any]:
    record = event.payload.get("record")
    return dict(record) if isinstance(record, dict) else dict(event.payload)


def _candidate_from_event(event: AgentEvent) -> CandidateIdentity | None:
    record = _event_record(event)
    expression = str(event.payload.get("expression") or record.get("expression") or "").strip()
    if not expression:
        return None
    settings = None
    for value in (
        event.payload.get("simulation_settings"),
        record.get("simulation_settings_effective"),
        record.get("effective_simulation_settings"),
        record.get("effective_settings"),
        record.get("simulation_settings"),
        record.get("settings"),
    ):
        if isinstance(value, dict):
            settings = value
            break
    return CandidateIdentity.create(
        expression,
        _effective_settings(settings or {}, event),
    )


def _effective_settings(settings: dict[str, Any], source: Any) -> EffectiveSettings:
    return EffectiveSettings.from_mapping({
        "account": settings.get("account") or getattr(source, "account", "primary"),
        "region": settings.get("region") or getattr(source, "region", "USA"),
        "universe": settings.get("universe") or getattr(source, "universe", "TOP3000"),
        "delay": settings.get("delay") if settings.get("delay") not in (None, "") else getattr(source, "delay", 1),
        "decay": settings.get("decay", 0),
        "neutralization": settings.get("neutralization", "SUBINDUSTRY"),
        "truncation": settings.get("truncation", 0.08),
        "maxTrade": settings.get("maxTrade", "OFF"),
        "maxPosition": settings.get("maxPosition", "OFF"),
    })


def _metrics(record: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in ("sharpe", "fitness", "returns", "turnover", "drawdown", "margin"):
        value = first_float(record.get(key))
        if value is not None:
            out[key] = value
    return out


def _correlation(record: dict[str, Any]) -> dict[str, Any]:
    values = {
        "sc_result": record.get("sc_result"),
        "sc_value": first_float(record.get("sc_value")),
        "sc_limit": first_float(record.get("sc_limit")),
        "prod_corr_result": record.get("prod_corr_result"),
        "prod_corr_value": first_float(record.get("prod_corr_value")),
        "prod_corr_limit": first_float(record.get("prod_corr_limit")),
    }
    return {key: value for key, value in values.items() if value not in (None, "")}


def _failure(record: dict[str, Any], event_type: str) -> dict[str, Any]:
    if event_type not in {
        EventType.VALIDATION_REJECTED.value,
        EventType.SIMULATION_FAILED.value,
        EventType.CHECK_BLOCKED.value,
        EventType.SUBMIT_FAILED.value,
        EventType.SUBMISSION_PENDING.value,
    }:
        return {}
    kind = _projected_failure_kind(record, event_type)
    if not kind:
        return {}
    return {
        "failure_kind": str(kind),
        "reason": record.get("reason") or record.get("detail") or record.get("error"),
        "failed_platform_checks": record.get("failed_platform_checks") or [],
    }


def _projected_failure_kind(record: dict[str, Any], event_type: str) -> str:
    canonical = canonical_failure_kind(record)
    if canonical and canonical != "platform_alpha":
        return canonical
    root_cause = audit_root_cause(record, stage=event_type)
    root_mapping = {
        "self_correlation": "self_correlation_fail",
        "prod_correlation": "prod_correlation_fail",
        "duplicate_or_similarity": "high_similarity",
        "distribution_concentration": "concentrated_weight",
        "turnover_density": "turnover_density",
        "subuniverse_coverage": "sub_universe_fail",
        "metric_fail": "base_metric_fail",
        "legal_input": "legal_input",
        "pending_check": "correlation_pending",
        "infra_timeout": "infra_timeout",
        "policy_block": "policy_block",
        "platform_check": "platform_check_fail",
    }
    if root_cause in root_mapping:
        return root_mapping[root_cause]
    return str(
        record.get("failure_kind")
        or record.get("api_check_status")
        or EVENT_STATUS.get(event_type)
        or "unknown_failure"
    )


def _event_row(row: WQAgentEvent) -> dict[str, Any]:
    return {
        "event_id": row.event_id,
        "schema_version": row.schema_version,
        "event_type": row.event_type,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "run_id": row.run_id,
        "attempt_uid": row.attempt_uid,
        "candidate_uid": row.candidate_uid,
        "scope_key": row.scope_key,
        "owner_key": row.owner_key,
        "user_id": str(row.user_id) if row.user_id else None,
        "account": row.account,
        "region": row.region,
        "universe": row.universe,
        "delay": row.delay,
        "alpha_id": row.alpha_id,
        "stage": row.stage,
        "payload": row.payload or {},
        "source_artifact": row.source_artifact,
    }


def _memory_row(row: WQMemoryItem) -> dict[str, Any]:
    return {
        "memory_id": row.memory_id,
        "scope_key": row.scope_key,
        "memory_key": row.memory_key,
        "memory_kind": row.memory_kind,
        "subject_key": row.subject_key,
        "candidate_uid": row.candidate_uid,
        "failure_kind": row.failure_kind,
        "severity": row.severity,
        "evidence_class": row.evidence_class,
        "polarity": row.polarity,
        "confidence": row.confidence,
        "support_count": row.support_count,
        "contradiction_count": row.contradiction_count,
        "state": row.state,
        "payload": row.payload or {},
        "evidence_event_ids": row.evidence_event_ids or [],
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
    }


def _memory_sort_key(row: dict[str, Any]) -> tuple[float, int, str]:
    return (
        float(row.get("confidence") or 0.0),
        int(row.get("support_count") or 0),
        str(row.get("last_seen_at") or ""),
    )


def _parse_time(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"user_id must be a valid UUID, got {value!r}") from exc
