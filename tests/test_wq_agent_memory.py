from __future__ import annotations

import json

from worldquant_harness.wq_agent_config import WorkflowPaths, WQAgentWorkflowConfig
from worldquant_harness.wq_agent_core import (
    AgentEvent,
    CandidateIdentity,
    EffectiveSettings,
    EventType,
    InMemoryAgentRepository,
    RunScope,
    attempt_uid,
)
from worldquant_harness.wq_agent_core.memory import ScopedMemoryRetriever
from worldquant_harness.wq_agent_core.workflow_adapter import sync_workflow_artifacts
from worldquant_harness.wq_workflow_memory import MemoryContextBuilder


def test_scoped_memory_retriever_balances_failure_buckets() -> None:
    repository = InMemoryAgentRepository()
    settings = EffectiveSettings()
    scope = RunScope.from_settings(settings.to_platform_dict())
    _append_outcome(repository, scope, settings, "rank(close)", "self_correlation", "check_blocked")
    _append_outcome(repository, scope, settings, "rank(vwap)", "self_correlation_above_cutoff", "check_blocked")
    _append_outcome(repository, scope, settings, "rank(volume)", "metric_threshold_fail", "check_blocked")
    _append_outcome(repository, scope, settings, "rank(returns)", "active", "active_confirmed")

    packet = ScopedMemoryRetriever(repository).retrieve(
        scope,
        limit=10,
        bucket_quotas={"self_correlation": 1, "metric_threshold": 1, "positive": 1},
    )

    assert packet["health"]["selected"] == 3
    assert packet["health"]["bucket_counts"] == {
        "metric_threshold": 1,
        "positive": 1,
        "self_correlation": 1,
    }
    assert {row["bucket"] for row in packet["items"]} == {
        "metric_threshold",
        "positive",
        "self_correlation",
    }
    assert all(row["recommendation"] for row in packet["items"])
    assert ScopedMemoryRetriever(repository).retrieve(
        RunScope(account="other"),
        limit=10,
    )["items"] == []


def test_memory_context_builder_includes_v2_packet_in_json_and_prompt(tmp_path) -> None:
    output_dir = tmp_path / "run"
    paths = WorkflowPaths.for_output_dir(output_dir)
    output_dir.mkdir(parents=True)
    config = WQAgentWorkflowConfig(
        output_dir=output_dir,
        use_ledger=False,
        agent_memory_v2=True,
        agent_memory_limit=7,
    )
    packet = {
        "schema_version": 2,
        "health": {"ok": True, "scope_key": "scope-test", "selected": 1, "available": 2},
        "items": [
            {
                "bucket": "self_correlation",
                "evidence_class": "platform_submit",
                "confidence": 1.0,
                "support_count": 2,
                "failure_kind": "self_correlation",
                "reason": "0.91 above cutoff",
                "recommendation": "Change the dominant field family.",
                "expression": "rank(close)",
            }
        ],
    }

    result = MemoryContextBuilder(
        config,
        paths,
        dependencies={"agent_memory_packet": lambda scope, limit, current_config: packet},
    ).run(active_inventory={"active": []})

    context = json.loads(paths.memory_context.read_text(encoding="utf-8"))
    markdown = paths.memory_context_markdown.read_text(encoding="utf-8")
    assert result["agent_memory_items"] == 1
    assert context["agent_memory_v2"]["enabled"] is True
    assert "## Canonical Agent Memory" in markdown
    assert "Change the dominant field family" in markdown


def test_workflow_adapter_is_idempotent(tmp_path) -> None:
    output_dir = tmp_path / "workflow"
    output_dir.mkdir()
    (output_dir / "simulation_results.jsonl").write_text(
        json.dumps(
            {
                "expression": "rank(close)",
                "alpha_id": "alpha-workflow",
                "ok": True,
                "simulation_settings_effective": {"decay": 8},
            }
        ) + "\n",
        encoding="utf-8",
    )
    repository = InMemoryAgentRepository()

    first = sync_workflow_artifacts(output_dir, account="primary", repository=repository)
    second = sync_workflow_artifacts(output_dir, account="primary", repository=repository)

    assert first["applied_events"] == 1
    assert second["applied_events"] == 0
    assert (output_dir / "agent_event_sync.json").is_file()


def _append_outcome(
    repository: InMemoryAgentRepository,
    scope: RunScope,
    settings: EffectiveSettings,
    expression: str,
    failure_kind: str,
    event_type: str,
) -> None:
    candidate = CandidateIdentity.create(expression, settings)
    run_id = f"memory-{candidate.candidate_uid}"
    record = {
        "expression": expression,
        "alpha_id": candidate.candidate_uid[:8],
        "failure_kind": None if failure_kind == "active" else failure_kind,
        "reason": failure_kind,
        "sharpe": 1.6,
        "fitness": 1.1,
    }
    event = AgentEvent.create(
        EventType(event_type),
        run_id=run_id,
        attempt_uid=attempt_uid(run_id, candidate.candidate_uid),
        candidate=candidate,
        scope=scope,
        stage="submit" if event_type == "active_confirmed" else "check",
        payload={"record": record},
        alpha_id=record["alpha_id"],
    )
    repository.append(event, candidate)
