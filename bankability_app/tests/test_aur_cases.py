import json

import openpyxl
import pytest

from core import aur_cases, financial_engine


def test_load_au_store_finds_22_configs(au_store):
    # 18 standard + 4 ORO (limitation non-firm 3000h/an) - voir docs/specs/aur_cases.md.
    assert len(au_store.configs) == 22


def test_config_by_drop_key_matches_expected_austore_key(au_store):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    assert config.austore_key == "2h HTA"
    assert config.duree_h == 2
    assert config.tension == "HTA"
    assert config.turpe_type == "Classique"
    assert config.gabarit is False
    assert config.oro is False
    assert config.valide_cod is None


def test_two_standard_configs_and_two_oro_configs_are_cod2030_only(au_store):
    cod2030_only = [c for c in au_store.configs if c.valide_cod is not None]
    assert {c.drop_key for c in cod2030_only} == {
        "4h HTB2 Injection g1 (COD2030)",
        "4h HTB2 Soutirage g1 (COD2030)",
        "4h HTB2 Injection ORO (COD2030)",
        "4h HTB2 Soutirage ORO (COD2030)",
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


def test_config_by_attributes_oro_true_returns_distinct_config_from_oro_false(au_store):
    """Sans le parametre oro, les 2 configs partageraient exactement le meme
    (duree_h, tension, turpe_type, gabarit) - bug signale par l'utilisateur,
    2026-09-23 : les cas ORO du databook Aurora etaient ecartes en silence a
    l'extraction (meme cle que la variante standard)."""
    standard = au_store.config_by_attributes(
        duree_h=2, tension="HTB2", turpe_type="Injection", gabarit=False, oro=False
    )
    oro = au_store.config_by_attributes(
        duree_h=2, tension="HTB2", turpe_type="Injection", gabarit=False, oro=True
    )
    assert standard.austore_key == "2h HTB2 injection"
    assert oro.austore_key == "2h HTB2 injection ORO"
    assert standard.oro is False
    assert oro.oro is True


def test_config_by_attributes_oro_true_raises_when_unmodelled(au_store):
    # HTA n'a jamais ete modelise en ORO par Aurora.
    with pytest.raises(aur_cases.AuroraConfigError):
        au_store.config_by_attributes(
            duree_h=2, tension="HTA", turpe_type="Classique", gabarit=False, oro=True
        )


def test_oro_config_revenue_is_lower_than_standard_due_to_curtailment(au_store):
    standard = au_store.config_by_attributes(
        duree_h=2, tension="HTB2", turpe_type="Injection", gabarit=False, oro=False
    )
    oro = au_store.config_by_attributes(
        duree_h=2, tension="HTB2", turpe_type="Injection", gabarit=False, oro=True
    )
    _, revenue_standard, _ = aur_cases.revenue_and_turpe_series(
        au_store, standard, cod_year=2027, operating_years=3, power_mw=1.0
    )
    _, revenue_oro, _ = aur_cases.revenue_and_turpe_series(
        au_store, oro, cod_year=2027, operating_years=3, power_mw=1.0
    )
    assert all(o < s for o, s in zip(revenue_oro, revenue_standard, strict=True))


def test_pre_degraded_oro_config_skips_degradation_table(au_store):
    """Les 2 configs 4h ORO (COD2030 verrouille) sont deja sourcees depuis la
    trajectoire degradee du databook Aurora (pas de variante "undegraded"
    disponible pour ce COD) - `revenue_and_turpe_series` ne doit pas leur
    reappliquer un 2e facteur de degradation par-dessus (voir
    docs/specs/aur_cases.md)."""
    config = au_store.config_by_drop_key("4h HTB2 Injection ORO (COD2030)")
    assert config.pre_degraded is True
    raw_curve = au_store.raw_by_key[config.austore_key]
    years, revenue, _ = aur_cases.revenue_and_turpe_series(
        au_store, config, cod_year=2030, operating_years=5, power_mw=1.0
    )
    for year, value in zip(years, revenue, strict=True):
        assert value == pytest.approx(raw_curve[year])


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


def test_capex_and_opex_keur_sources_from_icp_library(au_store, copex_library):
    """Depuis 2026-09-24, CAPEX/OPEX viennent en priorite d'ICP
    (`config/copex_icp.xlsx`, mis a jour mensuellement) - Aurora
    `COPEX_library` ne reste que le repli pour Land lease-bibliotheque cote
    OPEX (quand non renseigne) et HTB3 entierement - voir `core/copex_icp.py`.
    Depuis le 2026-10-08, Development/Asset Management/Insurance
    (operation)/Other sont tous ICP, et 'Grid charges'/'Accise' sont remplaces
    par le calcul precis `opex_grid_charges` (voir
    `test_capex_and_opex_keur_grid_charges_replace_aurora_fallback`), donc
    exclus ici du recoupement direct avec `icp_opex_year1_keur`."""
    from core import copex_icp, opex_grid_charges

    icp_library = copex_icp.load_icp_library_cached()
    expected_capex_generic, _ = copex_icp.icp_capex_total_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=1.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    expected_connection, _ = copex_icp.icp_connection_capex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=1.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    expected_opex_generic, _ = copex_icp.icp_opex_year1_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=1.0,
        icp_library=icp_library,
        aurora_library=copex_library,
        capex_total_keur=expected_capex_generic + expected_connection,
    )
    aurora_grid_charges = aur_cases._library_opex_line_keur(
        "Grid charges",
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=1.0,
        copex_library=copex_library,
    )
    aurora_accise = aur_cases._library_opex_line_keur(
        "Accise", tension="HTA", duree_h=2, cod_year=2027, power_mw=1.0, copex_library=copex_library
    )
    precise_grid_charges, _ = opex_grid_charges.grid_charges_opex_keur(
        tension="HTA", duree_h=2, power_mw=1.0, cod_year=2027
    )
    expected_opex = (
        expected_opex_generic - aurora_grid_charges - aurora_accise + precise_grid_charges
    )

    capex, opex = aur_cases.capex_and_opex_keur(
        tension="HTA", duree_h=2, cod_year=2027, power_mw=1.0, copex_library=copex_library
    )
    assert capex == pytest.approx(expected_capex_generic + expected_connection)
    assert opex == pytest.approx(expected_opex)


