"""Generate manual22 earnings/rel-ret candidates after manual21 partial failures."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worldquant_harness.wq_candidate_generation import run_static_candidate_generator

DEFAULT_OUTPUT = (
    ROOT
    / "reports"
    / "wq_agent_runs"
    / "submit5_active_fresh_20260702_104807"
    / "manual22_earnings_relret_candidates.jsonl"
)


def main(argv: list[str] | None = None) -> int:
    return run_static_candidate_generator(
        argv,
        records_func=_records,
        default_output=DEFAULT_OUTPUT,
        default_limit=18,
        description="Generate manual22 earnings/rel-ret candidates",
        limit_valid_count=False,
    )


def _settings(neutralization: str, decay: int, truncation: float = 0.01) -> dict[str, Any]:
    return {
        "region": "USA",
        "universe": "TOP3000",
        "delay": 1,
        "neutralization": neutralization,
        "decay": decay,
        "truncation": truncation,
    }


def _add(rows: list[dict[str, Any]], tag: str, family: str, expr: str, settings: dict[str, Any], rationale: str) -> None:
    rows.append(
        {
            "tag": tag,
            "source_family": family,
            "source": "generate_wq_submit5_more_manual22_earnings_relret_candidates",
            "expression": expr,
            "simulation_settings": settings,
            "mutation_strategy": "manual22_after_manual21_negative_ivmean",
            "rationale": rationale,
            "risk_flags": [
                "real_submit_candidate",
                "requires_online_simulation",
                "fresh_after_manual21_partial_failures",
                "avoid_returns_value_reversal_cluster",
            ],
        }
    )


def _records() -> list[dict[str, Any]]:
    sub12 = _settings("SUBINDUSTRY", 12)
    sub16 = _settings("SUBINDUSTRY", 16)
    ind12 = _settings("INDUSTRY", 12)
    ind16 = _settings("INDUSTRY", 16)
    sec12 = _settings("SECTOR", 12)
    sec16 = _settings("SECTOR", 16)
    rows: list[dict[str, Any]] = []

    _add(
        rows,
        "manual22-anl4-dts-quality-no-iv-i16",
        "manual22_anl4_dts_quality_no_iv",
        "rank(0.30*ts_rank(ts_backfill(anl4_afv4_eps_mean,120)/close,90)-0.24*ts_rank(ts_backfill(anl4_afv4_dts_spe,120),90)+0.20*rank(-1*cashflow_efficiency_rank_derivative)+0.16*ts_rank(rel_ret_cust,140)+0.10*rank(volume/adv20))",
        ind16,
        "Repair manual21 kq3wOoR8 by removing the negative IV-mean leg that dragged most candidates down.",
    )
    _add(
        rows,
        "manual22-anl4-dts-analyst-sub16",
        "manual22_anl4_dts_analyst",
        "rank(0.26*ts_rank(ts_backfill(anl4_afv4_eps_mean,120)/close,90)-0.22*ts_rank(ts_backfill(anl4_afv4_dts_spe,120),90)+0.20*ts_rank(ts_backfill(earnings_momentum_analyst_score,120),100)+0.18*rank(-1*cashflow_efficiency_rank_derivative)+0.10*rank(volume/adv20))",
        sub16,
        "Add analyst momentum to the anl4 dts repair without adding returns.",
    )
    _add(
        rows,
        "manual22-anl4-dts-relret-sec12",
        "manual22_anl4_dts_relret",
        "rank(0.28*group_rank(ts_rank(ts_backfill(anl4_afv4_eps_mean,120)/close,90),industry)-0.22*group_rank(ts_rank(ts_backfill(anl4_afv4_dts_spe,120),90),industry)+0.20*ts_rank(rel_ret_cust,140)+0.18*rank(-1*cashflow_efficiency_rank_derivative)+0.08*rank(volume/adv20))",
        sec12,
        "Change cross-sectional geometry with group_rank and rel_ret_cust to reduce direct overlap with leVrxOdn.",
    )
    _add(
        rows,
        "manual22-anl4-dts-positive-iv-small-i12",
        "manual22_anl4_dts_positive_iv_small",
        "rank(0.26*ts_rank(ts_backfill(anl4_afv4_eps_mean,120)/close,90)-0.22*ts_rank(ts_backfill(anl4_afv4_dts_spe,120),90)+0.16*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.18*rank(-1*cashflow_efficiency_rank_derivative)+0.10*rank(volume/adv20))",
        ind12,
        "Flip IV mean to a small positive leg after all negative-IV variants failed.",
    )
    _add(
        rows,
        "manual22-analyst-momentum-price-ratio-sub16",
        "manual22_analyst_momentum_price_ratio",
        "rank(0.26*ts_rank(ts_backfill(earnings_momentum_analyst_score,120),100)+0.22*ts_rank(ts_backfill(earnings_revision_magnitude,120),100)+0.20*rank(ts_delta(fifty_to_two_hundred_day_price_ratio,20))+0.18*ts_rank(ts_backfill(actual_sales_value_quarterly,120)/enterprise_value,120)+0.10*rank(volume/adv20))",
        sub16,
        "Repair analyst momentum metric weakness by adding price-ratio trend instead of short returns reversal.",
    )
    _add(
        rows,
        "manual22-analyst-momentum-relret-i12",
        "manual22_analyst_momentum_relret",
        "rank(0.26*ts_rank(ts_backfill(earnings_momentum_analyst_score,120),100)+0.22*ts_rank(ts_backfill(earnings_revision_magnitude,120),100)+0.20*ts_rank(rel_ret_cust,140)+0.18*ts_rank(ts_backfill(forward_sales_to_price,120),150)+0.10*rank(volume/adv20))",
        ind12,
        "Use rel_ret_cust and forward sales to strengthen the analyst branch without returns.",
    )
    _add(
        rows,
        "manual22-analyst-certainty-inverted-sec16",
        "manual22_analyst_certainty_inverted",
        "rank(0.24*ts_rank(ts_backfill(earnings_momentum_analyst_score,120),100)+0.22*ts_rank(ts_backfill(earnings_revision_magnitude,120),100)-0.22*rank(earnings_certainty_rank_derivative)+0.18*rank(ts_delta(fifty_to_two_hundred_day_price_ratio,20))+0.08*rank(volume/adv20))",
        sec16,
        "Analyst/revision branch with inverted certainty and price-ratio trend, still avoiding returns.",
    )
    _add(
        rows,
        "manual22-forward-revision-no-return-sec16",
        "manual22_forward_revision_no_return",
        "rank(0.28*ts_rank(ts_backfill(forward_sales_to_price,120),150)+0.24*ts_rank(ts_backfill(forward_book_value_to_price,120),150)+0.20*ts_rank(ts_backfill(analyst_revision_rank_derivative,120),100)+0.18*ts_rank(rel_ret_cust,140)+0.10*rank(ts_corr(vwap,volume,120)))",
        sec16,
        "Rebuild manual20 vRLEOo3r by removing returns and relative_valuation, replacing with rel_ret_cust.",
    )
    _add(
        rows,
        "manual22-forward-revision-price-ratio-i16",
        "manual22_forward_revision_price_ratio",
        "rank(0.28*ts_rank(ts_backfill(forward_sales_to_price,120),150)+0.22*ts_rank(ts_backfill(forward_book_value_to_price,120),150)+0.20*ts_rank(ts_backfill(analyst_revision_rank_derivative,120),100)+0.18*rank(ts_delta(fifty_to_two_hundred_day_price_ratio,20))+0.08*rank(volume/adv20))",
        ind16,
        "Forward-value/revision repair using price-ratio trend instead of returns reversal.",
    )
    _add(
        rows,
        "manual22-forward-cashflow-relret-sub16",
        "manual22_forward_cashflow_relret",
        "rank(0.30*ts_rank(ts_backfill(forward_cash_flow_to_price,120),150)+0.22*rank(-1*cashflow_efficiency_rank_derivative)+0.20*ts_rank(rel_ret_cust,140)+0.18*rank(fixed_cash_to_current_liabilities_ratio)+0.10*rank(volume/adv20))",
        sub16,
        "Repair manual20 mL8GK909 by replacing returns with rel_ret_cust and dropping cashflow_op/cap.",
    )
    _add(
        rows,
        "manual22-forward-cashflow-price-ratio-i12",
        "manual22_forward_cashflow_price_ratio",
        "rank(0.30*ts_rank(ts_backfill(forward_cash_flow_to_price,120),150)+0.22*rank(-1*cashflow_efficiency_rank_derivative)+0.20*rank(ts_delta(fifty_to_two_hundred_day_price_ratio,20))+0.18*rank(fixed_cash_to_current_liabilities_ratio)+0.10*rank(volume/adv20))",
        ind12,
        "Use price-ratio trend as the non-returns support for forward cashflow quality.",
    )
    _add(
        rows,
        "manual22-growth-forward-relret-sec12",
        "manual22_growth_forward_relret",
        "rank(-0.14*(0.30*ts_rank(growth_potential_rank_derivative,140)+0.25*ts_rank(fundamental_growth_module_score,140)+0.22*ts_rank(earnings_certainty_rank_derivative,140)+0.16*ts_rank(earnings_momentum_composite_score_2,140))+0.28*ts_rank(ts_backfill(forward_sales_to_price,120),150)+0.22*rank(-1*cashflow_efficiency_rank_derivative)+0.20*ts_rank(rel_ret_cust,140)+0.08*rank(volume/adv20))",
        sec12,
        "Repair manual20 omKbRwdb by reducing inverse growth further and replacing returns with rel_ret_cust.",
    )
    _add(
        rows,
        "manual22-growth-forward-price-ratio-i16",
        "manual22_growth_forward_price_ratio",
        "rank(-0.14*(0.30*ts_rank(growth_potential_rank_derivative,140)+0.25*ts_rank(fundamental_growth_module_score,140)+0.22*ts_rank(earnings_certainty_rank_derivative,140)+0.16*ts_rank(earnings_momentum_composite_score_2,140))+0.28*ts_rank(ts_backfill(forward_sales_to_price,120),150)+0.22*rank(-1*cashflow_efficiency_rank_derivative)+0.20*rank(ts_delta(fifty_to_two_hundred_day_price_ratio,20))+0.08*rank(volume/adv20))",
        ind16,
        "Same repair as relret variant, but uses medium trend to test a different correlation projection.",
    )
    _add(
        rows,
        "manual22-operating-sales-relret-sec16",
        "manual22_operating_sales_relret",
        "rank(0.28*ts_rank(operating_income/assets,160)+0.24*ts_rank(ts_backfill(actual_sales_value_quarterly,120)/assets,120)+0.20*ts_rank(rel_ret_cust,140)+0.18*rank(-1*debt/assets)+0.10*rank(volume/adv20))",
        sec16,
        "Keep operating/sales balance-sheet quality but avoid the skipped operating/capex exact active geometry.",
    )
    _add(
        rows,
        "manual22-sales-assets-price-ratio-i12",
        "manual22_sales_assets_price_ratio",
        "rank(0.28*ts_rank(ts_backfill(actual_sales_value_quarterly,120)/assets,120)+0.22*rank(ts_delta(fifty_to_two_hundred_day_price_ratio,20))+0.20*rank(-1*debt/assets)+0.18*ts_rank(rel_ret_cust,140)+0.08*rank(volume/adv20))",
        ind12,
        "Actual sales/assets repair with price-ratio trend and debt quality; no returns or cashflow_op.",
    )
    _add(
        rows,
        "manual22-relret-pcr-positive-iv-sec12",
        "manual22_relret_pcr_positive_iv",
        "rank(0.30*ts_rank(rel_ret_cust,140)-0.22*ts_rank(ts_backfill(pcr_oi_60,120),100)+0.18*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.18*rank(ts_corr(vwap,volume,140))+0.08*rank(volume/adv20))",
        sec12,
        "Retest the interrupted rel_ret/pcr branch with IV mean flipped positive.",
    )
    _add(
        rows,
        "manual22-sentiment-relret-price-ratio-sub12",
        "manual22_sentiment_relret_price_ratio",
        "rank(0.24*zscore(ts_mean(scl12_sentiment_fast_d1,12))+0.22*ts_rank(rel_ret_cust,140)+0.20*rank(ts_delta(fifty_to_two_hundred_day_price_ratio,20))+0.18*rank(ts_corr(close,volume,120))+0.08*rank(volume/adv20))",
        sub12,
        "Sentiment only as a small overlay with rel_ret and price-ratio support.",
    )
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
