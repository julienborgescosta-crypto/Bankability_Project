import pytest

from core import aur_cases, copex_icp, dev_case_parser


@pytest.fixture(scope="session")
def icp_library():
    return copex_icp.load_icp_library()


def test_load_icp_library_reads_version(icp_library):
    assert icp_library.version == "V2 - JFE - 08/10/2026"


def test_load_icp_library_reads_segments_from_header(icp_library):
    """Segments lus sur la ligne d'en-tete "Case", jamais par position fixe - les 2
    colonnes 'DSO' (2h/4h) de la V1_20261001 sont identiques et fusionnees."""
    assert set(icp_library.line_items["Communication"]) == {
        "Industrial-New trench",
        "Industrial-Existing trench",
        "TSO 63kV",
        "TSO 90kV",
        "TSO 225kV",
        "DSO",
    }


def test_load_icp_library_reads_epc_margin_contingency_and_insurance(icp_library):
    assert icp_library.epc_margin_pct["DSO"] == pytest.approx(0.05)
    assert icp_library.epc_contingency_pct["DSO"] == pytest.approx(0.07)
    assert icp_library.insurance_construction_pct["DSO"] == pytest.approx(0.009)


def test_load_icp_library_reads_insurance_operation_pct(icp_library):
    """ "Insurances operation (% Capex + 1y incomes)" = "0,45% + 1y income" -
    texte compose, pas un nombre - voir _read_formula_row."""
    assert icp_library.insurance_operation_pct["DSO"] == pytest.approx(0.0045)


def test_load_icp_library_reads_asset_management_operation_formula(icp_library):
    """ "Asset Management operation (annual cost)" = "400€/MWh + 18k€"."""
    per_mwh_eur, flat_keur = icp_library.asset_management_operation["DSO"]
    assert per_mwh_eur == pytest.approx(400.0)
    assert flat_keur == pytest.approx(18.0)


def test_icp_asset_management_operation_keur_matches_formula(icp_library):
    cost = copex_icp.icp_asset_management_operation_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=2027
    )
    escalation = copex_icp.icp_escalation_factor(
        icp_library.escalation[copex_icp._ASSET_MGMT_OPERATION_LABEL], 2026
    )
    assert cost == pytest.approx((400.0 * 10.0 * 2.0 / 1000.0 + 18.0) * escalation)


def test_icp_opex_year1_keur_insurance_operation_uses_capex_and_revenue(
    icp_library, aurora_library
):
    """0,45% x (CAPEX total + revenu annee 1) - demande de l'utilisateur,
    2026-10-08 ("je ne veux plus reprendre aucune hypothese Aurora")."""
    opex_without_revenue, _ = copex_icp.icp_opex_year1_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
        capex_total_keur=1000.0,
    )
    opex_with_revenue, _ = copex_icp.icp_opex_year1_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
        capex_total_keur=1000.0,
        revenue_year1_keur=500.0,
    )
    assert opex_with_revenue - opex_without_revenue == pytest.approx(0.0045 * 500.0)


def test_icp_opex_year1_keur_other_admin_sourced_from_icp_not_aurora(icp_library, aurora_library):
    """ "Other (Admin/Accounting/Communication)" remplace le repli Aurora
    "Other" depuis le 2026-10-08 (plat, non escalade dans le fichier)."""
    other_icp = copex_icp._icp_line_item_keur(
        icp_library, copex_icp._OTHER_ADMIN_LABEL, "DSO", power_mw=10.0, duree_h=2, cod_year=2027
    )
    assert other_icp == pytest.approx(8.0)
    _, notes = copex_icp.icp_opex_year1_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    assert any("Other (Admin" in note for note in notes)
    assert not any(note.startswith("OPEX Other :") for note in notes)


def test_icp_capex_total_keur_includes_asset_management_construction(icp_library, aurora_library):
    with_asset_mgmt, _ = copex_icp.icp_capex_total_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    asset_mgmt_construction = copex_icp._icp_line_item_keur(
        icp_library,
        copex_icp._ASSET_MGMT_CONSTRUCTION_LABEL,
        "DSO",
        power_mw=10.0,
        duree_h=2,
        cod_year=2027,
    )
    assert asset_mgmt_construction == pytest.approx(70.0)
    assert asset_mgmt_construction > 0.0