def test_capex_and_opex_keur_manual_connection_capex(au_store, copex_library):
    library_mode_capex, _ = aur_cases.capex_and_opex_keur(
        tension="HTA", duree_h=2, cod_year=2027, power_mw=1.0, copex_library=copex_library
    )
    manual_capex, _ = aur_cases.capex_and_opex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=1.0,
        copex_library=copex_library,
        connection_capex_mode="manual",
        manual_connection_capex_keur=999.0,
    )
    assert manual_capex != pytest.approx(library_mode_capex)


def test_capex_and_opex_keur_distance_rte_connection_capex(au_store, copex_library):
    """= 4650.7 x distance^0.239 (dev_case._connection_cost_from_distance),
    comme dans le BP Stockage Standalone 160926 - I-Project."""
    capex_without_connection, _ = aur_cases.capex_and_opex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=1.0,
        copex_library=copex_library,
        connection_capex_mode="manual",
        manual_connection_capex_keur=0.0,
    )
    capex_with_distance, _ = aur_cases.capex_and_opex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=1.0,
        copex_library=copex_library,
        connection_capex_mode="distance_rte",
        distance_rte_km=5.0,
    )
    expected_connection_cost = 4650.7 * 5.0**0.239
    assert capex_with_distance == pytest.approx(
        capex_without_connection + expected_connection_cost, abs=0.05
    )


def test_capex_and_opex_keur_land_lease_opex_replaces_aurora_estimate(au_store, copex_library):
    """Corrige le 2026-10-01 (retour utilisateur) : un loyer manuel REMPLACE
    l'estimation generique Aurora 'Land lease' (deja incluse dans l'OPEX par
    defaut) - il ne s'y ajoute plus (un projet ne paie pas 2 loyers fonciers
    empiles). Teste a power_mw=1.0 pour que le resultat soit directement
    comparable au loyer manuel saisi (lui non escalade par MW)."""
    _, opex_without = aur_cases.capex_and_opex_keur(
        tension="HTA", duree_h=2, cod_year=2027, power_mw=1.0, copex_library=copex_library
    )
    _, opex_with = aur_cases.capex_and_opex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=1.0,
        copex_library=copex_library,
        land_lease_opex_keur=20.0,
    )
    key = aur_cases.voltage_duration_key("HTA", 2)
    aurora_land_lease = aur_cases.escalated_unit_cost(
        copex_library.opex_unit_costs[key]["Land lease"],
        copex_library.opex_escalation.get("Land lease", {}),
        2027,
    )
    assert opex_with == pytest.approx(opex_without - aurora_land_lease + 20.0)
    # Sans override, l'estimation Aurora reste utilisee telle quelle (comportement inchange).
    assert opex_without > 0.0


def test_build_project_inputs_land_lease_indexation_escalates_rent_only(au_store, copex_library):
    """Demande de l'utilisateur, 2026-10-07 : loyer indexe au taux choisi a partir
    de l'op-year 2 (loyer_N = loyer_1 x (1 + taux)^(N-1)), le reste de l'OPEX
    reste plat."""
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    kwargs = {"cod_year": 2027, "power_mw": 10.0, "operating_years": 10}
    flat = aur_cases.build_project_inputs(
        au_store, config, copex_library, land_lease_opex_keur=200.0, **kwargs
    )
    indexed = aur_cases.build_project_inputs(
        au_store,
        config,
        copex_library,
        land_lease_opex_keur=200.0,
        land_lease_indexation_pct=0.02,
        **kwargs,
    )
    assert indexed.opex_keur[0] == 0.0
    assert indexed.opex_year1_keur == pytest.approx(flat.opex_year1_keur)
    for op_year in range(1, 11):
        expected_extra_rent = 200.0 * (1.02 ** (op_year - 1) - 1)
        assert indexed.opex_keur[op_year] == pytest.approx(
            flat.opex_keur[op_year] - expected_extra_rent
        )
    assert indexed.capex_keur == pytest.approx(flat.capex_keur)
    assert indexed.revenues_keur == pytest.approx(flat.revenues_keur)
    assert indexed.net_cashflow_keur[-1] < flat.net_cashflow_keur[-1]


