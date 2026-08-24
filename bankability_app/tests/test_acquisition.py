import numpy_financial as npf
import pytest

from core import acquisition, financial_engine


def _debt_kwargs(inputs):
    return {
        "gearing_pct": inputs.gearing_pct,
        "interest_rate": inputs.interest_rate,
        "debt_tenor_years": inputs.debt_tenor_years,
    }


def test_headroom_matches_npv_of_equity_series(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    equity_series = [y.equity_cashflow_keur for y in result.yearly]

    valuation = acquisition.compute_acquisition_valuation(result, target_equity_irr=0.10)

    expected_headroom = npf.npv(0.10, equity_series)
    assert valuation.max_acquisition_premium_keur == pytest.approx(expected_headroom)
    assert valuation.pv_future_equity_cashflows_keur == pytest.approx(
        expected_headroom + result.equity_amount_keur
    )
    assert valuation.base_equity_keur == pytest.approx(result.equity_amount_keur)
    assert valuation.max_total_equity_check_keur == pytest.approx(
        valuation.pv_future_equity_cashflows_keur
    )


def test_headroom_is_near_zero_when_target_equals_actual_irr(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    valuation = acquisition.compute_acquisition_valuation(result, result.equity_irr)
    # NPV au taux egal a l'IRR est nul par definition.
    assert valuation.max_acquisition_premium_keur == pytest.approx(0.0, abs=1e-6)


def test_headroom_positive_when_target_below_actual_irr(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    valuation = acquisition.compute_acquisition_valuation(result, result.equity_irr - 0.05)
    assert valuation.max_acquisition_premium_keur > 0


def test_headroom_negative_when_target_above_actual_irr(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    valuation = acquisition.compute_acquisition_valuation(result, result.equity_irr + 0.05)
    assert valuation.max_acquisition_premium_keur < 0


def test_run_acquisition_sensitivity_zero_shock_matches_base(simple_inputs):
    debt_kwargs = _debt_kwargs(simple_inputs)
    base_result = financial_engine.compute_results(simple_inputs, **debt_kwargs)
    base_valuation = acquisition.compute_acquisition_valuation(base_result, target_equity_irr=0.10)

    rows = acquisition.run_acquisition_sensitivity(
        simple_inputs, debt_kwargs, target_equity_irr=0.10
    )
    for row in rows:
        assert row[0.0] == pytest.approx(base_valuation.max_acquisition_premium_keur)


def test_run_acquisition_sensitivity_covers_core_variables(simple_inputs):
    debt_kwargs = _debt_kwargs(simple_inputs)
    rows = acquisition.run_acquisition_sensitivity(
        simple_inputs, debt_kwargs, target_equity_irr=0.10
    )
    labels = [r["variable"] for r in rows]
    assert labels == list(acquisition.CORE_VARIABLES.keys())


def test_revenue_shock_increases_headroom_monotonically(simple_inputs):
    debt_kwargs = _debt_kwargs(simple_inputs)
    rows = acquisition.run_acquisition_sensitivity(
        simple_inputs, debt_kwargs, target_equity_irr=0.10
    )
    revenue_row = next(r for r in rows if r["variable"] == "Revenue (Total)")
    headroom_by_shock = [revenue_row[shock] for shock in acquisition.SHOCKS]
    assert headroom_by_shock == sorted(headroom_by_shock)


def test_capex_shock_decreases_headroom_monotonically(simple_inputs):
    debt_kwargs = _debt_kwargs(simple_inputs)
    rows = acquisition.run_acquisition_sensitivity(
        simple_inputs, debt_kwargs, target_equity_irr=0.10
    )
    capex_row = next(r for r in rows if r["variable"] == "CAPEX")
    headroom_by_shock = [capex_row[shock] for shock in acquisition.SHOCKS]
    assert headroom_by_shock == sorted(headroom_by_shock, reverse=True)


def test_stage_benchmarks_are_well_formed():
    for entry in acquisition.STAGE_BENCHMARKS:
        assert entry["stage"]
        assert entry["example"]
        assert entry["benchmark"]
