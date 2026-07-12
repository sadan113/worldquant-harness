"""Phased adapter from legacy workflow artifacts to canonical agent events."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifact_io import write_json
from .backfill import apply_backfill, build_backfill
from .repositories import SqlAgentRepository


def sync_workflow_artifacts(
    output_dir: Path,
    *,
    account: str,
    user_id: str | None = None,
    repository: Any | None = None,
) -> dict[str, Any]:
    items, report = build_backfill(
        [output_dir],
        account=account,
        user_id=user_id,
        include_platform_snapshots=True,
        max_conflict_details=50,
    )
    applied = apply_backfill(repository or SqlAgentRepository(), items)
    summary = {
        "ok": True,
        "mode": "shadow_adapter",
        "recognized_files": report["recognized_files"],
        "rows_scanned": report["rows_scanned"],
        "unique_events": report["unique_events"],
        "duplicate_events": report["duplicate_events"],
        "skipped_rows": report["skipped_rows"],
        "conflict_count": report["conflict_count"],
        "event_counts": report["event_counts"],
        "applied_events": applied,
    }
    write_json(output_dir / "agent_event_sync.json", {**report, **summary, "dry_run": False})
    return summary
