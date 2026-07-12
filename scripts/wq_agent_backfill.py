"""Backfill canonical WQ agent events from legacy local artifacts.

Dry-run is the default. Use --apply only after reviewing the generated report.
This command is offline and never calls the WorldQuant platform.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worldquant_harness.artifact_io import write_json
from worldquant_harness.wq_agent_core.backfill import apply_backfill, build_backfill
from worldquant_harness.wq_agent_core.repositories import SqlAgentRepository


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.rebuild_projections:
        result = SqlAgentRepository().rebuild_projections()
        output = {"ok": True, "mode": "rebuild_projections", **result}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    roots = [_resolve(path) for path in (args.roots or ["reports"])]
    items, report = build_backfill(
        roots,
        account=args.account,
        user_id=args.user_id,
        include_platform_snapshots=not args.exclude_platform_snapshots,
        max_conflict_details=args.max_conflict_details,
    )
    if args.apply:
        report["applied_events"] = apply_backfill(
            SqlAgentRepository(),
            items,
            batch_size=args.batch_size,
        )
    report["dry_run"] = not args.apply
    report_path = _resolve(args.report)
    write_json(report_path, report)
    output = {
        "ok": True,
        "mode": "dry_run" if report["dry_run"] else "apply",
        "report": str(report_path),
        "recognized_files": report["recognized_files"],
        "rows_scanned": report["rows_scanned"],
        "unique_events": report["unique_events"],
        "duplicate_events": report["duplicate_events"],
        "skipped_rows": report["skipped_rows"],
        "conflict_count": report["conflict_count"],
        "applied_events": report["applied_events"],
        "event_counts": report["event_counts"],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline backfill of canonical WQ agent events")
    parser.add_argument("roots", nargs="*", help="Artifact roots or individual JSONL files; defaults to reports/")
    parser.add_argument("--apply", action="store_true", help="Write events and projections to DATABASE_URL")
    parser.add_argument("--rebuild-projections", action="store_true", help="Rebuild candidate and memory projections from existing canonical events")
    parser.add_argument("--account", default="primary")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--exclude-platform-snapshots", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-conflict-details", type=int, default=200)
    parser.add_argument("--report", default="reports/wq_agent_backfill_report.json")
    return parser.parse_args(argv)


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
