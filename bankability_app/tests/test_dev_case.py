import pytest

from core import dev_case, financial_engine


@pytest.fixture
def copex_library() -> dev_case.CopexLibrary:
    return dev_case.CopexLibrary(
        capex_unit_costs={
            "2h - HTB1": {
                "Battery system": 100.0,
                "Inverter": 20.0,
                "Balance of system": 15.0,
                "Development": 10.0,
                "Grid connection": 20.0,
                "EPC soft costs": 15.0,
            },
        },
        opex_unit_costs={
            "2h - HTB1": {
                "Fixed O&M": 2.0,
                "Insurance": 1.0,
                "Grid charges": 0.5,
                "Land lease": 0.0,
                "Accise": 0.0,
                "Other": 0.5,
            },
        },
    )


@pytest.fixture
def aurora_library() -> dev_case.AuroraLibrary:
    # "HTB1" (Classique, sans gabarit), duree 2h, revenu constant 50 000 €/an
    # et TURPE constant -5 000 €/an (par MW, avant le /1000 de conversion en
    # k€ - voir _revenue_and_turpe_series), sur 2028-2030. Avec power_mw=10 :
    # revenu = 50 000 x 10 / 1000 = 500 k€/an, TURPE = -50 k€/an.
    combo_2h = {
        2028: {"wholesale_storage_sell_revenue": 50_000.0, "tariff_TURPE 7 revenue": -5_000.0},
        2029: {"wholesale_storage_sell_revenue": 50_000.0, "tariff_TURPE 7 revenue": -5_000.0},
        2030: {"wholesale_storage_sell_revenue": 50_000.0, "tariff_TURPE 7 revenue": -5_000.0},
    }
    return dev_case.AuroraLibrary(combos={"HTB1": {2: combo_2h}})


@pytest.fixture
def base_params() -> dev_case.DevCaseParams:
    return dev_case.DevCaseParams(
        cod_year=2028,
        power_mw=10.0,
        duration_h=2,
        connection_type="TSO 90kV",
        turpe_type="Classique",
        gabarit=False,
        repowering=False,
        operating_years=3,
        connection_capex_mode="library",
        land_lease_opex_keur=5.0,
    )


def test_aurora_combo_key_classique_ignores_gabarit():
    assert dev_case.aurora_combo_key("HTA", "Classique", False) == "HTA"
    assert dev_case.aurora_combo_key("HTA", "Classique", True) == "HTA"


def test_aurora_combo_key_injection_and_soutirage():
    assert dev_case.aurora_combo_key("HTA", "Injection", False) == "HTA injection"
    assert dev_case.aurora_combo_key("HTA", "Injection", True) == "HTA injection gabarit"
    assert dev_case.aurora_combo_key("HTB2", "Soutirage", True) == "HTB2 soutirage gabarit"
    assert dev_case.aurora_combo_key("HTB2", "Soutirage", False) == "HTB2 soutirage"


def test_voltage_class_fixed_mapping():
    assert dev_case.DevCaseParams(2028, 10, 2, "DSO").voltage_class == "HTA"
    assert dev_case.DevCaseParams(2028, 10, 2, "TSO 63kV").voltage_class == "HTB1"
    assert dev_case.DevCaseParams(2028, 10, 2, "TSO 90kV").voltage_class == "HTB1"
    assert dev_case.DevCaseParams(2028, 10, 2, "TSO 225kV").voltage_class == "HTB2"


def test_voltage_class_industrial_requires_override():
    params = dev_case.DevCaseParams(2028, 10, 2, "Industrial-New trench")
    with pytest.raises(ValueError, match="voltage_class_override"):
        _ = params.voltage_class

    params_with_override = dev_case.DevCaseParams(
        2028, 10, 2, "Industrial-New trench", voltage_class_override="HTB2"
    )
    assert params_with_override.voltage_class == "HTB2"


def test_connection_capex_keur_library_mode(base_params, copex_library):
    # Grid connection (20) x power_mw (10) = 200.
    assert dev_case.connection_capex_keur(base_params, copex_library) == pytest.approx(200.0)


def test_connection_capex_keur_manual_mode(base_params, copex_library):
    base_params.connection_capex_mode = "manual"
    base_params.manual_connection_capex_keur = 77.0
    assert dev_case.connection_capex_keur(base_params, copex_library) == pytest.approx(77.0)


def test_connection_capex_keur_distance_rte_formula(base_params, copex_library):
    base_params.connection_capex_mode = "distance_rte"
    base_params.distance_rte_km = 1.0
    # Inputs Dev!D20 : 4650.7 x 1^0.239 = 4650.7
    assert dev_case.connection_capex_keur(base_params, copex_library) == pytest.approx(4650.7)