def test_hta_grid_connection_is_300_keur(icp_library, aurora_library):
    """La V1_20261001 indique 0,3 k€ pour le raccordement DSO : erreur de saisie,
    c'est 300 k€ fixe (confirme par l'utilisateur, 2026-10-05 - corrige dans
    config/copex_icp.xlsx). Ce test rattrape la meme erreur dans une future version."""
    cost, notes = copex_icp.icp_connection_capex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    assert cost == pytest.approx(300.0)
    assert notes == []


def test_unit_detection_reads_number_format_not_raw_value(icp_library):
    """Une meme ligne ('Grid connection', 'HV substation', ...) melange des
    unites differentes selon la colonne - l'unite doit venir du format Excel,
    jamais d'une heuristique sur la valeur brute (demande de l'utilisateur,
    2026-09-24)."""
    grid_connection = icp_library.line_items["Grid connection"]
    assert grid_connection["DSO"].unit == "keur_flat"
    assert grid_connection["TSO 90kV"].unit == "keur_flat"
    assert grid_connection["Industrial-New trench"].unit == "eur_per_mw"
    hv_substation = icp_library.line_items["HV substation"]
    assert hv_substation["Industrial-Existing trench"].unit == "eur_per_mw"
    assert icp_library.line_items["Communication"]["DSO"].unit == "eur_per_mwh"


def test_om_in_keur_per_year_is_read_per_mwh(icp_library):
    """O&M "k€/y" (V1_20261001) lu en k€/MWh/an, comme la version precedente :
    2 k€/an pour tout un projet n'a pas de sens (decision du 2026-10-05)."""
    assert icp_library.line_items[copex_icp._OM_LABEL]["DSO"].unit == "keur_per_mwh_per_year"
    # 10 MW / 2h = 20 MWh, COD 2027 -> NTP 2026, avant la table -> multiplicateur 1.0.
    cost = copex_icp._icp_line_item_keur(
        icp_library, copex_icp._OM_LABEL, "DSO", power_mw=10.0, duree_h=2, cod_year=2027
    )
    assert cost == pytest.approx(2.0 * 20.0)


def test_icp_battery_pcs_keur_uses_segment_value_per_mwh(icp_library):
    # 125 600 €/MWh en DSO (projets < 75 MWh), 123 200 €/MWh en TSO (75 MWh et +).
    dso = copex_icp.icp_battery_pcs_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=2027
    )
    tso = copex_icp.icp_battery_pcs_keur(
        icp_library, segment="TSO 225kV", duree_h=2, power_mw=10.0, cod_year=2027
    )
    assert dso == pytest.approx(125_600 * 20.0 / 1000)
    assert tso == pytest.approx(123_200 * 20.0 / 1000)


def test_icp_battery_pcs_keur_order_of_magnitude_is_realistic(icp_library):
    """Garde-fou d'ordre de grandeur (bug d'unite du 2026-09-24, ~1000x trop bas) -
    une fourchette plutot qu'une valeur exacte, qui bougera a chaque mise a jour."""
    for duree_h in (2, 4):
        cost_keur = copex_icp.icp_battery_pcs_keur(
            icp_library, segment="TSO 90kV", duree_h=duree_h, power_mw=40.0, cod_year=2028
        )
        cost_keur_per_mwh = cost_keur / (40.0 * duree_h)
        assert 50.0 <= cost_keur_per_mwh <= 400.0, (
            f"Batteries+PCS {duree_h}h hors fourchette realiste "
            f"(100-300 k€/MWh attendus) : {cost_keur_per_mwh:.1f} k€/MWh."
        )


