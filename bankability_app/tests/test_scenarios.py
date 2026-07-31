from core import financial_engine, scenarios


def _debt_kwargs(inputs):
    return {
        "gearing_pct": inputs.gearing_pct,
        "interest_rate": inputs.interest_rate,
        "debt_tenor_years": inputs.debt_tenor_years,
    }


def test_default_scenarios_are_ordered_bear_base_bull(simple_inputs):
    results = scenarios.run_scenarios(simple_inputs, _debt_kwargs(simple_inputs))

    bear_irr = results["Bear (P10)"][1].project_irr
    base_irr = results["Base (P50)"][1].project_irr
    bull_irr = results["Bull (P90)"][1].project_irr

    assert bear_irr < base_irr < bull_irr


def test_base_scenario_matches_unadjusted_compute_results(simple_inputs):
    debt_kwargs = _debt_kwargs(simple_inputs)
    results = scenarios.run_scenarios(simple_inputs, debt_kwargs)
    base_result = results["Base (P50)"][1]
    unadjusted = financial_engine.compute_results(simple_inputs, **debt_kwargs)

    assert base_result.project_irr == unadjusted.project_irr
    assert base_result.dscr_min == unadjusted.dscr_min


def test_custom_scenarios_override_defaults(simple_inputs):
    custom = {
        "Flat": scenarios.ScenarioFactors(
            revenue_multiplier=1.0, capex_multiplier=1.0, opex_multiplier=1.0, interest_rate_adj=0.0
        )
    }
    results = scenarios.run_scenarios(simple_inputs, _debt_kwargs(simple_inputs), scenarios=custom)
    assert list(results.keys()) == ["Flat"]
