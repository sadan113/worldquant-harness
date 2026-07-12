"""Offline, idempotent import of legacy WQ execution artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..expression_parser import normalize_expression
from ..record_utils import first_stripped_text, nested
from ..wq_failure_taxonomy import canonical_failure_kind
from .domain import (
    AgentEvent,
    CandidateIdentity,
    EffectiveSettings,
    EventType,
    RunScope,
    attempt_uid,
    stable_hash,
)
from .ports import AgentRepository

FILE_KINDS = {
    "agent_events.jsonl": "canonical",
    "simulation_results.jsonl": "simulation",
    "check_results.jsonl": "check",
    "api_check.jsonl": "check",
    "platform_check_results.jsonl": "check",
    "submission_check.jsonl": "check",
    "submit_results.jsonl": "submit",
    "submit_existing_results.jsonl": "submit",
    "submitted_accumulator.jsonl": "submitted",
    "presubmit_ready_sequential.jsonl": "ready",
    "presubmit_rejected.jsonl": "rejected",
    "platform_alphas.jsonl": "platform",
    "selected_platform_alphas.jsonl": "platform",
    "alpha_lifecycle_events.jsonl": "lifecycle",
    "history_alpha_events.jsonl": "lifecycle",
}

EVENT_ORDER = {
    EventType.ARTIFACT_IMPORTED.value: 0,
    EventType.CANDIDATE_CREATED.value: 1,
    EventType.VALIDATION_PASSED.value: 2,
    EventType.VALIDATION_REJECTED.value: 3,
    EventType.SIMULATION_STARTED.value: 4,
    EventType.SIMULATION_SUCCEEDED.value: 5,
    EventType.SIMULATION_FAILED.value: 6,
    EventType.CHECK_STARTED.value: 7,
    EventType.CHECK_SUCCEEDED.value: 8,
    EventType.CHECK_BLOCKED.value: 9,
    EventType.READY.value: 10,
    EventType.SUBMIT_STARTED.value: 11,
    EventType.SUBMISSION_PENDING.value: 12,
    EventType.SUBMIT_FAILED.value: 13,
    EventType.SUBMIT_SUCCEEDED.value: 14,
    EventType.ACTIVE_CONFIRMED.value: 15,
}


@dataclass(frozen=True)
class BackfillItem:
    event: AgentEvent
    candidate: CandidateIdentity


@dataclass
class _IdentityHint:
    expression: str
    settings: dict[str, Any]
    settings_score: int
    source_priority: int
    source: str


def build_backfill(
    roots: Iterable[Path | str],
    *,
    account: str = "primary",
    user_id: str | None = None,
    include_platform_snapshots: bool = True,
    max_conflict_details: int = 200,
    run_id_override: str | None = None,
) -> tuple[list[BackfillItem], dict[str, Any]]:
    root_paths = [Path(root).resolve() for root in roots]
    files, discovery = _discover(root_paths, include_platform_snapshots=include_platform_snapshots)
    alpha_hints: dict[str, _IdentityHint] = {}
    candidate_hints: dict[str, _IdentityHint] = {}
    report: dict[str, Any] = {
        "schema_version": 2,
        "dry_run": True,
        "roots": [str(path) for path in root_paths],
        "recognized_files": len(files),
        "recognized_files_physical": discovery["physical_files"],
        "deduped_platform_files": discovery["deduped_platform_files"],
        "recognized_by_kind": _counts(kind for _, kind, _ in files),
        "rows_scanned": 0,
        "importable_rows": 0,
        "unique_events": 0,
        "duplicate_events": 0,
        "skipped_rows": 0,
        "skipped_by_reason": {},
        "skipped_by_kind_reason": {},
        "conflict_count": 0,
        "conflicts": [],
        "event_counts": {},
        "applied_events": 0,
    }

    for path, kind, source in files:
        if kind == "platform":
            continue
        for line_no, row in _iter_jsonl(path):
            _learn_identity(
                row,
                kind=kind,
                source=f"{source}:{line_no}",
                account=account,
                alpha_hints=alpha_hints,
                candidate_hints=candidate_hints,
                report=report,
                max_conflict_details=max_conflict_details,
            )

    unique: dict[str, BackfillItem] = {}
    seen_platform_rows: set[str] = set()
    platform_entries: list[tuple[dict[str, Any], str, int, str]] = []

    def consume_row(row: dict[str, Any], kind: str, source: str, line_no: int, fallback_time: str) -> None:
        item, skip_reason = _row_to_item(
            row,
            kind=kind,
            source=source,
            line_no=line_no,
            fallback_time=fallback_time,
            account=account,
            user_id=user_id,
            alpha_hints=alpha_hints,
            candidate_hints=candidate_hints,
            report=report,
            max_conflict_details=max_conflict_details,
            run_id_override=run_id_override,
        )
        if item is None:
            report["skipped_rows"] += 1
            _increment(report["skipped_by_reason"], skip_reason or "unrecognized")
            _increment(report["skipped_by_kind_reason"], f"{kind}:{skip_reason or 'unrecognized'}")
            return
        report["importable_rows"] += 1
        if item.event.event_id in unique:
            report["duplicate_events"] += 1
            return
        unique[item.event.event_id] = item

    for path, kind, source in files:
        if kind != "platform":
            continue
        fallback_time = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        for line_no, row in _iter_jsonl(path):
            report["rows_scanned"] += 1
            platform_key = _platform_row_key(row)
            if platform_key in seen_platform_rows:
                report["importable_rows"] += 1
                report["duplicate_events"] += 1
                continue
            seen_platform_rows.add(platform_key)
            _learn_identity(
                row,
                kind=kind,
                source=f"{source}:{line_no}",
                account=account,
                alpha_hints=alpha_hints,
                candidate_hints=candidate_hints,
                report=report,
                max_conflict_details=max_conflict_details,
            )
            platform_entries.append((row, source, line_no, fallback_time))

    for row, source, line_no, fallback_time in platform_entries:
        consume_row(row, "platform", source, line_no, fallback_time)

    for path, kind, source in files:
        if kind == "platform":
            continue
        fallback_time = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        for line_no, row in _iter_jsonl(path):
            report["rows_scanned"] += 1
            consume_row(row, kind, source, line_no, fallback_time)

    items = sorted(
        unique.values(),
        key=lambda item: (
            item.event.occurred_at,
            EVENT_ORDER.get(item.event.event_type, 0),
            item.event.event_id,
        ),
    )
    report["unique_events"] = len(items)
    report["event_counts"] = _counts(item.event.event_type for item in items)
    report["identity_index"] = {
        "alpha_ids": len(alpha_hints),
        "candidate_keys": len(candidate_hints),
    }
    active_types = {EventType.SUBMIT_SUCCEEDED.value, EventType.ACTIVE_CONFIRMED.value}
    active_items = [item for item in items if item.event.event_type in active_types]
    candidates_by_alpha: dict[str, set[str]] = {}
    for item in active_items:
        if item.event.alpha_id:
            candidates_by_alpha.setdefault(item.event.alpha_id, set()).add(item.candidate.candidate_uid)
    ambiguous = {
        alpha_id: sorted(candidate_uids)
        for alpha_id, candidate_uids in candidates_by_alpha.items()
        if len(candidate_uids) > 1
    }
    report["active_identity_quality"] = {
        "active_events": len(active_items),
        "null_alpha_id_events": sum(not item.event.alpha_id for item in active_items),
        "distinct_alpha_ids": len(candidates_by_alpha),
        "ambiguous_alpha_ids": len(ambiguous),
        "ambiguous_examples": dict(list(sorted(ambiguous.items()))[:20]),
    }
    return items, report


def apply_backfill(
    repository: AgentRepository,
    items: list[BackfillItem],
    *,
    batch_size: int = 500,
) -> int:
    applied = 0
    size = max(1, int(batch_size))
    for start in range(0, len(items), size):
        batch = items[start : start + size]
        applied += repository.append_many([(item.event, item.candidate) for item in batch])
    return applied


def _discover(
    roots: list[Path],
    *,
    include_platform_snapshots: bool,
) -> tuple[list[tuple[Path, str, str]], dict[str, int]]:
    found: dict[Path, tuple[Path, str, str]] = {}
    physical_files = 0
    deduped_platform_files = 0
    platform_content: set[tuple[int, str]] = set()
    for root in roots:
        candidates = [root] if root.is_file() else root.rglob("*.jsonl") if root.is_dir() else []
        for path in candidates:
            kind = FILE_KINDS.get(path.name.lower())
            if not kind or (kind == "platform" and not include_platform_snapshots):
                continue
            physical_files += 1
            resolved = path.resolve()
            if kind == "platform":
                content_key = (resolved.stat().st_size, _file_digest(resolved))
                if content_key in platform_content:
                    deduped_platform_files += 1
                    continue
                platform_content.add(content_key)
            found[resolved] = (resolved, kind, _source_label(resolved, roots))
    files = [found[path] for path in sorted(found, key=lambda value: value.as_posix().lower())]
    return files, {
        "physical_files": physical_files,
        "deduped_platform_files": deduped_platform_files,
    }


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text.startswith("{"):
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield line_no, row


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _platform_row_key(row: dict[str, Any]) -> str:
    return stable_hash(
        {
            "alpha_id": _alpha_id(row),
            "expression": _expression(row),
            "status": row.get("status") or row.get("platform_status") or row.get("final_status"),
            "created_at": row.get("created_at") or row.get("dateCreated") or row.get("dateSubmitted"),
            "sharpe": row.get("sharpe"),
            "fitness": row.get("fitness"),
            "turnover": row.get("turnover"),
            "settings": row.get("settings") or row.get("effective_settings") or row.get("simulation_settings"),
        },
        length=40,
    )


def _learn_identity(
    row: dict[str, Any],
    *,
    kind: str,
    source: str,
    account: str,
    alpha_hints: dict[str, _IdentityHint],
    candidate_hints: dict[str, _IdentityHint],
    report: dict[str, Any],
    max_conflict_details: int,
) -> None:
    expression = _expression(row)
    if not expression:
        return
    settings, score = _settings(row, account=account)
    hint = _IdentityHint(
        expression=expression,
        settings=settings,
        settings_score=score,
        source_priority=_settings_source_priority(kind, row),
        source=source,
    )
    alpha_id = _alpha_id(row)
    candidate_key = first_stripped_text(row.get("candidate_key"), row.get("candidate_uid"))
    if alpha_id:
        _merge_hint(alpha_hints, alpha_id, hint, "alpha_id", report, max_conflict_details)
    if candidate_key:
        _merge_hint(candidate_hints, candidate_key, hint, "candidate_key", report, max_conflict_details)


def _merge_hint(
    hints: dict[str, _IdentityHint],
    key: str,
    incoming: _IdentityHint,
    key_kind: str,
    report: dict[str, Any],
    max_conflict_details: int,
) -> None:
    existing = hints.get(key)
    if existing is None:
        hints[key] = incoming
        return
    if normalize_expression(existing.expression) != normalize_expression(incoming.expression):
        _conflict(
            report,
            {
                "kind": "identity_expression_conflict",
                "key_kind": key_kind,
                "key": key,
                "existing_expression": existing.expression,
                "incoming_expression": incoming.expression,
                "existing_source": existing.source,
                "incoming_source": incoming.source,
            },
            max_conflict_details,
        )
        return
    if (incoming.source_priority, incoming.settings_score) > (existing.source_priority, existing.settings_score):
        hints[key] = incoming


def _row_to_item(
    row: dict[str, Any],
    *,
    kind: str,
    source: str,
    line_no: int,
    fallback_time: str,
    account: str,
    user_id: str | None,
    alpha_hints: dict[str, _IdentityHint],
    candidate_hints: dict[str, _IdentityHint],
    report: dict[str, Any],
    max_conflict_details: int,
    run_id_override: str | None,
) -> tuple[BackfillItem | None, str | None]:
    expression = _expression(row)
    settings, score = _settings(row, account=account)
    hint = _identity_hint(row, alpha_hints=alpha_hints, candidate_hints=candidate_hints)
    if not expression and hint:
        expression = hint.expression
    row_priority = _settings_source_priority(kind, row)
    if hint and (hint.source_priority, hint.settings_score) > (row_priority, score):
        settings = hint.settings
    if not expression:
        return None, "missing_expression"

    effective = EffectiveSettings.from_mapping(settings)
    candidate = CandidateIdentity.create(expression, effective)
    if kind == "canonical":
        direct = _canonical_event(
            row,
            candidate=candidate,
            source=source,
            fallback_time=fallback_time,
            user_id=user_id,
        )
        if direct is None:
            return None, "invalid_canonical_event"
        if row.get("candidate_uid") and str(row["candidate_uid"]) != candidate.candidate_uid:
            _conflict(
                report,
                {
                    "kind": "canonical_candidate_uid_mismatch",
                    "source": f"{source}:{line_no}",
                    "stored": row.get("candidate_uid"),
                    "reconstructed": candidate.candidate_uid,
                },
                max_conflict_details,
            )
        return BackfillItem(direct, candidate), None

    record = _normalized_record(row)
    event_type = _legacy_event_type(kind, record)
    if event_type is None:
        return None, "unrecognized_status"
    scope = RunScope.from_settings(effective.to_platform_dict(), user_id=user_id)
    run_id = _bounded_run_id(
        run_id_override
        or first_stripped_text(record.get("run_id"))
        or f"legacy:{Path(source).parent.as_posix()}"
    )
    attempt = attempt_uid(run_id, candidate.candidate_uid)
    alpha_id = _alpha_id(record)
    occurred_at = _occurred_at(record, fallback_time=fallback_time)
    stage = _event_stage(event_type)
    evidence_class = _evidence_class(event_type)
    metadata = _source_metadata(record)
    payload = {
        **metadata,
        "expression": candidate.expression,
        "simulation_settings": effective.to_platform_dict(),
        "record": record,
        "failure_kind": record.get("failure_kind"),
        "evidence_class_override": evidence_class,
        "backfill": {"source_artifact": source, "line": line_no, "kind": kind},
    }
    fingerprint = stable_hash(
        {
            "event_type": event_type.value,
            "candidate_uid": candidate.candidate_uid,
            "alpha_id": alpha_id,
            "created_at": first_stripped_text(
                record.get("created_at"),
                record.get("occurred_at"),
                record.get("updated_at"),
            ),
            "status": first_stripped_text(
                record.get("final_status"),
                record.get("platform_status"),
                record.get("status"),
                record.get("api_check_status"),
            ),
            "failure_kind": record.get("failure_kind"),
            "simulation_id": record.get("simulation_id"),
            "sharpe": record.get("sharpe"),
            "fitness": record.get("fitness"),
            "turnover": record.get("turnover"),
            "sc_result": record.get("sc_result"),
            "sc_value": record.get("sc_value"),
            "prod_corr_result": record.get("prod_corr_result"),
            "prod_corr_value": record.get("prod_corr_value"),
        },
        length=40,
    )
    event = AgentEvent.create(
        event_type,
        run_id=run_id,
        attempt_uid=attempt,
        candidate=candidate,
        scope=scope,
        stage=stage,
        payload=payload,
        alpha_id=alpha_id,
        source_artifact=source,
        event_key=(
            f"legacy-run:{stable_hash(run_id_override, length=16)}:{event_type.value}:{fingerprint}"
            if run_id_override
            else f"legacy:{event_type.value}:{fingerprint}"
        ),
        occurred_at=occurred_at,
    )
    return BackfillItem(event, candidate), None


def _canonical_event(
    row: dict[str, Any],
    *,
    candidate: CandidateIdentity,
    source: str,
    fallback_time: str,
    user_id: str | None,
) -> AgentEvent | None:
    event_id = first_stripped_text(row.get("event_id"))
    event_type = first_stripped_text(row.get("event_type"))
    if not event_id or not event_type:
        return None
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    effective = candidate.settings
    scope = RunScope(
        user_id=user_id or first_stripped_text(row.get("user_id")),
        account=first_stripped_text(row.get("account")) or effective.account,
        region=first_stripped_text(row.get("region")) or effective.region,
        universe=first_stripped_text(row.get("universe")) or effective.universe,
        delay=int(row.get("delay") if row.get("delay") not in (None, "") else effective.delay),
    )
    return AgentEvent(
        event_id=event_id,
        schema_version=int(row.get("schema_version") or 2),
        event_type=event_type,
        occurred_at=first_stripped_text(row.get("occurred_at")) or fallback_time,
        run_id=_bounded_run_id(first_stripped_text(row.get("run_id")) or "canonical-import"),
        attempt_uid=first_stripped_text(row.get("attempt_uid")) or attempt_uid("canonical-import", candidate.candidate_uid),
        candidate_uid=first_stripped_text(row.get("candidate_uid")) or candidate.candidate_uid,
        scope_key=first_stripped_text(row.get("scope_key")) or scope.scope_key,
        owner_key=first_stripped_text(row.get("owner_key")) or scope.owner_key,
        account=scope.account,
        region=scope.region,
        universe=scope.universe,
        delay=scope.delay,
        stage=first_stripped_text(row.get("stage")) or "import",
        payload=payload,
        alpha_id=first_stripped_text(row.get("alpha_id")),
        user_id=scope.user_id,
        source_artifact=first_stripped_text(row.get("source_artifact")) or source,
    )


def _legacy_event_type(kind: str, row: dict[str, Any]) -> EventType | None:
    if kind == "simulation":
        if str(row.get("status") or "").lower() == "validation_failed":
            return EventType.VALIDATION_REJECTED
        return EventType.SIMULATION_SUCCEEDED if row.get("ok") is not False else EventType.SIMULATION_FAILED
    if kind == "check":
        return EventType.CHECK_SUCCEEDED if _check_passed(row) else EventType.CHECK_BLOCKED
    if kind == "submit":
        return _submit_event_type(row)
    if kind == "submitted":
        return EventType.SUBMIT_SUCCEEDED if _is_active(row) else _submit_event_type(row)
    if kind == "ready":
        return EventType.READY
    if kind == "rejected":
        return EventType.CHECK_BLOCKED
    if kind == "platform":
        return EventType.ACTIVE_CONFIRMED if _is_active(row) else EventType.ARTIFACT_IMPORTED
    if kind == "lifecycle":
        legacy_type = str(row.get("event_type") or "").lower()
        if legacy_type == "simulation_finished":
            return EventType.SIMULATION_FAILED if row.get("ok") is False else EventType.SIMULATION_SUCCEEDED
        if legacy_type == "review_finished":
            return EventType.CHECK_SUCCEEDED if _check_passed(row) else EventType.CHECK_BLOCKED
        if legacy_type == "candidate_ready":
            return EventType.READY
        if legacy_type == "candidate_rejected":
            return EventType.CHECK_BLOCKED
        source_type = str(row.get("source_type") or "").lower()
        if source_type == "platform_alpha":
            return EventType.ACTIVE_CONFIRMED if _is_active(row) else EventType.ARTIFACT_IMPORTED
        if source_type == "simulation_result":
            status = str(row.get("status") or row.get("raw_status") or row.get("platform_status") or "").lower()
            if status in {"dry_run", "candidate", ""}:
                return EventType.ARTIFACT_IMPORTED
            if status in {"failed", "failure", "simulation_failed", "simulation_timeout"}:
                return EventType.SIMULATION_FAILED
            return EventType.SIMULATION_SUCCEEDED
        if source_type in {"review_queue", "api_check"}:
            status = str(row.get("status") or row.get("raw_status") or row.get("platform_status") or "").lower()
            if status == "dry_run" or (
                not row.get("api_check_status")
                and not row.get("sc_result")
                and not row.get("prod_corr_result")
            ):
                return EventType.ARTIFACT_IMPORTED
            return EventType.CHECK_SUCCEEDED if _check_passed(row) else EventType.CHECK_BLOCKED
        if source_type in {"submit_result", "submit_existing_result"}:
            return _submit_event_type(row)
        if source_type == "presubmit_ready":
            return EventType.READY
        if source_type == "presubmit_rejected":
            return EventType.CHECK_BLOCKED
        lifecycle_status = str(row.get("lifecycle_status") or "").lower()
        if lifecycle_status in {"active", "submitted"}:
            return EventType.ACTIVE_CONFIRMED
        if lifecycle_status in {"ready", "pre_submit_pass"}:
            return EventType.READY
        if lifecycle_status:
            return EventType.ARTIFACT_IMPORTED
        try:
            return EventType(legacy_type)
        except ValueError:
            return None
    return None


def _submit_event_type(row: dict[str, Any]) -> EventType:
    if _is_active(row):
        return EventType.SUBMIT_SUCCEEDED
    status = str(row.get("final_status") or row.get("platform_status") or "").upper()
    failure = str(row.get("failure_kind") or "").lower()
    if status in {"CORR_PENDING", "PENDING", "TIMEOUT"} or failure == "correlation_pending":
        return EventType.SUBMISSION_PENDING
    return EventType.SUBMIT_FAILED


def _check_passed(row: dict[str, Any]) -> bool:
    if row.get("failed_platform_checks"):
        return False
    status = str(row.get("api_check_status") or "")
    if status and status != "api_check_readable":
        return False
    self_result = str(row.get("sc_result") or nested(row, "self_correlation", "result") or "").upper()
    prod_result = str(row.get("prod_corr_result") or nested(row, "prod_correlation", "result") or "MISSING").upper()
    return self_result == "PASS" and prod_result not in {"FAIL", "PENDING"}


def _is_active(row: dict[str, Any]) -> bool:
    return str(row.get("final_status") or row.get("platform_status") or row.get("status") or "").upper() == "ACTIVE"


def _normalized_record(row: dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    if not record.get("status") and record.get("raw_status"):
        record["status"] = record["raw_status"]
    if not record.get("final_status") and record.get("raw_final_status"):
        record["final_status"] = record["raw_final_status"]
    if not record.get("failure_kind") and record.get("review_failure_kind"):
        record["failure_kind"] = record["review_failure_kind"]
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    for key in ("sharpe", "fitness", "returns", "turnover", "drawdown", "margin", "sc_value", "prod_corr_value"):
        if record.get(key) in (None, "") and metrics.get(key) not in (None, ""):
            record[key] = metrics[key]
    self_check = row.get("self_correlation") if isinstance(row.get("self_correlation"), dict) else {}
    prod_check = row.get("prod_correlation") if isinstance(row.get("prod_correlation"), dict) else {}
    record.setdefault("sc_result", self_check.get("result"))
    record.setdefault("sc_value", self_check.get("value"))
    record.setdefault("prod_corr_result", prod_check.get("result"))
    record.setdefault("prod_corr_value", prod_check.get("value"))
    if not record.get("failure_kind"):
        record["failure_kind"] = _derived_failure_kind(record)
    return record


def _derived_failure_kind(row: dict[str, Any]) -> str | None:
    canonical = canonical_failure_kind(row)
    if canonical and canonical != "platform_alpha":
        return canonical
    final_status = str(row.get("final_status") or "").upper()
    if final_status == "SC_FAIL" or str(row.get("sc_result") or "").upper() == "FAIL":
        return "self_correlation"
    if final_status == "PROD_CORR_FAIL" or str(row.get("prod_corr_result") or "").upper() == "FAIL":
        return "prod_correlation"
    if final_status in {"CORR_PENDING", "PENDING"} or str(row.get("api_check_status") or "") == "api_check_pending":
        return "correlation_pending"
    if row.get("failed_platform_checks"):
        first = row["failed_platform_checks"][0]
        return str(first.get("name") or "platform_check_fail").lower() if isinstance(first, dict) else "platform_check_fail"
    if str(row.get("status") or "").lower() == "validation_failed":
        return "validation_error"
    if row.get("ok") is False:
        return first_stripped_text(row.get("triage_reason"), row.get("reason"), row.get("status"), "unknown_failure")
    if str(row.get("status") or "").lower() in {"failed", "failure", "simulation_failed", "simulation_timeout"}:
        return "simulation_failed"
    return None


def _identity_hint(
    row: dict[str, Any],
    *,
    alpha_hints: dict[str, _IdentityHint],
    candidate_hints: dict[str, _IdentityHint],
) -> _IdentityHint | None:
    alpha_id = _alpha_id(row)
    if alpha_id and alpha_id in alpha_hints:
        return alpha_hints[alpha_id]
    candidate_key = first_stripped_text(row.get("candidate_key"), row.get("candidate_uid"))
    return candidate_hints.get(candidate_key or "")


def _expression(row: dict[str, Any]) -> str | None:
    return first_stripped_text(
        row.get("expression"),
        nested(row, "record", "expression"),
        nested(row, "payload", "expression"),
        nested(row, "payload", "record", "expression"),
        nested(row, "regular", "code"),
        nested(row, "alpha", "expression"),
        nested(row, "candidate", "expression"),
        nested(row, "result", "expression"),
    )


def _settings(row: dict[str, Any], *, account: str) -> tuple[dict[str, Any], int]:
    merged: dict[str, Any] = {"account": account}
    score = 0
    candidates = (
        row.get("simulation_settings"),
        row.get("settings"),
        row.get("efficiency_settings"),
        row.get("effective_settings"),
        row.get("effective_simulation_settings"),
        row.get("simulation_settings_effective"),
        nested(row, "payload", "simulation_settings"),
        nested(row, "payload", "record", "simulation_settings"),
        nested(row, "payload", "record", "simulation_settings_effective"),
    )
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key, value in candidate.items():
            if value not in (None, ""):
                merged[key] = value
        score = max(score, sum(key in candidate for key in ("region", "universe", "delay", "decay", "neutralization", "truncation")))
    return merged, score


def _alpha_id(row: dict[str, Any]) -> str | None:
    return first_stripped_text(
        row.get("alpha_id"),
        row.get("id") if isinstance(row.get("regular"), dict) or str(row.get("type") or "").upper() == "REGULAR" else None,
        nested(row, "record", "alpha_id"),
        nested(row, "payload", "record", "alpha_id"),
        nested(row, "result", "alpha_id"),
    )


def _settings_source_priority(kind: str, row: dict[str, Any]) -> int:
    if kind == "platform":
        return 100
    if kind == "canonical":
        return 95
    if kind == "simulation":
        return 90
    if kind in {"check", "submit", "submitted", "ready", "rejected"}:
        return 80
    if kind == "lifecycle":
        return 30 if str(row.get("source_type") or "") == "platform_alpha" else 20
    return 10


def _source_metadata(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
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
    )
    return {key: row.get(key) for key in keys if row.get(key) not in (None, "", [], {})}


def _occurred_at(row: dict[str, Any], *, fallback_time: str) -> str:
    return first_stripped_text(
        row.get("occurred_at"),
        row.get("created_at"),
        row.get("updated_at"),
        row.get("timestamp"),
    ) or fallback_time


def _event_stage(event_type: EventType) -> str:
    if event_type in {EventType.VALIDATION_PASSED, EventType.VALIDATION_REJECTED}:
        return "validation"
    if event_type in {EventType.SIMULATION_STARTED, EventType.SIMULATION_SUCCEEDED, EventType.SIMULATION_FAILED}:
        return "simulation"
    if event_type in {EventType.CHECK_STARTED, EventType.CHECK_SUCCEEDED, EventType.CHECK_BLOCKED}:
        return "check"
    if event_type == EventType.READY:
        return "ready"
    if event_type in {
        EventType.SUBMIT_STARTED,
        EventType.SUBMIT_SUCCEEDED,
        EventType.SUBMIT_FAILED,
        EventType.SUBMISSION_PENDING,
        EventType.ACTIVE_CONFIRMED,
    }:
        return "submit"
    return "import"


def _evidence_class(event_type: EventType) -> str:
    if event_type in {EventType.SUBMIT_SUCCEEDED, EventType.SUBMIT_FAILED, EventType.ACTIVE_CONFIRMED}:
        return "platform_submit"
    if event_type in {EventType.CHECK_SUCCEEDED, EventType.CHECK_BLOCKED, EventType.READY, EventType.SUBMISSION_PENDING}:
        return "platform_check"
    if event_type in {EventType.SIMULATION_SUCCEEDED, EventType.SIMULATION_FAILED}:
        return "simulation"
    if event_type in {EventType.VALIDATION_PASSED, EventType.VALIDATION_REJECTED}:
        return "local_validation"
    return "artifact_import"


def _source_label(path: Path, roots: list[Path]) -> str:
    for root in roots:
        base = root.parent if root.is_file() else root
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def _bounded_run_id(value: str, *, limit: int = 200) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    suffix = stable_hash(text, length=24)
    return f"{text[: limit - len(suffix) - 1]}:{suffix}"


def _conflict(report: dict[str, Any], detail: dict[str, Any], max_details: int) -> None:
    report["conflict_count"] += 1
    if len(report["conflicts"]) < max(0, max_details):
        report["conflicts"].append(detail)


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        _increment(counts, str(value))
    return dict(sorted(counts.items()))
