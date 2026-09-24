import pytest

from core import aur_cases, copex_icp, dev_case_parser


@pytest.fixture(scope="session")
def icp_library():
    return copex_icp.load_icp_library()


def test_load_icp_library_reads_metadata(icp_library):
    assert icp_library.update_date is not None
    assert icp_library.inflation_rate == pytest.approx(0.02)


def test_load_icp_library_reads_power_law_formulas(icp_library):
    assert icp_library.battery_pcs[2].base == pytest.approx(156.37)
    assert icp_library.battery_pcs[2].exponent == pytest.approx(-0.051)
    assert icp_library.battery_pcs[4].base == pytest.approx(149.18)
    assert icp_library.opex_guarantees[2].base == pytest.approx(794.13)
    assert icp_library.opex_guarantees[4].base == pytest.approx(1408.0)


def test_load_icp_library_reads_epc_margin_and_insurance(icp_library):
    assert icp_library.epc_margin_pct["DSO"] == pytest.approx(0.05)
    assert icp_library.insurance_construction_pct["DSO"] == pytest.approx(0.009)


def test_unit_detection_reads_number_format_not_raw_value():
    """Une meme ligne ('Grid connection', 'HV substation', ...) melange des
    unites differentes selon la colonne - l'unite doit venir du format Excel,
    jamais d'une heuristique sur la valeur brute (demande de l'utilisateur,
    2026-09-24)."""
    grid_connection = icp_library_for_unit_test().line_items["Grid connection"]
    assert grid_connection["DSO"].unit == "keur_flat"  # 2000 -> 2000 k€ forfait
    assert grid_connection["TSO 90kV"].unit == "keur_flat"  # 3700 -> 3700 k€ forfait
    hv_substation = icp_library_for_unit_test().line_items["HV substation"]
    assert hv_substation["Industrial-Existing trench"].unit == "eur_per_mw"  # 10000 -> €/MW


def icp_library_for_unit_test():
    return copex_icp.load_icp_library()


def test_icp_battery_pcs_keur_matches_power_law_formula(icp_library):
    # 10 MW / 2h -> 20 MWh, formule 156.37 * MWh^(-0.051), COD avant 2027 -> multiplicateur base (1.0).
    # Coefficient en EUR/kWh malgre le libelle Excel "€/MWh" (bug de mislabeling corrige le
    # 2026-09-24 - voir IcpPowerLawCost/_power_law_cost_keur) : cout total k€ = unit_cost x MWh,
    # sans division par 1000 supplementaire.
    result = copex_icp.icp_battery_pcs_keur(icp_library, duree_h=2, power_mw=10.0, cod_year=2026)
    expected_eur_per_kwh = 156.37 * 20.0**-0.051
    expected_keur = expected_eur_per_kwh * 20.0
    assert result == pytest.approx(expected_keur)


def test_icp_battery_pcs_keur_order_of_magnitude_is_realistic(icp_library):
    """Garde-fou de non-regression (bug 2026-09-24) : avant correction,
    `_power_law_cost_keur` divisait par 1000 de trop et donnait un cout
    Batteries+PCS d'environ 0.1 EUR/kWh installe (~1000x trop bas). Un vrai
    cout BESS batterie+PCS se situe dans une fourchette large mais realiste -
    verifie l'ordre de grandeur plutot qu'une valeur exacte qui bougera a
    chaque mise a jour mensuelle du fichier ICP."""
    for duree_h in (2, 4):
        cost_keur = copex_icp.icp_battery_pcs_keur(
            icp_library, duree_h=duree_h, power_mw=40.0, cod_year=2028
        )
        cost_keur_per_mwh = cost_keur / (40.0 * duree_h)
        assert 50.0 <= cost_keur_per_mwh <= 400.0, (
            f"Batteries+PCS {duree_h}h hors fourchette realiste "
            f"(100-300 k€/MWh attendus) : {cost_keur_per_mwh:.1f} k€/MWh."
        )


def test_icp_opex_guarantees_order_of_magnitude_is_realistic(icp_library):
    """Meme garde-fou que ci-dessus, pour la 2e (et derniere) ligne power-law
    du fichier ICP - avant correction, l'OPEX de garantie annualise tombait a
    ~0.2-0.3 k€/an au lieu de plusieurs centaines."""
    for duree_h in (2, 4):
        annualized_keur = copex_icp.icp_opex_guarantees_annualized_keur(
            icp_library, duree_h=duree_h, power_mw=40.0, cod_year=2028
        )
        annualized_keur_per_mw = annualized_keur / 40.0
        assert 1.0 <= annualized_keur_per_mw <= 20.0, (
            f"OPEX Guarantees {duree_h}h hors fourchette realiste "
            f"(1-20 k€/MW/an attendus) : {annualized_keur_per_mw:.2f} k€/MW/an."
        )


def test_icp_battery_pcs_keur_applies_year_multiplier(icp_library):
    base = copex_icp.icp_battery_pcs_keur(icp_library, duree_h=2, power_mw=10.0, cod_year=2026)
    escalated = copex_icp.icp_battery_pcs_keur(icp_library, duree_h=2, power_mw=10.0, cod_year=2028)
    assert escalated == pytest.approx(base * 0.966)  # multiplicateur 2028 = 0.966