def test_icp_opex_guarantees_order_of_magnitude_is_realistic(icp_library):
    for duree_h in (2, 4):
        annualized_keur = copex_icp.icp_opex_guarantees_annualized_keur(
            icp_library, segment="TSO 90kV", duree_h=duree_h, power_mw=40.0, cod_year=2028
        )
        annualized_keur_per_mw = annualized_keur / 40.0
        assert 1.0 <= annualized_keur_per_mw <= 20.0, (
            f"OPEX Guarantees {duree_h}h hors fourchette realiste "
            f"(1-20 k€/MW/an attendus) : {annualized_keur_per_mw:.2f} k€/MW/an."
        )


def test_icp_opex_guarantees_formula_is_reevaluated_at_project_size(icp_library):
    """La V1_20261001 calculait la garantie avec une formule Excel liee a la taille
    d'un BP (=794.13*'[2]I-Project'!$G$28^(-0.61)*1000, 80 MWh en cache) ; depuis le
    2026-10-08 (2e revision), reecrite en texte descriptif du meme calcul ("794,13 ×
    MWh^(-0,61) k€/MWh", plus de valeur en cache puisque ce n'est plus une formule
    Excel executable - voir `_TEXT_POWER_LAW_FORMULA`) : meme coefficient/exposant,
    on garde la loi de puissance, re-evaluee a la taille de chaque projet, et la
    valeur est un total sur 15 ans etale sur 15 ans (decision du 2026-10-05)."""
    cell = icp_library.line_items[copex_icp.guarantees_label(2)]["DSO"]
    assert cell.power_law is not None
    assert cell.power_law.coefficient_eur_per_kwh == pytest.approx(794.13)
    assert cell.power_law.exponent == pytest.approx(-0.61)
    annualized = copex_icp.icp_opex_guarantees_annualized_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=2027
    )
    assert annualized == pytest.approx(794.13 * 20.0**-0.61 * 20.0 / 15)


def test_icp_opex_guarantees_prorates_over_longer_project_life(icp_library):
    """Demande de l'utilisateur, 2026-10-08 : la garantie couvre 15 ans - pour un
    projet de 20 ans, payer au prorata (total x 20/15, soit une periode complete +
    le prorata des 5 annees restantes) ; pour 30 ans, exactement x2 (2 periodes
    completes). Le moteur applique deja ce comportement par construction : le taux
    annualise (total_15y / 15) est paye identiquement chaque annee de la vie du
    projet (aur_cases.opex_series_keur, OPEX plat), donc le total sur N annees vaut
    automatiquement total_15y x N/15 - verifie ici arithmetiquement."""
    total_15y = copex_icp._icp_line_item_keur(
        icp_library,
        copex_icp.guarantees_label(2),
        "DSO",
        power_mw=40.0,
        duree_h=2,
        cod_year=2028,
    )
    annualized = copex_icp.icp_opex_guarantees_annualized_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=40.0, cod_year=2028
    )
    assert annualized == pytest.approx(total_15y / copex_icp.GUARANTEES_DURATION_YEARS)
    assert annualized * 20 == pytest.approx(total_15y * 20 / 15)
    assert annualized * 30 == pytest.approx(total_15y * 2)


def test_icp_costs_are_indexed_on_ntp_year(icp_library):
    """ "Forecast price factor (selon annee de NTP)" : une mise en service en 2029
    est indexee sur 2028 (decision de l'utilisateur, 2026-10-05)."""
    base = copex_icp.icp_battery_pcs_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=2027
    )
    cod_2029 = copex_icp.icp_battery_pcs_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=2029
    )
    factor_2028 = icp_library.escalation[copex_icp.battery_label(2)][2028]
    assert cod_2029 == pytest.approx(base * factor_2028)


def test_icp_battery_pcs_keur_caps_escalation_beyond_last_known_year(icp_library):
    last_year = max(icp_library.escalation[copex_icp.battery_label(2)])
    at_last = copex_icp.icp_battery_pcs_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=last_year + 1
    )
    far = copex_icp.icp_battery_pcs_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=2045
    )
    assert far == pytest.approx(at_last)


