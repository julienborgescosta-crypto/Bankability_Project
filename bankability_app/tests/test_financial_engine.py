import numpy_financial as npf
import pytest

from core import financial_engine


def test_annuity_payment_matches_formula():
    # 500 k€ @ 5% sur 2 ans : formule standard verifiee hors code.
    expected = 500.0 * 0.05 / (1 - (1.05) ** -2)
    assert financial_engine.annuity_payment(500.0, 0.05, 2) == pytest.approx(expected)


def test_annuity_payment_zero_rate_is_straight_line():
    assert financial_engine.annuity_payment(600.0, 0.0, 3) == pytest.approx(200.0)


def test_annuity_payment_no_principal_or_no_tenor_is_zero():
    assert financial_engine.annuity_payment(0.0, 0.05, 5) == 0.0
    assert financial_engine.annuity_payment(500.0, 0.05, 0) == 0.0


def test_compute_results_yearly_breakdown(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    expected_ds = 500.0 * 0.05 / (1 - 1.05**-2)

    construction, year1, year2 = result.yearly

    # Annee de construction : equity finance 100% du CAPEX (gearing 50% -> equity_share = -500),
    # pas de DSCR.
    assert construction.capex_keur == pytest.approx(-1000.0)
    assert construction.dscr is None
    assert construction.equity_cashflow_keur == pytest.approx(-500.0)

    # Annees d'exploitation : CFADS = 500 - 100 - 20 = 380, service de la dette identique
    # chaque annee (tenor=2), DSCR = CFADS / service.
    for year_result in (year1, year2):
        assert year_result.cfads_keur == pytest.approx(380.0)
        assert year_result.debt_service_keur == pytest.approx(expected_ds)
        assert year_result.dscr == pytest.approx(380.0 / expected_ds)
        assert year_result.equity_cashflow_keur == pytest.approx(380.0 - expected_ds)


def test_compute_results_aggregates(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    expected_ds = 500.0 * 0.05 / (1 - 1.05**-2)

    assert result.capex_total_keur == pytest.approx(1000.0)
    assert result.debt_amount_keur == pytest.approx(500.0)
    assert result.equity_amount_keur == pytest.approx(500.0)
    assert result.debt_service_keur == pytest.approx(expected_ds)
    assert result.dscr_min == pytest.approx(380.0 / expected_ds)
    assert result.dscr_avg == pytest.approx(380.0 / expected_ds)


def test_compute_results_irr_matches_hand_derived_cashflows(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    expected_ds = 500.0 * 0.05 / (1 - 1.05**-2)

    expected_project_irr = npf.irr([-1000.0, 380.0, 380.0])
    expected_equity_irr = npf.irr([-500.0, 380.0 - expected_ds, 380.0 - expected_ds])

    assert result.project_irr == pytest.approx(expected_project_irr)
    assert result.equity_irr == pytest.approx(expected_equity_irr)


def test_npv_uses_wacc_and_undiscounted_year_zero(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    expected_npv = npf.npv(simple_inputs.wacc, [-1000.0, 380.0, 380.0])
    assert result.npv_keur == pytest.approx(expected_npv)


def test_multipliers_move_results_in_expected_direction(simple_inputs):
    base = financial_engine.compute_results(simple_inputs)
    higher_revenue = financial_engine.compute_results(simple_inputs, revenue_multiplier=1.2)
    higher_capex = financial_engine.compute_results(simple_inputs, capex_multiplier=1.2)
    higher_opex = financial_engine.compute_results(simple_inputs, opex_multiplier=1.2)

    assert higher_revenue.project_irr > base.project_irr
    assert higher_capex.project_irr < base.project_irr
    assert higher_opex.project_irr < base.project_irr


def test_interest_rate_adj_increases_debt_service(simple_inputs):
    base = financial_engine.compute_results(simple_inputs)
    stressed = financial_engine.compute_results(simple_inputs, interest_rate_adj=0.05)
    assert stressed.debt_service_keur > base.debt_service_keur
    assert stressed.dscr_min < base.dscr_min


def test_degradation_multipliers_reduce_revenue_and_dscr(simple_inputs):
    base = financial_engine.compute_results(simple_inputs)
    degraded = financial_engine.compute_results(
        simple_inputs, degradation_multipliers=[1.0, 0.5, 0.5]
    )
    assert degraded.yearly[1].revenue_keur == pytest.approx(base.yearly[1].revenue_keur * 0.5)
    assert degraded.dscr_min < base.dscr_min


def test_ramp_up_year_without_capex_or_revenue_has_no_debt_service(ramp_up_inputs):
    """Regression : une annee sans CAPEX mais aussi sans revenu (ramp-up avant la
    vraie mise en service) ne doit pas etre comptee comme une annee d'exploitation -
    sinon le DSCR de cette annee devient absurdement negatif (CFADS negatif / service
    de dette positif)."""
    result = financial_engine.compute_results(ramp_up_inputs)
    construction, ramp_up, op_year1, op_year2 = result.yearly

    assert ramp_up.capex_keur == 0.0
    assert ramp_up.revenue_keur == 0.0
    assert ramp_up.cfads_keur == pytest.approx(-10.0)
    assert ramp_up.debt_service_keur == 0.0
    assert ramp_up.dscr is None
    # Le CFADS negatif de l'annee de ramp-up est absorbe par l'equity, pas par la dette.
    assert ramp_up.equity_cashflow_keur == pytest.approx(-10.0)

    # Le service de la dette ne demarre qu'a la 1ere vraie annee d'exploitation.
    assert op_year1.debt_service_keur > 0
    assert op_year1.dscr is not None
    assert op_year1.dscr > 0


def test_equity_irr_is_none_without_equity(simple_inputs):
    result = financial_engine.compute_results(simple_inputs, gearing_pct=1.0)
    assert result.equity_amount_keur == pytest.approx(0.0)
    assert result.equity_irr is None
