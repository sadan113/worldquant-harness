"""Generate manual19 growth/certainty hybrid candidates after vRLEmN6a became ACTIVE."""

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
    / "manual19_growth_hybrid_candidates.jsonl"
)


def main(argv: list[str] | None = None) -> int:
    return run_static_candidate_generator(
        argv,
        records_func=_records,
        default_output=DEFAULT_OUTPUT,
        default_limit=16,
        description="Generate manual19 growth/certainty hybrid candidates",
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
            "source": "generate_wq_submit5_more_manual19_growth_hybrid_candidates",
            "expression": expr,
            "simulation_settings": settings,
            "mutation_strategy": "manual19_post_vRLEmN6a_growth_hybrid",
            "rationale": rationale,
            "risk_flags": [
                "real_submit_candidate",
                "requires_online_simulation",
                "fresh_after_manual18_active",
            ],
        }
    )


def _growth_stack(weight: str = "0.44") -> str:
    return (
        f"{weight}*(0.30*ts_rank(growth_potential_rank_derivative,100)+"
        "0.25*ts_rank(fundamental_growth_module_score,100)+"
        "0.23*ts_rank(earnings_certainty_rank_derivative,100)+"
        "0.16*ts_rank(earnings_momentum_composite_score_2,100))"
    )


def _records() -> list[dict[str, Any]]:
    sub12 = _settings("SUBINDUSTRY", 12)
    sub16 = _settings("SUBINDUSTRY", 16)
    ind12 = _settings("INDUSTRY", 12)
    ind16 = _settings("INDUSTRY", 16)
    sec12 = _settings("SECTOR", 12)
    rows: list[dict[str, Any]] = []

    _add(
        rows,
        "manual19-growth-micro-no-returns-sub16",
        "manual19_growth_micro_no_returns",
        f"rank(-{_growth_stack('0.42')}+0.18*rank(ts_corr(vwap,volume,80))+0.14*rank(ts_mean((open-close)/open,5))+0.10*rank(volume/adv20))",
        sub16,
        "Keep the successful inverse growth/certainty field family but remove the returns reversal main anchor.",
    )
    _add(
        rows,
        "manual19-growth-sector-neutral-micro-i14",
        "manual19_growth_sector_neutral_micro",
        f"rank(group_neutralize(-{_growth_stack('0.46')}+0.16*rank(ts_corr(close,volume,80))+0.12*rank(ts_mean((open-vwap)/open,5))+0.08*rank(volume/adv20),sector))",
        ind16,
        "Change operator family with an internal sector neutralization rather than another settings-only clone.",
    )
    _add(
        rows,
        "manual19-growth-cashflow-quality-sub12",
        "manual19_growth_cashflow_quality",
        f"rank(-{_growth_stack('0.34')}+0.18*ts_rank(cashflow_op/cap,80)+0.16*rank(-1*cashflow_efficiency_rank_derivative)+0.12*rank(ts_corr(vwap,volume,70))+0.08*rank(volume/adv20))",
        sub12,
        "Use inverse growth/certainty as a smaller payload and let cashflow quality carry part of the signal.",
    )
    _add(
        rows,
        "manual19-growth-netincome-cashflow-hybrid-sub12",
        "manual19_growth_netincome_cashflow_hybrid",
        "rank(0.44*group_neutralize(rank(0.34*ts_rank(anl4_adjusted_netincome_ft/cap,60)+0.30*ts_rank(cashflow_op/cap,80)+0.22*rank(-1*cashflow_efficiency_rank_derivative)-0.14*ts_rank(returns,60)),sector)+0.30*rank(-1*multi_factor_acceleration_score_derivative)+0.16*rank((high-close)/(high-low))+0.10*rank(volume/adv20))",
        sub12,
        "Hybridize the successful inverse score lesson with net income/cashflow and a microstructure leg.",
    )
    _add(
        rows,
        "manual19-netincome-cashflow-no-return-i16",
        "manual19_netincome_cashflow_no_return",
        "rank(0.42*group_neutralize(rank(0.36*ts_rank(anl4_adjusted_netincome_ft/cap,70)+0.30*ts_rank(cashflow_op/cap,90)+0.20*rank(-1*cashflow_efficiency_rank_derivative)+0.14*rank(volume/adv20)),industry)+0.32*rank(-1*multi_factor_acceleration_score_derivative)+0.16*rank((high-close)/(high-low))+0.10*rank(ts_corr(vwap,volume,60)))",
        ind16,
        "Remove the explicit returns term from the high-scoring net income/cashflow hybrid.",
    )
    _add(
        rows,
        "manual19-accel-micro-book-sub12",
        "manual19_acceleration_micro_book",
        "rank(0.32*rank(-1*multi_factor_acceleration_score_derivative)+0.22*rank((high-close)/(high-low))+0.18*rank(ts_mean((open-close)/open,3))+0.16*rank(-1*book_leverage_ratio_3)+0.12*rank(dividends_to_gross_profit))",
        sub12,
        "Optionless micro/book/dividend branch using inverse acceleration as the model-score payload.",
    )
    _add(
        rows,
        "manual19-composite-netincome-bridge-i12",
        "manual19_composite_netincome_bridge",
        "rank(-0.24*ts_rank(composite_factor_score_derivative,90)-0.20*ts_rank(multi_factor_acceleration_score_derivative,90)+0.22*ts_rank(anl4_adjusted_netincome_ft/cap,70)+0.18*rank(-1*cashflow_efficiency_rank_derivative)+0.10*rank(ts_corr(vwap,volume,60))+0.06*rank(volume/adv20))",
        ind12,
        "Repair the manual18 composite-growth self-corr fail by replacing half the payload with net income/cashflow quality.",
    )
    _add(
        rows,
        "manual19-certainty-dividend-quality-sub12",
        "manual19_certainty_dividend_quality",
        "rank(-0.22*ts_rank(earnings_certainty_rank_derivative,100)-0.16*ts_rank(fundamental_growth_module_score,100)+0.20*rank(global_dividend_model_composite_score)+0.18*rank(fixed_cash_to_current_liabilities_ratio)+0.14*rank(-1*book_leverage_ratio_3)+0.10*rank(volume/adv20))",
        sub12,
        "Use only two fields from vRLEmN6a and move the main breadth into dividend/cash/leverage quality.",
    )
    _add(
        rows,
        "manual19-growth-forward-sales-bridge-i12",
        "manual19_growth_forward_sales_bridge",
        f"rank(-{_growth_stack('0.30')}+0.20*ts_rank(forward_sales_to_price,120)+0.16*ts_rank(forward_book_value_to_price,120)+0.14*rank(ts_corr(vwap,volume,70))+0.08*rank(volume/adv20)-0.08*ts_rank(returns,140))",
        ind12,
        "Lower inverse growth weight and bridge into forward sales/book value plus price-volume dispersion.",
    )
    _add(
        rows,
        "manual19-growth-zscore-breadth-sec12",
        "manual19_growth_zscore_breadth",
        "rank(-0.34*zscore(ts_rank(growth_potential_rank_derivative,100))-0.26*zscore(ts_rank(fundamental_growth_module_score,100))-0.18*zscore(ts_rank(earnings_certainty_rank_derivative,100))+0.14*rank(ts_corr(close,volume,100))+0.10*rank(volume/adv20))",
        sec12,
        "Swap to zscore-normalized component transforms and sector settings to avoid a direct vRLEmN6a clone.",
    )
    _add(
        rows,
        "manual19-cashflow-accel-closevwap-sub12",
        "manual19_cashflow_accel_closevwap",
        "rank(0.34*ts_rank(cashflow_op/cap,80)+0.24*rank(-1*multi_factor_acceleration_score_derivative)+0.18*rank(-1*ts_decay_linear(close/vwap,5))+0.12*rank(ts_corr(vwap,volume,60))+0.12*rank(volume/adv20))",
        sub12,
        "Cashflow and inverse acceleration with close/vwap dispersion, avoiding EPS/options fields.",
    )
    _add(
        rows,
        "manual19-netincome-accel-highclose-i12",
        "manual19_netincome_accel_highclose",
        "rank(0.30*ts_rank(anl4_adjusted_netincome_ft/cap,70)+0.26*rank(-1*multi_factor_acceleration_score_derivative)+0.20*rank((high-close)/(high-low))+0.14*rank(ts_corr(open,volume,50))+0.10*rank(volume/adv20))",
        ind12,
        "Net-income plus inverse acceleration with high-close and open-volume timing support.",
    )
    _add(
        rows,
        "manual19-grouped-growth-cashflow-sub16",
        "manual19_grouped_growth_cashflow",
        "rank(0.28*group_rank(ts_rank(cashflow_op/cap,90),industry)-0.24*group_rank(ts_rank(growth_potential_rank_derivative,100),industry)-0.20*group_rank(ts_rank(fundamental_growth_module_score,100),subindustry)+0.16*rank(-1*cashflow_efficiency_rank_derivative)+0.12*rank(ts_corr(vwap,volume,80)))",
        sub16,
        "Group-rank the growth/cashflow components to change the cross-sectional geometry after vRLEmN6a.",
    )
    _add(
        rows,
        "manual19-accel-quality-no-growth-i12",
        "manual19_accel_quality_no_growth",
        "rank(0.30*rank(-1*multi_factor_acceleration_score_derivative)+0.22*ts_rank(anl4_adjusted_netincome_ft/cap,80)+0.18*rank(-1*cashflow_efficiency_rank_derivative)+0.16*rank(fixed_cash_to_current_liabilities_ratio)+0.14*rank(volume/adv20))",
        ind12,
        "Drop the vRLEmN6a growth/certainty fields entirely and keep inverse acceleration plus quality breadth.",
    )
    _add(
        rows,
        "manual19-growth-hilo-dispersion-sub12",
        "manual19_growth_hilo_dispersion",
        f"rank(-{_growth_stack('0.28')}+0.22*rank((high-close)/(high-low))+0.18*rank(ts_corr(open,volume,40))+0.14*rank(-1*book_leverage_ratio_3)+0.10*rank(dividends_to_gross_profit))",
        sub12,
        "Dilute inverse growth with high/low and open-volume dispersion instead of returns reversal.",
    )
    _add(
        rows,
        "manual19-sector-cashflow-accel-micro-sec12",
        "manual19_sector_cashflow_accel_micro",
        "rank(group_neutralize(0.30*ts_rank(cashflow_op/cap,80)+0.24*rank(-1*multi_factor_acceleration_score_derivative)+0.18*rank((high-close)/(high-low))+0.14*rank(ts_corr(vwap,volume,80))+0.08*rank(volume/adv20),sector))",
        sec12,
        "Sector-neutral cashflow/acceleration/micro blend with no vRLEmN6a growth-certainty fields.",
    )
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
