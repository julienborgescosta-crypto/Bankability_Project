import pytest

from core import sensitivity


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
