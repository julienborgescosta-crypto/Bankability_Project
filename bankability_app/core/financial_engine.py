from __future__ import annotations

import numpy_financial as npf

from .models import ProjectInputs, ProjectResults, YearlyResult


def annuity_payment(principal: float, rate: float, n_periods: int) -> float:
    if n_periods <= 0 or principal <= 0:
        return 0.0
    if rate == 0:
        return principal / n_periods
    return principal * rate / (1 - (1 + rate) ** -n_periods)


def debt_amount_from_annuity(payment: float, rate: float, n_periods: int) -> float:
    """Inverse of annuity_payment(): the principal that this constant annual
    payment services over n_periods at rate."""
    if n_periods <= 0 or payment <= 0:
        return 0.0
    if rate == 0:
        return payment * n_periods
    return payment * (1 - (1 + rate) ** -n_periods) / rate


def present_value(cashflows: list[float], rate: float) -> float:
    """PV of cashflows occurring at t=1, 2, ... (not t=0 - unlike numpy_financial.npv,
    which treats cashflows[0] as an undiscounted t=0 flow)."""
    if rate == 0:
        return sum(cashflows)
    return sum(cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cashflows))


def sculpt_debt_service(cfads_window: list[float], target_dscr: float) -> list[float]:
    """True cash-flow sculpting: debt service each year = CFADS_year / target_dscr,
    hitting the target DSCR exactly every year - not just in the single worst
    year like a level annuity would. This is the standard project-finance
    definition of a sculpted repayment profile, and what real models converge
    to via circular-reference iteration (see docs/specs/financial_engine.md)."""
    if target_dscr <= 0:
        return [0.0] * len(cfads_window)
    return [max(0.0, c / target_dscr) for c in cfads_window]


def capitalized_construction_interest(draws: list[float], rate: float) -> float:
    """Interest accruing on debt drawn during construction, capitalised (added
    to principal) rather than paid cash since there's no CFADS yet to service
    it. `draws` are chronological, one entry per construction year (last entry
    = the year immediately before COD). Mid-year drawdown convention (each draw
    accrues half a year of interest in its own year, then compounds for every
    full subsequent construction year) since only annual - not monthly -
    drawdown timing is available."""
    n = len(draws)
    total = 0.0
    for i, draw in enumerate(draws):
        years_to_cod = (n - 1 - i) + 0.5
        total += draw * ((1 + rate) ** years_to_cod - 1)
    return total


def _size_tranche_by_dscr(
    cfads_window: list[float],
    target_dscr: float,
    rate: float,
    tenor: int,
    gearing: float,
    capex_total: float,
    draws: list[float],
    upfront_fee_pct: float,
) -> tuple[list[float], float]:
    """Sculpts debt service to hit target_dscr every year of cfads_window, then
    caps the resulting principal by a gearing ceiling inflated by capitalised
    construction interest (IDC) and the upfront arrangement fee - both assumed
    financed pro-rata via the same gearing ratio as CAPEX (single-pass
    approximation off the CAPEX-driven draw, not resolved as a fully
    simultaneous system - fees/IDC are typically a few % of CAPEX, so this
    second-order feedback is negligible; see docs/specs/financial_engine.md).
    Returns (service_schedule_for_the_window, principal)."""
    sculpted = sculpt_debt_service(cfads_window, target_dscr)
    principal_uncapped = present_value(sculpted, rate)

    idc = capitalized_construction_interest(draws, rate)
    upfront_fee_amount = upfront_fee_pct * sum(draws)
    gearing_cap = gearing * (capex_total + idc + upfront_fee_amount)

    if principal_uncapped > gearing_cap:
        scale = (gearing_cap / principal_uncapped) if principal_uncapped else 0.0
        return [s * scale for s in sculpted], gearing_cap
    return sculpted, principal_uncapped


def _tranche_service_schedule(
    length: int,
    capex: list[float],
    start_after_index: int,
    service: float | list[float],
    tenor: int,
) -> list[float]:
    """Per-year debt service for one tranche: 0 during CAPEX years and years at
    or before start_after_index, then `service` for the next `tenor` operating
    years (years where this tranche's CAPEX is not being drawn), 0 after.
    `service` is either a constant annuity (float, gearing mode) or a sculpted
    per-year list (dscr mode - service[0] is this tranche's 1st operating year,
    service[1] its 2nd, ...)."""
    service_list = [service] * tenor if isinstance(service, (int, float)) else service
    schedule = [0.0] * length
    counter = 0
    for i in range(length):
        if capex[i] != 0 or i <= start_after_index:
            continue
        if counter < len(service_list):
            schedule[i] = service_list[counter]
        counter += 1
    return schedule


