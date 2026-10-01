import io

import openpyxl
import pytest

from core import portfolio_import
from core.contract_overlay import FLOOR, FULL_MERCHANT


def _write_projects_sheet(path, header: list[str], rows: list[list]):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = portfolio_import.SHEET_NAME
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_build_template_workbook_has_projects_and_legend_sheets():
    wb = portfolio_import.build_template_workbook()
    assert wb.sheetnames == [portfolio_import.SHEET_NAME, portfolio_import.LEGEND_SHEET_NAME]
    header = [cell.value for cell in wb[portfolio_import.SHEET_NAME][1]]
    assert header == portfolio_import._COLUMNS


def test_template_round_trips_into_valid_project_configs():
    configs = portfolio_import.parse_portfolio_excel(io.BytesIO(portfolio_import.template_bytes()))
    assert len(configs) == 2
    site_a, site_b = configs
    assert site_a.name == "Site A"
    assert site_a.duree_h == 2
    assert site_a.tension == "HTA"
    assert site_a.contract_structure.kind == FULL_MERCHANT
    assert site_b.name == "Site B"
    assert site_b.gabarit is True
    assert site_b.oro_requested is True
    assert site_b.contract_structure.kind == FLOOR
    assert site_b.contract_structure.price_keur_per_mw_per_year == pytest.approx(80.0)
    assert site_b.gearing_pct_override == pytest.approx(0.70)
    assert site_b.interest_rate_override == pytest.approx(0.05)
    assert site_a.turpe_50pct_reduction is False
    assert site_b.turpe_50pct_reduction is True


def test_minimal_file_with_only_required_columns_uses_defaults(tmp_path):
    path = tmp_path / "minimal.xlsx"
    _write_projects_sheet(
        path,
        [
            "Project name",
            "BESS duration (h)",
            "Voltage (Tension)",
            "TURPE type",
            "Gabarit",
            "COD year",
            "Power (MW)",
        ],
        [["Only Required", 2, "HTA", "Classique", "No", 2028, 10]],
    )
    configs = portfolio_import.parse_portfolio_excel(path)
    assert len(configs) == 1
    config = configs[0]
    assert config.operating_years == 20
    assert config.contract_structure.kind == FULL_MERCHANT
    assert config.repowering_enabled is True
    assert config.repowering_year_mode == "manual"
    assert config.gearing_pct_override is None


def test_missing_required_column_raises_clear_error(tmp_path):
    path = tmp_path / "broken.xlsx"
    _write_projects_sheet(
        path,
        ["Project name", "Voltage (Tension)"],  # BESS duration (h) etc. manquants
        [["Site A", "HTA"]],
    )
    with pytest.raises(ValueError, match="Missing required column"):
        portfolio_import.parse_portfolio_excel(path)


def test_missing_required_value_in_a_row_raises_with_row_context(tmp_path):
    path = tmp_path / "broken_row.xlsx"
    _write_projects_sheet(
        path,
        [
            "Project name",
            "BESS duration (h)",
            "Voltage (Tension)",
            "TURPE type",
            "Gabarit",
            "COD year",
            "Power (MW)",
        ],
        [["Site A", None, "HTA", "Classique", "No", 2028, 10]],  # duree manquante
    )
    with pytest.raises(ValueError, match="Row 2 'Site A'"):
        portfolio_import.parse_portfolio_excel(path)


def test_blank_trailing_rows_are_skipped(tmp_path):
    path = tmp_path / "trailing_blank.xlsx"
    _write_projects_sheet(
        path,
        [
            "Project name",
            "BESS duration (h)",
            "Voltage (Tension)",
            "TURPE type",
            "Gabarit",
            "COD year",
            "Power (MW)",
        ],
        [
            ["Site A", 2, "HTA", "Classique", "No", 2028, 10],
            [None, None, None, None, None, None, None],
            [None, None, None, None, None, None, None],
        ],
    )
    configs = portfolio_import.parse_portfolio_excel(path)
    assert len(configs) == 1


def test_invalid_connection_capex_mode_raises_clear_error(tmp_path):
    """Reproduit le bug signale par l'utilisateur le 2026-09-29 : 'distance'
    au lieu de 'distance_rte' plantait tres loin dans dev_case.connection_capex_keur
    avec une erreur generique illisible en prod - doit maintenant etre rejete
    des l'import, avec un message clair."""
    path = tmp_path / "bad_mode.xlsx"
    _write_projects_sheet(
        path,
        [
            "Project name",
            "BESS duration (h)",
            "Voltage (Tension)",
            "TURPE type",
            "Gabarit",
            "COD year",
            "Power (MW)",
            "Grid connection CAPEX mode",
        ],
        [["Kerlo", 2, "HTB2", "Classique", "No", 2028, 65, "distance"]],
    )
    with pytest.raises(ValueError, match="Grid connection CAPEX mode.*library, manual"):
        portfolio_import.parse_portfolio_excel(path)


def test_invalid_repowering_year_mode_raises_clear_error(tmp_path):
    path = tmp_path / "bad_repowering_mode.xlsx"
    _write_projects_sheet(
        path,
        [
            "Project name",
            "BESS duration (h)",
            "Voltage (Tension)",
            "TURPE type",
            "Gabarit",
            "COD year",
            "Power (MW)",
            "Repowering year mode",
        ],
        [["Site A", 2, "HTA", "Classique", "No", 2028, 10, "automatic"]],
    )
    with pytest.raises(ValueError, match="Repowering year mode.*auto, manual"):
        portfolio_import.parse_portfolio_excel(path)


def test_no_project_rows_raises_clear_error(tmp_path):
    path = tmp_path / "empty.xlsx"
    _write_projects_sheet(
        path,
        [
            "Project name",
            "BESS duration (h)",
            "Voltage (Tension)",
            "TURPE type",
            "Gabarit",
            "COD year",
            "Power (MW)",
        ],
        [],
    )
    with pytest.raises(ValueError, match="No project row found"):
        portfolio_import.parse_portfolio_excel(path)
