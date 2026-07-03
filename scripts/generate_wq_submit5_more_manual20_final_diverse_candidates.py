"""Generate manual20 final diverse candidates after reaching 4/5 ACTIVE."""

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
    / "manual20_final_diverse_candidates.jsonl"
)


def main(argv: list[str] | None = None) -> int:
    return run_static_candidate_generator(
        argv,
        records_func=_records,
        default_output=DEFAULT_OUTPUT,
        default_limit=20,
        description="Generate manual20 final diverse candidates",
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
            "source": "generate_wq_submit5_more_manual20_final_diverse_candidates",
            "expression": expr,
            "simulation_settings": settings,
            "mutation_strategy": "manual20_post_1Y78XZVM_final_diverse",
            "rationale": rationale,
            "risk_flags": [
                "real_submit_candidate",
                "requires_online_simulation",
                "fresh_after_manual19_active",
                "avoid_threshold_active_dense_seed",
            ],
        }
    )


def _growth_stack(weight: str = "0.24", window: int = 120) -> str:
    return (
        f"{weight}*(0.30*ts_rank(growth_potential_rank_derivative,{window})+"
        f"0.25*ts_rank(fundamental_growth_module_score,{window})+"
        f"0.22*ts_rank(earnings_certainty_rank_derivative,{window})+"
        f"0.16*ts_rank(earnings_momentum_composite_score_2,{window}))"
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
        "manual20-growth-cashflow-fitness-repair-sub12",
        "manual20_growth_cashflow_fitness_repair",
        f"rank(-{_growth_stack('0.22', 120)}+0.24*ts_rank(cashflow_op/cap,100)+0.18*rank(-1*cashflow_efficiency_rank_derivative)-0.16*ts_rank(returns,150)+0.12*rank(ts_corr(vwap,volume,90))+0.08*rank(volume/adv20))",
        sub12,
        "Repair manual19-growth-cashflow-quality fitness miss by adding a small slow reversal leg while cutting the inverse-growth payload.",
    )
    _add(
        rows,
        "manual20-growth-cashflow-no-micro-i16",
        "manual20_growth_cashflow_no_micro",
        f"rank(-{_growth_stack('0.18', 130)}+0.30*ts_rank(cashflow_op/cap,110)+0.22*rank(-1*cashflow_efficiency_rank_derivative)-0.18*ts_rank(returns,160)+0.12*rank(fixed_cash_to_current_liabilities_ratio))",
        ind16,
        "Remove high/low and open-close microstructure from the cashflow repair to avoid the vRLlM7Mz self-corr path.",
    )
    _add(
        rows,
        "manual20-grouped-cashflow-growth-residual-sub16",
        "manual20_grouped_cashflow_growth_residual",
        "rank(0.30*group_rank(ts_rank(cashflow_op/cap,110),industry)+0.22*rank(-1*cashflow_efficiency_rank_derivative)-0.20*group_rank(ts_rank(growth_potential_rank_derivative,130),industry)-0.16*group_rank(ts_rank(fundamental_growth_module_score,130),subindustry)-0.12*ts_rank(returns,150))",
        sub16,
        "Keep the manual19 grouped idea but delete vwap/volume, which made the prior strong variant correlate to existing actives.",
    )
    _add(
        rows,
        "manual20-netincome-cashquality-reversal-i16",
        "manual20_netincome_cashquality_reversal",
        "rank(0.30*ts_rank(anl4_adjusted_netincome_ft/cap,100)+0.24*rank(-1*cashflow_efficiency_rank_derivative)+0.18*rank(fixed_cash_to_current_liabilities_ratio)-0.18*ts_rank(returns,160)+0.10*rank(volume/adv20))",
        ind16,
        "Repair manual19-composite-netincome-bridge by removing acceleration and using slow reversal for fitness.",
    )
    _add(
        rows,
        "manual20-netincome-forward-value-bridge-i12",
        "manual20_netincome_forward_value_bridge",
        "rank(0.24*ts_rank(anl4_adjusted_netincome_ft/cap,90)+0.22*ts_rank(forward_sales_to_price,140)+0.18*ts_rank(forward_book_value_to_price,140)-0.18*ts_rank(returns,150)+0.10*rank(ts_corr(vwap,volume,90)))",
        ind12,
        "Move net income into forward sales/book value instead of the high-corr acceleration/cashflow pair.",
    )
    _add(
        rows,
        "manual20-forward-revision-value-sec16",
        "manual20_forward_revision_value",
        "rank(0.26*ts_rank(forward_sales_to_price,150)+0.22*ts_rank(forward_book_value_to_price,150)+0.18*ts_rank(analyst_revision_rank_derivative,100)-0.18*ts_rank(relative_valuation_rank_derivative,120)-0.12*ts_rank(returns,170)+0.04*rank(volume/adv20))",
        sec16,
        "Try a forward-value plus revision axis with only a very small liquidity pad; avoids the inverse growth/certainty cluster.",
    )
    _add(
        rows,
        "manual20-relative-revision-cashquality-sub16",
        "manual20_relative_revision_cashquality",
        "rank(-0.24*ts_rank(relative_valuation_rank_derivative,120)+0.22*ts_rank(analyst_revision_rank_derivative,100)+0.20*rank(fixed_cash_to_current_liabilities_ratio)+0.16*rank(-1*cashflow_efficiency_rank_derivative)-0.14*ts_rank(returns,150)+0.04*rank(volume/adv20))",
        sub16,
        "Repair the manual18 relative-valuation self-corr fail by dropping certainty and adding balance-sheet quality.",
    )
    _add(
        rows,
        "manual20-expectation-revision-risk-sub12",
        "manual20_expectation_revision_risk",
        "rank(0.24*ts_rank(earnings_expectation_module_score,100)+0.22*ts_rank(earnings_revision_magnitude,100)-0.20*ts_rank(distress_risk_measure,120)-0.16*ts_rank(unsystematic_risk_last_360_days,140)-0.12*ts_rank(returns,150)+0.06*rank(volume/adv20))",
        sub12,
        "Retest event/revision fields as the main axis, but pair them with long-horizon risk instead of shortfall/torpedo.",
    )
    _add(
        rows,
        "manual20-risk-forward-quality-i16",
        "manual20_risk_forward_quality",
        "rank(-0.22*ts_rank(systematic_risk_last_360_days,140)-0.20*ts_rank(distress_risk_measure,120)+0.22*ts_rank(forward_sales_to_price,150)+0.18*rank(fixed_cash_to_current_liabilities_ratio)-0.14*ts_rank(returns,160)+0.04*rank(volume/adv20))",
        ind16,
        "Risk branch repair: add forward sales and liquidity quality because pure long-risk was too weak in manual18.",
    )
    _add(
        rows,
        "manual20-assetgrowth-roeq-reversal-sub12",
        "manual20_assetgrowth_roeq_reversal",
        "rank(-0.28*ts_rank(asset_growth_rate,120)+0.24*ts_rank(cash_earnings_return_on_equity,100)+0.18*rank(fixed_cash_to_current_liabilities_ratio)+0.14*rank(-1*current_liabilities_to_price)-0.12*ts_rank(returns,150)+0.04*rank(volume/adv20))",
        sub12,
        "Repair the manual18 asset-growth quality miss with liability and slow-reversal support.",
    )
    _add(
        rows,
        "manual20-cashburn-liability-no-div-sub16",
        "manual20_cashburn_liability_no_div",
        "rank(-0.24*ts_rank(cash_burn_rate,110)+0.22*rank(-1*current_liabilities_to_price)+0.20*rank(fixed_cash_to_current_liabilities_ratio)+0.18*ts_rank(cashflow_op/cap,100)-0.12*ts_rank(returns,150)+0.04*rank(volume/adv20))",
        sub16,
        "Keep cash-burn/liability economics but remove dividends, sentiment, and open-close timing from the old active template.",
    )
    _add(
        rows,
        "manual20-certainty-revision-quality-ind12",
        "manual20_certainty_revision_quality",
        "rank(-0.22*ts_rank(earnings_certainty_rank_derivative,120)+0.24*ts_rank(earnings_revision_magnitude,100)+0.20*ts_rank(analyst_revision_rank_derivative,100)+0.16*rank(fixed_cash_to_current_liabilities_ratio)-0.14*ts_rank(returns,150)+0.04*rank(volume/adv20))",
        ind12,
        "Use inverted certainty only as a minority leg and let revision magnitude drive the signal.",
    )
    _add(
        rows,
        "manual20-actual-sales-cashflow-reversal-sec12",
        "manual20_actual_sales_cashflow_reversal",
        "rank(0.24*ts_rank(ts_backfill(actual_sales_value_quarterly,120)/cap,100)+0.22*ts_rank(ts_backfill(actual_cashflow_per_share_value_quarterly,120)/vwap,110)+0.18*rank(-1*cashflow_efficiency_rank_derivative)-0.18*ts_rank(returns,160)+0.10*rank(ts_corr(close,volume,90)))",
        sec12,
        "Controlled actual-sales/cashflow test without options or dividend legs; likely useful only if self-corr stays below old active cluster.",
    )
    _add(
        rows,
        "manual20-eps-surprise-revision-no-options-i16",
        "manual20_eps_surprise_revision_no_options",
        "rank(0.24*ts_rank(ts_backfill(change_in_eps_surprise,120),100)+0.22*ts_rank(earnings_revision_magnitude,100)+0.18*ts_rank(analyst_revision_rank_derivative,100)+0.16*ts_rank(forward_sales_to_price,150)-0.16*ts_rank(returns,150)+0.04*rank(volume/adv20))",
        ind16,
        "EPS surprise/revision branch with no IV/options shell, included to test whether the earnings axis can pass decorrelated.",
    )
    _add(
        rows,
        "manual20-forward-cashflow-no-price-micro-sub16",
        "manual20_forward_cashflow_no_price_micro",
        "rank(0.28*ts_rank(forward_cash_flow_to_price,140)+0.22*ts_rank(cashflow_op/cap,110)+0.18*rank(-1*cashflow_efficiency_rank_derivative)+0.16*rank(fixed_cash_to_current_liabilities_ratio)-0.12*ts_rank(returns,160)+0.04*rank(volume/adv20))",
        sub16,
        "Cashflow valuation repair with no close/vwap/high-low terms because those drove prior self-corr failures.",
    )
    _add(
        rows,
        "manual20-composite-cashquality-diluted-sec16",
        "manual20_composite_cashquality_diluted",
        "rank(-0.20*ts_rank(composite_factor_score_derivative,120)-0.16*ts_rank(multi_factor_acceleration_score_derivative,120)+0.24*ts_rank(cashflow_op/cap,110)+0.18*rank(-1*cashflow_efficiency_rank_derivative)-0.16*ts_rank(returns,160)+0.06*rank(volume/adv20))",
        sec16,
        "A diluted composite/acceleration repair; included with low weights because the direct version self-correlated to 0m7ZgQer.",
    )
    _add(
        rows,
        "manual20-dividend-cashquality-no-book-i12",
        "manual20_dividend_cashquality_no_book",
        "rank(0.22*rank(global_dividend_model_composite_score)+0.22*rank(fixed_cash_to_current_liabilities_ratio)+0.20*ts_rank(cashflow_op/cap,100)+0.18*rank(-1*cashflow_efficiency_rank_derivative)-0.14*ts_rank(returns,150)+0.04*rank(volume/adv20))",
        ind12,
        "Retest dividend quality without book leverage or high-low, avoiding the exact 1Y7dvrAR and 1Y78XZVM field mix.",
    )
    _add(
        rows,
        "manual20-openvwap-tiny-cashquality-sub12",
        "manual20_openvwap_tiny_cashquality",
        "rank(0.28*ts_rank(cashflow_op/cap,110)+0.22*rank(-1*cashflow_efficiency_rank_derivative)+0.18*rank(fixed_cash_to_current_liabilities_ratio)+0.12*rank(ts_mean((open-vwap)/open,5))-0.16*ts_rank(returns,160)+0.04*rank(volume/adv20))",
        sub12,
        "Use open-vwap only as a tiny timing overlay after removing acceleration and high-low legs.",
    )
    _add(
        rows,
        "manual20-growth-forward-cashquality-sec12",
        "manual20_growth_forward_cashquality",
        f"rank(-{_growth_stack('0.16', 140)}+0.24*ts_rank(forward_sales_to_price,150)+0.22*ts_rank(cashflow_op/cap,110)+0.18*rank(-1*cashflow_efficiency_rank_derivative)-0.16*ts_rank(returns,160)+0.04*rank(volume/adv20))",
        sec12,
        "Keep inverse growth below one-sixth of total weight and use forward sales plus cash quality as the main axis.",
    )
    _add(
        rows,
        "manual20-no-return-forward-quality-i12",
        "manual20_no_return_forward_quality",
        "rank(0.26*ts_rank(forward_sales_to_price,150)+0.24*ts_rank(forward_book_value_to_price,150)+0.20*rank(fixed_cash_to_current_liabilities_ratio)+0.16*rank(-1*current_liabilities_to_price)+0.14*rank(ts_corr(vwap,volume,100)))",
        ind12,
        "A no-returns variant to test whether return-reversal is causing active correlation in the repair candidates.",
    )
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
