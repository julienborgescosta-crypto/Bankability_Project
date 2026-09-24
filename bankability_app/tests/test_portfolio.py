import pytest

from core import contract_overlay, portfolio


def _config(**overrides) -> portfolio.ProjectConfig:
    defaults = {
        "name": "Test HTA",
        "duree_h": 2,
        "tension": "HTA",
        "turpe_type": "Classique",
        "gabarit": False,
        "cod_year": 2027,
        "power_mw": 10.0,
        "operating_years": 10,
    }
    defaults.update(overrides)
    return portfolio.ProjectConfig(**defaults)


def test_build_project_inputs_full_merchant_has_no_secured_revenue(
    au_store, copex_library, default_financing_terms
):
    config = _config()
    inputs, secured_revenue, _ = portfolio.build_project_inputs(
        config, au_store, copex_library, default_financing_terms
    )
    assert secured_revenue == [0.0] * config.operating_years
    assert len(inputs.years) == config.operating_years + 1


def test_build_project_inputs_tolling_secures_revenue_during_duration(
    au_store, copex_library, default_financing_terms
):
    config = _config(
        contract_structure=contract_overlay.ContractStructure(
            kind=contract_overlay.TOLLING, price_keur_per_mw_per_year=80.0, duration_years=5
        )
    )
    inputs, secured_revenue, _ = portfolio.build_project_inputs(
        config, au_store, copex_library, default_financing_terms
    )
    assert secured_revenue[:5] == pytest.approx([800.0] * 5)  # 80 keur/MW x 10 MW
    assert secured_revenue[5:] == pytest.approx([0.0] * (config.operating_years - 5))
    # pendant la tolling, le revenu operationnel = prix fixe (10 MW x 80) - aucun frais
    # d'agregateur (merchant_revenue = 0 pendant cette periode, voir docs/adr/0005).
    assert inputs.revenues_keur[1:6] == pytest.approx([800.0] * 5)


def test_build_project_inputs_extrapolates_unmodelled_combo(
    au_store, copex_library, default_financing_terms
):
    """HTB1 n'a que Classique dans AU_Store - depuis le 2026-09-24 ceci est
    extrapole (core.config_extrapolation), plus une erreur bloquante."""
    config = _config(tension="HTB1", turpe_type="Injection")
    inputs, _, resolved = portfolio.build_project_inputs(
        config, au_store, copex_library, default_financing_terms
    )
    assert resolved.config.extrapolated is True
    assert inputs.revenues_keur[1] > 0.0


def test_build_project_inputs_raises_for_gabarit_with_classique(
    au_store, copex_library, default_financing_terms
):
    """Combinaison sans equivalent business (pas juste une donnee manquante) -
    reste bloquante meme apres l'introduction de l'extrapolation."""
    from core.aur_cases import AuroraConfigError

    config = _config(tension="HTA", turpe_type="Classique", gabarit=True)
    with pytest.raises(AuroraConfigError):
        portfolio.build_project_inputs(config, au_store, copex_library, default_financing_terms)


def test_run_portfolio_full_merchant_uses_merchant_dscr_and_maturity(
    au_store, copex_library, default_financing_terms
):
    rows = portfolio.run_portfolio([_config()], au_store, copex_library, default_financing_terms)
    row = rows[0]
    assert row.target_dscr_used == pytest.approx(default_financing_terms["target_dscr_merchant"])
    assert row.debt_tenor_years == default_financing_terms["maturity_full_merchant_years"]
    assert row.gearing_used_pct == pytest.approx(0.70)


def test_run_portfolio_tolling_uses_secured_dscr_and_ppa_plus_3_maturity(
    au_store, copex_library, default_financing_terms
):
    # duration_years == operating_years : 100% du revenu de la fenetre est
    # securise, le blend retombe donc exactement sur target_dscr_secured.
    tolling_duration_years = 10
    config = _config(
        operating_years=tolling_duration_years,
        contract_structure=contract_overlay.ContractStructure(
            kind=contract_overlay.TOLLING,
            price_keur_per_mw_per_year=80.0,
            duration_years=tolling_duration_years,
        ),
    )
    rows = portfolio.run_portfolio([config], au_store, copex_library, default_financing_terms)
    row = rows[0]
    assert row.target_dscr_used == pytest.approx(default_financing_terms["target_dscr_secured"])
    expected_maturity = (
        tolling_duration_years + default_financing_terms["maturity_years_added_after_ppa"]
    )
    assert row.debt_tenor_years == expected_maturity