def test_connection_capex_keur_distance_and_substation_formula(base_params, copex_library):
    base_params.connection_capex_mode = "distance_rte_and_substation"
    base_params.distance_rte_km = 1.0
    base_params.distance_substation_km = 1.0
    # 4650.7 x 1^0.239 + 1257.3 x 1^0.5761 = 4650.7 + 1257.3
    expected = 4650.7 + 1257.3
    assert dev_case.connection_capex_keur(base_params, copex_library) == pytest.approx(expected)


def test_connection_capex_keur_zero_distance_is_zero(base_params, copex_library):
    base_params.connection_capex_mode = "distance_rte"
    base_params.distance_rte_km = 0.0
    assert dev_case.connection_capex_keur(base_params, copex_library) == pytest.approx(0.0)


def test_capex_total_keur_matches_hand_calc(base_params, copex_library):
    # generique = (100+20+15+10+15) x 10 MW = 1600 ; raccordement = 20 x 10 MW
    # = 200 -> total 1800 (pas de marge/assurance - "Total" de la table source
    # est deja une simple somme, voir test unitaire sur le fichier reel).
    assert dev_case.capex_total_keur(base_params, copex_library) == pytest.approx(1800.0)


def test_opex_year1_keur_matches_hand_calc(base_params, copex_library):
    # (2 + 1 + 0.5 + 0 + 0 + 0.5) x 10 MW = 40, + loyer foncier 5 = 45
    assert dev_case.opex_year1_keur(base_params, copex_library) == pytest.approx(45.0)


def testescalated_unit_cost_base_year_and_known_year():
    escalation = {2028: 0.0, 2029: -0.01, 2030: -0.02}
    assert dev_case.escalated_unit_cost(100.0, escalation, 2028) == pytest.approx(100.0)
    assert dev_case.escalated_unit_cost(100.0, escalation, 2029) == pytest.approx(99.0)
    assert dev_case.escalated_unit_cost(100.0, escalation, 2030) == pytest.approx(98.0)


def testescalated_unit_cost_beyond_last_year_clamps(base_params):
    escalation = {2028: 0.0, 2029: -0.01, 2030: -0.02}
    # 2035 est hors table -> plafonne sur le dernier delta connu (2030 : -2%),
    # ne revient pas a 0% au-dela.
    assert dev_case.escalated_unit_cost(100.0, escalation, 2035) == pytest.approx(98.0)


def testescalated_unit_cost_no_escalation_data_is_unchanged():
    assert dev_case.escalated_unit_cost(100.0, {}, 2030) == pytest.approx(100.0)


def test_capex_total_keur_applies_escalation_by_cod_year(base_params, copex_library):
    copex_library.capex_escalation = {
        "Battery system": {2028: 0.0, 2030: -0.10},
        "Grid connection": {2028: 0.0, 2030: 0.0},
    }
    base_params.cod_year = 2030
    # Seule "Battery system" (100 x 10 MW = 1000) est escaladee a -10% -> 900 ;
    # les autres postes generiques (20+15+10+15)x10=600 restent inchanges (pas
    # de delta fourni pour eux -> valeur de base) ; raccordement 200 inchange.
    expected = 900.0 + 600.0 + 200.0
    assert dev_case.capex_total_keur(base_params, copex_library) == pytest.approx(expected)


def test_opex_year1_keur_applies_escalation_by_cod_year(base_params, copex_library):
    copex_library.opex_escalation = {"Fixed O&M": {2028: 0.0, 2030: -0.50}}
    base_params.cod_year = 2030
    # Fixed O&M (2 x 10 MW = 20) escalade a -50% -> 10 ; le reste
    # (1+0.5+0+0+0.5)x10=20 inchange ; + loyer foncier 5 -> 10+20+5=35
    assert dev_case.opex_year1_keur(base_params, copex_library) == pytest.approx(35.0)


def test_build_project_inputs_series_shape(base_params, aurora_library, copex_library):
    inputs = dev_case.build_project_inputs(
        base_params, aurora_library, copex_library, degradation_case=None
    )

    assert inputs.years == [2027, 2028, 2029, 2030]
    assert inputs.capex_keur == pytest.approx([-1800.0, 0.0, 0.0, 0.0])
    assert inputs.opex_keur == pytest.approx([0.0, -45.0, -45.0, -45.0])
    # revenu = 50 x 10 MW = 500/an ; TURPE = -5 x 10 MW = -50/an
    assert inputs.revenues_keur == pytest.approx([0.0, 500.0, 500.0, 500.0])
    assert inputs.turpe_keur == pytest.approx([0.0, -50.0, -50.0, -50.0])
    assert inputs.usable_power_mw == pytest.approx(10.0)
    assert inputs.usable_energy_mwh == pytest.approx(20.0)
    assert inputs.segment == "HTB1"
    assert inputs.cod == "2028-01-01"


