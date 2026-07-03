import json
import shutil
import uuid
from pathlib import Path

import pytest

from worldquant_harness.wq_agent_config import WorkflowPaths, WQAgentWorkflowConfig
from worldquant_harness.wq_agent_workflow import run_workflow
from worldquant_harness.wq_autopilot_controller import (
    build_autopilot_branch_plan,
    build_autopilot_status_inventory,
    compile_autopilot_policy,
    prepare_autopilot_candidate_files,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def workdir():
    path = Path(__file__).resolve().parents[1] / ".test_tmp" / f"wq_autopilot_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_autopilot_policy_and_branch_prioritize_self_correlation_repairs(workdir):
    run_dir = workdir / "policy_run"
    _write_jsonl(
        run_dir / "presubmit_rejected.jsonl",
        [
            {"alpha_id": "a1", "presubmit_reject_reason": "self_correlation_value_above_strict_cutoff"},
            {"alpha_id": "a2", "triage_reason": "self-correlation failed (0.79)"},
            {"alpha_id": "a3", "presubmit_reject_reason": "base_submit_thresholds_failed"},
        ],
    )
    (run_dir / "post_submit_review").mkdir(parents=True)
    (run_dir / "post_submit_review" / "next_run_constraints.json").write_text(
        json.dumps(
            {
                "preferred_field_families": ["analyst_revision"],
                "avoid_field_signatures": ["close|volume"],
                "required_repairs": ["existing repair"],
            }
        ),
        encoding="utf-8",
    )

    config = WQAgentWorkflowConfig(output_dir=run_dir, target_ready=1, autopilot_resume=True, use_ledger=False)
    paths = WorkflowPaths.for_output_dir(run_dir)
    inventory = build_autopilot_status_inventory(config, paths)
    policy = compile_autopilot_policy(config, paths, inventory=inventory)
    branch = build_autopilot_branch_plan(policy, inventory=inventory)

    assert policy["gates"]["strict_self_correlation_cutoff"] == 0.68
    assert policy["failure_counts"]["self_correlation"] == 2
    assert "analyst_revision" in policy["preferred_field_families"]
    assert "close|volume" in policy["avoid_field_signatures"]
    assert branch["primary_branch"] == "decorrelate_field_operator_family"
    assert "switch field family before window tuning" in branch["actions"]


def test_autopilot_candidate_schema_writes_sanitized_manual_file(workdir):
    candidates = workdir / "manual_candidates.jsonl"
    _write_jsonl(
        candidates,
        [
            {"expression": "rank(open)", "tag": "missing-context"},
            {
                "expression": "rank(ts_rank(analyst_eps_revision, 60))",
                "tag": "analyst-revision",
                "source_family": "analyst_revision",
                "rationale": "Fresh analyst revision family with low overlap to active price anchors.",
                "provenance": {"source_run": "manual-test", "evidence": "unit"},
            },
        ],
    )

    config = WQAgentWorkflowConfig(output_dir=workdir / "schema_run", candidate_files=[candidates], target_ready=1)
    paths = WorkflowPaths.for_output_dir(config.output_dir)
    files, summary = prepare_autopilot_candidate_files(config, paths)

    assert files == [paths.autopilot_candidates]
    assert summary["accepted"] == 1
    assert summary["skipped"] == 1
    rows = _read_jsonl(paths.autopilot_candidates)
    assert rows[0]["source_family"] == "analyst_revision"
    assert rows[0]["simulation_settings"]["region"] == "USA"
    skipped = _read_jsonl(paths.autopilot_candidates.with_name("autopilot_candidate_skipped.jsonl"))
    assert skipped[0]["candidate_skip_reason"] == "autopilot_schema_missing_required"


def test_autopilot_presubmit_runs_without_real_submit_and_writes_decision_artifacts(workdir):
    submit_calls = []
    prompts = []

    def fake_model(prompt, config):
        prompts.append(prompt)
        return [
            {
                "expression": "rank(ts_rank(open, 20))",
                "source_family": "price_fresh_probe",
                "tag": "open-probe",
                "rationale": "Different windowed price anchor for a smoke presubmit candidate.",
            }
        ]

    def fake_simulate(candidate, config):
        return {
            "ok": True,
            "alpha_id": "alpha_ready",
            "is_metrics": {
                "sharpe": 1.8,
                "fitness": 1.2,
                "returns": 0.12,
                "turnover": 0.25,
                "checks": [{"name": "SELF_CORRELATION", "result": "PENDING"}],
            },
            "submit_eligible": True,
            "submitted": False,
        }

    config = WQAgentWorkflowConfig(
        output_dir=workdir / "autopilot_presubmit",
        target_ready=1,
        max_total_simulations=1,
        cycle_candidate_count=1,
        max_simulations=1,
        max_cycles=1,
        virtual_similarity_cutoff=1.0,
        max_virtual_field_signature_count=10,
        fallback_template_limit=0,
        use_ledger=False,
    )
    summary = run_workflow(
        config,
        mode="autopilot",
        dependencies={
            "list_alphas": lambda config: [],
            "model_generate_candidates": fake_model,
            "simulate": fake_simulate,
            "check_submissions": lambda ids, config: {
                "alpha_ready": {
                    "status": "UNSUBMITTED",
                    "sharpe": 1.8,
                    "fitness": 1.2,
                    "turnover": 0.25,
                    "sc_result": "PASS",
                    "sc_value": 0.52,
                    "prod_corr_result": "MISSING",
                }
            },
            "submit_by_ids": lambda ids, config: submit_calls.append(list(ids)),
        },
    )

    assert summary["ok"] is True
    assert summary["autopilot"]["state"]["ready_count"] == 1
    assert summary["autopilot"]["state"]["child_mode"] == "presubmit-sequential"
    assert submit_calls == []
    assert "AUTOPILOT RUN POLICY" in prompts[0]
    assert (config.output_dir / "autopilot_state.json").is_file()
    assert (config.output_dir / "autopilot_policy.json").is_file()
    assert (config.output_dir / "autopilot_branch_plan.json").is_file()
    assert (config.output_dir / "autopilot_decisions.md").is_file()
    events = _read_jsonl(config.output_dir / "autopilot_events.jsonl")
    assert [row["event"] for row in events][-1] == "autopilot_finished"
    child_ready = _read_jsonl(config.output_dir / "autopilot_presubmit" / "presubmit_ready_sequential.jsonl")
    assert child_ready[0]["alpha_id"] == "alpha_ready"


def test_autopilot_submit_requires_explicit_submit_flag_and_can_reach_active(workdir):
    def fake_model(prompt, config):
        return [{"expression": "rank(ts_rank(volume, 20))", "source_family": "volume_probe"}]

    def fake_simulate(candidate, config):
        return {
            "ok": True,
            "alpha_id": "alpha_submit",
            "is_metrics": {
                "sharpe": 1.8,
                "fitness": 1.2,
                "returns": 0.12,
                "turnover": 0.25,
                "checks": [{"name": "SELF_CORRELATION", "result": "PENDING"}],
            },
            "submit_eligible": True,
            "submitted": False,
        }

    submit_calls = []
    config = WQAgentWorkflowConfig(
        output_dir=workdir / "autopilot_submit",
        autopilot_submit=True,
        target_active=1,
        max_total_simulations=1,
        cycle_candidate_count=1,
        max_simulations=1,
        max_cycles=1,
        fallback_template_limit=0,
        use_ledger=False,
        post_submit_review_enabled=False,
    )
    summary = run_workflow(
        config,
        mode="autopilot",
        dependencies={
            "list_alphas": lambda config: [],
            "model_generate_candidates": fake_model,
            "simulate": fake_simulate,
            "check_alphas": lambda ids, config: {
                "alpha_submit": {
                    "status": "UNSUBMITTED",
                    "sharpe": 1.8,
                    "fitness": 1.2,
                    "turnover": 0.25,
                    "sc_result": "PASS",
                    "sc_value": 0.52,
                    "prod_corr_result": "MISSING",
                }
            },
            "submit_by_ids": lambda ids, config: (
                submit_calls.append(list(ids))
                or {"results": {alpha_id: {"ok": True, "final_status": "ACTIVE"} for alpha_id in ids}}
            ),
        },
    )

    assert summary["ok"] is True
    assert submit_calls == [["alpha_submit"]]
    assert summary["autopilot"]["state"]["child_mode"] == "run-submit"
    assert summary["autopilot"]["state"]["active_count"] == 1
