from __future__ import annotations

from dataclasses import dataclass

from . import financial_engine
from .models import ProjectInputs, ProjectResults


@dataclass
class ScenarioFactors:
    revenue_multiplier: float
    capex_multiplier: float
    opex_multiplier: float
    interest_rate_adj: float


DEFAULT_SCENARIOS: dict[str, ScenarioFactors] = {
    "Bear (P10)": ScenarioFactors(0.85, 1.10, 1.05, 0.003),
    "Base (P50)": ScenarioFactors(1.00, 1.00, 1.00, 0.000),
    "Bull (P90)": ScenarioFactors(1.25, 0.90, 0.95, -0.005),
}


def run_scenarios(
    inputs: ProjectInputs,
    debt_kwargs: dict,
    scenarios: dict[str, ScenarioFactors] | None = None,
) -> dict[str, tuple[ScenarioFactors, ProjectResults]]:
    scenarios = scenarios or DEFAULT_SCENARIOS
    results = {}
    for name, factors in scenarios.items():
        result = financial_engine.compute_results(
            inputs,
            revenue_multiplier=factors.revenue_multiplier,
            capex_multiplier=factors.capex_multiplier,
            opex_multiplier=factors.opex_multiplier,
            interest_rate_adj=factors.interest_rate_adj,
            **debt_kwargs,
        )
        results[name] = (factors, result)
    return results
