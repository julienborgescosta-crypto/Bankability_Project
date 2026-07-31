from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RevenueBreakdown:
    """Per-stream revenue series (k€). Populated only once a detailed multi-tab
    BP (C-SPV / I-Project) is parsed; None when only the summary tab is available."""

    arbitrage_keur: Optional[list[float]] = None
    contracted_keur: Optional[list[float]] = None
    ancillary_keur: Optional[list[float]] = None


@dataclass
class ProjectInputs:
    name: str
    location: str
    segment: str
    cod: str
    operating_years: int
    usable_power_mw: float
    usable_energy_mwh: float

    capex_initial_keur: float
    capex_repowering_keur: float
    repowering: bool
    opex_year1_keur: float
    opex_adjustment_keur: float
    turpe_fixed_eur_per_kw: float

    years: list[int]
    capex_keur: list[float]
    opex_keur: list[float]
    end_of_life_keur: list[float]
    revenues_keur: list[float]
    turpe_keur: list[float]
    net_cashflow_keur: list[float]

    reported_irr: Optional[float] = None
    reported_equity_irr: Optional[float] = None
    reported_wacc: Optional[float] = None
    reported_npv_keur: Optional[float] = None
    reported_dscr_avg: Optional[float] = None
    reported_dscr_min: Optional[float] = None

    # Financing assumptions are not extracted from the BP (it reports project-level
    # cashflows, not a debt schedule) - these are editable defaults set in the UI.
    wacc: float = 0.10
    gearing_pct: float = 0.70
    interest_rate: float = 0.05
    debt_tenor_years: int = 15

    revenue_detail: Optional[RevenueBreakdown] = None


@dataclass
class YearlyResult:
    year: int
    capex_keur: float
    opex_keur: float
    revenue_keur: float
    turpe_keur: float
    end_of_life_keur: float
    cfads_keur: float
    net_cashflow_keur: float
    debt_service_keur: float
    dscr: Optional[float]
    equity_cashflow_keur: float


@dataclass
class ProjectResults:
    yearly: list[YearlyResult]
    project_irr: Optional[float]
    equity_irr: Optional[float]
    npv_keur: Optional[float]
    capex_total_keur: float
    debt_amount_keur: float
    equity_amount_keur: float
    debt_service_keur: float
    dscr_min: Optional[float]
    dscr_avg: Optional[float]
