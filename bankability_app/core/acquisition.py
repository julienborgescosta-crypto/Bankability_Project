from __future__ import annotations

from dataclasses import dataclass

import numpy_financial as npf

from . import financial_engine
from .models import ProjectInputs, ProjectResults
from .sensitivity import CORE_VARIABLES, SHOCKS, shocked_compute_kwargs

# Reference market benchmarks by development stage - static context, not computed
# by this app. Sourced from the acquisition-valuation reference material the user
# provided; update if better/more recent comparables become available.
STAGE_BENCHMARKS = [
    {
        "stage": "Development Rights (pre-construction)",
        "example": "NextEnergy (2022) - 250 MW BESS portfolio, UK",
        "benchmark": "~£130k / MW",
        "note": "Rights only - value reflects development risk and remaining milestones.",
    },
    {
        "stage": "Development Premium (RTB / late-stage)",
        "example": "Enerdatics - RTB BESS projects, Germany",
        "benchmark": "$50k - $170k / MW",
        "note": "Varies with duration, revenue profile, merchant vs contracted share, execution risk.",
    },
    {
        "stage": "Operational Assets",
        "example": "Harmony Energy Income Trust (2024) - 400 MW BESS in operation, UK",
        "benchmark": "~£860k / MW EV",
        "note": "Operating portfolio - value driven by cashflow, performance and risk.",
    },
]


@dataclass
class AcquisitionValuation:
    target_equity_irr: float
    actual_equity_irr: float | None
    base_equity_keur: float
    pv_future_equity_cashflows_keur: float
    max_acquisition_premium_keur: float
    max_total_equity_check_keur: float


def compute_acquisition_valuation(
    result: ProjectResults, target_equity_irr: float
) -> AcquisitionValuation:
    """Solves for the maximum price a buyer can pay for the SPV while still
    clearing target_equity_irr, instead of assuming an acquisition premium as
    an input:

        Purchase Price + Base Equity Investment <= PV(future equity cashflows @ target IRR)

    equity_cashflow_keur already carries its own sign (negative during CAPEX
    years - including a future repowering outflow, if any - positive/negative
    during operations), so discounting the whole series at the target rate is
    exactly the NPV of the equity investment at that rate: the "headroom" a
    buyer has above the base equity requirement before paying a premium drags
    the return below target.
    """
    equity_series = [y.equity_cashflow_keur for y in result.yearly]
    headroom = float(npf.npv(target_equity_irr, equity_series)) if equity_series else 0.0
    base_equity = result.equity_amount_keur
    pv_future_flows = headroom + base_equity

    return AcquisitionValuation(
        target_equity_irr=target_equity_irr,
        actual_equity_irr=result.equity_irr,
        base_equity_keur=base_equity,
        pv_future_equity_cashflows_keur=pv_future_flows,
        max_acquisition_premium_keur=headroom,
        max_total_equity_check_keur=pv_future_flows,
    )


def run_acquisition_sensitivity(
    inputs: ProjectInputs, debt_kwargs: dict, target_equity_irr: float
) -> list[dict]:
    """Same shocked variables as sensitivity.run_sensitivity(), but reporting
    the maximum acquisition premium (headroom) per shock instead of Equity
    IRR/DSCR - answers "how does my acquisition headroom move if grid cost
    (~ OPEX), CAPEX, revenue, financing terms move?"."""
    base_gearing = debt_kwargs.get("gearing_pct", inputs.gearing_pct)
    base_interest = debt_kwargs.get("interest_rate", inputs.interest_rate)

    rows = []
    for label, spec in CORE_VARIABLES.items():
        row = {"variable": label}
        for shock in SHOCKS:
            kwargs = shocked_compute_kwargs(
                spec["kind"], shock, debt_kwargs, base_gearing, base_interest
            )
            result = financial_engine.compute_results(inputs, **kwargs)
            row[shock] = compute_acquisition_valuation(
                result, target_equity_irr
            ).max_acquisition_premium_keur
        rows.append(row)
    return rows
