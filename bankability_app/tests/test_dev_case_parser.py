import pytest

from core import dev_case, dev_case_parser


def test_extract_duration_h_ignores_digit_from_prefix():
    """Régression : certaines sections de CF Aurora préfixent le label de
    config par 'STHTB1'/'STHTB2' sans séparateur (ex. 'STHTB12h1MW') - un
    regex gourmand (`\\d+`) happe le '1' final du préfixe et lit '12h' (durée
    12, inexistante) au lieu de '2h' (durée 2, correcte)."""
    assert dev_case_parser._extract_duration_h("STHTB12h1MW") == 2
    assert dev_case_parser._extract_duration_h("STHTB14h1MW") == 4
    assert dev_case_parser._extract_duration_h("C2h1MW") == 2
    assert dev_case_parser._extract_duration_h("CTest4h1MW") == 4


def test_has_dev_case_sheets_true_for_dev_case_workbook(sample_dev_case_workbook_path):
    assert dev_case_parser.has_dev_case_sheets(sample_dev_case_workbook_path) is True


def test_has_dev_case_sheets_false_for_summary_workbook(sample_summary_bp_path):
    assert dev_case_parser.has_dev_case_sheets(sample_summary_bp_path) is False


def test_parse_inputs_dev_reads_current_project_config(sample_dev_case_workbook_path):
    grids = dev_case_parser.load_dev_case_grids(sample_dev_case_workbook_path)
    params = dev_case_parser.parse_inputs_dev(grids[0])

    assert params.cod_year == 2028
    assert params.power_mw == pytest.approx(10.0)
    assert params.duration_h == 2
    assert params.connection_type == "TSO 90kV"
    assert params.turpe_type == "Classique"
    assert params.gabarit is False
    assert params.repowering is False
    assert params.land_lease_opex_keur == pytest.approx(5.0)


def test_parse_copex_library_reads_capex_and_opex_tables(sample_dev_case_workbook_path):
    grids = dev_case_parser.load_dev_case_grids(sample_dev_case_workbook_path)
    library = dev_case_parser.parse_copex_library(grids[1])

    assert library.capex_unit_costs["2h - HTB1"]["Grid connection"] == pytest.approx(20.0)
    assert library.capex_unit_costs["2h - HTB1"]["Battery system"] == pytest.approx(100.0)
    assert library.capex_unit_costs["2h - HTA"]["Grid connection"] == pytest.approx(15.0)

    assert library.opex_unit_costs["2h - HTB1"]["Fixed O&M"] == pytest.approx(2.0)
    assert library.opex_unit_costs["2h - HTA"]["Fixed O&M"] == pytest.approx(1.5)


def test_parse_copex_library_reads_escalation_factors(sample_dev_case_workbook_path):
    grids = dev_case_parser.load_dev_case_grids(sample_dev_case_workbook_path)
    library = dev_case_parser.parse_copex_library(grids[1])

    assert library.capex_escalation["Battery system"] == {2028: 0.0, 2030: -0.10}
    # Poste sans delta renseigne dans le fixture -> seule l'annee de base (0.0,
    # un no-op) est enregistree, l'escalade reste de fait non appliquee.
    assert library.capex_escalation["Inverter"] == {2028: 0.0}


def test_parse_cf_aurora_reads_both_durations(sample_dev_case_workbook_path):
    grids = dev_case_parser.load_dev_case_grids(sample_dev_case_workbook_path)
    library = dev_case_parser.parse_cf_aurora(grids[2])

    assert set(library.combos.keys()) == {"HTB1"}
    assert set(library.combos["HTB1"].keys()) == {2, 4}
    assert library.combos["HTB1"][2][2028]["wholesale_storage_sell_revenue"] == pytest.approx(
        50_000.0
    )
    assert library.combos["HTB1"][2][2028]["tariff_TURPE 7 revenue"] == pytest.approx(-5_000.0)
    assert library.combos["HTB1"][4][2029]["wholesale_storage_sell_revenue"] == pytest.approx(
        90_000.0
    )


def test_parse_cf_aurora_ignores_trailing_clean_horizon_blocks():
    """Regression : chaque ligne réelle de CF Aurora contient 4 blocs
    juxtaposés sur la même ligne physique (1 run 'Aurora' + 3 runs 'Clean
    Horizon' décalés d'1 an chacun, séparés par 3 colonnes vides puis 3
    colonnes de labels répétés), pas 1 seul. Sans troncature au 1er blanc, les
    années du run Aurora se retrouvaient zippées avec des valeurs des runs
    Clean Horizon après le 1er blanc - ex. sur le fichier réel, l'année 2030
    récupérait la valeur réelle de l'année 2053 du 2e bloc (décalage cumulatif
    après chaque frontière de bloc). Ce test reproduit la structure à 4 blocs
    et vérifie qu'on ne lit bien QUE le premier."""
    grid = [
        ["HTA", None],
        [
            None,
            "configuration",
            "price",
            "stream",
            2028,
            2029,
            2030,
            None,
            None,
            None,
            "configuration",
            "price",
            "stream",
            2029,
            2030,
            2031,
        ],
        [
            None,
            "C2h1MW",
            "Aurora - Forecast",
            "wholesale_storage_sell_revenue",
            100.0,
            200.0,
            300.0,
            None,
            None,
            None,
            "C2h1MW",
            "Clean Horizon",
            "wholesale_storage_sell_revenue",
            999.0,
            999.0,
            999.0,
        ],
    ]
    library = dev_case_parser.parse_cf_aurora(grid)
    assert library.combos["HTA"][2] == {
        2028: {"wholesale_storage_sell_revenue": 100.0},
        2029: {"wholesale_storage_sell_revenue": 200.0},
        2030: {"wholesale_storage_sell_revenue": 300.0},
    }


def test_end_to_end_parse_and_build_project_inputs(sample_dev_case_workbook_path):
    """Le pipeline complet (parse les 3 onglets -> construit un ProjectInputs)
    doit tourner sans erreur et produire des chiffres coherents avec le cas de
    base du fichier (10 MW, 2h, TSO 90kV/HTB1)."""
    grids = dev_case_parser.load_dev_case_grids(sample_dev_case_workbook_path)
    params = dev_case_parser.parse_inputs_dev(grids[0])
    params.operating_years = 3
    copex_library = dev_case_parser.parse_copex_library(grids[1])
    aurora_library = dev_case_parser.parse_cf_aurora(grids[2])

    inputs = dev_case.build_project_inputs(
        params, aurora_library, copex_library, degradation_case=None
    )

    assert inputs.usable_power_mw == pytest.approx(10.0)
    assert inputs.segment == "HTB1"
    assert inputs.revenues_keur[1:] == pytest.approx([500.0, 500.0, 500.0])
    assert inputs.capex_initial_keur > 0
