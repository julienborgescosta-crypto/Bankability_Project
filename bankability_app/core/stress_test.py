from __future__ import annotations

from . import degradation, financial_engine
from .models import ProjectInputs

REVENUE_CASES = {"Base": 1.0, "Bear": 0.85}


def run_stress_matrix(inputs: ProjectInputs, debt_kwargs: dict) -> list[dict]:
    rows = []
    length = len(inputs.years)
    for rev_label, rev_mult in REVENUE_CASES.items():
        for deg_label, deg_params in degradation.DEGRADATION_CASES.items():
            deg_curve = degradation.degradation_multipliers(length, **deg_params)
            result = financial_engine.compute_results(
                inputs,
                revenue_multiplier=rev_mult,
                degradation_multipliers=deg_curve,
                **debt_kwargs,
            )
            rows.append(
                {
                    "revenue_case": rev_label,
                    "degradation_case": deg_label,
                    "combined": rev_label != "Base" and deg_label != "Base",
                    "project_irr": result.project_irr,
                    "equity_irr": result.equity_irr,
                    "dscr_min": result.dscr_min,
                }
            )
    return rows