def _mean_active(schedule: list[float]) -> float:
    active = [s for s in schedule if s > 0]
    return sum(active) / len(active) if active else 0.0


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
    debt_sizing_mode: str = "gearing",
    target_dscr: float | None = None,
) -> ProjectResults:
    """debt_sizing_mode:
    - "gearing" (default): debt = gearing_pct x CAPEX, constant annuity, DSCR is
      an output. Simple fixed-leverage assumption when no real covenant is known -
      entirely unaffected by the "dscr" mode below (zero behaviour change).
    - "dscr": debt is sculpted (core/sculpt_debt_service) so CFADS / debt service
      == target_dscr every year of the tenor (not just >= in the worst year),
      capped by a gearing ceiling that also accounts for capitalised construction
      interest and the senior debt upfront fee when available (_size_tranche_by_dscr).
      Mirrors how the real BP (I-Project "Target DSCR" + "Gearing max" + "Senior
      Debt Upfront fee") actually sizes its senior debt - see docs/specs/financial_engine.md
      for what is and is not reproduced (no DSRA, commitment fees, or cash sweep;
      fees/IDC affect the debt ceiling only, not modeled as cash costs elsewhere).
      Requires target_dscr (this kwarg or inputs.target_dscr) - raises otherwise.
    """
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
    length = len(inputs.years)

    cfads_list = [revenue[i] + opex[i] + turpe[i] + end_of_life[i] for i in range(length)]

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

    # Debt service must only start once operations actually begin - a construction/
    # ramp-up year with no CAPEX outflow but zero revenue yet (e.g. COD falls a year
    # after the last CAPEX disbursement) must not be mistaken for an operating year,
    # or DSCR comes out spuriously negative for that year.
    first_op_index = next((i for i, r in enumerate(revenue) if r != 0), length)
    # Same ramp-up protection for the repowering tranche: operations don't
    # necessarily resume the very year after the repowering CAPEX outflow (e.g.
    # a repowering construction spanning into the following year) - without this,
    # repowering debt service could start against a still-zero CFADS year, same
    # bug class as the initial tranche's ramp-up (see financial_engine.md).
    first_op_index_after_repowering = (
        next((i for i in range(repowering_index + 1, length) if revenue[i] != 0), length)
        if repowering_index is not None
        else None
    )

    if debt_sizing_mode == "dscr":
        effective_target_dscr = inputs.target_dscr if target_dscr is None else target_dscr
        if not effective_target_dscr or effective_target_dscr <= 0:
            raise ValueError(
                "debt_sizing_mode='dscr' necessite un target_dscr positif "
                "(ni fourni en argument, ni present dans ProjectInputs.target_dscr)."
            )
        # Sized sequentially, in chronological order: the initial tranche is
        # closed before repowering happens, so it's sized first, in isolation.
        initial_draws = [
            gearing * -capex[i]
            for i in range(length)
            if capex[i] < 0 and not _is_repowering_year(i)
        ]
        initial_window = cfads_list[first_op_index : first_op_index + tenor]
        initial_service, debt_amount_initial = _size_tranche_by_dscr(
            initial_window,
            effective_target_dscr,
            rate,
            tenor,
            gearing,
            capex_total_initial,
            initial_draws,
            inputs.senior_debt_upfront_fee_pct or 0.0,
        )
    elif debt_sizing_mode == "gearing":
        debt_amount_initial = gearing * capex_total_initial
        initial_service = annuity_payment(debt_amount_initial, rate, tenor)
    else:
        raise ValueError(
            f"debt_sizing_mode inconnu : '{debt_sizing_mode}' (attendu 'gearing' ou 'dscr')."
        )
    initial_schedule = _tranche_service_schedule(
        length, capex, first_op_index - 1, initial_service, tenor
    )
    debt_service_initial = _mean_active(initial_schedule)

    if debt_sizing_mode == "dscr" and repowering_index is not None:
        # Sized against CFADS net of whatever initial debt service is still
        # running during the overlap (initial_schedule, just computed, already
        # reflects the final - possibly capped - initial debt service).
        repowering_draws = [
            rep_gearing * -capex[i]
            for i in range(length)
            if capex[i] < 0 and _is_repowering_year(i)
        ]
        rep_window = [
            cfads_list[i] - initial_schedule[i]
            for i in range(
                first_op_index_after_repowering,
                min(first_op_index_after_repowering + rep_tenor, length),
            )
        ]
        # No upfront-fee field is extracted for the repowering tranche (not
        # present in I-Project's repowering debt section).
        repowering_service, debt_amount_repowering = _size_tranche_by_dscr(
            rep_window,
            effective_target_dscr,
            rep_rate,
            rep_tenor,
            rep_gearing,
            capex_total_repowering,
            repowering_draws,
            0.0,
        )
    else:
        debt_amount_repowering = rep_gearing * capex_total_repowering
        repowering_service = annuity_payment(debt_amount_repowering, rep_rate, rep_tenor)
    repowering_schedule = (
        _tranche_service_schedule(
            length, capex, first_op_index_after_repowering - 1, repowering_service, rep_tenor
        )
        if repowering_index is not None
        else [0.0] * length
    )
    debt_service_repowering = _mean_active(repowering_schedule)

    equity_amount_initial = capex_total_initial - debt_amount_initial
    equity_amount_repowering = capex_total_repowering - debt_amount_repowering
    capex_total = capex_total_initial + capex_total_repowering
    debt_amount = debt_amount_initial + debt_amount_repowering
    equity_amount = equity_amount_initial + equity_amount_repowering

    yearly: list[YearlyResult] = []
    net_cashflow_series: list[float] = []
    equity_cashflow_series: list[float] = []

    for i, year in enumerate(inputs.years):
        capex_out = capex[i]
        cfads = cfads_list[i]
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
            ds_year = initial_schedule[i] + repowering_schedule[i]
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
