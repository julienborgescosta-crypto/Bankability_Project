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
    payment services over n_periods at rate. Used by DSCR-based debt sizing to
    turn "the most we can pay each year" into "the most we can borrow"."""
    if n_periods <= 0 or payment <= 0:
        return 0.0
    if rate == 0:
        return payment * n_periods
    return payment * (1 - (1 + rate) ** -n_periods) / rate


def _tranche_service_schedule(
    length: int,
    capex: list[float],
    start_after_index: int,
    annuity: float,
    tenor: int,
) -> list[float]:
    """Per-year debt service for one tranche: 0 during CAPEX years and years at
    or before start_after_index, then `annuity` for the next `tenor` operating
    years (years where this tranche's CAPEX is not being drawn), 0 after."""
    schedule = [0.0] * length
    counter = 0
    for i in range(length):
        if capex[i] != 0 or i <= start_after_index:
            continue
        counter += 1
        if counter <= tenor:
            schedule[i] = annuity
    return schedule


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
    - "gearing" (default): debt = gearing_pct x CAPEX, DSCR is an output. Matches
      a simple fixed-leverage assumption when no real covenant is known.
    - "dscr": debt is sized (sculpted) so CFADS / debt service >= target_dscr in
      every year of the tranche's tenor, capped by gearing_pct x CAPEX as a
      ceiling - mirrors how the real BP (I-Project "Target DSCR" + "Gearing max")
      actually sizes its senior debt, so results become comparable to the BP's
      own reported DSCR/Equity IRR instead of structurally diverging from them.
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

    if debt_sizing_mode == "dscr":
        effective_target_dscr = inputs.target_dscr if target_dscr is None else target_dscr
        if not effective_target_dscr or effective_target_dscr <= 0:
            raise ValueError(
                "debt_sizing_mode='dscr' necessite un target_dscr positif "
                "(ni fourni en argument, ni present dans ProjectInputs.target_dscr)."
            )

        # Sized sequentially, in chronological order: the initial tranche is
        # closed before repowering happens, so it's sized first, in isolation.
        initial_window = cfads_list[first_op_index : first_op_index + tenor]
        max_annuity_initial = (
            max(0.0, min(initial_window) / effective_target_dscr) if initial_window else 0.0
        )
        debt_amount_initial = min(
            debt_amount_from_annuity(max_annuity_initial, rate, tenor),
            gearing * capex_total_initial,
        )
    elif debt_sizing_mode == "gearing":
        debt_amount_initial = gearing * capex_total_initial
    else:
        raise ValueError(
            f"debt_sizing_mode inconnu : '{debt_sizing_mode}' (attendu 'gearing' ou 'dscr')."
        )
    debt_service_initial = annuity_payment(debt_amount_initial, rate, tenor)
    initial_schedule = _tranche_service_schedule(
        length, capex, first_op_index - 1, debt_service_initial, tenor
    )

    if debt_sizing_mode == "dscr" and repowering_index is not None:
        # The repowering tranche is sized against CFADS net of whatever initial
        # debt service is still running during the overlap (initial_schedule,
        # just computed, already reflects the final - possibly gearing-capped -
        # initial debt service).
        rep_window = [
            cfads_list[i] - initial_schedule[i]
            for i in range(repowering_index + 1, min(repowering_index + 1 + rep_tenor, length))
        ]
        max_annuity_repowering = (
            max(0.0, min(rep_window) / effective_target_dscr) if rep_window else 0.0
        )
        debt_amount_repowering = min(
            debt_amount_from_annuity(max_annuity_repowering, rep_rate, rep_tenor),
            rep_gearing * capex_total_repowering,
        )
    else:
        debt_amount_repowering = rep_gearing * capex_total_repowering
    debt_service_repowering = annuity_payment(debt_amount_repowering, rep_rate, rep_tenor)
    repowering_schedule = (
        _tranche_service_schedule(
            length, capex, repowering_index, debt_service_repowering, rep_tenor
        )
        if repowering_index is not None
        else [0.0] * length
    )

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
