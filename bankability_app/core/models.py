from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RevenueBreakdown:
    """Per-stream revenue series (k€). `contracted_keur`/`merchant_keur` come from
    O-Financials (PPA Revenues + Capacity market vs Merchant revenues) when the
    full-format BP is parsed - used by risk_rules.py to weight the DSCR threshold
    by revenue quality (contracted cashflow is more bankable than merchant).
    `arbitrage_keur`/`ancillary_keur` (DA/ID vs FCR/aFRR split) remain unpopulated -
    blocked on the Annual cashflows 1 MW `configuration` key, see bp_parsing.md."""

    arbitrage_keur: list[float] | None = None
    contracted_keur: list[float] | None = None
    merchant_keur: list[float] | None = None
    ancillary_keur: list[float] | None = None


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

    reported_irr: float | None = None
    reported_equity_irr: float | None = None
    reported_wacc: float | None = None
    reported_npv_keur: float | None = None
    reported_dscr_avg: float | None = None
    reported_dscr_min: float | None = None

    # Financing assumptions are not extracted from the BP (it reports project-level
    # cashflows, not a debt schedule) - these are editable defaults set in the UI.
    wacc: float = 0.10
    gearing_pct: float = 0.70
    interest_rate: float = 0.05
    debt_tenor_years: int = 15

    # Repowering debt is a separate facility from the initial senior debt (own
    # closing date, gearing, rate, maturity - see I-Project section 6 "Financing").
    # Defaults mirror the initial tranche's when not extracted from the BP.
    repowering_gearing_pct: float = 0.70
    repowering_interest_rate: float = 0.05
    repowering_debt_tenor_years: int = 10

    # Project-specific DSCR covenant target (I-Project "Target DSCR"), used by
    # risk_rules.py in place of the generic config threshold when available.
    target_dscr: float | None = None
    # CAPEX total as stated in I-Project, for cross-check against the CAPEX series
    # sourced from O-Financials/O-Control - a discrepancy has been observed on at
    # least one real project and is not yet explained (docs/specs/bp_parsing.md).
    reported_capex_i_project_keur: float | None = None
    # One-off senior debt arrangement fee (% of the amount drawn), I-Project
    # "Senior Debt Upfront fee" - folded into the financing need in debt_sizing_mode
    # "dscr" only (see financial_engine.py). No equivalent field is extracted for
    # the repowering tranche (not present in I-Project's repowering debt section).
    senior_debt_upfront_fee_pct: float | None = None

    # O-Control "Uses & Sources" block: additional financing uses beyond CAPEX
    # itself (DSRA, financing costs/fees/interest during construction, operating
    # costs during construction, minimum cash at hands). The real gearing % is
    # applied to CAPEX + these, not to CAPEX alone - widening the funding base
    # in debt_sizing_mode "gearing" by their sum reconciles our computed debt
    # almost exactly against the real reported debt (see docs/specs/financial_engine.md).
    reported_dsra_keur: float | None = None
    reported_financing_fees_construction_keur: float | None = None
    reported_opex_during_construction_keur: float | None = None
    reported_minimum_cash_keur: float | None = None

    revenue_detail: RevenueBreakdown | None = None


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
    dscr: float | None
    equity_cashflow_keur: float


@dataclass
class ProjectResults:
    yearly: list[YearlyResult]
    project_irr: float | None
    equity_irr: float | None
    npv_keur: float | None
    capex_total_keur: float
    debt_amount_keur: float
    equity_amount_keur: float
    debt_service_keur: float
    dscr_min: float | None
    dscr_avg: float | None

    # Breakdown between the initial senior debt tranche and the repowering debt
    # tranche (0.0 when there is no repowering CAPEX year in the series). The
    # aggregate fields above are the sum of both tranches.
    capex_total_initial_keur: float = 0.0
    capex_total_repowering_keur: float = 0.0
    debt_amount_initial_keur: float = 0.0
    debt_amount_repowering_keur: float = 0.0
    debt_service_initial_keur: float = 0.0
    debt_service_repowering_keur: float = 0.0

    # Additional financing uses beyond CAPEX (DSRA + financing fees/interest
    # during construction + operating costs during construction + minimum cash),
    # folded into the funding base for the initial tranche in debt_sizing_mode
    # "gearing" only (see ProjectInputs.reported_dsra_keur and financial_engine.py).
    # 0.0 when the BP doesn't report this "Uses & Sources" block.
    funding_uses_addon_initial_keur: float = 0.0