def test_icp_battery_pcs_keur_caps_escalation_beyond_last_known_year(icp_library):
    year_2031 = copex_icp.icp_battery_pcs_keur(icp_library, duree_h=2, power_mw=10.0, cod_year=2031)
    year_2040 = copex_icp.icp_battery_pcs_keur(icp_library, duree_h=2, power_mw=10.0, cod_year=2040)
    assert year_2040 == pytest.approx(
        year_2031
    )  # plafonne sur le dernier multiplicateur connu (2031)


def test_icp_opex_guarantees_annualized_is_total_divided_by_15(icp_library):
    total_via_formula = copex_icp._power_law_cost_keur(
        icp_library.opex_guarantees[2], power_mw=10.0, duree_h=2, cod_year=2027
    )
    annualized = copex_icp.icp_opex_guarantees_annualized_keur(
        icp_library, duree_h=2, power_mw=10.0, cod_year=2027
    )
    assert annualized == pytest.approx(total_via_formula / 15)


def test_icp_capex_total_keur_includes_epc_margin_and_insurance(icp_library, aurora_library):
    """EPC Margin (5%) puis Insurance (0,9%) sur le total incluant la marge -
    confirme par l'utilisateur, 2026-09-24 (docs/specs/copex_icp.md)."""
    direct_only = 0.0
    for label in copex_icp._DIRECT_CAPEX_LABELS:
        cost = copex_icp._icp_line_item_keur(
            icp_library, label, "DSO", power_mw=10.0, duree_h=2, cod_year=2027
        )
        direct_only += cost or 0.0
    direct_only += copex_icp.icp_battery_pcs_keur(
        icp_library, duree_h=2, power_mw=10.0, cod_year=2027
    )

    capex, notes = copex_icp.icp_capex_total_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    expected_construction = direct_only * 1.05 * 1.009
    # capex inclut aussi Development (Aurora, additif hors marquage EPC/assurance).
    assert capex > expected_construction
    assert capex == pytest.approx(
        expected_construction
        + copex_icp.escalated_unit_cost(
            aurora_library.capex_unit_costs["2h - HTA"].get("Development", 0.0),
            aurora_library.capex_escalation.get("Development", {}),
            2027,
        )
        * 10.0
    )
    assert any("Development" in note for note in notes)


def test_icp_capex_total_keur_falls_back_to_aurora_for_htb3(icp_library, aurora_library):
    capex, notes = copex_icp.icp_capex_total_keur(
        tension="HTB3",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    assert capex == 0.0  # HTB3 absent aussi d'Aurora COPEX_library (limite pre-existante)
    assert any("HTB3" in note for note in notes)


def test_icp_opex_year1_keur_replaces_fixed_om_and_adds_guarantees(icp_library, aurora_library):
    opex, notes = copex_icp.icp_opex_year1_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    om = copex_icp._icp_line_item_keur(
        icp_library, copex_icp._OM_LABEL, "DSO", power_mw=10.0, duree_h=2, cod_year=2027
    )
    guarantees = copex_icp.icp_opex_guarantees_annualized_keur(
        icp_library, duree_h=2, power_mw=10.0, cod_year=2027
    )
    assert opex > om + guarantees  # + repli Aurora (Insurance/Grid charges/Land lease/Accise/Other)
    assert any("Insurance" in note for note in notes)


def test_icp_connection_capex_keur_sources_from_icp_when_tension_covered(
    icp_library, aurora_library
):
    cost, notes = copex_icp.icp_connection_capex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    assert cost > 0.0
    assert notes == []


def test_icp_repowering_capex_keur_matches_battery_pcs_formula(icp_library, aurora_library):
    cost, notes = copex_icp.icp_repowering_capex_keur(
        tension="HTA",
        duree_h=2,
        repowering_year=2041,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    expected = copex_icp.icp_battery_pcs_keur(icp_library, duree_h=2, power_mw=10.0, cod_year=2041)
    assert cost == pytest.approx(expected)
    assert notes == []


def test_capex_opex_source_notes_mentions_icp_and_aurora_for_covered_tension():
    notes = copex_icp.capex_opex_source_notes("HTA")
    joined = " ".join(notes)
    assert "ICP" in joined
    assert "Aurora" in joined


def test_capex_opex_source_notes_flags_htb3_as_fully_aurora():
    notes = copex_icp.capex_opex_source_notes("HTB3")
    assert any("HTB3" in note and "Aurora" in note for note in notes)


@pytest.fixture(scope="session")
def aurora_library():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent
        / "sample_data"
        / "160926_BP_Stockage_Standalone__.xlsx"
    )
    _, copex_grid, _ = dev_case_parser.load_dev_case_grids(path)
    return dev_case_parser.parse_copex_library(copex_grid)


def test_aur_cases_capex_and_opex_keur_end_to_end_still_positive(aurora_library):
    """Bout-en-bout via aur_cases (pas juste copex_icp isole) - garde le
    cablage capex_and_opex_keur/repowering_capex_keur sous surveillance."""
    capex, opex = aur_cases.capex_and_opex_keur(
        tension="HTB1", duree_h=2, cod_year=2027, power_mw=10.0, copex_library=aurora_library
    )
    assert capex > 0.0
    assert opex > 0.0
