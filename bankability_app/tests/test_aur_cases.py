import pytest

from core import aur_cases, financial_engine


def test_load_au_store_finds_18_configs(au_store):
    assert len(au_store.configs) == 18


def test_config_by_drop_key_matches_expected_austore_key(au_store):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    assert config.austore_key == "2h HTA"
    assert config.duree_h == 2
    assert config.tension == "HTA"
    assert config.turpe_type == "Classique"
    assert config.gabarit is False
    assert config.valide_cod is None


def test_two_configs_are_cod2030_only(au_store):
    cod2030_only = [c for c in au_store.configs if c.valide_cod is not None]
    assert {c.drop_key for c in cod2030_only} == {
        "4h HTB2 Injection g1 (COD2030)",
        "4h HTB2 Soutirage g1 (COD2030)",
    }
    assert all(c.valide_cod == 2030 for c in cod2030_only)


def test_config_by_attributes_raises_on_unmodelled_combo(au_store):
    # HTB1 n'a que "Classique g0" (2h et 4h) dans AU_Store - pas de variante Injection.
    with pytest.raises(aur_cases.AuroraConfigError):
        au_store.config_by_attributes(
            duree_h=2, tension="HTB1", turpe_type="Injection", gabarit=False
        )


def test_revenue_and_turpe_series_is_cod_independent_curve(au_store):
    """Meme config lue a partir de 2 COD differents : les valeurs de l'annee
    civile commune doivent etre identiques (avant application de la
    degradation, qui depend de l'op-year - donc on compare l'op-year 1 de
    chaque run, qui tombe sur une annee civile differente a chaque fois, et on
    verifie a la place que la valeur brute de la courbe pour une annee civile
    commune aux deux runs est bien la meme avant degradation)."""
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    years_a, revenue_a, _ = aur_cases.revenue_and_turpe_series(
        au_store, config, cod_year=2027, operating_years=5, power_mw=1.0
    )
    years_b, revenue_b, _ = aur_cases.revenue_and_turpe_series(
        au_store, config, cod_year=2028, operating_years=5, power_mw=1.0
    )
    # 2028 est l'annee civile commune : op-year 2 du run COD2027, op-year 1 du run COD2028.
    raw_curve = au_store.raw_by_key[config.austore_key]
    assert revenue_a[1] == pytest.approx(raw_curve[2028] * au_store.degradation[2])
    assert revenue_b[0] == pytest.approx(raw_curve[2028] * au_store.degradation[1])
    assert years_a[1] == years_b[0] == 2028


def test_revenue_and_turpe_series_rejects_cod2030_only_config_at_other_cod(au_store):
    config = au_store.config_by_drop_key("4h HTB2 Injection g1 (COD2030)")
    with pytest.raises(aur_cases.AuroraConfigError):
        aur_cases.revenue_and_turpe_series(
            au_store, config, cod_year=2027, operating_years=5, power_mw=1.0
        )
    # COD=2030 doit passer sans lever.
    aur_cases.revenue_and_turpe_series(
        au_store, config, cod_year=2030, operating_years=5, power_mw=1.0
    )


def test_revenue_and_turpe_series_rejects_op_year_beyond_calendar_range(au_store):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    with pytest.raises(aur_cases.AuroraConfigError):
        aur_cases.revenue_and_turpe_series(
            au_store, config, cod_year=2050, operating_years=20, power_mw=1.0
        )


def test_degradation_resets_at_op_year_15_with_repowering(au_store):
    assert au_store.degradation[15] == pytest.approx(au_store.degradation[1])
    assert au_store.degradation_no_repo[15] < au_store.degradation_no_repo[14]


def test_repowering_scalars(au_store):
    assert au_store.repowering_op_year == 15
    assert au_store.eol_per_kw == pytest.approx(118.44)


def test_aggregator_fee_series_is_tiered_not_flat():
    terms = aur_cases.AggregatorFeeTerms(
        rate_before_threshold=0.0,
        rate_after_threshold=-0.075,
        yearly_threshold_keur_per_mw=100.0,
        net_of_turpe=True,
    )
    # power_mw=1 -> seuil = 100 keur ; revenu net de TURPE = 100 + (-20) = 80 (< seuil) -> pas de frais.
    fees_below = aur_cases.aggregator_fee_series([100.0], [-20.0], power_mw=1.0, terms=terms)
    assert fees_below == pytest.approx([0.0])
    # revenu net de TURPE = 200 - 20 = 180 (> seuil 100) -> frais sur les 80 au-dela du seuil.
    fees_above = aur_cases.aggregator_fee_series([200.0], [-20.0], power_mw=1.0, terms=terms)
    assert fees_above == pytest.approx([-0.075 * 80.0])


def test_load_financing_terms_defaults():
    terms = aur_cases.load_financing_terms()
    assert terms["target_dscr_secured"] == pytest.approx(1.20)
    assert terms["target_dscr_merchant"] == pytest.approx(1.40)
    fee_terms = aur_cases.aggregator_fee_terms_from_config(terms)
    assert fee_terms.rate_after_threshold == pytest.approx(-0.075)


def test_devex_keur_for_tension():
    terms = aur_cases.load_financing_terms()
    assert aur_cases.devex_keur_for_tension("HTA", terms) == pytest.approx(150.0)
    assert aur_cases.devex_keur_for_tension("HTB2", terms) == pytest.approx(300.0)
    assert aur_cases.devex_keur_for_tension("HTB1", terms) == pytest.approx(300.0)


def test_dsa_default_keur_is_target_margin_plus_devex():
    terms = aur_cases.load_financing_terms()
    result = aur_cases.dsa_default_keur(duree_h=2, power_mw=10.0, devex_keur=150.0, terms=terms)
    # marge cible 2h = 50 k€/MW x 10 MW + DEVEX 150 k€ = 650 k€.
    assert result == pytest.approx(650.0)


