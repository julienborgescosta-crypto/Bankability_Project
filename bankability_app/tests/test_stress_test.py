from core import stress_test


def _debt_kwargs(inputs):
    return {
        "gearing_pct": inputs.gearing_pct,
        "interest_rate": inputs.interest_rate,
        "debt_tenor_years": inputs.debt_tenor_years,
    }


def test_stress_matrix_covers_all_combinations(simple_inputs):
    rows = stress_test.run_stress_matrix(simple_inputs, _debt_kwargs(simple_inputs))
    combos = {(r["revenue_case"], r["degradation_case"]) for r in rows}
    assert combos == {
        ("Base", "Base"),
        ("Base", "Conservative"),
        ("Bear", "Base"),
        ("Bear", "Conservative"),
    }


def test_only_bear_and_conservative_together_is_flagged_combined(simple_inputs):
    rows = stress_test.run_stress_matrix(simple_inputs, _debt_kwargs(simple_inputs))
    for row in rows:
        expected = row["revenue_case"] != "Base" and row["degradation_case"] != "Base"
        assert row["combined"] == expected


def test_base_base_is_the_least_stressed_case(simple_inputs):
    rows = stress_test.run_stress_matrix(simple_inputs, _debt_kwargs(simple_inputs))
    by_combo = {(r["revenue_case"], r["degradation_case"]): r for r in rows}

    base_base = by_combo[("Base", "Base")]
    bear_conservative = by_combo[("Bear", "Conservative")]

    assert base_base["project_irr"] > bear_conservative["project_irr"]
    assert base_base["dscr_min"] > bear_conservative["dscr_min"]