def test_build_project_inputs_land_lease_indexation_applies_to_library_estimate(
    au_store, copex_library
):
    """Sans loyer manuel, l'indexation porte sur la ligne 'Land lease' generique
    de la bibliotheque - c'est elle le loyer du projet."""
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    kwargs = {"cod_year": 2027, "power_mw": 10.0, "operating_years": 10}
    flat = aur_cases.build_project_inputs(au_store, config, copex_library, **kwargs)
    indexed = aur_cases.build_project_inputs(
        au_store, config, copex_library, land_lease_indexation_pct=0.03, **kwargs
    )
    key = aur_cases.voltage_duration_key("HTA", 2)
    library_rent = (
        aur_cases.escalated_unit_cost(
            copex_library.opex_unit_costs[key]["Land lease"],
            copex_library.opex_escalation.get("Land lease", {}),
            2027,
        )
        * 10.0
    )
    assert library_rent > 0.0
    assert indexed.opex_keur[10] == pytest.approx(flat.opex_keur[10] - library_rent * (1.03**9 - 1))


def test_build_project_inputs_zero_land_lease_indexation_keeps_flat_opex(au_store, copex_library):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store,
        config,
        copex_library,
        cod_year=2027,
        power_mw=10.0,
        operating_years=10,
        land_lease_opex_keur=200.0,
    )
    assert inputs.opex_keur[1:] == [-inputs.opex_year1_keur] * 10


def test_capex_and_opex_keur_raises_for_tension_missing_from_copex_library(au_store, copex_library):
    """HTB3 existe dans AU_Store (2h/4h HTB3 Classique g0) mais pas dans
    COPEX_library (seules HTA/HTB1/HTB2 y sont) - doit lever, jamais retourner
    silencieusement 0 (voir docs/adr/... / brief section 7)."""
    with pytest.raises(aur_cases.AuroraConfigError):
        aur_cases.capex_and_opex_keur(
            tension="HTB3", duree_h=2, cod_year=2027, power_mw=1.0, copex_library=copex_library
        )


def test_end_of_life_value_keur_aurora_only_matches_pdf_formula(au_store, copex_library):
    """PDF Aurora Q2 2026 : "the end-of-life value is made up of 5% of the
    battery system, inverter and balance of system costs, as well as 100% of
    the grid connection, while development and soft costs are considered
    sunk costs" - verifie directement contre les couts unitaires Aurora pour
    une tension/duree donnee (mode 'aurora', pas de dependance ICP)."""
    power_mw = 10.0
    key = aur_cases.voltage_duration_key("HTA", 2)
    unit_costs = copex_library.capex_unit_costs[key]
    expected = power_mw * (
        0.05
        * (unit_costs["Battery system"] + unit_costs["Inverter"] + unit_costs["Balance of system"])
        + 1.00 * unit_costs["Grid connection"]
    )
    result = aur_cases.end_of_life_value_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2026,  # annee de reference COPEX_library, pas d'escalade a appliquer
        power_mw=power_mw,
        copex_library=copex_library,
        capex_opex_source="aurora",
    )
    assert result == pytest.approx(expected, rel=1e-3)


def test_end_of_life_value_keur_excludes_development(au_store, copex_library):
    """ "development and soft costs are considered sunk costs" - un Development
    tres eleve ne doit avoir aucun effet sur la valeur de fin de vie."""
    baseline = aur_cases.end_of_life_value_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        copex_library=copex_library,
        capex_opex_source="aurora",
    )
    import copy

    inflated = copy.deepcopy(copex_library)
    key = aur_cases.voltage_duration_key("HTA", 2)
    inflated.capex_unit_costs[key]["Development"] *= 100
    inflated_result = aur_cases.end_of_life_value_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        copex_library=inflated,
        capex_opex_source="aurora",
    )
    assert inflated_result == pytest.approx(baseline)


def test_end_of_life_value_keur_manual_connection_uses_actual_value(au_store, copex_library):
    """100% du raccordement REELLEMENT applique au projet (manuel ici), pas
    l'estimation bibliotheque Aurora - meme convention que `capex_and_opex_keur`."""
    library_mode = aur_cases.end_of_life_value_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        copex_library=copex_library,
        connection_capex_mode="library",
    )
    manual_mode = aur_cases.end_of_life_value_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        copex_library=copex_library,
        connection_capex_mode="manual",
        manual_connection_capex_keur=999.0,
    )
    library_connection_keur, _ = aur_cases.copex_icp.icp_connection_capex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=aur_cases.copex_icp.load_icp_library_cached(),
        aurora_library=copex_library,
    )
    # Le delta entre les 2 modes doit etre exactement la difference de raccordement
    # (100% credite, EOL_GRID_CONNECTION_PCT=1.00) - la base equipement (5%) est identique.
    assert manual_mode - library_mode == pytest.approx(999.0 - library_connection_keur)


def test_build_project_inputs_credits_end_of_life_value_at_final_year_only(au_store, copex_library):
    """Retour utilisateur, 2026-10-01 : la valeur de fin de vie (non modelisee
    jusqu'ici, `end_of_life_keur` toujours a 0 - voir README "Limites
    connues") doit creditee au DERNIER op-year seulement, jamais ailleurs.
    Valorisee aux prix de cette derniere annee (2027 + 15 - 1 = 2041), pas de la
    COD - definition Aurora, "% of the CAPEX value in the last year of operation"
    (corrige le 2026-10-02)."""
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=10.0, operating_years=15
    )
    assert inputs.years[-1] == 2041
    assert inputs.end_of_life_keur[-1] > 0
    assert all(v == 0.0 for v in inputs.end_of_life_keur[:-1])
    expected = aur_cases.end_of_life_value_keur(
        tension="HTA", duree_h=2, cod_year=2041, power_mw=10.0, copex_library=copex_library
    )
    assert inputs.end_of_life_keur[-1] == pytest.approx(expected)


