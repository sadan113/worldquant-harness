"""Scoped memory retrieval and compact action-oriented context packets."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .domain import RunScope
from .ports import AgentRepository

FAILURE_BUCKETS = {
    "self_correlation": "self_correlation",
    "self_correlation_fail": "self_correlation",
    "self_correlation_above_cutoff": "self_correlation",
    "prod_correlation": "prod_correlation",
    "prod_correlation_fail": "prod_correlation",
    "prod_corr_fail": "prod_correlation",
    "correlation_pending": "correlation_pending",
    "correlation_missing": "correlation_pending",
    "concentrated_weight": "concentration",
    "low_sub_universe_sharpe": "concentration",
    "low_sub_universe_fitness": "concentration",
    "sub_universe_fail": "concentration",
    "metric_threshold_fail": "metric_threshold",
    "base_metric_fail": "metric_threshold",
    "low_sharpe": "metric_threshold",
    "low_fitness": "metric_threshold",
    "low_turnover": "metric_threshold",
    "high_turnover": "metric_threshold",
    "simulation_failed": "infrastructure",
    "simulation_timeout": "infrastructure",
    "api_check_error": "infrastructure",
    "infra_timeout": "infrastructure",
    "validation_error": "validation",
    "legal_input": "validation",
    "high_similarity": "duplicate",
    "policy_block": "duplicate",
    "active": "positive",
    "ready": "positive",
}

DEFAULT_BUCKET_QUOTAS = {
    "positive": 12,
    "self_correlation": 12,
    "metric_threshold": 10,
    "concentration": 8,
    "prod_correlation": 6,
    "correlation_pending": 4,
    "validation": 4,
    "infrastructure": 3,
    "other": 6,
    "duplicate": 6,
}

RECOMMENDATIONS = {
    "positive": "Reuse the economic family as a seed, but change fields/operators and verify correlation before submission.",
    "self_correlation": "Change the dominant field or operator family; window-only edits are too weak. Recheck against ACTIVE alphas before simulation.",
    "prod_correlation": "Replace common production-like legs with a different data family and neutralization structure; do not submit until PROD is explicit PASS or safely MISSING.",
    "correlation_pending": "Do not spend a submit attempt. Re-run check-only review later and require explicit SELF PASS.",
    "concentration": "Broaden cross-sectional coverage, add backfill/coverage guards, reduce sparse-leg weight, and test a broader group neutralization.",
    "metric_threshold": "Repair the failing metric directly: improve signal persistence for Sharpe/Fitness or adjust decay/truncation for turnover before adding complexity.",
    "validation": "Repair syntax, legal fields, and operator arity before any platform call.",
    "infrastructure": "Treat this as non-economic evidence; retry only after transport/auth/rate-limit health recovers.",
    "other": "Inspect the original platform detail and make one diagnosis-linked mutation before retrying.",
    "duplicate": "Do not tune the same signature. Change field family and operator skeleton before spending another simulation.",
}


class ScopedMemoryRetriever:
    """Retrieve a bounded, diverse packet from the canonical memory projection."""

    def __init__(self, repository: AgentRepository) -> None:
        self.repository = repository

    def retrieve(
        self,
        scope: RunScope,
        *,
        limit: int = 60,
        bucket_quotas: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        requested = max(1, int(limit))
        quotas = {**DEFAULT_BUCKET_QUOTAS, **(bucket_quotas or {})}
        rows_by_key: dict[str, dict[str, Any]] = {}
        for row in self.repository.query_memory(scope, limit=max(requested * 6, 200)):
            rows_by_key[_memory_identity(row)] = row
        failure_kinds_by_bucket: dict[str, list[str]] = defaultdict(list)
        for failure_kind, bucket in FAILURE_BUCKETS.items():
            failure_kinds_by_bucket[bucket].append(failure_kind)
        for bucket, failure_kinds in failure_kinds_by_bucket.items():
            quota = max(0, int(quotas.get(bucket, quotas["other"])))
            if quota == 0:
                continue
            for row in self.repository.query_memory(
                scope,
                limit=max(quota * 3, 12),
                failure_kinds=failure_kinds,
            ):
                rows_by_key[_memory_identity(row)] = row
        rows = sorted(rows_by_key.values(), key=_memory_priority, reverse=True)
        selected: list[dict[str, Any]] = []
        bucket_counts: dict[str, int] = defaultdict(int)
        seen_subjects: set[tuple[str, str]] = set()
        rows_by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            bucket = _bucket(row)
            subject_key = str(row.get("subject_key") or row.get("candidate_uid") or "")
            dedupe_key = (bucket, subject_key)
            if dedupe_key in seen_subjects:
                continue
            seen_subjects.add(dedupe_key)
            rows_by_bucket[bucket].append(row)

        bucket_order = [bucket for bucket in DEFAULT_BUCKET_QUOTAS if bucket in rows_by_bucket]
        bucket_order.extend(sorted(set(rows_by_bucket) - set(bucket_order)))
        bucket_offsets: dict[str, int] = defaultdict(int)
        while len(selected) < requested:
            made_progress = False
            for bucket in bucket_order:
                quota = max(0, int(quotas.get(bucket, quotas["other"])))
                offset = bucket_offsets[bucket]
                if bucket_counts[bucket] >= quota or offset >= len(rows_by_bucket[bucket]):
                    continue
                selected.append(_compact_memory(rows_by_bucket[bucket][offset], bucket=bucket))
                bucket_offsets[bucket] += 1
                bucket_counts[bucket] += 1
                made_progress = True
                if len(selected) >= requested:
                    break
            if not made_progress:
                break

        evidence_counts = _counts(str(row.get("evidence_class") or "unknown") for row in selected)
        polarity_counts = _counts(str(row.get("polarity") or "unknown") for row in selected)
        health = {
            "ok": True,
            "scope_key": scope.scope_key,
            "owner_key": scope.owner_key,
            "available": len(rows),
            "selected": len(selected),
            "bucket_counts": dict(sorted(bucket_counts.items())),
            "evidence_counts": evidence_counts,
            "polarity_counts": polarity_counts,
            "contradicted_items": sum(int(row.get("contradiction_count") or 0) > 0 for row in selected),
            "low_confidence_items": sum(float(row.get("confidence") or 0.0) < 0.7 for row in selected),
        }
        return {
            "schema_version": 2,
            "scope": {
                "scope_key": scope.scope_key,
                "owner_key": scope.owner_key,
                "account": scope.account,
                "region": scope.region,
                "universe": scope.universe,
                "delay": scope.delay,
            },
            "health": health,
            "items": selected,
            "recommendations": [
                {"bucket": bucket, "advice": RECOMMENDATIONS[bucket]}
                for bucket in bucket_counts
            ],
        }


def _bucket(row: dict[str, Any]) -> str:
    failure_kind = str(row.get("failure_kind") or "").lower()
    if failure_kind in FAILURE_BUCKETS:
        return FAILURE_BUCKETS[failure_kind]
    if "self" in failure_kind and "corr" in failure_kind:
        return "self_correlation"
    if "prod" in failure_kind and "corr" in failure_kind:
        return "prod_correlation"
    if any(token in failure_kind for token in ("concentr", "sub_universe", "coverage")):
        return "concentration"
    if any(token in failure_kind for token in ("sharpe", "fitness", "turnover", "metric")):
        return "metric_threshold"
    if any(token in failure_kind for token in ("timeout", "connection", "rate_limit", "simulation")):
        return "infrastructure"
    return "other"


def _compact_memory(row: dict[str, Any], *, bucket: str) -> dict[str, Any]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    return {
        "memory_id": row.get("memory_id"),
        "candidate_uid": row.get("candidate_uid"),
        "bucket": bucket,
        "failure_kind": row.get("failure_kind"),
        "polarity": row.get("polarity"),
        "evidence_class": row.get("evidence_class"),
        "confidence": row.get("confidence"),
        "support_count": row.get("support_count"),
        "contradiction_count": row.get("contradiction_count"),
        "last_seen_at": row.get("last_seen_at"),
        "alpha_id": payload.get("alpha_id") or record.get("alpha_id"),
        "tag": record.get("tag"),
        "source_family": record.get("source_family"),
        "field_signature": record.get("field_signature"),
        "expression": record.get("expression"),
        "metrics": {
            key: record.get(key)
            for key in ("sharpe", "fitness", "returns", "turnover")
            if record.get(key) not in (None, "")
        },
        "correlation": {
            key: record.get(key)
            for key in ("sc_result", "sc_value", "prod_corr_result", "prod_corr_value")
            if record.get(key) not in (None, "")
        },
        "reason": record.get("reason") or record.get("detail") or record.get("error"),
        "recommendation": RECOMMENDATIONS[bucket],
        "source_artifact": payload.get("source_artifact"),
        "run_id": payload.get("run_id"),
    }


def _memory_identity(row: dict[str, Any]) -> str:
    return str(row.get("memory_id") or row.get("memory_key") or id(row))


def _memory_priority(row: dict[str, Any]) -> tuple[float, int, str]:
    return (
        float(row.get("confidence") or 0.0),
        int(row.get("support_count") or 0),
        str(row.get("last_seen_at") or ""),
    )


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))