def test_run_portfolio_dsa_defaults_to_margin_plus_devex(
    au_store, copex_library, default_financing_terms
):
    """Sans override, le DSA doit suivre marge de dev cible (par duree) x MW +
    DEVEX (par tension) - pas retomber silencieusement a 0 (bug signale par
    l'utilisateur le 2026-09-18), et pas un taux plat independant du DEVEX
    (corrige le meme jour suite a un 2e retour) - voir
    aur_cases.dsa_default_keur."""
    rows = portfolio.run_portfolio(
        [_config(power_mw=20.0)], au_store, copex_library, default_financing_terms
    )
    expected = (
        default_financing_terms["target_margin_keur_per_mw_2h"] * 20.0
        + default_financing_terms["devex_flat_keur_hta"]
    )
    assert rows[0].dsa_keur == pytest.approx(expected)
    assert rows[0].dsa_keur > 0.0


def test_run_portfolio_dsa_default_uses_4h_margin_rate(
    au_store, copex_library, default_financing_terms
):
    rows = portfolio.run_portfolio(
        [_config(duree_h=4, tension="HTB2", power_mw=10.0)],
        au_store,
        copex_library,
        default_financing_terms,
    )
    expected = (
        default_financing_terms["target_margin_keur_per_mw_4h"] * 10.0
        + default_financing_terms["devex_flat_keur_htb"]
    )
    assert rows[0].dsa_keur == pytest.approx(expected)


def test_run_portfolio_dsa_default_respects_devex_override(
    au_store, copex_library, default_financing_terms
):
    """Un DEVEX override pour ce projet doit se repercuter sur le DSA par
    defaut (pas silencieusement recalculer le DEVEX standard) - sinon
    marge nette = TSP - DEVEX ne retomberait plus sur la marge cible quand
    SPA = 0, meme avec un DEVEX personnalise."""
    rows = portfolio.run_portfolio(
        [_config(power_mw=10.0, devex_keur_override=999.0)],
        au_store,
        copex_library,
        default_financing_terms,
    )
    expected = default_financing_terms["target_margin_keur_per_mw_2h"] * 10.0 + 999.0
    assert rows[0].dsa_keur == pytest.approx(expected)


def test_run_portfolio_dsa_override(au_store, copex_library, default_financing_terms):
    rows = portfolio.run_portfolio(
        [_config(dsa_keur_override=42.0)], au_store, copex_library, default_financing_terms
    )
    assert rows[0].dsa_keur == pytest.approx(42.0)


def test_run_portfolio_reports_devex_by_tension(au_store, copex_library, default_financing_terms):
    rows = portfolio.run_portfolio(
        [_config(tension="HTA"), _config(name="Test HTB2", tension="HTB2")],
        au_store,
        copex_library,
        default_financing_terms,
    )
    assert rows[0].devex_keur == pytest.approx(default_financing_terms["devex_flat_keur_hta"])
    assert rows[1].devex_keur == pytest.approx(default_financing_terms["devex_flat_keur_htb"])


def test_run_portfolio_devex_override(au_store, copex_library, default_financing_terms):
    rows = portfolio.run_portfolio(
        [_config(devex_keur_override=999.0)], au_store, copex_library, default_financing_terms
    )
    assert rows[0].devex_keur == pytest.approx(999.0)


def test_run_portfolio_net_margin_is_tsp_minus_devex(
    au_store, copex_library, default_financing_terms
):
    rows = portfolio.run_portfolio([_config()], au_store, copex_library, default_financing_terms)
    row = rows[0]
    assert row.net_margin_keur == pytest.approx(row.tsp_keur - row.devex_keur)


def test_run_portfolio_produces_one_row_per_config(
    au_store, copex_library, default_financing_terms
):
    rows = portfolio.run_portfolio(
        [_config(), _config(name="Second", tension="HTB2")],
        au_store,
        copex_library,
        default_financing_terms,
    )
    assert len(rows) == 2
    assert {r.name for r in rows} == {"Test HTA", "Second"}


