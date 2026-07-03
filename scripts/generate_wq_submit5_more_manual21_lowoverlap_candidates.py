"""Generate manual21 low-overlap candidates after manual20 self-corr failures."""

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
    / "manual21_lowoverlap_candidates.jsonl"
)


def main(argv: list[str] | None = None) -> int:
    return run_static_candidate_generator(
        argv,
        records_func=_records,
        default_output=DEFAULT_OUTPUT,
        default_limit=20,
        description="Generate manual21 low-overlap candidates",
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
            "source": "generate_wq_submit5_more_manual21_lowoverlap_candidates",
            "expression": expr,
            "simulation_settings": settings,
            "mutation_strategy": "manual21_after_manual20_akoKgld2_selfcorr",
            "rationale": rationale,
            "risk_flags": [
                "real_submit_candidate",
                "requires_online_simulation",
                "fresh_after_manual20_selfcorr_failures",
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
        "manual21-ivmean-forward-quality-sub12",
        "manual21_ivmean_forward_quality",
        "rank(-0.30*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.22*ts_rank(ts_backfill(forward_sales_to_price,120),150)+0.18*rank(fixed_cash_to_current_liabilities_ratio)+0.16*ts_rank(rel_ret_cust,140)+0.10*rank(ts_corr(vwap,volume,120))+0.04*rank(volume/adv20))",
        sub12,
        "Replace returns reversal with low-overlap implied-volatility mean and relative-return custom breadth.",
    )
    _add(
        rows,
        "manual21-ivmean-skew-relret-sec12",
        "manual21_ivmean_skew_relret",
        "rank(-0.28*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.24*rank(ts_backfill(implied_volatility_mean_skew_90,120))+0.20*ts_rank(rel_ret_cust,140)+0.16*rank(ts_corr(close,volume,120))+0.08*rank(volume/adv20))",
        sec12,
        "Use option-volatility shape plus rel_ret_cust; no returns or cashflow value leg.",
    )
    _add(
        rows,
        "manual21-ivmean-pcr-sentiment-i16",
        "manual21_ivmean_pcr_sentiment",
        "rank(-0.28*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)-0.20*ts_rank(ts_backfill(pcr_oi_60,120),100)+0.22*rank(scl12_sentiment_fast_d1)+0.18*ts_rank(rel_ret_cust,140)+0.08*rank(volume/adv20))",
        ind16,
        "Combine low-vol, put/call pressure, and sentiment instead of another dividend/value/reversal repair.",
    )
    _add(
        rows,
        "manual21-ivmean-eps-uncertainty-sec16",
        "manual21_ivmean_eps_uncertainty",
        "rank(-0.26*ts_rank(ts_backfill(implied_volatility_mean_30,120),100)-0.22*ts_rank(coefficient_variation_fy1_eps,120)+0.20*ts_rank(ts_backfill(forward_sales_to_price,120),150)+0.16*rank(ts_corr(vwap,volume,120))+0.10*rank(volume/adv20))",
        sec16,
        "Test low implied volatility and lower EPS uncertainty with only small volume confirmation.",
    )
    _add(
        rows,
        "manual21-opinc-capex-no-returns-i16",
        "manual21_opinc_capex_no_returns",
        "rank(0.32*group_rank(ts_rank(operating_income/assets,160),industry)+0.22*group_rank(ts_rank(capex/assets,140),industry)+0.18*rank(-1*debt/assets)+0.16*ts_rank(rel_ret_cust,140)+0.12*rank(ts_corr(vwap,volume,120)))",
        ind16,
        "Retest operating-income/capex quality without the returns leg that caused value/reversal self-corr.",
    )
    _add(
        rows,
        "manual21-opinc-debt-ivmean-sub16",
        "manual21_opinc_debt_ivmean",
        "rank(0.28*group_rank(ts_rank(operating_income/assets,160),industry)+0.22*rank(-1*debt/assets)-0.22*ts_rank(ts_backfill(implied_volatility_mean_30,120),100)+0.18*ts_rank(rel_ret_cust,140)+0.10*rank(volume/adv20))",
        sub16,
        "Use profitability plus debt and implied-volatility mean; avoids cap/cashflow_op/returns.",
    )
    _add(
        rows,
        "manual21-capex-ivmean-relret-sec12",
        "manual21_capex_ivmean_relret",
        "rank(0.26*group_rank(ts_rank(capex/assets,140),industry)-0.24*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.22*ts_rank(rel_ret_cust,140)+0.16*rank(-1*debt/assets)+0.08*rank(volume/adv20))",
        sec12,
        "Capex/assets with volatility and rel_ret_cust, intentionally leaving cashflow_op out.",
    )
    _add(
        rows,
        "manual21-earnings-analyst-momentum-sub16",
        "manual21_earnings_analyst_momentum",
        "rank(0.24*ts_rank(ts_backfill(earnings_revision_magnitude,120),100)+0.22*ts_rank(ts_backfill(earnings_momentum_analyst_score,120),100)+0.18*ts_rank(ts_backfill(actual_sales_value_quarterly,120)/enterprise_value,120)+0.16*rank(-1*earnings_certainty_rank_derivative)+0.12*ts_rank(rel_ret_cust,140)+0.08*rank(volume/adv20))",
        sub16,
        "Rebuild the analyst momentum branch without the explicit returns term from existing active WjglwMlG.",
    )
    _add(
        rows,
        "manual21-earnings-momentum-ivmean-i12",
        "manual21_earnings_momentum_ivmean",
        "rank(0.24*ts_rank(ts_backfill(earnings_momentum_analyst_score,120),100)+0.20*ts_rank(ts_backfill(earnings_revision_magnitude,120),100)-0.22*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.18*ts_rank(ts_backfill(forward_sales_to_price,120),150)+0.08*rank(volume/adv20))",
        ind12,
        "Pair analyst momentum with low implied-volatility mean, not price reversal.",
    )
    _add(
        rows,
        "manual21-anl4-dts-ivmean-quality-i16",
        "manual21_anl4_dts_ivmean_quality",
        "rank(0.26*ts_rank(ts_backfill(anl4_afv4_eps_mean,120)/close,90)-0.22*ts_rank(ts_backfill(anl4_afv4_dts_spe,120),90)-0.20*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.18*rank(-1*cashflow_efficiency_rank_derivative)+0.08*rank(volume/adv20))",
        ind16,
        "Use analyst EPS mean and dts_spe with IV mean; cashflow efficiency is only a small quality overlay.",
    )
    _add(
        rows,
        "manual21-relret-forward-bucket-sub12",
        "manual21_relret_forward_bucket",
        "rank(group_rank(0.28*ts_rank(rel_ret_cust,140)-0.24*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.22*group_rank(ts_rank(ts_backfill(forward_sales_to_price,120),150),sector)+0.14*rank(ts_corr(close,volume,160)),bucket(rank(cap),range=\"0.1,1,0.1\")))",
        sub12,
        "Borrow the size-bucket geometry from high-quality actives but remove their returns/cashflow core.",
    )
    _add(
        rows,
        "manual21-relret-pcr-bucket-sec16",
        "manual21_relret_pcr_bucket",
        "rank(group_rank(0.30*ts_rank(rel_ret_cust,140)-0.22*ts_rank(ts_backfill(pcr_oi_60,120),100)-0.20*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.16*rank(ts_corr(vwap,volume,140)),bucket(rank(cap),range=\"0.1,1,0.1\")))",
        sec16,
        "A no-fundamental bucketed rel_ret/option-pressure test to escape value/cashflow clusters.",
    )
    _add(
        rows,
        "manual21-sentiment-fast-ivmean-sub12",
        "manual21_sentiment_fast_ivmean",
        "rank(0.26*zscore(ts_mean(scl12_sentiment_fast_d1,12))-0.24*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.20*ts_rank(rel_ret_cust,140)+0.18*rank(ts_corr(close,volume,100))+0.08*rank(volume/adv20))",
        sub12,
        "Retest sentiment only as a component paired with low-overlap IV mean and rel_ret_cust.",
    )
    _add(
        rows,
        "manual21-sentiment-revision-ivmean-i12",
        "manual21_sentiment_revision_ivmean",
        "rank(0.24*zscore(ts_mean(scl12_sentiment_fast_d1,12))+0.22*group_zscore(ts_delta(snt1_d1_netearningsrevision,7),subindustry)-0.22*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.18*ts_rank(rel_ret_cust,140)+0.08*rank(volume/adv20))",
        ind12,
        "Forum sentiment/revision branch with an IV-mean decorrelation anchor and no returns.",
    )
    _add(
        rows,
        "manual21-price-ratio-ivmean-sec12",
        "manual21_price_ratio_ivmean",
        "rank(0.28*rank(ts_delta(fifty_to_two_hundred_day_price_ratio,20))-0.26*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.20*ts_rank(rel_ret_cust,140)+0.16*rank(ts_corr(vwap,volume,120))+0.10*rank(volume/adv20))",
        sec12,
        "Use medium-horizon price-ratio change instead of returns rank; checks whether this avoids akoKgld2.",
    )
    _add(
        rows,
        "manual21-price-ratio-analyst-i16",
        "manual21_price_ratio_analyst",
        "rank(0.26*rank(ts_delta(fifty_to_two_hundred_day_price_ratio,20))+0.22*ts_rank(ts_backfill(earnings_momentum_analyst_score,120),100)-0.22*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.18*ts_rank(rel_ret_cust,140)+0.08*rank(volume/adv20))",
        ind16,
        "Blend price-ratio trend with analyst momentum and IV mean, avoiding short returns reversal.",
    )
    _add(
        rows,
        "manual21-ivmean-forward-book-quality-sub16",
        "manual21_ivmean_forward_book_quality",
        "rank(-0.28*ts_rank(ts_backfill(implied_volatility_mean_30,120),100)+0.24*ts_rank(ts_backfill(forward_book_value_to_price,120),150)+0.18*rank(fixed_cash_to_current_liabilities_ratio)+0.16*ts_rank(rel_ret_cust,140)+0.10*rank(ts_corr(vwap,volume,120)))",
        sub16,
        "Forward book value with IV mean and rel_ret_cust; no forward cashflow/cashflow_op/returns.",
    )
    _add(
        rows,
        "manual21-ivmean-actual-sales-assets-i12",
        "manual21_ivmean_actual_sales_assets",
        "rank(-0.26*ts_rank(ts_backfill(implied_volatility_mean_30,120),100)+0.24*ts_rank(ts_backfill(actual_sales_value_quarterly,120)/assets,120)+0.20*ts_rank(rel_ret_cust,140)+0.18*rank(-1*debt/assets)+0.08*rank(volume/adv20))",
        ind12,
        "Actual sales/assets with IV mean and debt quality, avoiding enterprise_value/cashflow_op/returns.",
    )
    _add(
        rows,
        "manual21-ivmean-operating-sales-sec16",
        "manual21_ivmean_operating_sales",
        "rank(-0.26*ts_rank(ts_backfill(implied_volatility_mean_30,120),90)+0.24*ts_rank(operating_income/assets,160)+0.22*ts_rank(ts_backfill(actual_sales_value_quarterly,120)/assets,120)+0.18*ts_rank(rel_ret_cust,140)+0.10*rank(ts_corr(close,volume,140)))",
        sec16,
        "Operating income plus sales/assets with IV mean; avoids the cashflow_op/cap family.",
    )
    _add(
        rows,
        "manual21-ivmean-no-volume-quality-i12",
        "manual21_ivmean_no_volume_quality",
        "rank(-0.32*ts_rank(ts_backfill(implied_volatility_mean_30,120),100)+0.24*ts_rank(rel_ret_cust,140)+0.20*rank(fixed_cash_to_current_liabilities_ratio)+0.14*rank(-1*current_liabilities_to_price)+0.10*ts_rank(ts_backfill(forward_sales_to_price,120),150))",
        ind12,
        "Remove volume/vwap entirely to test whether price-volume overlays are contributing to self-corr.",
    )
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
