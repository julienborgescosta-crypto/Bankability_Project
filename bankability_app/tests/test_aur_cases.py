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
    `COPEX_library` ne reste que le repli pour les postes qu'ICP ne couvre pas
    (Development cote CAPEX ; Insurance/Grid charges/Land lease-bibliotheque/
    Accise/Other cote OPEX) - voir `core/copex_icp.py`."""
    from core import copex_icp

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
    expected_opex, _ = copex_icp.icp_opex_year1_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=1.0,
        icp_library=icp_library,
        aurora_library=copex_library,
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


def test_capex_and_opex_keur_land_lease_opex_is_additive(au_store, copex_library):
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
    assert opex_with == pytest.approx(opex_without + 20.0)


def test_capex_and_opex_keur_raises_for_tension_missing_from_copex_library(au_store, copex_library):
    """HTB3 existe dans AU_Store (2h/4h HTB3 Classique g0) mais pas dans
    COPEX_library (seules HTA/HTB1/HTB2 y sont) - doit lever, jamais retourner
    silencieusement 0 (voir docs/adr/... / brief section 7)."""
    with pytest.raises(aur_cases.AuroraConfigError):
        aur_cases.capex_and_opex_keur(
            tension="HTB3", duree_h=2, cod_year=2027, power_mw=1.0, copex_library=copex_library
        )


def test_repowering_capex_keur_uses_icp_battery_pcs_formula(copex_library):
    """Depuis 2026-09-24, le repowering suit ICP (Batteries and PCS,
    power-law) par coherence avec le CAPEX initial, plutot que le figer sur
    Aurora `Battery system + Inverter` - voir `core/copex_icp.py`."""
    from core import copex_icp

    icp_library = copex_icp.load_icp_library_cached()
    expected = copex_icp.icp_battery_pcs_keur(icp_library, duree_h=2, power_mw=1.0, cod_year=2041)
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


def test_build_project_inputs_adds_repowering_capex_at_op_year_15(au_store, copex_library):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    inputs = aur_cases.build_project_inputs(
        au_store, config, copex_library, cod_year=2027, power_mw=10.0, operating_years=20
    )
    assert inputs.capex_keur[15] < 0
    assert inputs.capex_repowering_keur == pytest.approx(-inputs.capex_keur[15])
    assert inputs.repowering_op_year == 15


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
    assert inputs.capex_keur[10] < 0
    assert inputs.capex_keur[15] == 0.0  # plus de sortie a l'ancien op-year par defaut
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
    # op-year 15 (index 15) porte la sortie de repowering (with_repowering=True
    # par defaut, operating_years=20 >= repowering_op_year=15) - toutes les
    # autres annees restent a 0.
    assert inputs.capex_keur[15] < 0
    assert all(c == 0.0 for i, c in enumerate(inputs.capex_keur[1:], start=1) if i != 15)
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