def test_build_project_inputs_missing_year_is_zero_not_error(
    base_params, aurora_library, copex_library
):
    base_params.operating_years = 5  # 2028-2032, mais la fixture Aurora ne couvre que 2028-2030
    inputs = dev_case.build_project_inputs(
        base_params, aurora_library, copex_library, degradation_case=None
    )
    assert inputs.revenues_keur[-2:] == [0.0, 0.0]


def test_build_project_inputs_unknown_combo_raises(base_params, aurora_library, copex_library):
    base_params.turpe_type = "Injection"  # combo "HTB1 injection" absente de la fixture
    with pytest.raises(ValueError, match="Aurora combo"):
        dev_case.build_project_inputs(base_params, aurora_library, copex_library)


def test_build_project_inputs_unknown_duration_raises(base_params, aurora_library, copex_library):
    base_params.duration_h = 4  # seule la duree 2h existe dans la fixture
    with pytest.raises(ValueError, match="Duration"):
        dev_case.build_project_inputs(base_params, aurora_library, copex_library)


def test_build_project_inputs_feeds_financial_engine(base_params, aurora_library, copex_library):
    """Sanity check bout-en-bout : le ProjectInputs synthetique doit etre
    directement utilisable par compute_results(), sans aucune adaptation."""
    inputs = dev_case.build_project_inputs(
        base_params, aurora_library, copex_library, degradation_case=None
    )
    result = financial_engine.compute_results(
        inputs, gearing_pct=0.5, interest_rate=0.05, debt_tenor_years=2
    )
    assert result.project_irr is not None
    assert result.dscr_min is not None
    assert result.capex_total_keur == pytest.approx(1800.0)


def test_run_distance_sensitivity_moves_capex_and_irr(base_params, aurora_library, copex_library):
    rows = dev_case.run_distance_sensitivity(
        base_params,
        aurora_library,
        copex_library,
        [0.0, 5.0, 20.0],
        compute_kwargs={"gearing_pct": 0.5, "interest_rate": 0.05, "debt_tenor_years": 2},
    )
    capex_costs = [r["connection_capex_keur"] for r in rows]
    assert capex_costs == sorted(capex_costs)  # plus loin -> plus cher, monotone
    irrs = [r["project_irr"] for r in rows]
    assert irrs == sorted(irrs, reverse=True)  # plus cher -> IRR plus bas


def test_run_duration_sensitivity_runs_available_durations(base_params, copex_library):
    # bibliotheque avec les 2 durees pour permettre le balayage
    combo = {2028: {"wholesale_storage_sell_revenue": 50_000.0}}
    combo4 = {2028: {"wholesale_storage_sell_revenue": 90_000.0}}
    library = dev_case.AuroraLibrary(combos={"HTB1": {2: combo, 4: combo4}})
    base_params.operating_years = 1
    rows = dev_case.run_duration_sensitivity(base_params, library, copex_library, [2, 4])
    assert [r["duration_h"] for r in rows] == [2, 4]


def test_run_config_sensitivity_labels_base_case(base_params, aurora_library, copex_library):
    rows = dev_case.run_config_sensitivity(base_params, aurora_library, copex_library, [{}])
    assert rows[0]["label"] == "Cas de base"


def test_aurora_library_year_range_across_combos_and_durations():
    library = dev_case.AuroraLibrary(
        combos={
            "HTA": {2: {2028: {"x": 1.0}, 2030: {"x": 1.0}}, 4: {2029: {"x": 1.0}}},
            "HTB1": {2: {2025: {"x": 1.0}, 2057: {"x": 1.0}}},
        }
    )
    assert library.year_range() == (2025, 2057)


def test_aurora_library_year_range_empty_is_none():
    assert dev_case.AuroraLibrary(combos={}).year_range() is None


def test_run_cod_year_sensitivity_reslices_same_calendar_curve(base_params, copex_library):
    combo = {
        2028: {"wholesale_storage_sell_revenue": 50_000.0},
        2029: {"wholesale_storage_sell_revenue": 60_000.0},
        2030: {"wholesale_storage_sell_revenue": 70_000.0},
    }
    library = dev_case.AuroraLibrary(combos={"HTB1": {2: combo}})
    base_params.operating_years = 1
    rows = dev_case.run_cod_year_sensitivity(
        base_params, library, copex_library, [2028, 2029, 2030]
    )
    # Decaler le COD lit une autre annee de la MEME courbe -> revenu different chaque fois.
    irrs = [r["project_irr"] for r in rows]
    assert len({round(x, 6) for x in irrs}) == 3
