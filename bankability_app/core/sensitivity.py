from __future__ import annotations

from . import financial_engine
from .models import ProjectInputs, ProjectResults

SHOCKS = [-0.20, -0.10, 0.0, 0.10, 0.20]

# Variables available from the summary BP alone (Temps 1). "kind" tells
# run_sensitivity() which compute_results() kwarg to shock and how.
CORE_VARIABLES: dict[str, dict] = {
    "Revenue (Total)": {"kind": "revenue_multiplier"},
    "CAPEX": {"kind": "capex_multiplier"},
    "OPEX": {"kind": "opex_multiplier"},
    "Interest Rate": {"kind": "interest_rate_relative"},
    "Debt Ratio": {"kind": "gearing_relative"},
}

# Variables that require the granular multi-tab BP (Temps 2). Kept out of
# run_sensitivity() until inputs.revenue_detail is populated - see bp_parser.py.
DETAILED_VARIABLES = ["DAM Spread", "ID Spread", "Cycles", "Capacity Price"]


def run_sensitivity(inputs: ProjectInputs, debt_kwargs: dict) -> tuple[ProjectResults, list[dict]]:
    base = financial_engine.compute_results(inputs, **debt_kwargs)
    base_gearing = debt_kwargs.get("gearing_pct", inputs.gearing_pct)
    base_interest = debt_kwargs.get("interest_rate", inputs.interest_rate)

    rows = []
    for label, spec in CORE_VARIABLES.items():
        row = {"variable": label}
        for shock in SHOCKS:
            kwargs = dict(debt_kwargs)
            kind = spec["kind"]
            if kind == "revenue_multiplier":
                kwargs["revenue_multiplier"] = 1 + shock
            elif kind == "capex_multiplier":
                kwargs["capex_multiplier"] = 1 + shock
            elif kind == "opex_multiplier":
                kwargs["opex_multiplier"] = 1 + shock
            elif kind == "interest_rate_relative":
                kwargs["interest_rate"] = base_interest * (1 + shock)
            elif kind == "gearing_relative":
                kwargs["gearing_pct"] = min(max(base_gearing * (1 + shock), 0.0), 0.95)
            result = financial_engine.compute_results(inputs, **kwargs)
            row[shock] = {"equity_irr": result.equity_irr, "dscr_min": result.dscr_min}
        rows.append(row)
    return base, rows