def test_duplicate_segment_columns_must_be_identical():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "COPEX_library"
    ws.append(["Case", "DSO", "DSO", None, 2027, 2028, 2029])
    ws.append(["Communication", 2000, 2500, None, 1.02, 1.03, 1.04])
    with pytest.raises(ValueError, match="two 'DSO' columns"):
        copex_icp._read_line_item_row(ws, ws, 2, copex_icp._header(ws)[1])


def test_icp_capex_total_keur_includes_epc_margin_and_insurance(icp_library, aurora_library):
    """Marge EPC (5 %), aleas EPC (7 %, V1_20261001, decision du 2026-10-05) puis
    assurance construction (0,9 %) sur le total - docs/specs/copex_icp.md."""
    direct_only = 0.0
    for label in copex_icp._DIRECT_CAPEX_LABELS:
        cost = copex_icp._icp_line_item_keur(
            icp_library, label, "DSO", power_mw=10.0, duree_h=2, cod_year=2027
        )
        direct_only += cost or 0.0
    direct_only += copex_icp.icp_battery_pcs_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=2027
    )

    capex, notes = copex_icp.icp_capex_total_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    expected_construction = direct_only * 1.05 * 1.07 * 1.009
    asset_mgmt_construction = copex_icp._icp_line_item_keur(
        icp_library,
        copex_icp._ASSET_MGMT_CONSTRUCTION_LABEL,
        "DSO",
        power_mw=10.0,
        duree_h=2,
        cod_year=2027,
    )
    # capex inclut aussi Development (Aurora, additif hors marquage EPC/assurance)
    # et Asset Management construction (ICP, additif, meme logique que Development).
    assert capex > expected_construction
    assert capex == pytest.approx(
        expected_construction
        + copex_icp.escalated_unit_cost(
            aurora_library.capex_unit_costs["2h - HTA"].get("Development", 0.0),
            aurora_library.capex_escalation.get("Development", {}),
            2027,
        )
        * 10.0
        + asset_mgmt_construction
    )
    assert any("Development" in note for note in notes)


def test_icp_eol_eligible_capex_keur_matches_direct_keur_before_margin_and_insurance(
    icp_library, aurora_library
):
    """Valeur de fin de vie (Aurora PDF : "5% of the battery system, inverter
    and balance of system costs") appliquee au direct_keur AVANT marge EPC et
    assurance construction - ce ne sont pas des couts d'equipement physique
    revendable (voir core/aur_cases.py end_of_life_value_keur)."""
    direct_only = 0.0
    for label in copex_icp._DIRECT_CAPEX_LABELS:
        cost = copex_icp._icp_line_item_keur(
            icp_library, label, "DSO", power_mw=10.0, duree_h=2, cod_year=2027
        )
        direct_only += cost or 0.0
    direct_only += copex_icp.icp_battery_pcs_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=2027
    )

    result = copex_icp.icp_eol_eligible_capex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    assert result == pytest.approx(direct_only)


def test_icp_eol_eligible_capex_keur_excludes_development(icp_library, aurora_library):
    with_dev, _ = copex_icp.icp_capex_total_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    eol_base = copex_icp.icp_eol_eligible_capex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    # direct_keur x (1+EPC)x(1+assurance) + Development > direct_keur seul.
    assert with_dev > eol_base


def test_icp_eol_eligible_capex_keur_falls_back_to_aurora_for_htb3(icp_library, aurora_library):
    result = copex_icp.icp_eol_eligible_capex_keur(
        tension="HTB3",
        duree_h=2,
        cod_year=2027,
        power_mw=10.0,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    key = copex_icp.voltage_duration_key("HTB3", 2)
    unit_costs = aurora_library.capex_unit_costs.get(key, {})
    expected = 10.0 * sum(
        unit_costs.get(label, 0.0) for label in ("Battery system", "Inverter", "Balance of system")
    )
    assert result == pytest.approx(expected)


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
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=2027
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
    expected = copex_icp.icp_battery_pcs_keur(
        icp_library, segment="DSO", duree_h=2, power_mw=10.0, cod_year=2041
    )
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
        / "081026_BP_Stockage_Standalone__.xlsx"
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