def test_repowering_capex_keur_uses_icp_battery_pcs_formula(copex_library):
    """Depuis 2026-09-24, le repowering suit ICP (Batteries and PCS,
    power-law) par coherence avec le CAPEX initial, plutot que le figer sur
    Aurora `Battery system + Inverter` - voir `core/copex_icp.py`."""
    from core import copex_icp

    icp_library = copex_icp.load_icp_library_cached()
    expected = copex_icp.icp_battery_pcs_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=1.0, cod_year=2041
    )
    result = aur_cases.repowering_capex_keur(
        tension="HTA", duree_h=2, repowering_year=2041, power_mw=1.0, copex_library=copex_library
    )
    assert result == pytest.approx(expected)


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


def test_capex_and_opex_keur_aurora_only_matches_copex_comparison_totals(au_store, copex_library):
    """`capex_and_opex_keur_aurora_only` doit reproduire exactement les
    totaux Aurora deja calcules par `copex_comparison.compare_capex_opex`
    (meme formule, juste restitue en (capex, opex) directement utilisable
    par `build_project_inputs`) - option "Use Aurora's own CAPEX/OPEX
    assumptions" du Configurateur, demande de l'utilisateur, 2026-10-01."""
    from core import copex_comparison, copex_icp

    icp_library = copex_icp.load_icp_library_cached()
    comparison = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=1.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    expected_capex = next(r.aurora_keur for r in comparison.capex_rows if r.label == "TOTAL CAPEX")
    expected_opex = next(r.aurora_keur for r in comparison.opex_rows if r.label == "TOTAL OPEX")

    capex, opex = aur_cases.capex_and_opex_keur_aurora_only(
        tension="HTA", duree_h=2, cod_year=2027, power_mw=1.0, copex_library=copex_library
    )
    assert capex == pytest.approx(expected_capex)
    assert opex == pytest.approx(expected_opex)


def test_capex_and_opex_keur_aurora_only_differs_from_icp(au_store, copex_library):
    capex_icp, opex_icp = aur_cases.capex_and_opex_keur(
        tension="HTB2", duree_h=4, cod_year=2030, power_mw=10.0, copex_library=copex_library
    )
    capex_aurora, opex_aurora = aur_cases.capex_and_opex_keur_aurora_only(
        tension="HTB2", duree_h=4, cod_year=2030, power_mw=10.0, copex_library=copex_library
    )
    assert capex_aurora != pytest.approx(capex_icp)
    assert opex_aurora != pytest.approx(opex_icp)


def test_repowering_capex_keur_aurora_only_uses_battery_system_only(copex_library):
    """Definition Aurora (databook Q2 2026, onglet Inputs) : "Repowering cost =
    battery system cost" - l'onduleur n'est PAS remplace, a la difference de
    notre mode ICP (Battery + Inverter, confirme par l'utilisateur 2026-09-18)."""
    assert aur_cases.AURORA_REPOWERING_CAPEX_LINE_ITEMS == ["Battery system"]
    expected = aur_cases.escalated_unit_cost(
        copex_library.capex_unit_costs["4h - HTA"]["Battery system"],
        copex_library.capex_escalation.get("Battery system", {}),
        2041,
    )
    result = aur_cases.repowering_capex_keur_aurora_only(
        tension="HTA", duree_h=4, repowering_year=2041, power_mw=1.0, copex_library=copex_library
    )
    assert result == pytest.approx(expected)


def test_build_project_inputs_aurora_source_uses_pure_q2_2026_capex_priced_at_cod_minus_1(
    au_store, copex_library
):
    """Mode "couts Aurora" : databook Q2 2026 pur (jamais fusionne avec le
    fixture), CAPEX valorise l'annee avant la COD et OPEX a l'annee d'entree -
    convention Aurora, "for a battery entering the market in 2027, the 2026 CAPEX
    value is used" (decision de l'utilisateur, 2026-10-02)."""
    from core.dev_case import load_copex_library_q2_2026_cached

    q2_library = load_copex_library_q2_2026_cached()
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store,
        config,
        copex_library,
        cod_year=2030,
        power_mw=10.0,
        operating_years=20,
        capex_opex_source="aurora",
    )
    expected_capex, _ = aur_cases.capex_and_opex_keur_aurora_only(
        tension="HTA", duree_h=2, cod_year=2029, power_mw=10.0, copex_library=q2_library
    )
    _, expected_opex = aur_cases.capex_and_opex_keur_aurora_only(
        tension="HTA", duree_h=2, cod_year=2030, power_mw=10.0, copex_library=q2_library
    )
    assert inputs.capex_initial_keur == pytest.approx(expected_capex)
    assert inputs.opex_year1_keur == pytest.approx(expected_opex)
    expected_repowering = aur_cases.repowering_capex_keur_aurora_only(
        tension="HTA", duree_h=2, repowering_year=2044, power_mw=10.0, copex_library=q2_library
    )
    assert inputs.capex_repowering_keur == pytest.approx(expected_repowering)


def test_q2_2026_copex_library_escalation_extends_past_2035():
    """Le databook Aurora Q2 2026 couvre l'escalade jusqu'en 2060 : la plafonner
    a 2035 (ancienne extraction) surestimait le cout d'un repowering ~2045-2050
    et la valeur de fin de vie (retour utilisateur, 2026-10-02)."""
    from core.dev_case import load_copex_library_q2_2026_cached

    q2_library = load_copex_library_q2_2026_cached()
    battery_2035 = aur_cases.escalated_unit_cost(
        q2_library.capex_unit_costs["2h - HTA"]["Battery system"],
        q2_library.capex_escalation["Battery system"],
        2035,
    )
    battery_2050 = aur_cases.escalated_unit_cost(
        q2_library.capex_unit_costs["2h - HTA"]["Battery system"],
        q2_library.capex_escalation["Battery system"],
        2050,
    )
    assert battery_2050 < battery_2035
    assert max(int(y) for y in q2_library.capex_escalation["Battery system"]) >= 2050