def test_dsa_default_keur_uses_4h_rate():
    terms = aur_cases.load_financing_terms()
    result = aur_cases.dsa_default_keur(duree_h=4, power_mw=10.0, devex_keur=300.0, terms=terms)
    # marge cible 4h = 80 k€/MW x 10 MW + DEVEX 300 k€ = 1100 k€.
    assert result == pytest.approx(1100.0)


def test_dsa_default_keur_raises_for_unsupported_duree_h():
    terms = aur_cases.load_financing_terms()
    with pytest.raises(aur_cases.AuroraConfigError):
        aur_cases.dsa_default_keur(duree_h=6, power_mw=10.0, devex_keur=150.0, terms=terms)


def test_capex_and_opex_keur_matches_copex_library(au_store, copex_library):
    capex, opex = aur_cases.capex_and_opex_keur(
        tension="HTA", duree_h=2, cod_year=2027, power_mw=1.0, copex_library=copex_library
    )
    # Base 2028 (466.76/35.06 EUR/kW), COD 2027 < 2028 -> pas d'escalade (dev_case.escalated_unit_cost).
    assert capex == pytest.approx(466.76, abs=0.05)
    assert opex == pytest.approx(35.06, abs=0.05)


def test_capex_and_opex_keur_raises_for_tension_missing_from_copex_library(au_store, copex_library):
    """HTB3 existe dans AU_Store (2h/4h HTB3 Classique g0) mais pas dans
    COPEX_library (seules HTA/HTB1/HTB2 y sont) - doit lever, jamais retourner
    silencieusement 0 (voir docs/adr/... / brief section 7)."""
    with pytest.raises(aur_cases.AuroraConfigError):
        aur_cases.capex_and_opex_keur(
            tension="HTB3", duree_h=2, cod_year=2027, power_mw=1.0, copex_library=copex_library
        )


def test_repowering_capex_keur_composes_battery_and_inverter(copex_library):
    from core.dev_case import escalated_unit_cost

    expected_per_kw = escalated_unit_cost(
        copex_library.capex_unit_costs["2h - HTA"]["Battery system"],
        copex_library.capex_escalation.get("Battery system", {}),
        2041,
    ) + escalated_unit_cost(
        copex_library.capex_unit_costs["2h - HTA"]["Inverter"],
        copex_library.capex_escalation.get("Inverter", {}),
        2041,
    )
    result = aur_cases.repowering_capex_keur(
        tension="HTA", duree_h=2, repowering_year=2041, power_mw=1.0, copex_library=copex_library
    )
    assert result == pytest.approx(expected_per_kw)


def test_repowering_capex_keur_excludes_other_capex_line_items(copex_library):
    # Battery+Inverter seulement (pas Balance of system/Development/EPC/raccordement)
    # -> strictement moins que le CAPEX initial complet.
    capex, _ = aur_cases.capex_and_opex_keur(
        tension="HTA", duree_h=2, cod_year=2027, power_mw=1.0, copex_library=copex_library
    )
    repowering = aur_cases.repowering_capex_keur(
        tension="HTA", duree_h=2, repowering_year=2028, power_mw=1.0, copex_library=copex_library
    )
    assert 0.0 < repowering < capex


def test_build_project_inputs_adds_repowering_capex_at_op_year_15(au_store, copex_library):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=10.0, operating_years=20
    )
    assert inputs.capex_keur[15] < 0
    assert inputs.capex_repowering_keur == pytest.approx(-inputs.capex_keur[15])


def test_build_project_inputs_skips_repowering_if_operating_years_too_short(
    au_store, copex_library
):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=10.0, operating_years=10
    )
    assert all(c == 0.0 for c in inputs.capex_keur[1:])
    assert inputs.capex_repowering_keur == 0.0


def test_build_project_inputs_skips_repowering_if_with_repowering_false(au_store, copex_library):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store,
        config,
        copex_library,
        cod_year=2027,
        power_mw=10.0,
        operating_years=20,
        with_repowering=False,
    )
    assert all(c == 0.0 for c in inputs.capex_keur[1:])
    assert inputs.capex_repowering_keur == 0.0


def test_build_project_inputs_repowering_triggers_second_debt_tranche(au_store, copex_library):
    """financial_engine detecte deja une 2e tranche de dette a la 2e sortie
    CAPEX de la serie - verifie que le repowering Aurora s'y branche sans
    modification du moteur (README section 5bis)."""
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=10.0, operating_years=20
    )
    result = financial_engine.compute_results(
        inputs,
        gearing_pct=0.5,
        interest_rate=0.05,
        debt_tenor_years=10,
        repowering_gearing_pct=0.5,
        repowering_interest_rate=0.05,
        repowering_debt_tenor_years=5,
    )
    assert result.capex_total_repowering_keur == pytest.approx(inputs.capex_repowering_keur)
    assert result.debt_amount_repowering_keur > 0.0


def test_build_project_inputs_produces_valid_engine_input(au_store, copex_library):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=1.0, operating_years=20
    )
    assert inputs.years[0] == 2026  # annee de construction = COD - 1
    assert len(inputs.years) == 21
    assert inputs.capex_keur[0] < 0
    # op-year 15 (index 15) porte la sortie de repowering (with_repowering=True
    # par defaut, operating_years=20 >= repowering_op_year=15) - toutes les
    # autres annees restent a 0.
    assert inputs.capex_keur[15] < 0
    assert all(c == 0.0 for i, c in enumerate(inputs.capex_keur[1:], start=1) if i != 15)
    assert inputs.capex_repowering_keur > 0.0

    result = financial_engine.compute_results(inputs, gearing_pct=0.0)
    assert result.project_irr is not None
