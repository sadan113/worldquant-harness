"""Autopilot controller for the canonical WQ agent workflow.

The controller owns run-level decisions and artifacts. It delegates simulation,
review, presubmit, and submission mechanics to ``wq_agent_workflow`` so the
existing gates remain the single implementation of those behaviors.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .artifact_io import (
    append_jsonl,
    read_json,
    read_jsonish_rows,
    read_jsonl,
    utc_now,
    write_json,
    write_jsonl,
    write_text,
)
from .record_utils import safe_float, safe_int
from .wq_agent_config import WorkflowPaths, WQAgentWorkflowConfig
from .wq_agent_records import candidate_dedupe_key, clean_simulation_settings, workflow_config_dict
from .wq_workflow_loop_status import _finish
from .wq_workflow_prompts import default_model_generate_candidates

DEFAULT_AUTOPILOT_SELF_CORRELATION_CUTOFF = 0.68
AUTOPILOT_REQUIRED_CANDIDATE_FIELDS = (
    "expression",
    "source_family",
    "tag",
    "rationale",
    "provenance",
)
SUCCESS_STATUSES = {"ACTIVE", "SUBMITTED"}


def run_autopilot(
    config: WQAgentWorkflowConfig,
    paths: WorkflowPaths | None = None,
    *,
    dependencies: dict[str, Any] | None = None,
    workflow_runner: Any | None = None,
) -> dict:
    """Run the repo-level autopilot around the existing workflow loops."""

    dependencies = dependencies or {}
    paths = paths or WorkflowPaths.for_output_dir(config.output_dir)
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    _validate_autopilot_config(config)

    _append_event(paths, "autopilot_started", {"config": workflow_config_dict(config)})
    inventory = build_autopilot_status_inventory(config, paths)
    _append_event(paths, "status_inventory", _inventory_event_payload(inventory))

    policy = compile_autopilot_policy(config, paths, inventory=inventory)
    write_json(paths.autopilot_policy, policy)
    _append_event(paths, "policy_compiled", _policy_event_payload(policy))

    branch_plan = build_autopilot_branch_plan(policy, inventory=inventory)
    write_json(paths.autopilot_branch_plan, branch_plan)
    _append_event(paths, "branch_selected", _branch_event_payload(branch_plan))

    candidate_files, candidate_summary = prepare_autopilot_candidate_files(config, paths)
    if candidate_summary.get("enabled"):
        _append_event(paths, "candidate_sources_sanitized", candidate_summary)

    child_mode = "run-submit" if config.autopilot_submit else "presubmit-sequential"
    child_config = _child_config(
        config,
        paths,
        branch_plan=branch_plan,
        policy=policy,
        candidate_files=candidate_files,
    )
    child_dependencies = _autopilot_dependencies(dependencies, branch_plan=branch_plan, policy=policy)
    _append_event(
        paths,
        "child_workflow_started",
        {
            "mode": child_mode,
            "output_dir": str(child_config.output_dir),
            "target_ready": child_config.target_ready,
            "target_submissions": child_config.target_submissions,
            "strict_self_correlation_cutoff": child_config.presubmit_self_correlation_cutoff,
        },
    )

    if workflow_runner is None:
        raise ValueError("autopilot requires a workflow_runner callback")
    child_summary = workflow_runner(child_config, mode=child_mode, dependencies=child_dependencies)
    _append_event(
        paths,
        "child_workflow_finished",
        {
            "mode": child_mode,
            "ok": bool(child_summary.get("ok")),
            "stop_reason": _child_stop_reason(child_summary, child_mode),
            "output_dir": str(child_config.output_dir),
        },
    )

    final_inventory = build_autopilot_status_inventory(config, paths, child_output_dir=child_config.output_dir)
    state = build_autopilot_state(
        config,
        paths,
        inventory=final_inventory,
        policy=policy,
        branch_plan=branch_plan,
        child_summary=child_summary,
        child_mode=child_mode,
        child_output_dir=child_config.output_dir,
    )
    write_json(paths.autopilot_state, state)
    write_text(paths.autopilot_decisions, render_autopilot_decisions(state, policy=policy, branch_plan=branch_plan))
    _append_event(paths, "autopilot_finished", {"ok": state["ok"], "stop_reason": state["stop_reason"]})

    autopilot_summary = {
        "ok": state["ok"],
        "state": state,
        "policy": {
            "file": str(paths.autopilot_policy),
            "failure_counts": policy.get("failure_counts") or {},
            "strict_self_correlation_cutoff": policy.get("gates", {}).get("strict_self_correlation_cutoff"),
        },
        "branch_plan": {
            "file": str(paths.autopilot_branch_plan),
            "primary_branch": branch_plan.get("primary_branch"),
            "generation_mode": branch_plan.get("generation_mode"),
        },
        "candidate_sources": candidate_summary,
        "child": child_summary,
        "files": {
            "state": str(paths.autopilot_state),
            "events": str(paths.autopilot_events),
            "policy": str(paths.autopilot_policy),
            "branch_plan": str(paths.autopilot_branch_plan),
            "decisions": str(paths.autopilot_decisions),
            "child_output_dir": str(child_config.output_dir),
        },
    }
    summary = _finish(paths, config, "autopilot", {"autopilot": autopilot_summary})
    summary["ok"] = state["ok"]
    write_json(paths.summary, summary)
    return summary


def build_autopilot_status_inventory(
    config: WQAgentWorkflowConfig,
    paths: WorkflowPaths,
    *,
    child_output_dir: Path | None = None,
) -> dict[str, Any]:
    """Collect current ready, rejected, and submitted state before decisions."""

    roots = [paths.output_dir] if config.autopilot_resume else []
    if child_output_dir:
        roots.append(child_output_dir)
    ready_paths = _artifact_paths(
        roots,
        "presubmit_ready_sequential.jsonl",
        explicit=config.seed_ready_files,
    )
    rejected_paths = _artifact_paths(
        roots,
        "presubmit_rejected.jsonl",
        "candidate_skipped.jsonl",
        "review_queue.jsonl",
        explicit=config.seed_rejected_files,
    )
    submitted_paths = _artifact_paths(
        roots,
        "submitted_accumulator.jsonl",
        "submit_results.jsonl",
        "submit_existing_results.jsonl",
    )

    ready_rows = _read_rows_from_paths(ready_paths)
    rejected_rows = _read_rows_from_paths(rejected_paths)
    submitted_rows = _read_rows_from_paths(submitted_paths)
    active_rows = [row for row in submitted_rows if _is_successful_submit_row(row)]
    pending_rows = [row for row in [*ready_rows, *submitted_rows] if _is_pending_row(row)]
    invalid_ready_rows = [row for row in ready_rows if not str(row.get("alpha_id") or "").strip()]
    already_submitted_ready = [
        row
        for row in ready_rows
        if str(row.get("platform_status") or row.get("status") or "").upper() in SUCCESS_STATUSES
        or bool(row.get("submitted"))
    ]

    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "ready_count": len(ready_rows),
        "rejected_count": len(rejected_rows),
        "submitted_count": len(submitted_rows),
        "active_count": len(active_rows),
        "pending_count": len(pending_rows),
        "invalid_ready_count": len(invalid_ready_rows),
        "already_submitted_ready_count": len(already_submitted_ready),
        "ready_alpha_ids": _unique_text(row.get("alpha_id") for row in ready_rows),
        "active_alpha_ids": _unique_text(_alpha_id(row) for row in active_rows),
        "pending_alpha_ids": _unique_text(row.get("alpha_id") for row in pending_rows),
        "ready_files": [str(path) for path in ready_paths],
        "rejected_files": [str(path) for path in rejected_paths],
        "submitted_files": [str(path) for path in submitted_paths],
        "ready_rows": ready_rows,
        "rejected_rows": rejected_rows,
        "submitted_rows": submitted_rows,
    }


def compile_autopilot_policy(
    config: WQAgentWorkflowConfig,
    paths: WorkflowPaths,
    *,
    inventory: dict[str, Any],
) -> dict[str, Any]:
    """Turn memory, failures, and post-submit constraints into one run policy."""

    constraint_roots = [*config.post_submit_baseline_roots]
    if config.autopilot_resume:
        constraint_roots.append(paths.output_dir)
    constraints = _load_next_run_constraints(constraint_roots)
    rejected_rows = list(inventory.get("rejected_rows") or [])
    submitted_rows = list(inventory.get("submitted_rows") or [])
    failure_counts = Counter(_failure_bucket(row) for row in [*rejected_rows, *submitted_rows])
    failure_counts.pop("other", None)
    strict_sc = config.presubmit_self_correlation_cutoff
    if strict_sc is None:
        strict_sc = DEFAULT_AUTOPILOT_SELF_CORRELATION_CUTOFF

    blocked_alpha_ids = _unique_text(
        value
        for constraint in constraints
        for value in constraint.get("blocked_alpha_ids") or []
    )
    avoid_field_signatures = _unique_text(
        value
        for constraint in constraints
        for value in constraint.get("avoid_field_signatures") or []
    )
    preferred_field_families = _unique_text(
        value
        for constraint in constraints
        for value in constraint.get("preferred_field_families") or []
    )
    required_repairs = _unique_text(
        value
        for constraint in constraints
        for value in constraint.get("required_repairs") or []
    )
    avoid_patterns = _unique_text(
        value
        for constraint in constraints
        for value in constraint.get("avoid_expression_patterns") or []
    )

    if failure_counts.get("self_correlation", 0) > 0:
        required_repairs = _unique_text([*required_repairs, "self-correlation failures must change field/operator family before recheck"])
    if failure_counts.get("concentration", 0) > 0:
        required_repairs = _unique_text([*required_repairs, "reduce sparse legs and add broad coverage before truncation-only retests"])
    if failure_counts.get("metric_threshold", 0) > 0:
        required_repairs = _unique_text([*required_repairs, "add high-coverage breadth before another metric-threshold retest"])

    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "mode": "wq_autopilot_policy",
        "read_only": True,
        "gates": {
            "strict_self_correlation_cutoff": strict_sc,
            "virtual_similarity_cutoff": config.virtual_similarity_cutoff,
            "daily_return_correlation_cutoff": config.presubmit_daily_return_correlation_cutoff,
            "daily_return_correlation_warn": config.presubmit_daily_return_correlation_warn,
            "max_virtual_family_count": config.max_virtual_family_count,
            "max_virtual_field_signature_count": config.max_virtual_field_signature_count,
        },
        "candidate_schema": {
            "required_fields": list(AUTOPILOT_REQUIRED_CANDIDATE_FIELDS),
            "filled_fields": ["field_signature", "simulation_settings"],
            "reject_missing_required": True,
        },
        "failure_counts": dict(sorted(failure_counts.items())),
        "blocked_alpha_ids": blocked_alpha_ids,
        "avoid_field_signatures": avoid_field_signatures,
        "avoid_expression_patterns": avoid_patterns,
        "preferred_field_families": preferred_field_families,
        "required_repairs": required_repairs,
        "source_files": {
            "ready": inventory.get("ready_files") or [],
            "rejected": inventory.get("rejected_files") or [],
            "submitted": inventory.get("submitted_files") or [],
            "next_run_constraints": [str(path) for path in _next_run_constraint_paths(constraint_roots)],
        },
    }


def build_autopilot_branch_plan(policy: dict[str, Any], *, inventory: dict[str, Any]) -> dict[str, Any]:
    """Choose the next branch using a conservative DFS-with-small-beam policy."""

    failure_counts = Counter(policy.get("failure_counts") or {})
    ready_count = safe_int(inventory.get("ready_count"), 0) or 0
    active_count = safe_int(inventory.get("active_count"), 0) or 0
    dominant_failure = _dominant_failure(failure_counts)

    if dominant_failure == "self_correlation":
        primary = "decorrelate_field_operator_family"
        actions = [
            "switch field family before window tuning",
            "avoid exact prior field signatures",
            "use orthogonal overlay only after anchor change",
        ]
    elif dominant_failure == "metric_threshold":
        primary = "breadth_metric_repair"
        actions = [
            "add high-coverage breadth",
            "prefer smooth quality or analyst revisions over narrow sparse legs",
            "retry settings only after expression-level repair",
        ]
    elif dominant_failure == "concentration":
        primary = "reduce_sparse_concentration"
        actions = [
            "reduce sparse fundamental/PCR legs",
            "add broad dispersion before group transforms",
            "block truncation-only repairs",
        ]
    elif dominant_failure == "duplicate":
        primary = "orthogonal_fresh_family"
        actions = [
            "change source family",
            "change operator skeleton",
            "cap family and field-signature reuse",
        ]
    elif ready_count > 0 or active_count > 0:
        primary = "exploit_successful_family_with_guards"
        actions = [
            "continue successful family with small beam",
            "preserve strict correlation guard",
            "stop branch on first repeated self-correlation rejection",
        ]
    else:
        primary = "fresh_low_correlation_exploration"
        actions = [
            "start from forum/research low-overlap fields",
            "avoid direct forum template copies",
            "keep expressions concise and coverage-oriented",
        ]

    secondary = [branch for branch in (
        "breadth_metric_repair",
        "decorrelate_field_operator_family",
        "fresh_low_correlation_exploration",
    ) if branch != primary][:2]
    quotas = {primary: 0.60}
    for branch in secondary:
        quotas[branch] = 0.20

    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "strategy": "dfs_with_small_beam",
        "primary_branch": primary,
        "secondary_branches": secondary,
        "dominant_failure": dominant_failure,
        "generation_mode": "mixed-evolutionary",
        "branch_quotas": quotas,
        "actions": actions,
        "preferred_field_families": policy.get("preferred_field_families") or [],
        "avoid_field_signatures": policy.get("avoid_field_signatures") or [],
        "required_repairs": policy.get("required_repairs") or [],
        "stop_conditions": [
            "target reached",
            "max_total_simulations reached",
            "max_consecutive_empty_cycles reached",
            "strict self-correlation cutoff repeated on current branch",
        ],
    }


def prepare_autopilot_candidate_files(
    config: WQAgentWorkflowConfig,
    paths: WorkflowPaths,
) -> tuple[list[Path], dict[str, Any]]:
    """Validate manual candidate files and write a sanitized autopilot file."""

    if not config.candidate_files:
        return [], {"enabled": False, "reason": "no manual candidate files"}

    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_path in config.candidate_files:
        for row in read_jsonish_rows(source_path, collection_keys=("candidates", "rows", "records")):
            normalized = _normalize_candidate_row(row, source_path=source_path, config=config)
            missing = [field for field in AUTOPILOT_REQUIRED_CANDIDATE_FIELDS if not normalized.get(field)]
            if missing:
                skipped.append({
                    **normalized,
                    "candidate_skip_reason": "autopilot_schema_missing_required",
                    "missing_required_fields": missing,
                })
                continue
            dedupe_key = candidate_dedupe_key(normalized)
            if dedupe_key in seen:
                skipped.append({**normalized, "candidate_skip_reason": "autopilot_duplicate_candidate"})
                continue
            seen.add(dedupe_key)
            accepted.append(normalized)

    write_jsonl(paths.autopilot_candidates, accepted)
    if skipped:
        write_jsonl(paths.autopilot_candidates.with_name("autopilot_candidate_skipped.jsonl"), skipped)
    return [paths.autopilot_candidates] if accepted else [], {
        "enabled": True,
        "input_files": [str(path) for path in config.candidate_files],
        "accepted": len(accepted),
        "skipped": len(skipped),
        "output": str(paths.autopilot_candidates),
        "skipped_output": str(paths.autopilot_candidates.with_name("autopilot_candidate_skipped.jsonl")) if skipped else "",
    }


def build_autopilot_state(
    config: WQAgentWorkflowConfig,
    paths: WorkflowPaths,
    *,
    inventory: dict[str, Any],
    policy: dict[str, Any],
    branch_plan: dict[str, Any],
    child_summary: dict[str, Any],
    child_mode: str,
    child_output_dir: Path,
) -> dict[str, Any]:
    target_ready = config.target_ready if not config.autopilot_submit else 0
    target_active = config.target_active or config.target_submissions
    ready_count = _child_ready_count(child_summary, child_mode, inventory)
    active_count = _child_active_count(child_summary, child_mode, inventory)
    ok = active_count >= target_active if config.autopilot_submit else ready_count >= target_ready
    return {
        "schema_version": 1,
        "updated_at": utc_now(),
        "mode": "autopilot",
        "ok": ok,
        "running": False,
        "submit_enabled": bool(config.autopilot_submit),
        "target_ready": target_ready,
        "target_active": target_active,
        "ready_count": ready_count,
        "active_count": active_count,
        "status_inventory": _inventory_event_payload(inventory),
        "strict_self_correlation_cutoff": policy.get("gates", {}).get("strict_self_correlation_cutoff"),
        "primary_branch": branch_plan.get("primary_branch"),
        "branch_strategy": branch_plan.get("strategy"),
        "child_mode": child_mode,
        "child_output_dir": str(child_output_dir),
        "stop_reason": _child_stop_reason(child_summary, child_mode),
        "files": {
            "state": str(paths.autopilot_state),
            "events": str(paths.autopilot_events),
            "policy": str(paths.autopilot_policy),
            "branch_plan": str(paths.autopilot_branch_plan),
            "decisions": str(paths.autopilot_decisions),
            "child_summary": str(child_output_dir / "summary.json"),
        },
    }


def render_autopilot_decisions(
    state: dict[str, Any],
    *,
    policy: dict[str, Any],
    branch_plan: dict[str, Any],
) -> str:
    lines = [
        "# WQ Autopilot Decisions",
        "",
        f"- Updated: {state.get('updated_at')}",
        f"- Submit enabled: {state.get('submit_enabled')}",
        f"- Target ready: {state.get('target_ready')}",
        f"- Target active: {state.get('target_active')}",
        f"- Ready count: {state.get('ready_count')}",
        f"- Active count: {state.get('active_count')}",
        f"- Stop reason: {state.get('stop_reason')}",
        "",
        "## Policy",
        "",
        f"- Strict self-correlation cutoff: {state.get('strict_self_correlation_cutoff')}",
        f"- Failure counts: {policy.get('failure_counts') or {}}",
        f"- Preferred field families: {', '.join(policy.get('preferred_field_families') or []) or 'none'}",
        f"- Required repairs: {'; '.join(policy.get('required_repairs') or []) or 'none'}",
        "",
        "## Branch",
        "",
        f"- Strategy: {branch_plan.get('strategy')}",
        f"- Primary branch: {branch_plan.get('primary_branch')}",
        f"- Dominant failure: {branch_plan.get('dominant_failure') or 'none'}",
        f"- Actions: {'; '.join(branch_plan.get('actions') or [])}",
        "",
        "## Files",
        "",
    ]
    for label, value in (state.get("files") or {}).items():
        lines.append(f"- {label}: `{value}`")
    lines.append("")
    return "\n".join(lines)


def _validate_autopilot_config(config: WQAgentWorkflowConfig) -> None:
    if config.autopilot_submit:
        target = config.target_active or config.target_submissions
        if target <= 0:
            raise ValueError("autopilot submit mode requires target_active or target_submissions > 0")
        return
    if config.target_ready <= 0:
        raise ValueError("autopilot presubmit mode requires target_ready > 0")


def _child_config(
    config: WQAgentWorkflowConfig,
    paths: WorkflowPaths,
    *,
    branch_plan: dict[str, Any],
    policy: dict[str, Any],
    candidate_files: list[Path],
) -> WQAgentWorkflowConfig:
    strict_sc = safe_float(policy.get("gates", {}).get("strict_self_correlation_cutoff"))
    if strict_sc is None:
        strict_sc = DEFAULT_AUTOPILOT_SELF_CORRELATION_CUTOFF
    common = {
        "presubmit_self_correlation_cutoff": strict_sc,
        "candidate_files": candidate_files,
        "submit_alpha_ids": [],
        "submit_count": 0,
        "generation_mode": str(branch_plan.get("generation_mode") or config.generation_mode),
    }
    if config.autopilot_submit:
        target = config.target_active or config.target_submissions
        return replace(
            config,
            output_dir=paths.output_dir / "autopilot_run_submit",
            target_submissions=target,
            target_ready=0,
            **common,
        )
    return replace(
        config,
        output_dir=paths.output_dir / "autopilot_presubmit",
        target_submissions=0,
        **common,
    )


def _autopilot_dependencies(
    dependencies: dict[str, Any],
    *,
    branch_plan: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    delegate = dependencies.get("model_generate_candidates") or default_model_generate_candidates

    def model_generate_candidates(prompt: str, config: WQAgentWorkflowConfig) -> Any:
        return delegate(_enrich_model_prompt(prompt, branch_plan=branch_plan, policy=policy), config)

    return {**dependencies, "model_generate_candidates": model_generate_candidates}


def _enrich_model_prompt(prompt: str, *, branch_plan: dict[str, Any], policy: dict[str, Any]) -> str:
    return (
        f"{prompt}\n\n"
        "AUTOPILOT RUN POLICY\n"
        f"- Strategy: {branch_plan.get('strategy')}\n"
        f"- Primary branch: {branch_plan.get('primary_branch')}\n"
        f"- Actions: {'; '.join(branch_plan.get('actions') or [])}\n"
        f"- Strict self-correlation cutoff: {policy.get('gates', {}).get('strict_self_correlation_cutoff')}\n"
        f"- Avoid field signatures: {', '.join(policy.get('avoid_field_signatures') or []) or 'none'}\n"
        f"- Preferred field families: {', '.join(policy.get('preferred_field_families') or []) or 'none'}\n"
        "Return candidates with expression, source_family, tag, rationale, provenance, and simulation_settings when possible.\n"
    )


def _normalize_candidate_row(row: dict[str, Any], *, source_path: Path, config: WQAgentWorkflowConfig) -> dict[str, Any]:
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    expression = str(row.get("expression") or result.get("expression") or "").strip()
    settings = clean_simulation_settings(row.get("simulation_settings") or row.get("settings_override")) or {
        "region": config.region,
        "universe": config.universe,
        "delay": config.delay,
        "decay": config.decay,
        "neutralization": config.neutralization,
        "truncation": config.truncation,
    }
    provenance = row.get("provenance") or row.get("source_run") or row.get("forum_evidence") or row.get("repair_evidence")
    if isinstance(provenance, str):
        provenance = {"source": provenance}
    return {
        **row,
        "expression": expression,
        "tag": row.get("tag"),
        "source_family": row.get("source_family") or row.get("mutation_strategy"),
        "field_signature": row.get("field_signature"),
        "rationale": row.get("rationale"),
        "simulation_settings": settings,
        "provenance": provenance,
        "source": str(source_path),
    }


def _append_event(paths: WorkflowPaths, event_type: str, payload: dict[str, Any]) -> None:
    append_jsonl(paths.autopilot_events, {"created_at": utc_now(), "event": event_type, **payload})


def _inventory_event_payload(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "ready_count": inventory.get("ready_count", 0),
        "rejected_count": inventory.get("rejected_count", 0),
        "submitted_count": inventory.get("submitted_count", 0),
        "active_count": inventory.get("active_count", 0),
        "pending_count": inventory.get("pending_count", 0),
        "invalid_ready_count": inventory.get("invalid_ready_count", 0),
        "already_submitted_ready_count": inventory.get("already_submitted_ready_count", 0),
        "ready_alpha_ids": inventory.get("ready_alpha_ids") or [],
        "active_alpha_ids": inventory.get("active_alpha_ids") or [],
        "pending_alpha_ids": inventory.get("pending_alpha_ids") or [],
        "ready_files": inventory.get("ready_files") or [],
        "rejected_files": inventory.get("rejected_files") or [],
        "submitted_files": inventory.get("submitted_files") or [],
    }


def _policy_event_payload(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "failure_counts": policy.get("failure_counts") or {},
        "strict_self_correlation_cutoff": policy.get("gates", {}).get("strict_self_correlation_cutoff"),
        "preferred_field_families": policy.get("preferred_field_families") or [],
        "required_repairs": policy.get("required_repairs") or [],
    }


def _branch_event_payload(branch_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy": branch_plan.get("strategy"),
        "primary_branch": branch_plan.get("primary_branch"),
        "dominant_failure": branch_plan.get("dominant_failure"),
        "actions": branch_plan.get("actions") or [],
    }


def _artifact_paths(
    roots: list[Path],
    *names: str,
    explicit: list[Path] | None = None,
) -> list[Path]:
    out: list[Path] = []
    for path in explicit or []:
        if path and path.is_file():
            out.append(path)
    for root in roots:
        if not root.exists():
            continue
        for name in names:
            direct = root / name
            if direct.is_file():
                out.append(direct)
            out.extend(path for path in root.rglob(name) if path.is_file())
    return _dedupe_paths(out)


def _read_rows_from_paths(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for row in read_jsonl(path):
            rows.append({**row, "source_file": str(path)})
    return rows


def _load_next_run_constraints(roots: list[Path]) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    for path in _next_run_constraint_paths(roots):
        payload = read_json(path)
        if payload:
            constraints.append(payload)
    return constraints


def _next_run_constraint_paths(roots: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        if root and root.exists():
            direct = root / "post_submit_review" / "next_run_constraints.json"
            if direct.is_file():
                paths.append(direct)
            paths.extend(path for path in root.rglob("post_submit_review/next_run_constraints.json") if path.is_file())
    return _dedupe_paths(paths)


def _failure_bucket(row: dict[str, Any]) -> str:
    checks = " ".join(str((check or {}).get("name") or "") for check in row.get("failed_platform_checks") or [])
    text = " ".join(
        str(value or "")
        for value in (
            row.get("presubmit_reject_reason"),
            row.get("candidate_skip_reason"),
            row.get("triage_reason"),
            row.get("review_failure_kind"),
            row.get("failure_kind"),
            row.get("final_status"),
            row.get("status"),
            row.get("detail"),
            checks,
        )
    ).lower()
    if "self" in text and "corr" in text or "sc_fail" in text:
        return "self_correlation"
    if "too_similar" in text or "duplicate" in text or "similarity" in text or "field_signature" in text:
        return "duplicate"
    if "concentrat" in text or "sparse" in text or "distribution" in text:
        return "concentration"
    if "sub_universe" in text or "subuniverse" in text or "threshold" in text or "low_" in text or "fitness" in text or "sharpe" in text:
        return "metric_threshold"
    if "pending" in text:
        return "pending"
    if "platform" in text:
        return "platform"
    return "other"


def _dominant_failure(failure_counts: Counter[str]) -> str:
    if not failure_counts:
        return ""
    return sorted(failure_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _child_ready_count(child_summary: dict[str, Any], child_mode: str, inventory: dict[str, Any]) -> int:
    if child_mode == "presubmit-sequential":
        return safe_int((child_summary.get("presubmit_loop") or {}).get("ready_count"), 0) or 0
    return safe_int(inventory.get("ready_count"), 0) or 0


def _child_active_count(child_summary: dict[str, Any], child_mode: str, inventory: dict[str, Any]) -> int:
    if child_mode == "run-submit":
        return safe_int((child_summary.get("run_submit_loop") or {}).get("submitted_successes"), 0) or 0
    return safe_int(inventory.get("active_count"), 0) or 0


def _child_stop_reason(child_summary: dict[str, Any], child_mode: str) -> str:
    if child_mode == "presubmit-sequential":
        return str((child_summary.get("presubmit_loop") or {}).get("stop_reason") or "")
    return str((child_summary.get("run_submit_loop") or {}).get("stop_reason") or "")


def _is_successful_submit_row(row: dict[str, Any]) -> bool:
    status = _row_status(row)
    if status in SUCCESS_STATUSES:
        return True
    submit_entry = row.get("submit_entry") if isinstance(row.get("submit_entry"), dict) else {}
    return str(submit_entry.get("final_status") or submit_entry.get("status") or "").upper() in SUCCESS_STATUSES


def _is_pending_row(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            row.get("api_check_status"),
            row.get("sc_result"),
            row.get("prod_corr_result"),
            row.get("status"),
            row.get("final_status"),
            row.get("failure_kind"),
        )
    ).lower()
    return "pending" in text


def _row_status(row: dict[str, Any]) -> str:
    return str(row.get("final_status") or row.get("platform_status") or row.get("status") or "").upper()


def _alpha_id(row: dict[str, Any]) -> str:
    submit_entry = row.get("submit_entry") if isinstance(row.get("submit_entry"), dict) else {}
    return str(row.get("alpha_id") or submit_entry.get("alpha_id") or "")


def _unique_text(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out
