from __future__ import annotations

from typing import Any

from sqlalchemy import select

from worldquant_harness import db
from worldquant_harness.async_utils import run_coro_sync
from worldquant_harness.models import WQCandidateState, WQMemoryItem
from worldquant_harness.wq_agent_core import (
    AgentEvent,
    CandidateIdentity,
    EffectiveSettings,
    EventType,
    RunScope,
    SqlAgentRepository,
    attempt_uid,
)


def test_sql_repository_projects_events_and_isolates_memory(tmp_path: Any, monkeypatch: Any) -> None:
    database_path = (tmp_path / "agent-core.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    db._engine = None
    db._session_factory = None

    settings = EffectiveSettings(account="primary", region="USA", universe="TOP3000", delay=1)
    candidate = CandidateIdentity.create("rank(close)", settings)
    scope = RunScope.from_settings(settings.to_platform_dict())
    other_scope = RunScope(account="secondary", region="USA", universe="TOP3000", delay=1)
    attempt = attempt_uid("repository-test", candidate.candidate_uid)
    repository = SqlAgentRepository()

    blocked_record = {
        "alpha_id": "alpha-1",
        "failure_kind": "self_correlation_above_cutoff",
        "sc_result": "PASS",
        "sc_value": 0.82,
        "reason": "strict local cutoff",
    }
    blocked = AgentEvent.create(
        EventType.CHECK_BLOCKED,
        run_id="repository-test",
        attempt_uid=attempt,
        candidate=candidate,
        scope=scope,
        stage="check",
        alpha_id="alpha-1",
        payload={"record": blocked_record, "source_family": "unit"},
    )
    active_record = {
        "alpha_id": "alpha-1",
        "final_status": "ACTIVE",
        "platform_status": "ACTIVE",
        "ok": True,
        "sharpe": 1.7,
        "fitness": 1.3,
    }
    active = AgentEvent.create(
        EventType.ACTIVE_CONFIRMED,
        run_id="repository-test",
        attempt_uid=attempt,
        candidate=candidate,
        scope=scope,
        stage="submit_reconcile",
        alpha_id="alpha-1",
        payload={"record": active_record},
    )

    try:
        assert repository.append_many([(blocked, candidate), (active, candidate)]) == 2
        assert repository.append(blocked, candidate) is False
        assert repository.append_many([(blocked, candidate), (active, candidate)]) == 0

        events = repository.events_for_attempt(attempt)
        assert [event["event_type"] for event in events] == ["check_blocked", "active_confirmed"]

        scoped_memory = repository.query_memory(scope)
        assert len(scoped_memory) == 1
        assert scoped_memory[0]["failure_kind"] == "active"
        assert scoped_memory[0]["evidence_class"] == "platform_submit"
        assert repository.query_memory(other_scope) == []

        rebuilt = repository.rebuild_projections()
        assert rebuilt == {
            "events_replayed": 2,
            "events_skipped": 0,
            "candidate_states": 1,
            "memory_items": 2,
        }

        state, memories = run_coro_sync(_read_projection_rows())
        assert state.lifecycle_status == "active"
        assert state.revision == 2
        assert state.metrics == {"sharpe": 1.7, "fitness": 1.3}
        assert state.source_meta == {"source_family": "unit"}
        assert {memory.failure_kind: memory.state for memory in memories} == {
            "active": "active",
            "self_correlation_fail": "superseded",
        }
    finally:
        run_coro_sync(db.close_db())


async def _read_projection_rows() -> tuple[WQCandidateState, list[WQMemoryItem]]:
    factory = db._get_session_factory()
    async with factory() as session:
        state_result = await session.execute(select(WQCandidateState))
        memory_result = await session.execute(select(WQMemoryItem).order_by(WQMemoryItem.failure_kind))
        return state_result.scalar_one(), list(memory_result.scalars().all())