def test_build_project_inputs_capex_opex_source_aurora_differs_from_icp(au_store, copex_library):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs_icp = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=10.0, operating_years=20
    )
    inputs_aurora = aur_cases.build_project_inputs(
        au_store,
        config,
        copex_library,
        cod_year=2027,
        power_mw=10.0,
        operating_years=20,
        capex_opex_source="aurora",
    )
    assert inputs_aurora.capex_initial_keur != pytest.approx(inputs_icp.capex_initial_keur)


def test_build_project_inputs_rejects_unknown_capex_opex_source(au_store, copex_library):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    with pytest.raises(aur_cases.AuroraConfigError):
        aur_cases.build_project_inputs(
            au_store,
            config,
            copex_library,
            cod_year=2027,
            power_mw=10.0,
            operating_years=20,
            capex_opex_source="bogus",
        )


def test_build_project_inputs_turpe_50pct_reduction_halves_turpe_series(au_store, copex_library):
    """Abattement TURPE 50% (code de l'energie, annexe art. D.341-9) - demande
    de l'utilisateur, 2026-10-01, voir docs/specs/turpe_50pct_reduction.md."""
    config = au_store.config_by_drop_key("2h HTB2 Classique g0")
    baseline = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=10.0, operating_years=10
    )
    reduced = aur_cases.build_project_inputs(
        au_store,
        config,
        copex_library,
        cod_year=2027,
        power_mw=10.0,
        operating_years=10,
        turpe_50pct_reduction=True,
    )
    assert reduced.turpe_keur == pytest.approx([t * 0.5 for t in baseline.turpe_keur])
    assert reduced.revenues_keur == pytest.approx(baseline.revenues_keur)


def test_build_project_inputs_turpe_50pct_reduction_also_halves_grid_charges_opex(
    au_store, copex_library
):
    """Extension du 2026-10-01 (meme jour, retour utilisateur) : l'abattement
    doit aussi reduire la part FIXE du TURPE (poste OPEX 'Grid charges', +
    CTA), pas seulement le TURPE variable cote revenu - la reglementation
    (annexe art. D.341-9) reduit la "part acheminement" dans son ensemble.
    Pas de double-compte : 'Grid charges' (fixe) et le TURPE AU_Store
    (variable, cote revenu) sont 2 composantes distinctes et non chevauchantes
    (voir docs/specs/copex_comparison.md, "Mise en garde TURPE")."""
    config = au_store.config_by_drop_key("2h HTB2 Classique g0")
    baseline = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=10.0, operating_years=10
    )
    reduced = aur_cases.build_project_inputs(
        au_store,
        config,
        copex_library,
        cod_year=2027,
        power_mw=10.0,
        operating_years=10,
        turpe_50pct_reduction=True,
    )
    from core import copex_icp, opex_grid_charges

    terms = opex_grid_charges.grid_charges_terms_cached()
    icp_escalation = copex_icp.load_icp_library_cached().escalation
    precise_turpe_power = opex_grid_charges.turpe_power_keur(
        tension="HTB2", power_mw=10.0, cod_year=2027, terms=terms, icp_escalation=icp_escalation
    )
    precise_cta = opex_grid_charges.cta_keur(
        tension="HTB2", turpe_power_value_keur=precise_turpe_power, terms=terms
    )
    assert baseline.opex_year1_keur - reduced.opex_year1_keur == pytest.approx(
        (precise_turpe_power + precise_cta) * 0.5
    )
    # Le reste de l'OPEX (O&M, Insurance, Land lease, Accise, Other) est inchange.
    assert reduced.opex_year1_keur > 0.0


def test_capex_and_opex_keur_aurora_only_turpe_50pct_reduction_also_halves_grid_charges(
    au_store, copex_library
):
    """Meme garantie que ci-dessus, mais sur capex_and_opex_keur_aurora_only
    (capex_opex_source='aurora') - les 2 chemins doivent se comporter pareil."""
    _, opex_without = aur_cases.capex_and_opex_keur_aurora_only(
        tension="HTB2", duree_h=2, cod_year=2027, power_mw=10.0, copex_library=copex_library
    )
    _, opex_with = aur_cases.capex_and_opex_keur_aurora_only(
        tension="HTB2",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        copex_library=copex_library,
        turpe_50pct_reduction=True,
    )
    key = aur_cases.voltage_duration_key("HTB2", 2)
    aurora_grid_charges = (
        aur_cases.escalated_unit_cost(
            copex_library.opex_unit_costs[key]["Grid charges"],
            copex_library.opex_escalation.get("Grid charges", {}),
            2027,
        )
        * 10.0
    )
    assert opex_without - opex_with == pytest.approx(aurora_grid_charges * 0.5)


def test_build_project_inputs_turpe_50pct_reduction_rejects_tension_below_50kv(
    au_store, copex_library
):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    with pytest.raises(aur_cases.AuroraConfigError, match="HTA"):
        aur_cases.build_project_inputs(
            au_store,
            config,
            copex_library,
            cod_year=2027,
            power_mw=10.0,
            operating_years=10,
            turpe_50pct_reduction=True,
        )


