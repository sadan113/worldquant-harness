"""Private low-correlation helpers for WorldQuant candidate diversification.

This module is intentionally independent from platform submission code.  It
builds structural fingerprints, compares candidate families, and provides an
MMR selector that can be used before spending simulation budget.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Iterable

from .expression_parser import extract_components, normalize_expression

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_NUMBER_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?")
_WINDOW_RE = re.compile(r"(?:,|\()\s*(\d{1,4})\s*(?:,|\))")

_PRICE_VOLUME = {
    "open", "high", "low", "close", "volume", "vwap", "returns", "cap",
    "market_cap", "range",
}
_FUNDAMENTAL_HINTS = (
    "cashflow", "cash_flow", "revenue", "sales", "income", "dividend",
    "asset", "liabil", "debt", "book", "enterprise_value", "equity",
    "ebit", "ebitda", "capex", "inventory", "goodwill", "margin",
)
_ANALYST_HINTS = (
    "anl", "analyst", "estimate", "est_", "eps", "earnings", "recommend",
    "price_target", "revision", "surprise", "forecast",
)
_OPTION_HINTS = (
    "pcr", "implied_vol", "option", "open_interest", "iv_", "_iv",
)
_SENTIMENT_HINTS = (
    "sentiment", "snt", "scl", "buzz", "news", "nws", "headline",
)
_INSTITUTION_HINTS = ("institution", "insider", "ownership")
_SHORT_HINTS = ("short_interest", "short_ratio", "short_sale")
_MACRO_HINTS = (
    "macro", "gdp", "inflation", "pmi", "yield", "interest_rate", "fx_",
    "credit_risk", "policy_rate",
)
_RISK_HINTS = ("risk", "beta", "volatility", "vol_", "drawdown")
_RELATIONSHIP_HINTS = ("rel_", "customer", "supplier")

_OPERATOR_FAMILIES = {
    "rank": "cross_section",
    "zscore": "cross_section",
    "scale": "cross_section",
    "group_rank": "group_cross_section",
    "group_zscore": "group_cross_section",
    "group_neutralize": "group_neutralize",
    "indneutralize": "group_neutralize",
    "ts_mean": "ts_level",
    "ts_std": "ts_level",
    "ts_max": "ts_level",
    "ts_min": "ts_level",
    "ts_sum": "ts_level",
    "ts_shift": "ts_level",
    "decay_linear": "ts_level",
    "product": "ts_level",
    "ts_av_diff": "ts_change",
    "ts_delta": "ts_change",
    "delta": "ts_change",
    "ts_rank": "ts_order",
    "ts_argmax": "ts_order",
    "ts_argmin": "ts_order",
    "ts_corr": "ts_relation",
    "ts_cov": "ts_relation",
    "correlation": "ts_relation",
    "covariance": "ts_relation",
    "where": "conditional",
    "trade_when": "conditional",
    "abs": "pointwise",
    "sign": "pointwise",
    "log": "pointwise",
    "sqrt": "pointwise",
    "power": "pointwise",
    "sign_power": "pointwise",
    "max": "pointwise",
    "min": "pointwise",
}


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a = {str(value) for value in left if value}
    b = {str(value) for value in right if value}
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def field_family(field: str) -> str:
    value = str(field or "").lower()
    if not value:
        return "unknown"
    if value in _PRICE_VOLUME or value.startswith("adv"):
        return "price_volume"
    if any(token in value for token in _OPTION_HINTS):
        return "options"
    if any(token in value for token in _SENTIMENT_HINTS):
        return "news_sentiment"
    if any(token in value for token in _SHORT_HINTS):
        return "short_interest"
    if any(token in value for token in _INSTITUTION_HINTS):
        return "institutions_insiders"
    if any(token in value for token in _MACRO_HINTS):
        return "macro_credit"
    if value.startswith("rel_") or any(token in value for token in _RELATIONSHIP_HINTS):
        return "relationships"
    if any(token in value for token in _ANALYST_HINTS):
        return "analyst_earnings"
    if any(token in value for token in _FUNDAMENTAL_HINTS):
        return "fundamental"
    if any(token in value for token in _RISK_HINTS):
        return "risk"
    if value in {"industry", "sector", "subindustry", "market"}:
        return "group"
    return "other"


def operator_family(operator: str) -> str:
    value = str(operator or "").lower()
    return _OPERATOR_FAMILIES.get(value, "other")


def _window_bucket(value: int) -> str:
    if value <= 5:
        return "w_1_5"
    if value <= 20:
        return "w_6_20"
    if value <= 63:
        return "w_21_63"
    if value <= 126:
        return "w_64_126"
    return "w_127_plus"


def _window_buckets(expression: str) -> tuple[str, ...]:
    buckets = {_window_bucket(int(match.group(1))) for match in _WINDOW_RE.finditer(expression)}
    return tuple(sorted(buckets))


def _skeleton(expression: str, fields: set[str]) -> str:
    text = normalize_expression(expression)
    field_map = {field.lower(): field_family(field) for field in fields}

    def repl_identifier(match: re.Match[str]) -> str:
        token = match.group(0)
        lower = token.lower()
        if lower in field_map:
            return f"FIELD_{field_map[lower]}"
        return lower

    text = _IDENTIFIER_RE.sub(repl_identifier, text)

    def repl_number(match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            number = float(raw)
        except ValueError:
            return "CONST"
        if number.is_integer() and abs(number) >= 2:
            return _window_bucket(int(abs(number))).upper()
        return "CONST"

    return _NUMBER_RE.sub(repl_number, text)


def fingerprint_expression(expression: str) -> dict[str, Any]:
    components = extract_components(expression)
    operators = tuple(sorted({str(value).lower() for value in components.get("operators", []) if value}))
    fields = tuple(sorted({str(value).lower() for value in components.get("fields", []) if value}))
    field_families = tuple(sorted({field_family(value) for value in fields}))
    operator_families = tuple(sorted({operator_family(value) for value in operators}))
    return {
        "operators": operators,
        "fields": fields,
        "field_families": field_families,
        "operator_families": operator_families,
        "window_buckets": _window_buckets(expression),
        "skeleton": _skeleton(expression, set(fields)),
    }


def compute_lowcorr_similarity(expr_a: str, expr_b: str) -> dict[str, float]:
    """Return a structure-aware similarity score in [0, 1].

    It deliberately gives more weight to structural skeleton and economic field
    families than to raw expression text.  This catches "same idea, different
    window" clones that ordinary text similarity often misses.
    """

    fp_a = fingerprint_expression(expr_a)
    fp_b = fingerprint_expression(expr_b)
    norm_a = normalize_expression(expr_a)
    norm_b = normalize_expression(expr_b)

    text_similarity = SequenceMatcher(None, norm_a, norm_b).ratio()
    skeleton_similarity = SequenceMatcher(None, fp_a["skeleton"], fp_b["skeleton"]).ratio()
    operator_overlap = _jaccard(fp_a["operators"], fp_b["operators"])
    field_overlap = _jaccard(fp_a["fields"], fp_b["fields"])
    field_family_overlap = _jaccard(fp_a["field_families"], fp_b["field_families"])
    operator_family_overlap = _jaccard(fp_a["operator_families"], fp_b["operator_families"])
    window_overlap = _jaccard(fp_a["window_buckets"], fp_b["window_buckets"])

    overall = (
        0.10 * text_similarity
        + 0.20 * skeleton_similarity
        + 0.15 * operator_overlap
        + 0.15 * field_overlap
        + 0.20 * field_family_overlap
        + 0.15 * operator_family_overlap
        + 0.05 * window_overlap
    )
    return {
        "text_similarity": round(text_similarity, 4),
        "skeleton_similarity": round(skeleton_similarity, 4),
        "operator_overlap": round(operator_overlap, 4),
        "field_overlap": round(field_overlap, 4),
        "field_family_overlap": round(field_family_overlap, 4),
        "operator_family_overlap": round(operator_family_overlap, 4),
        "window_overlap": round(window_overlap, 4),
        "overall_similarity": round(overall, 4),
    }


def nearest_lowcorr_similarity(expression: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    nearest: dict[str, Any] | None = None
    normalized = normalize_expression(expression)
    for row in rows:
        other = str(row.get("expression") or "").strip()
        if not other:
            continue
        similarity = compute_lowcorr_similarity(expression, other)
        item = {
            "alpha_id": row.get("alpha_id"),
            "candidate_uid": row.get("candidate_uid"),
            "expression": other,
            "status": row.get("status") or row.get("virtual_active_status"),
            "source_family": row.get("source_family"),
            "similarity": similarity,
            "exact": normalized == normalize_expression(other),
        }
        if nearest is None or similarity["overall_similarity"] > nearest["similarity"]["overall_similarity"]:
            nearest = item
    return nearest


def _raw_quality(row: dict[str, Any]) -> float:
    for key in ("quality_score", "harness_score", "priority_score", "repair_priority_score"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    sharpe = row.get("sharpe")
    fitness = row.get("fitness")
    if isinstance(sharpe, (int, float)) or isinstance(fitness, (int, float)):
        return 0.55 * float(sharpe or 0.0) + 0.45 * float(fitness or 0.0)
    rank = row.get("candidate_rank")
    if isinstance(rank, (int, float)) and rank > 0:
        return 1.0 / float(rank)
    return 0.5


def mmr_select_candidates(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    comparison_rows: list[dict[str, Any]] | None = None,
    diversity_lambda: float = 0.45,
    hard_similarity_cutoff: float | None = None,
    max_source_family_count: int = 2,
) -> list[dict[str, Any]]:
    """Select a quality/diversity-balanced batch using MMR.

    diversity_lambda is the penalty weight for nearest structural similarity.
    A value near 0.45 is intentionally diversity-biased for research batches.
    """

    if limit <= 0 or not rows:
        return []

    candidates = [dict(row) for row in rows if str(row.get("expression") or "").strip()]
    if not candidates:
        return []

    raw = [_raw_quality(row) for row in candidates]
    lo, hi = min(raw), max(raw)

    def norm_quality(value: float) -> float:
        if hi <= lo:
            return 0.5
        return (value - lo) / (hi - lo)

    quality = {id(row): norm_quality(_raw_quality(row)) for row in candidates}
    selected: list[dict[str, Any]] = []
    baseline = list(comparison_rows or [])
    family_counts: Counter[str] = Counter()

    while candidates and len(selected) < limit:
        best_index: int | None = None
        best_score = float("-inf")
        best_nearest = 0.0

        for index, row in enumerate(candidates):
            family = str(row.get("source_family") or "")
            if max_source_family_count > 0 and family and family_counts[family] >= max_source_family_count:
                continue

            comparison = baseline + selected
            nearest = nearest_lowcorr_similarity(str(row["expression"]), comparison)
            nearest_score = (
                float(nearest["similarity"]["overall_similarity"])
                if nearest
                else 0.0
            )
            if hard_similarity_cutoff is not None and nearest_score >= hard_similarity_cutoff:
                continue

            score = (1.0 - diversity_lambda) * quality[id(row)] - diversity_lambda * nearest_score
            if score > best_score:
                best_index = index
                best_score = score
                best_nearest = nearest_score

        if best_index is None:
            break

        chosen = candidates.pop(best_index)
        chosen["lowcorr_mmr_score"] = round(best_score, 4)
        chosen["lowcorr_nearest_similarity"] = round(best_nearest, 4)
        chosen["lowcorr_fingerprint"] = fingerprint_expression(str(chosen["expression"]))
        selected.append(chosen)
        family = str(chosen.get("source_family") or "")
        if family:
            family_counts[family] += 1

    return selected
