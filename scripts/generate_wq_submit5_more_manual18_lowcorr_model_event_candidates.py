"""Generate manual18 low-correlation model/event candidates for submit-5 continuation."""

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
    / "manual18_lowcorr_model_event_candidates.jsonl"
)


def main(argv: list[str] | None = None) -> int:
    return run_static_candidate_generator(
        argv,
        records_func=_records,
        default_output=DEFAULT_OUTPUT,
        default_limit=16,
        description="Generate manual18 low-correlation model/event candidates",
        limit_valid_count=False,
    )


def _settings(neutralization: str = "SUBINDUSTRY", decay: int = 12, truncation: float = 0.01) -> dict[str, Any]:
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
            "source": "generate_wq_submit5_more_manual18_lowcorr_model_event_candidates",
            "expression": expr,
            "simulation_settings": settings,
            "mutation_strategy": "manual18_lowcorr_model_event_shift",
            "rationale": rationale,
            "risk_flags": [
                "real_submit_candidate",
                "requires_online_simulation",
                "fresh_after_generated17_selfcorr_fails",
            ],
        }
    )


def _records() -> list[dict[str, Any]]:
    sub12 = _settings("SUBINDUSTRY", 12, 0.01)
    sub16 = _settings("SUBINDUSTRY", 16, 0.01)
    ind12 = _settings("INDUSTRY", 12, 0.01)
    ind16 = _settings("INDUSTRY", 16, 0.01)
    sec12 = _settings("SECTOR", 12, 0.01)
    rows: list[dict[str, Any]] = []

    _add(
        rows,
        "manual18-inv-composite-growth-breadth-d12",
        "manual18_inverse_composite_growth",
        "rank(-0.58*(0.32*ts_rank(composite_factor_score_derivative,80)+0.26*ts_rank(multi_factor_acceleration_score_derivative,80)+0.22*ts_rank(growth_potential_rank_derivative,80)+0.14*ts_rank(fundamental_growth_module_score,80))+0.17*rank(-1*ts_rank(returns,110))+0.09*rank(volume/adv20))",
        sub12,
        "Fresh inverse model-score branch: reuse the successful manual06 sign lesson but replace every active value-score field.",
    )
    _add(
        rows,
        "manual18-inv-growth-certainty-liquidity-d16",
        "manual18_inverse_growth_certainty",
        "rank(-0.50*(0.28*ts_rank(growth_potential_rank_derivative,100)+0.24*ts_rank(fundamental_growth_module_score,100)+0.22*ts_rank(earnings_certainty_rank_derivative,100)+0.16*ts_rank(earnings_momentum_composite_score_2,100))+0.16*rank(-1*ts_rank(returns,130))+0.10*rank(volume/adv20))",
        sub16,
        "Slower inverse growth/certainty branch intended to move away from both value-score active and qMX options active.",
    )
    _add(
        rows,
        "manual18-relative-valuation-inv-revision-d12",
        "manual18_relative_valuation_revision",
        "rank(-0.34*ts_rank(relative_valuation_rank_derivative,90)-0.24*ts_rank(earnings_certainty_rank_derivative,90)+0.20*ts_rank(analyst_revision_rank_derivative,80)+0.12*rank(-1*ts_rank(returns,100))+0.10*rank(volume/adv20))",
        ind12,
        "Use relative valuation and certainty as the negative payload, with analyst revision only as a low-weight stabilizer.",
    )
    _add(
        rows,
        "manual18-event-risk-snt-torpedo-d12",
        "manual18_event_risk_snt_torpedo",
        "rank(-0.30*ts_rank(snt1_d1_earningstorpedo,80)-0.24*ts_rank(abnormal_return_earnings_release,80)-0.18*ts_rank(earnings_shortfall_metric,80)+0.16*ts_rank(earnings_expectation_module_score,70)+0.08*rank(volume/adv20))",
        sub12,
        "Replace part of the active shortfall/torpedo formula with the sentiment torpedo and abnormal-return event fields.",
    )
    _add(
        rows,
        "manual18-event-risk-no-shortfall-d12",
        "manual18_event_risk_no_shortfall",
        "rank(-0.34*ts_rank(snt1_d1_earningstorpedo,90)-0.24*ts_rank(abnormal_return_earnings_release,90)+0.18*ts_rank(earnings_expectation_module_score,80)+0.14*rank(-1*ts_rank(returns,110))+0.10*rank(volume/adv20))",
        sub12,
        "Remove earnings_shortfall_metric entirely to lower direct overlap with omKjbEGb while keeping event-risk direction.",
    )
    _add(
        rows,
        "manual18-shortfall-expectation-revision-d16",
        "manual18_shortfall_revision_bridge",
        "rank(-0.26*ts_rank(earnings_shortfall_metric,100)-0.22*ts_rank(snt1_d1_earningstorpedo,100)+0.22*ts_rank(earnings_revision_magnitude,90)+0.16*ts_rank(earnings_expectation_module_score,90)+0.08*rank(volume/adv20)-0.10*ts_rank(returns,130))",
        sub16,
        "Bridge active shortfall success into revision magnitude with slower windows and reduced torpedo/shortfall weight.",
    )
    _add(
        rows,
        "manual18-sent-revision-core-d10",
        "manual18_sentiment_revision_core",
        "rank(0.24*zscore(ts_mean(scl12_sentiment_fast_d1,10))+0.22*group_zscore(ts_delta(snt1_d1_netearningsrevision,5),subindustry)+0.16*ts_rank(snt1_d1_analystcoverage,80)-0.16*ts_rank(returns,90)+0.12*rank(volume/adv20))",
        sub12,
        "A sentiment/revision main-axis candidate with no EPS/options/cashflow/value-score fields.",
    )
    _add(
        rows,
        "manual18-sent-revision-value-bridge-d12",
        "manual18_sentiment_revision_value_bridge",
        "rank(0.18*zscore(ts_mean(scl12_sentiment_fast_d1,12))+0.18*group_zscore(ts_delta(snt1_d1_netearningsrevision,7),subindustry)+0.18*ts_rank(forward_book_value_to_price,120)+0.16*ts_rank(forward_sales_to_price,120)-0.14*ts_rank(returns,120)+0.08*rank(ts_corr(vwap,volume,60)))",
        ind12,
        "Forum sentiment/revision recipe with forward value bridge, but no qMX EPS/options shell.",
    )
    _add(
        rows,
        "manual18-dividend-global-lowleverage-d12",
        "manual18_global_dividend_lowleverage",
        "rank(0.28*rank(global_dividend_model_composite_score)+0.22*rank(fixed_cash_to_current_liabilities_ratio)+0.20*rank(-1*book_leverage_ratio_3)+0.16*rank(-1*current_liabilities_to_price)+0.14*rank(-1*ts_rank(returns,120)))",
        sub12,
        "Dividend/liquidity quality branch without open-close or IV legs; tests if quality breadth can pass below active self-corr.",
    )
    _add(
        rows,
        "manual18-cashburn-liability-sent-d12",
        "manual18_cashburn_liability_sentiment",
        "rank(-0.26*ts_rank(cash_burn_rate,90)+0.22*rank(-1*current_liabilities_to_price)+0.18*rank(fixed_cash_to_current_liabilities_ratio)+0.18*rank(snt1_cored1_score)+0.10*rank(-1*ts_rank(returns,110)))",
        sub12,
        "Retest the old cash-burn/liability/sentiment idea with fixed-cash support and no open-close timing leg.",
    )
    _add(
        rows,
        "manual18-lowvol-quality-value-d16",
        "manual18_lowvol_quality_value",
        "rank(-0.22*rank(historical_volatility_120)+0.20*rank(-1*book_leverage_ratio_3)+0.18*rank(fixed_cash_to_current_liabilities_ratio)+0.16*rank(dividends_to_gross_profit)+0.14*rank(-1*relative_valuation_rank_derivative)+0.10*rank(-1*ts_rank(returns,140)))",
        ind16,
        "Low-vol quality/value blend using historical volatility as a decorrelating main leg.",
    )
    _add(
        rows,
        "manual18-risk360-expectation-d16",
        "manual18_long_horizon_risk_expectation",
        "rank(-0.26*ts_rank(systematic_risk_last_360_days,120)-0.20*ts_rank(unsystematic_risk_last_360_days,120)-0.18*ts_rank(distress_risk_measure,100)+0.18*ts_rank(earnings_expectation_module_score,90)+0.10*rank(volume/adv20))",
        ind16,
        "Long-horizon risk branch with expectation support; avoids the qMX/options and value-score templates.",
    )
    _add(
        rows,
        "manual18-asset-growth-quality-spread-d12",
        "manual18_asset_growth_quality_spread",
        "rank(-0.28*ts_rank(asset_growth_rate,100)+0.22*ts_rank(cash_earnings_return_on_equity,90)+0.18*rank(fixed_cash_to_current_liabilities_ratio)+0.16*rank(-1*book_leverage_ratio_3)+0.10*rank(-1*ts_rank(returns,110)))",
        sub12,
        "Quality-minus-asset-growth spread, keeping FCF fields out because manual07 standalone FCF was weak.",
    )
    _add(
        rows,
        "manual18-forward-earnings-yield-risk-d12",
        "manual18_forward_earnings_yield_risk",
        "rank(0.28*ts_rank(forward_earnings_yield,90)+0.22*ts_rank(forward_median_earnings_yield,90)-0.20*ts_rank(distress_risk_measure,90)-0.14*ts_rank(earnings_shortfall_metric,90)+0.10*rank(volume/adv20))",
        sec12,
        "Forward earnings-yield branch with downside-risk filter; field axis differs from active inverse value scores.",
    )
    _add(
        rows,
        "manual18-revision-momentum-inverted-certainty-d12",
        "manual18_revision_momentum_certainty",
        "rank(0.26*ts_rank(earnings_revision_magnitude,80)+0.22*ts_rank(analyst_revision_rank_derivative,80)-0.22*ts_rank(earnings_certainty_rank_derivative,90)+0.14*rank(-1*ts_rank(returns,100))+0.08*rank(volume/adv20))",
        sub12,
        "Repair manual07 inverse-certainty weakness by giving revision magnitude more weight while keeping certainty inverted.",
    )
    _add(
        rows,
        "manual18-openclose-small-event-risk-d12",
        "manual18_small_openclose_event_risk",
        "rank(-0.28*ts_rank(snt1_d1_earningstorpedo,90)-0.20*ts_rank(abnormal_return_earnings_release,90)+0.18*ts_rank(earnings_expectation_module_score,80)+0.12*rank(ts_mean((open-close)/open,3))+0.10*rank(volume/adv20)-0.10*ts_rank(returns,110))",
        sub12,
        "Keep event risk as main axis and use open-close only as a small timing leg to avoid cloning old open-close active formulas.",
    )
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