def test_build_project_inputs_pays_repowering_capex_the_year_before_op_year_15(
    au_store, copex_library
):
    """Repowering (reset de degradation) a l'op-year 15 -> CAPEX paye l'op-year
    14 (index 14), comme le CAPEX initial est paye l'annee avant la COD -
    convention Aurora, appliquee aussi au mode ICP (retour utilisateur,
    2026-10-02). Value aux prix de l'annee de mise en service (2027 + 15 - 1)."""
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=10.0, operating_years=20
    )
    assert inputs.capex_keur[14] < 0
    assert inputs.capex_keur[15] == 0.0
    assert inputs.capex_repowering_keur == pytest.approx(-inputs.capex_keur[14])
    assert inputs.repowering_op_year == 15
    expected = aur_cases.repowering_capex_keur(
        tension="HTA", duree_h=2, repowering_year=2041, power_mw=10.0, copex_library=copex_library
    )
    assert inputs.capex_repowering_keur == pytest.approx(expected)


def test_build_project_inputs_degrades_turpe_with_mean_year_soh(au_store, copex_library):
    """Le TURPE variable (proportionnel aux volumes soutires/injectes) decroit
    avec la retention d'energie, comme le revenu - Aurora applique le SoH moyen
    de l'annee ((SoH debut + SoH fin) / 2) a ses "network charges" (databook Q2
    2026, Case 40 : ratio 0.98 a l'op1, 0.87 a l'op6). Il restait fige a la
    courbe brute jusqu'au 2026-10-02 (~1.5 pt de TRI sur un 4h HTA 30 ans)."""
    from core import soh_degradation

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
    soh_curve = soh_degradation.load_soh_curves_cached()[2]
    turpe_curve = au_store.turpe_by_key[config.austore_key]
    for op_year in (1, 6, 12):
        mean_soh = (
            soh_degradation.soh_at_op_year(soh_curve, op_year - 1)
            + soh_degradation.soh_at_op_year(soh_curve, op_year)
        ) / 2
        assert inputs.turpe_keur[op_year] == pytest.approx(
            turpe_curve[2027 + op_year - 1] * mean_soh * 10.0
        )
    assert abs(inputs.turpe_keur[12]) < abs(inputs.turpe_keur[1])


def test_build_project_inputs_resets_turpe_degradation_at_repowering(au_store, copex_library):
    from core import soh_degradation

    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store,
        config,
        copex_library,
        cod_year=2027,
        power_mw=10.0,
        operating_years=20,
        repowering_op_year_override=12,
    )
    soh_curve = soh_degradation.load_soh_curves_cached()[2]
    mean_soh_new_battery = (
        soh_degradation.soh_at_op_year(soh_curve, 0) + soh_degradation.soh_at_op_year(soh_curve, 1)
    ) / 2
    turpe_curve = au_store.turpe_by_key[config.austore_key]
    assert inputs.turpe_keur[12] == pytest.approx(
        turpe_curve[2027 + 12 - 1] * mean_soh_new_battery * 10.0
    )


def test_build_project_inputs_repowering_op_year_override_moves_capex_and_reset(
    au_store, copex_library
):
    """Demande de l'utilisateur, 2026-09-24 : l'annee de repowering doit
    pouvoir etre choisie plutot que subie figee a 15 - la sortie CAPEX ET le
    reset de degradation suivent l'override."""
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store,
        config,
        copex_library,
        cod_year=2027,
        power_mw=10.0,
        operating_years=20,
        repowering_op_year_override=10,
    )
    assert inputs.repowering_op_year == 10
    assert inputs.capex_keur[9] < 0  # paye l'annee avant la mise en service
    assert inputs.capex_keur[14] == 0.0  # plus de sortie a l'ancien op-year par defaut
    # Le revenu de l'op-year 10 (annee du repowering) doit refleter un reset
    # (deg factor = op1) plutot que la poursuite de la decroissance brute.
    raw_curve = au_store.raw_by_key[config.austore_key]
    assert inputs.revenues_keur[10] == pytest.approx(
        raw_curve[2027 + 10 - 1] * au_store.degradation_no_repo[1] * 10.0
    )


def test_build_project_inputs_repowering_op_year_override_skipped_if_beyond_operating_years(
    au_store, copex_library
):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store,
        config,
        copex_library,
        cod_year=2027,
        power_mw=10.0,
        operating_years=12,
        repowering_op_year_override=15,
    )
    assert all(c == 0.0 for c in inputs.capex_keur[1:])
    assert inputs.capex_repowering_keur == 0.0
    assert inputs.repowering_op_year is None


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
    # 40 MW (pas 1 MW) : depuis la correction du bug d'unite ICP du 2026-09-24
    # (voir docs/specs/copex_icp.md "Bugs corriges"), l'OPEX de garanties est
    # ~1000x plus eleve qu'avant - a 1 MW il domine un revenu HTA trop petit et
    # le cashflow ne redevient jamais positif (IRR non definie, cf. _safe_irr).
    # 40 MW reste dans la plage economiquement viable, ce que ce test verifie
    # (input bien forme + consommable par le moteur financier), pas 1 MW.
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=40.0, operating_years=20
    )
    assert inputs.years[0] == 2026  # annee de construction = COD - 1
    assert len(inputs.years) == 21
    assert inputs.capex_keur[0] < 0
    # Repowering a l'op-year 15 (with_repowering=True par defaut, operating_years=20
    # >= repowering_op_year=15), paye l'annee d'avant (index 14) - toutes les
    # autres annees restent a 0.
    assert inputs.capex_keur[14] < 0
    assert all(c == 0.0 for i, c in enumerate(inputs.capex_keur[1:], start=1) if i != 14)
    assert inputs.capex_repowering_keur > 0.0

    result = financial_engine.compute_results(inputs, gearing_pct=0.0)
    assert result.project_irr is not None


