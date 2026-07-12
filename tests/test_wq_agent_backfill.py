from __future__ import annotations

from worldquant_harness.artifact_io import write_jsonl
from worldquant_harness.wq_agent_core import (
    AgentEvent,
    CandidateIdentity,
    EffectiveSettings,
    EventType,
    InMemoryAgentRepository,
    RunScope,
    attempt_uid,
)
from worldquant_harness.wq_agent_core.backfill import apply_backfill, build_backfill


def test_backfill_hydrates_missing_identity_and_dedupes_copied_results(tmp_path) -> None:
    expression = "rank(close)"
    settings = {"region": "USA", "universe": "TOP3000", "delay": 1, "decay": 8}
    write_jsonl(
        tmp_path / "simulation_results.jsonl",
        [
            {
                "created_at": "2026-06-01T10:00:00+00:00",
                "expression": expression,
                "simulation_settings_effective": settings,
                "alpha_id": "alpha-1",
                "ok": True,
                "status": "pending_correlation_check",
                "sharpe": 1.7,
                "fitness": 1.2,
                "turnover": 0.2,
            }
        ],
    )
    write_jsonl(
        tmp_path / "check_results.jsonl",
        [
            {
                "created_at": "2026-06-01T10:01:00+00:00",
                "alpha_id": "alpha-1",
                "api_check_status": "api_check_readable",
                "sc_result": "PASS",
                "sc_value": 0.4,
                "prod_corr_result": "MISSING",
            },
            {"alpha_id": "unresolvable", "api_check_status": "api_check_error"},
        ],
    )
    active = {
        "created_at": "2026-06-01T10:02:00+00:00",
        "alpha_id": "alpha-1",
        "ok": True,
        "final_status": "ACTIVE",
        "platform_status": "ACTIVE",
        "sharpe": 1.7,
        "fitness": 1.2,
    }
    write_jsonl(tmp_path / "submit_results.jsonl", [active])
    write_jsonl(tmp_path / "submitted_accumulator.jsonl", [active])

    items, report = build_backfill([tmp_path], include_platform_snapshots=False)

    assert report["rows_scanned"] == 5
    assert report["unique_events"] == 3
    assert report["duplicate_events"] == 1
    assert report["skipped_by_reason"] == {"missing_expression": 1}
    assert report["event_counts"] == {
        "check_succeeded": 1,
        "simulation_succeeded": 1,
        "submit_succeeded": 1,
    }
    assert {item.candidate.settings.decay for item in items} == {8}

    repository = InMemoryAgentRepository()
    assert apply_backfill(repository, items, batch_size=2) == 3
    assert apply_backfill(repository, items, batch_size=2) == 0
    scope = RunScope.from_settings(EffectiveSettings(decay=8).to_platform_dict())
    memory = repository.query_memory(scope)
    assert len(memory) == 1
    assert memory[0]["failure_kind"] == "active"
    state = next(iter(repository.candidates.values()))
    assert state["lifecycle_status"] == "active"
    assert state["failure"] == {}


def test_backfill_preserves_canonical_event_identity(tmp_path) -> None:
    settings = EffectiveSettings(decay=6)
    candidate = CandidateIdentity.create("rank(volume)", settings)
    scope = RunScope.from_settings(settings.to_platform_dict())
    event = AgentEvent.create(
        EventType.CANDIDATE_CREATED,
        run_id="canonical-run",
        attempt_uid=attempt_uid("canonical-run", candidate.candidate_uid),
        candidate=candidate,
        scope=scope,
        stage="candidate",
        payload={
            "expression": candidate.expression,
            "simulation_settings": settings.to_platform_dict(),
            "source_family": "canonical-test",
        },
    )
    write_jsonl(tmp_path / "agent_events.jsonl", [event.to_dict(), event.to_dict()])

    items, report = build_backfill([tmp_path], include_platform_snapshots=False)

    assert len(items) == 1
    assert items[0].event.event_id == event.event_id
    assert items[0].candidate.candidate_uid == candidate.candidate_uid
    assert report["duplicate_events"] == 1
    assert report["conflict_count"] == 0


def test_platform_identity_overrides_synthesized_history_settings(tmp_path) -> None:
    expression = "rank(close)"
    write_jsonl(
        tmp_path / "platform_alphas.jsonl",
        [
            {
                "id": "alpha-platform",
                "type": "REGULAR",
                "regular": {"code": expression},
                "status": "ACTIVE",
                "settings": {
                    "region": "USA",
                    "universe": "TOP3000",
                    "delay": 1,
                    "decay": 8,
                    "neutralization": "SUBINDUSTRY",
                    "truncation": 0.01,
                },
            }
        ],
    )
    write_jsonl(
        tmp_path / "history_alpha_events.jsonl",
        [
            {
                "source_type": "submit_result",
                "alpha_id": "alpha-platform",
                "expression": expression,
                "platform_status": "ACTIVE",
                "raw_final_status": "ACTIVE",
                "settings": {
                    "region": "USA",
                    "universe": "TOP3000",
                    "delay": 1,
                    "decay": 0,
                    "neutralization": "SUBINDUSTRY",
                    "truncation": 0.08,
                },
            }
        ],
    )

    items, report = build_backfill([tmp_path])

    assert report["conflict_count"] == 0
    assert {item.event.alpha_id for item in items} == {"alpha-platform"}
    assert {item.candidate.settings.decay for item in items} == {8}
    assert {item.candidate.settings.truncation for item in items} == {0.01}
