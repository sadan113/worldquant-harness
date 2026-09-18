"""Community-sourced five-stage WorldQuant research skill pipeline.

The design is distilled from publicly available WorldQuant BRAIN skill material
and adapted to this harness without copying third-party implementation code.

Stages:
1. knowledge_search
2. research_recorder
3. candidate_designer
4. factor_backtest
5. critic_repair

The module is intentionally submission-agnostic.  It only records research
state, plans batches, and enforces batch discipline when enabled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .artifact_io import append_jsonl, utc_now, write_json

COMMUNITY_POST_URL = (
    "https://support.worldquantbrain.com/hc/zh-cn/community/posts/"
    "42274443124119"
)
PUBLIC_SKILL_REPO = "https://github.com/GRD-Chang/worldquant-skill"


@dataclass(frozen=True)
class SkillStage:
    name: str
    purpose: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    hard_rules: tuple[str, ...] = ()


STAGES: tuple[SkillStage, ...] = (
    SkillStage(
        name="knowledge_search",
        purpose="Search traceable forum, dataset, operator, failure-memory, and optimization evidence before generation.",
        inputs=("research_brief", "community_memory", "legal_inputs", "active_inventory"),
        outputs=("evidence_refs", "field_opportunities", "constraints"),
        hard_rules=(
            "Every adopted community lesson must retain source provenance.",
            "Do not invent field availability or operator compatibility.",
        ),
    ),
    SkillStage(
        name="research_recorder",
        purpose="Persist session constraints, each research round, failure causes, and final summary.",
        inputs=("session_config", "round_events", "review_results"),
        outputs=("skill_pipeline_events.jsonl", "skill_pipeline_manifest.json"),
        hard_rules=(
            "Record hypothesis and economic rationale.",
            "Do not skip the session-level configuration record.",
        ),
    ),
    SkillStage(
        name="candidate_designer",
        purpose="Generate a larger candidate pool, validate expressions, then diversify with structural low-correlation MMR.",
        inputs=("evidence_refs", "active_inventory", "failure_memory"),
        outputs=("candidate_pool.jsonl",),
        hard_rules=(
            "Prefer different field families and operator families.",
            "Settings-only mutations are low priority after self-correlation failure.",
        ),
    ),
    SkillStage(
        name="factor_backtest",
        purpose="Plan validated research batches before live simulation; community-compatible mode uses eight expressions per batch.",
        inputs=("candidate_pool.jsonl",),
        outputs=("simulation_results.jsonl", "batch_plan"),
        hard_rules=(
            "Validate expressions before simulation.",
            "When strict Rule-of-8 mode is enabled, only complete batches of eight are simulated.",
            "Never auto-submit from this stage.",
        ),
    ),
    SkillStage(
        name="critic_repair",
        purpose="Classify metric, correlation, concentration, coverage, syntax, and infrastructure failures and route the next repair.",
        inputs=("simulation_results.jsonl", "check_results", "active_inventory"),
        outputs=("review_queue.jsonl", "repair_queue.jsonl", "failure_memory"),
        hard_rules=(
            "A failed expression must change before retry.",
            "Correlation failures should trigger family/skeleton shifts instead of parameter-only churn.",
        ),
    ),
)


def pipeline_manifest(
    *,
    region: str,
    universe: str,
    delay: int,
    batch_size: int = 8,
    strict_rule_of_eight: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "pipeline": "community-five-stage-v1",
        "region": region,
        "universe": universe,
        "delay": delay,
        "batch_size": max(1, int(batch_size)),
        "strict_rule_of_eight": bool(strict_rule_of_eight),
        "submit_behavior": "never_auto_submit",
        "stages": [asdict(stage) for stage in STAGES],
        "sources": [
            {
                "kind": "requested_community_post",
                "url": COMMUNITY_POST_URL,
                "verification": "page may require authenticated WorldQuant Support access",
            },
            {
                "kind": "public_companion_skill_repository",
                "url": PUBLIC_SKILL_REPO,
                "license": "Apache-2.0",
                "verified_components": [
                    "knowledge_base_search",
                    "alpha-research-recorder",
                    "factor_backtest",
                ],
            },
        ],
    }


def write_pipeline_manifest(
    output_dir: Path,
    *,
    region: str,
    universe: str,
    delay: int,
    batch_size: int = 8,
    strict_rule_of_eight: bool = False,
) -> Path:
    path = output_dir / "skill_pipeline_manifest.json"
    write_json(
        path,
        pipeline_manifest(
            region=region,
            universe=universe,
            delay=delay,
            batch_size=batch_size,
            strict_rule_of_eight=strict_rule_of_eight,
        ),
    )
    return path


def record_skill_event(
    output_dir: Path,
    *,
    stage: str,
    event: str,
    payload: dict[str, Any] | None = None,
) -> None:
    append_jsonl(
        output_dir / "skill_pipeline_events.jsonl",
        {
            "created_at": utc_now(),
            "stage": stage,
            "event": event,
            "payload": payload or {},
        },
    )


def build_rule_of_eight_batches(
    rows: Iterable[dict[str, Any]],
    *,
    batch_size: int = 8,
    strict: bool = True,
) -> dict[str, Any]:
    size = max(1, int(batch_size))
    items = [dict(row) for row in rows if str(row.get("expression") or "").strip()]
    complete = len(items) // size
    kept_count = complete * size if strict else len(items)
    kept = items[:kept_count]
    dropped = items[kept_count:]
    batches = [kept[index:index + size] for index in range(0, len(kept), size)]
    if not strict and batches and len(batches[-1]) < size:
        # A partial final batch is allowed only in compatibility mode.
        pass
    return {
        "batch_size": size,
        "strict": bool(strict),
        "input_count": len(items),
        "kept_count": len(kept),
        "dropped_count": len(dropped),
        "batches": batches,
        "dropped": dropped,
    }