# --- load_aurora_curves (asset statique config/aurora_curves_22configs.json) ---
# Les courbes sont universelles (memes valeurs pour tout projet, verifiees a la
# decimale contre le databook Aurora Q2 2026 brut) - voir docs/specs/aur_cases.md.
# Regression demandee par l'utilisateur (2026-09-24) suite au diagnostic de
# l'ecart TURPE/RAW du fixture legacy Belle Epine (une seule courbe HTB2 codee
# en dur appliquee a tout, quelle que soit la tension reelle du projet).


def test_load_aurora_curves_matches_json_source_to_the_decimal():
    with open(aur_cases.DEFAULT_AURORA_CURVES_PATH, encoding="utf-8") as handle:
        reference = json.load(handle)
    library = aur_cases.load_aurora_curves()

    for drop_key in ["2h HTB1 Classique g0", "2h HTB2 Classique g0", "2h HTB2 Injection ORO"]:
        entry = next(c for c in reference["configs"] if c["drop_key"] == drop_key)
        au_key = entry["au_key"]
        for year_str, expected_raw in entry["raw"].items():
            assert library.raw_by_key[au_key][int(year_str)] == pytest.approx(expected_raw)
        for year_str, expected_turpe in entry["turpe_curve"].items():
            assert library.turpe_by_key[au_key][int(year_str)] == pytest.approx(expected_turpe)


def test_load_aurora_curves_routes_by_real_tension():
    """Le legacy (fixture Belle Epine) appliquait une seule courbe HTB2 codee
    en dur quelle que soit la tension reelle du projet - ici, chaque config
    doit tirer sa propre courbe (RAW different pour HTA/HTB1/HTB2/HTB3)."""
    library = aur_cases.load_aurora_curves()
    raw_2027_by_tension = {}
    for drop_key in [
        "2h HTA Classique g0",
        "2h HTB1 Classique g0",
        "2h HTB2 Classique g0",
        "2h HTB3 Classique g0",
    ]:
        config = library.config_by_drop_key(drop_key)
        raw_2027_by_tension[config.tension] = library.raw_by_key[config.austore_key][2027]
    assert len(set(raw_2027_by_tension.values())) == 4
    assert raw_2027_by_tension["HTB1"] == pytest.approx(211.89)
    assert raw_2027_by_tension["HTB2"] == pytest.approx(212.46)


def test_load_aurora_curves_has_22_configs_and_degradation_table():
    library = aur_cases.load_aurora_curves()
    assert len(library.configs) == 22
    assert library.repowering_op_year == 15
    assert library.eol_per_kw == pytest.approx(118.44)
    assert library.degradation[1] == pytest.approx(0.9942)
    assert library.degradation[15] == pytest.approx(library.degradation[1])  # reset repowering


def test_load_aurora_curves_uses_a_2h_specific_revenue_degradation():
    """Backtest du 2026-10-02 contre la Summary table Aurora : la table
    `DegFactor_noRepo` est celle des 4h ; l'appliquer aux 2h (qui cyclent 1,5 fois
    par jour) surestimait leur revenu d'environ +0,5 pt de TRI. Les 2h ont leur
    propre table (config/aurora_degradation_and_cm.json), les 4h gardent l'ancienne."""
    library = aur_cases.load_aurora_curves()
    table_2h = library.degradation_no_repo_for(2)
    assert library.degradation_no_repo_for(4) is library.degradation_no_repo
    assert set(table_2h) == set(library.degradation_no_repo)
    assert table_2h[1] == pytest.approx(0.9932, abs=1e-4)
    assert table_2h[10] < library.degradation_no_repo[10] - 0.015
    assert all(table_2h[op] > table_2h[op + 1] for op in range(1, 30))


def test_revenue_series_applies_the_duration_specific_degradation(copex_library):
    library = aur_cases.load_aurora_curves()
    config = library.config_by_drop_key("2h HTB2 Classique g0")
    _, revenue, _ = aur_cases.revenue_and_turpe_series(
        library, config, cod_year=2027, operating_years=12, power_mw=1.0, with_repowering=False
    )
    raw = library.raw_by_key[config.austore_key]
    assert revenue[9] == pytest.approx(raw[2036] * library.degradation_no_repo_for(2)[10])


def test_capacity_mechanism_is_excluded_from_the_trading_fee_base():
    """Aurora : frais de trading = 7,5 % x (energie + services systeme + network
    charges), hors mecanisme de capacite (decision de l'utilisateur, 2026-10-02)."""
    terms = aur_cases.AggregatorFeeTerms(
        rate_before_threshold=0.0, rate_after_threshold=-0.075, yearly_threshold_keur_per_mw=0.0
    )
    with_cm = aur_cases.aggregator_fee_series([100.0], [-10.0], power_mw=1.0, terms=terms)
    without_cm = aur_cases.aggregator_fee_series(
        [100.0], [-10.0], power_mw=1.0, terms=terms, excluded_keur=[6.0]
    )
    assert with_cm[0] == pytest.approx(-0.075 * 90.0)
    assert without_cm[0] == pytest.approx(-0.075 * 84.0)


