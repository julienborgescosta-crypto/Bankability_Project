from __future__ import annotations

from typing import Optional

import numpy_financial as npf

from .models import ProjectInputs, ProjectResults, YearlyResult


def annuity_payment(principal: float, rate: float, n_periods: int) -> float:
    if n_periods <= 0 or principal <= 0:
        return 0.0
    if rate == 0:
        return principal / n_periods
    return principal * rate / (1 - (1 + rate) ** -n_periods)


def compute_results(
    inputs: ProjectInputs,
    *,
    gearing_pct: Optional[float] = None,
    interest_rate: Optional[float] = None,
    debt_tenor_years: Optional[int] = None,
    revenue_multiplier: float = 1.0,
    capex_multiplier: float = 1.0,
    opex_multiplier: float = 1.0,
    interest_rate_adj: float = 0.0,
    degradation_multipliers: Optional[list[float]] = None,
) -> ProjectResults:
    gearing = inputs.gearing_pct if gearing_pct is None else gearing_pct
    rate = (inputs.interest_rate if interest_rate is None else interest_rate) + interest_rate_adj
    tenor = inputs.debt_tenor_years if debt_tenor_years is None else debt_tenor_years

    capex = [c * capex_multiplier for c in inputs.capex_keur]
    opex = [o * opex_multiplier for o in inputs.opex_keur]
    revenue = [r * revenue_multiplier for r in inputs.revenues_keur]
    if degradation_multipliers is not None:
        revenue = [r * m for r, m in zip(revenue, degradation_multipliers)]
    turpe = list(inputs.turpe_keur)
    end_of_life = list(inputs.end_of_life_keur)

    capex_total = -sum(c for c in capex if c < 0)
    debt_amount = gearing * capex_total
    equity_amount = capex_total - debt_amount
    debt_service = annuity_payment(debt_amount, rate, tenor)

    yearly: list[YearlyResult] = []
    net_cashflow_series: list[float] = []
    equity_cashflow_series: list[float] = []
    op_year_counter = 0
    # Debt service must only start once operations actually begin - a construction/
    # ramp-up year with no CAPEX outflow but zero revenue yet (e.g. COD falls a year
    # after the last CAPEX disbursement) must not be mistaken for an operating year,
    # or DSCR comes out spuriously negative for that year.
    first_op_index = next((i for i, r in enumerate(revenue) if r != 0), len(revenue))

    for i, year in enumerate(inputs.years):
        capex_out = capex[i]
        # opex/turpe series carry their own sign in the BP (already negative outflows),
        # revenue and end_of_life are positive inflows - CFADS is a plain sum.
        cfads = revenue[i] + opex[i] + turpe[i] + end_of_life[i]
        net_cf = cfads + capex_out

        if capex_out != 0:
            # capex_out is negative -> equity_share comes out negative (an outflow), as required for IRR.
            equity_share = equity_amount * (capex_out / capex_total) if capex_total else 0.0
            dscr = None
            ds_year = 0.0
            equity_cf = equity_share
        elif i < first_op_index:
            dscr = None
            ds_year = 0.0
            equity_cf = cfads
        else:
            op_year_counter += 1
            ds_year = debt_service if op_year_counter <= tenor else 0.0
            dscr = (cfads / ds_year) if ds_year > 0 else None
            equity_cf = cfads - ds_year

        net_cashflow_series.append(net_cf)
        equity_cashflow_series.append(equity_cf)

        yearly.append(
            YearlyResult(
                year=year,
                capex_keur=capex_out,
                opex_keur=opex[i],
                revenue_keur=revenue[i],
                turpe_keur=turpe[i],
                end_of_life_keur=end_of_life[i],
                cfads_keur=cfads,
                net_cashflow_keur=net_cf,
                debt_service_keur=ds_year,
                dscr=dscr,
                equity_cashflow_keur=equity_cf,
            )
        )

    project_irr = _safe_irr(net_cashflow_series)
    equity_irr = _safe_irr(equity_cashflow_series) if equity_amount > 0 else None
    npv = float(npf.npv(inputs.wacc, net_cashflow_series)) if net_cashflow_series else None

    dscr_values = [r.dscr for r in yearly if r.dscr is not None]
    dscr_min = min(dscr_values) if dscr_values else None
    dscr_avg = sum(dscr_values) / len(dscr_values) if dscr_values else None

    return ProjectResults(
        yearly=yearly,
        project_irr=project_irr,
        equity_irr=equity_irr,
        npv_keur=npv,
        capex_total_keur=capex_total,
        debt_amount_keur=debt_amount,
        equity_amount_keur=equity_amount,
        debt_service_keur=debt_service,
        dscr_min=dscr_min,
        dscr_avg=dscr_avg,
    )


def _safe_irr(cashflows: list[float]) -> Optional[float]:
    if not cashflows or all(c == 0 for c in cashflows):
        return None
    try:
        value = npf.irr(cashflows)
    except Exception:
        return None
    if value is None or value != value:  # NaN check
        return None
    return float(value)