def test_build_project_inputs_connection_capex_manual_overrides_library(
    au_store, copex_library, default_financing_terms
):
    config = _config()
    baseline, _, _ = portfolio.build_project_inputs(
        config, au_store, copex_library, default_financing_terms
    )
    manual, _, _ = portfolio.build_project_inputs(
        _config(connection_capex_mode="manual", manual_connection_capex_keur=500.0),
        au_store,
        copex_library,
        default_financing_terms,
    )
    assert manual.capex_initial_keur != pytest.approx(baseline.capex_initial_keur)
    # OPEX non touche par le mode de CAPEX raccordement.
    assert manual.opex_keur[1] == pytest.approx(baseline.opex_keur[1])


def test_build_project_inputs_connection_capex_distance_rte_matches_formula(
    au_store, copex_library, default_financing_terms
):
    """= 4650.7 x distance^0.239 (dev_case._connection_cost_from_distance),
    comme dans le BP Stockage Standalone 160926 - I-Project."""
    config = _config(connection_capex_mode="distance_rte", distance_rte_km=5.0)
    with_distance, _, _ = portfolio.build_project_inputs(
        config, au_store, copex_library, default_financing_terms
    )
    without_connection, _, _ = portfolio.build_project_inputs(
        _config(connection_capex_mode="manual", manual_connection_capex_keur=0.0),
        au_store,
        copex_library,
        default_financing_terms,
    )
    expected_connection_cost = 4650.7 * 5.0**0.239
    assert with_distance.capex_initial_keur == pytest.approx(
        without_connection.capex_initial_keur + expected_connection_cost, abs=0.05
    )


def test_build_project_inputs_land_lease_opex_is_additive(
    au_store, copex_library, default_financing_terms
):
    config = _config()
    baseline, _, _ = portfolio.build_project_inputs(
        config, au_store, copex_library, default_financing_terms
    )
    with_land_lease, _, _ = portfolio.build_project_inputs(
        _config(land_lease_opex_keur=20.0), au_store, copex_library, default_financing_terms
    )
    assert with_land_lease.opex_year1_keur == pytest.approx(baseline.opex_year1_keur + 20.0)
    assert with_land_lease.opex_keur[1] == pytest.approx(baseline.opex_keur[1] - 20.0)
    # CAPEX non touche par le loyer foncier.
    assert with_land_lease.capex_keur[0] == pytest.approx(baseline.capex_keur[0])


def test_run_portfolio_connection_capex_mode_defaults_to_library(
    au_store, copex_library, default_financing_terms
):
    """Sans override, le mode par defaut ('library') doit redonner exactement
    le meme CAPEX qu'avant l'introduction de ces leviers (non-regression)."""
    rows = portfolio.run_portfolio([_config()], au_store, copex_library, default_financing_terms)
    inputs, _, _ = portfolio.build_project_inputs(
        _config(), au_store, copex_library, default_financing_terms
    )
    assert rows[0].capex_total_keur == pytest.approx(inputs.capex_initial_keur)


def test_run_portfolio_build_and_flip_net_return_is_internally_consistent(
    au_store, copex_library, default_financing_terms
):
    rows = portfolio.run_portfolio([_config()], au_store, copex_library, default_financing_terms)
    row = rows[0]
    assert row.build_and_flip_net_return_keur == pytest.approx(
        row.resale_value_cod_keur
        - row.tsp_keur
        - row.capex_total_keur
        - row.build_and_flip_carry_cost_keur
    )
    assert row.build_and_flip_carry_cost_keur > 0.0


def test_run_portfolio_carry_overrides(au_store, copex_library, default_financing_terms):
    rows_default = portfolio.run_portfolio(
        [_config()], au_store, copex_library, default_financing_terms
    )
    rows_override = portfolio.run_portfolio(
        [_config(carry_months_override=36, carry_rate_override=0.20)],
        au_store,
        copex_library,
        default_financing_terms,
    )
    assert (
        rows_override[0].build_and_flip_carry_cost_keur
        > rows_default[0].build_and_flip_carry_cost_keur
    )