def test_capacity_mechanism_series_depends_only_on_duration_and_year():
    library = aur_cases.load_aurora_curves()
    cm_2h = aur_cases.capacity_mechanism_series(library, 2, [2027, 2038, 2040], power_mw=10.0)
    cm_4h = aur_cases.capacity_mechanism_series(library, 4, [2027, 2038, 2040], power_mw=10.0)
    assert cm_2h[0] == pytest.approx(69.79715)
    assert cm_4h[0] > cm_2h[0]
    assert cm_2h[1] < cm_2h[0]  # creux du mecanisme de capacite 2038-2041 chez Aurora
    assert aur_cases.capacity_mechanism_series(library, 6, [2027], power_mw=10.0) == [0.0]


def test_load_aurora_curves_raises_on_unmodelled_combo():
    """Garde-fou explicite - jamais un revenu nul silencieux (voir README
    'zero zero silencieux')."""
    library = aur_cases.load_aurora_curves()
    with pytest.raises(aur_cases.AuroraConfigError):
        library.config_by_attributes(
            duree_h=2, tension="HTB1", turpe_type="Injection", gabarit=False
        )


def test_load_aurora_curves_produces_valid_engine_input(copex_library):
    library = aur_cases.load_aurora_curves()
    config = library.config_by_drop_key("2h HTB1 Classique g0")
    inputs = aur_cases.build_project_inputs(
        library, config, copex_library, cod_year=2027, power_mw=10.0, operating_years=20
    )
    result = financial_engine.compute_results(inputs, gearing_pct=0.0)
    assert result.project_irr is not None


# --- load_au_store : robustesse de localisation du bloc TURPE ---
# Signale par l'utilisateur (2026-09-24) : le BP 160926 (post ajout des configs
# ORO) empile le bloc TURPE sous le bloc RAW (son propre bloc 'Year'), au lieu
# de le mettre a cote sur la meme ligne d'entete comme la mise en page
# historique - le parseur doit localiser par libelle, pas par decalage fixe,
# et gerer les deux mises en page.

_METADATA_HEADER = [
    "DropKey",
    "AUStoreKey",
    "Duree",
    "Tension",
    "TURPE",
    "Gabarit",
    "ValideCOD",
]


def _au_store_header_row(raw_labels: list[str]) -> list:
    return (
        ["Year", *raw_labels, None]
        + _METADATA_HEADER
        + [None, "OpYear", "DegFactor", "DegFactor_noRepo", None, "RepowOpYear", 15]
    )


def _au_store_data_row(year: int, raw_values: list[float], *, drop_key, op_year, deg) -> list:
    return (
        [year, *raw_values, None, drop_key, drop_key.split()[0] + " " + drop_key.split()[1]]
        + ["2h", "HTA" if "HTA" in drop_key else "HTB1", "Classique", 0, None]
        + [None, op_year, deg, deg]
    )


def test_load_au_store_finds_turpe_block_stacked_below_raw(tmp_path):
    raw_labels = ["2h HTA", "2h HTB1"]
    path = tmp_path / "stacked_turpe_au_store.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = aur_cases.AU_STORE_SHEET
    ws.append(_au_store_header_row(raw_labels))
    ws.append(
        _au_store_data_row(
            2027, [100.0, 200.0], drop_key="2h HTA Classique g0", op_year=1, deg=0.99
        )
        + [None, "EoL_perkW", 50.0]
    )
    ws.append(
        _au_store_data_row(
            2028, [90.0, 190.0], drop_key="2h HTB1 Classique g0", op_year=2, deg=0.98
        )
    )
    ws.append([])  # ligne vide entre le bloc RAW et le bloc TURPE empile
    ws.append(["Year", *raw_labels])
    ws.append([2027, -5.0, -8.0])
    ws.append([2028, -4.5, -7.5])
    wb.save(path)

    library = aur_cases.load_au_store(path)
    assert library.turpe_by_key["2h HTA"][2027] == pytest.approx(-5.0)
    assert library.turpe_by_key["2h HTA"][2028] == pytest.approx(-4.5)
    assert library.turpe_by_key["2h HTB1"][2027] == pytest.approx(-8.0)
    assert library.turpe_by_key["2h HTB1"][2028] == pytest.approx(-7.5)
    # le bloc RAW, lui, n'a pas bouge.
    assert library.raw_by_key["2h HTA"][2027] == pytest.approx(100.0)


def test_load_au_store_raises_explicit_error_if_turpe_block_missing_entirely(tmp_path):
    """Ni a cote sur la meme ligne d'entete, ni empile dessous -> erreur
    explicite, jamais un TURPE a 0 silencieux."""
    raw_labels = ["2h HTA", "2h HTB1"]
    path = tmp_path / "no_turpe_au_store.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = aur_cases.AU_STORE_SHEET
    ws.append(_au_store_header_row(raw_labels))
    ws.append(
        _au_store_data_row(
            2027, [100.0, 200.0], drop_key="2h HTA Classique g0", op_year=1, deg=0.99
        )
        + [None, "EoL_perkW", 50.0]
    )
    ws.append(
        _au_store_data_row(
            2028, [90.0, 190.0], drop_key="2h HTB1 Classique g0", op_year=2, deg=0.98
        )
    )
    wb.save(path)

    with pytest.raises(aur_cases.AuroraConfigError, match="TURPE block not found"):
        aur_cases.load_au_store(path)
