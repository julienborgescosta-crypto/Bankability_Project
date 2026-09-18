import pytest

from core import financial_engine, sensitivity


def _debt_kwargs(inputs):
    return {
        "gearing_pct": inputs.gearing_pct,
        "interest_rate": inputs.interest_rate,
        "debt_tenor_years": inputs.debt_tenor_years,
    }


def test_run_sensitivity_covers_all_core_variables(simple_inputs):
    base, rows = sensitivity.run_sensitivity(simple_inputs, _debt_kwargs(simple_inputs))
    labels = [row["variable"] for row in rows]
    assert labels == list(sensitivity.CORE_VARIABLES.keys())
    assert base.project_irr is not None


def test_zero_shock_matches_base_case(simple_inputs):
    base, rows = sensitivity.run_sensitivity(simple_inputs, _debt_kwargs(simple_inputs))
    for row in rows:
        assert row[0.0]["equity_irr"] == pytest.approx(base.equity_irr)
        assert row[0.0]["dscr_min"] == pytest.approx(base.dscr_min)


def test_revenue_sensitivity_is_monotonic_on_equity_irr(simple_inputs):
    _, rows = sensitivity.run_sensitivity(simple_inputs, _debt_kwargs(simple_inputs))
    revenue_row = next(r for r in rows if r["variable"] == "Revenue (Total)")
    irr_by_shock = [revenue_row[shock]["equity_irr"] for shock in sensitivity.SHOCKS]
    assert irr_by_shock == sorted(irr_by_shock)


def test_capex_sensitivity_is_inversely_monotonic_on_equity_irr(simple_inputs):
    _, rows = sensitivity.run_sensitivity(simple_inputs, _debt_kwargs(simple_inputs))
    capex_row = next(r for r in rows if r["variable"] == "CAPEX")
    irr_by_shock = [capex_row[shock]["equity_irr"] for shock in sensitivity.SHOCKS]
    assert irr_by_shock == sorted(irr_by_shock, reverse=True)


def test_npv_sensitivity_grid_shape(simple_inputs):
    grid = sensitivity.run_npv_sensitivity_grid(simple_inputs, _debt_kwargs(simple_inputs))
    assert len(grid) == len(sensitivity.NPV_REVENUE_SHOCKS)
    assert all(len(row) == len(sensitivity.NPV_DISCOUNT_RATES) for row in grid)


def test_npv_sensitivity_grid_monotonic_on_both_axes(simple_inputs):
    """A chaque taux d'actualisation fixe, plus de revenu -> NPV plus haute ; a
    revenu fixe, un taux d'actualisation plus eleve -> NPV plus basse."""
    grid = sensitivity.run_npv_sensitivity_grid(simple_inputs, _debt_kwargs(simple_inputs))
    for col in range(len(sensitivity.NPV_DISCOUNT_RATES)):
        column_values = [row[col] for row in grid]
        assert column_values == sorted(column_values)
    for row in grid:
        assert row == sorted(row, reverse=True)


def test_npv_sensitivity_grid_zero_shock_column_matches_wacc_override(simple_inputs):
    debt_kwargs = _debt_kwargs(simple_inputs)
    grid = sensitivity.run_npv_sensitivity_grid(simple_inputs, debt_kwargs)
    zero_shock_idx = sensitivity.NPV_REVENUE_SHOCKS.index(0.0)
    for col, rate in enumerate(sensitivity.NPV_DISCOUNT_RATES):
        direct = financial_engine.compute_results(simple_inputs, wacc=rate, **debt_kwargs)
        assert grid[zero_shock_idx][col] == pytest.approx(direct.npv_keur)
