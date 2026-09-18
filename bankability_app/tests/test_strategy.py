import numpy_financial as npf
import pytest

from core import financial_engine, strategy


def test_hold_and_operate_is_a_plain_passthrough(simple_inputs):
    result = strategy.compute_hold_and_operate(
        simple_inputs,
        financing_kwargs={"gearing_pct": 0.5, "interest_rate": 0.05, "debt_tenor_years": 2},
    )
    expected = financial_engine.compute_results(
        simple_inputs, gearing_pct=0.5, interest_rate=0.05, debt_tenor_years=2
    )
    assert result.project_irr == pytest.approx(expected.project_irr)
    assert result.equity_irr == pytest.approx(expected.equity_irr)


def test_dev_and_sell_net_margin_is_tsp_minus_devex(simple_inputs):
    result = strategy.compute_dev_and_sell(
        simple_inputs,
        dsa_keur=100.0,
        buyer_target_equity_irr=0.12,
        devex_keur=150.0,
        financing_kwargs={"gearing_pct": 0.5, "interest_rate": 0.05, "debt_tenor_years": 2},
    )
    assert result.devex_keur == pytest.approx(150.0)
    assert result.net_margin_keur == pytest.approx(result.tsp_keur - 150.0)


def test_dev_and_sell_defaults_devex_to_zero(simple_inputs):
    result = strategy.compute_dev_and_sell(
        simple_inputs,
        dsa_keur=100.0,
        buyer_target_equity_irr=0.12,
        financing_kwargs={"gearing_pct": 0.5, "interest_rate": 0.05, "debt_tenor_years": 2},
    )
    assert result.devex_keur == 0.0
    assert result.net_margin_keur == pytest.approx(result.tsp_keur)


def test_dev_and_sell_tsp_is_dsa_plus_spa(simple_inputs):
    result = strategy.compute_dev_and_sell(
        simple_inputs,
        dsa_keur=100.0,
        buyer_target_equity_irr=0.12,
        financing_kwargs={"gearing_pct": 0.5, "interest_rate": 0.05, "debt_tenor_years": 2},
    )
    assert result.tsp_keur == pytest.approx(result.dsa_keur + result.spa_keur)
    assert result.dsa_keur == pytest.approx(100.0)


def test_dev_and_sell_dsa_joins_gearable_capex_base(simple_inputs):
    result = strategy.compute_dev_and_sell(
        simple_inputs,
        dsa_keur=100.0,
        buyer_target_equity_irr=0.12,
        financing_kwargs={"gearing_pct": 0.5, "interest_rate": 0.05, "debt_tenor_years": 2},
    )
    # CAPEX total (1000 + 100 DSA) x 50% gearing = 550 de dette.
    assert result.result_at_dsa_only.capex_total_keur == pytest.approx(1100.0)
    assert result.result_at_dsa_only.debt_amount_keur == pytest.approx(550.0)


def test_dev_and_sell_spa_brings_actual_equity_irr_exactly_to_target(simple_inputs):
    """Verification de bout en bout du mecanisme SPA (docs/adr/0004) : si on
    soustrait le SPA calcule du cashflow equity de l'annee 0 (en plus du DSA deja
    inclus), le TRI equity reellement realise doit tomber exactement sur le TRI
    cible de l'acheteur - c'est la definition meme du SPA, pas une coincidence
    numerique."""
    target_irr = 0.12
    result = strategy.compute_dev_and_sell(
        simple_inputs,
        dsa_keur=100.0,
        buyer_target_equity_irr=target_irr,
        financing_kwargs={"gearing_pct": 0.5, "interest_rate": 0.05, "debt_tenor_years": 2},
    )
    equity_series = [y.equity_cashflow_keur for y in result.result_at_dsa_only.yearly]
    equity_series_with_spa = list(equity_series)
    equity_series_with_spa[0] -= result.spa_keur
    realized_irr = npf.irr(equity_series_with_spa)
    assert realized_irr == pytest.approx(target_irr, abs=1e-4)


def test_dev_and_sell_spa_can_be_negative_without_forcing_tsp_negative(simple_inputs):
    """Un DSA trop eleve pour la rentabilite du projet donne un SPA negatif (le
    prix doit etre rabaisse pour tenir le TRI cible) - TSP peut rester positif
    tant que le DSA compense (voir CONTEXT.md "SPA")."""
    result = strategy.compute_dev_and_sell(
        simple_inputs,
        dsa_keur=5000.0,  # tres eleve vs un projet a 1000 keur de CAPEX de base
        buyer_target_equity_irr=0.30,  # cible tres exigeante
        financing_kwargs={"gearing_pct": 0.5, "interest_rate": 0.05, "debt_tenor_years": 2},
    )
    assert result.spa_keur < 0
    assert result.tsp_keur == pytest.approx(result.dsa_keur + result.spa_keur)


def test_dev_and_sell_raises_without_any_capex_outflow():
    from core.models import ProjectInputs

    inputs = ProjectInputs(
        name="x",
        location="",
        segment="HTA",
        cod="2027-01-01",
        operating_years=1,
        usable_power_mw=1,
        usable_energy_mwh=1,
        capex_initial_keur=0.0,
        capex_repowering_keur=0.0,
        repowering=False,
        opex_year1_keur=0.0,
        opex_adjustment_keur=0.0,
        turpe_fixed_eur_per_kw=0.0,
        years=[2027],
        capex_keur=[0.0],
        opex_keur=[0.0],
        end_of_life_keur=[0.0],
        revenues_keur=[100.0],
        turpe_keur=[0.0],
        net_cashflow_keur=[100.0],
    )
    with pytest.raises(ValueError):
        strategy.compute_dev_and_sell(inputs, dsa_keur=10.0, buyer_target_equity_irr=0.10)


def test_cod_resale_value_matches_present_value_of_post_cod_cfads(simple_inputs):
    value = strategy.compute_cod_resale_value_keur(simple_inputs, resale_target_irr=0.10)
    expected = financial_engine.present_value([380.0, 380.0], 0.10)
    assert value == pytest.approx(expected)


def test_build_and_flip_net_return_is_internally_consistent(simple_inputs):
    result = strategy.compute_build_and_flip(
        simple_inputs,
        dsa_keur=100.0,
        buyer_target_equity_irr_at_rtb=0.12,
        resale_target_irr=0.10,
        carry_months=18,
        carry_rate=0.08,
        financing_kwargs={"gearing_pct": 0.5, "interest_rate": 0.05, "debt_tenor_years": 2},
    )
    assert result.net_return_keur == pytest.approx(
        result.resale_value_cod_keur
        - result.rtb_price_keur
        - result.construction_capex_keur
        - result.carry_cost_keur
    )
    assert result.carry_cost_keur > 0.0
    assert result.construction_capex_keur == pytest.approx(simple_inputs.capex_initial_keur)
