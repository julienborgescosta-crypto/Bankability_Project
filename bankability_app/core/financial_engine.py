from __future__ import annotations

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
    gearing_pct: float | None = None,
    interest_rate: float | None = None,
    debt_tenor_years: int | None = None,
    repowering_gearing_pct: float | None = None,
    repowering_interest_rate: float | None = None,
    repowering_debt_tenor_years: int | None = None,
    revenue_multiplier: float = 1.0,
    capex_multiplier: float = 1.0,
    opex_multiplier: float = 1.0,
    interest_rate_adj: float = 0.0,
    degradation_multipliers: list[float] | None = None,
) -> ProjectResults:
    gearing = inputs.gearing_pct if gearing_pct is None else gearing_pct
    rate = (inputs.interest_rate if interest_rate is None else interest_rate) + interest_rate_adj
    tenor = inputs.debt_tenor_years if debt_tenor_years is None else debt_tenor_years
    rep_gearing = (
        inputs.repowering_gearing_pct if repowering_gearing_pct is None else repowering_gearing_pct
    )
    rep_rate = (
        inputs.repowering_interest_rate
        if repowering_interest_rate is None
        else repowering_interest_rate
    ) + interest_rate_adj
    rep_tenor = (
        inputs.repowering_debt_tenor_years
        if repowering_debt_tenor_years is None
        else repowering_debt_tenor_years
    )

    capex = [c * capex_multiplier for c in inputs.capex_keur]
    opex = [o * opex_multiplier for o in inputs.opex_keur]
    revenue = [r * revenue_multiplier for r in inputs.revenues_keur]
    if degradation_multipliers is not None:
        revenue = [r * m for r, m in zip(revenue, degradation_multipliers, strict=True)]
    turpe = list(inputs.turpe_keur)
    end_of_life = list(inputs.end_of_life_keur)

    # Repowering CAPEX is a separate debt facility from the initial senior debt
    # (own gearing/rate/tenor - see I-Project section 6 "Financing"). Detected as
    # the 2nd CAPEX outflow year in the series, if any; a 3rd+ outflow (unusual)
    # is bundled into the repowering tranche rather than adding a 3rd facility.
    capex_out_indices = [i for i, c in enumerate(capex) if c < 0]
    repowering_index = capex_out_indices[1] if len(capex_out_indices) > 1 else None

    def _is_repowering_year(i: int) -> bool:
        return repowering_index is not None and i >= repowering_index

    capex_total_initial = -sum(
        c for i, c in enumerate(capex) if c < 0 and not _is_repowering_year(i)
    )
    capex_total_repowering = -sum(
        c for i, c in enumerate(capex) if c < 0 and _is_repowering_year(i)
    )

    debt_amount_initial = gearing * capex_total_initial
    equity_amount_initial = capex_total_initial - debt_amount_initial
    debt_service_initial = annuity_payment(debt_amount_initial, rate, tenor)

    debt_amount_repowering = rep_gearing * capex_total_repowering
    equity_amount_repowering = capex_total_repowering - debt_amount_repowering
    debt_service_repowering = annuity_payment(debt_amount_repowering, rep_rate, rep_tenor)

    capex_total = capex_total_initial + capex_total_repowering
    debt_amount = debt_amount_initial + debt_amount_repowering
    equity_amount = equity_amount_initial + equity_amount_repowering

    yearly: list[YearlyResult] = []
    net_cashflow_series: list[float] = []
    equity_cashflow_series: list[float] = []
    op_year_counter = 0
    op_year_counter_repowering = 0
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
            tranche_total = (
                capex_total_repowering if _is_repowering_year(i) else capex_total_initial
            )
            tranche_equity = (
                equity_amount_repowering if _is_repowering_year(i) else equity_amount_initial
            )
            equity_share = tranche_equity * (capex_out / tranche_total) if tranche_total else 0.0
            dscr = None
            ds_year = 0.0
            equity_cf = equity_share
        elif i < first_op_index:
            dscr = None
            ds_year = 0.0
            equity_cf = cfads
        else:
            op_year_counter += 1
            ds_year = debt_service_initial if op_year_counter <= tenor else 0.0
            if repowering_index is not None and i > repowering_index:
                op_year_counter_repowering += 1
                if op_year_counter_repowering <= rep_tenor:
                    ds_year += debt_service_repowering
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
        debt_service_keur=debt_service_initial + debt_service_repowering,
        dscr_min=dscr_min,
        dscr_avg=dscr_avg,
        capex_total_initial_keur=capex_total_initial,
        capex_total_repowering_keur=capex_total_repowering,
        debt_amount_initial_keur=debt_amount_initial,
        debt_amount_repowering_keur=debt_amount_repowering,
        debt_service_initial_keur=debt_service_initial,
        debt_service_repowering_keur=debt_service_repowering,
    )


def _safe_irr(cashflows: list[float]) -> float | None:
    if not cashflows or all(c == 0 for c in cashflows):
        return None
    try:
        value = npf.irr(cashflows)
    except Exception:
        return None
    if value is None or value != value:  # NaN check
        return None
    return float(value)