def test_run_portfolio_defaults_financing_terms_when_not_given(au_store, copex_library):
    rows = portfolio.run_portfolio([_config()], au_store, copex_library)
    assert len(rows) == 1
    assert rows[0].project_irr is not None


def test_run_portfolio_oro_requested_and_real_lowers_revenue(
    au_store, copex_library, default_financing_terms
):
    config = _config(tension="HTB2", turpe_type="Injection", oro_requested=True)
    rows_oro = portfolio.run_portfolio([config], au_store, copex_library, default_financing_terms)
    rows_standard = portfolio.run_portfolio(
        [_config(tension="HTB2", turpe_type="Injection")],
        au_store,
        copex_library,
        default_financing_terms,
    )
    assert rows_oro[0].oro_requested is True
    assert rows_oro[0].extrapolated is False
    assert rows_oro[0].revenue_total_keur < rows_standard[0].revenue_total_keur


def test_run_portfolio_oro_requested_but_unmodelled_is_extrapolated_not_dropped(
    au_store, copex_library, default_financing_terms
):
    """HTA n'a jamais ete modelise en ORO par Aurora - depuis le 2026-09-24, ça
    ne retombe plus silencieusement sur la courbe standard : c'est extrapole
    (jamais un revenu nul ni un repli invisible, voir
    docs/specs/config_extrapolation.md)."""
    config = _config(tension="HTA", turpe_type="Injection", oro_requested=True)
    rows_oro = portfolio.run_portfolio([config], au_store, copex_library, default_financing_terms)
    rows_standard = portfolio.run_portfolio(
        [_config(tension="HTA", turpe_type="Injection")],
        au_store,
        copex_library,
        default_financing_terms,
    )
    assert rows_oro[0].oro_requested is True
    assert rows_oro[0].extrapolated is True
    assert rows_oro[0].extrapolation_notes
    assert rows_oro[0].revenue_total_keur < rows_standard[0].revenue_total_keur


def test_run_portfolio_oro_with_classique_raises(au_store, copex_library, default_financing_terms):
    """ORO n'a de sens que pour Injection/Soutirage - pas juste une donnee
    manquante, une combinaison sans equivalent business."""
    from core.aur_cases import AuroraConfigError

    config = _config(tension="HTA", turpe_type="Classique", oro_requested=True)
    with pytest.raises(AuroraConfigError):
        portfolio.run_portfolio([config], au_store, copex_library, default_financing_terms)


def test_build_project_inputs_pre_degraded_4h_oro_config_matches_databook_directly(
    au_store, copex_library, default_financing_terms
):
    config = _config(
        duree_h=4,
        tension="HTB2",
        turpe_type="Injection",
        cod_year=2030,
        operating_years=5,
        oro_requested=True,
    )
    inputs, _, resolved = portfolio.build_project_inputs(
        config, au_store, copex_library, default_financing_terms
    )
    assert resolved.config.extrapolated is False
    assert resolved.config.pre_degraded is True


def test_run_portfolio_missing_combo_is_extrapolated_not_raised(
    au_store, copex_library, default_financing_terms
):
    """HTB1 n'a que Classique dans AU_Store - avant le 2026-09-24 ceci levait
    AuroraConfigError, desormais c'est extrapole (voir
    docs/specs/config_extrapolation.md)."""
    config = _config(tension="HTB1", turpe_type="Injection")
    rows = portfolio.run_portfolio([config], au_store, copex_library, default_financing_terms)
    assert rows[0].extrapolated is True
    assert rows[0].extrapolation_notes


def test_run_portfolio_custom_curtailment_hours(au_store, copex_library, default_financing_terms):
    config = _config(
        tension="HTB2", turpe_type="Injection", oro_requested=True, curtailment_hours=1000
    )
    rows_1000 = portfolio.run_portfolio([config], au_store, copex_library, default_financing_terms)
    rows_3000 = portfolio.run_portfolio(
        [_config(tension="HTB2", turpe_type="Injection", oro_requested=True)],
        au_store,
        copex_library,
        default_financing_terms,
    )
    assert rows_1000[0].extrapolated is True
    assert rows_3000[0].extrapolated is False
    assert rows_1000[0].revenue_total_keur > rows_3000[0].revenue_total_keur
