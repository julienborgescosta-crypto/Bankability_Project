import pytest

from core import copex_comparison, copex_icp


@pytest.fixture(scope="session")
def icp_library():
    return copex_icp.load_icp_library()


def test_total_capex_row_sums_construction_development_and_grid(icp_library, copex_library):
    comparison = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    total = next(r for r in comparison.capex_rows if r.label == "TOTAL CAPEX")
    construction = next(r for r in comparison.capex_rows if r.label.startswith("Construction"))
    development = next(r for r in comparison.capex_rows if r.label == "Development")
    grid = next(r for r in comparison.capex_rows if r.label == "Grid connection")
    assert total.ours_keur == pytest.approx(
        construction.ours_keur + development.ours_keur + grid.ours_keur
    )
    assert total.aurora_keur == pytest.approx(
        construction.aurora_keur + development.aurora_keur + grid.aurora_keur
    )


def test_development_row_is_identical_both_sides_and_marked_info_only(icp_library, copex_library):
    """Development n'est jamais couvert par ICP - toujours = Aurora, jamais
    un ecart a interpreter (voir docs/specs/copex_comparison.md)."""
    comparison = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    development = next(r for r in comparison.capex_rows if r.label == "Development")
    assert development.ours_keur == pytest.approx(development.aurora_keur)
    assert development.comparable is False
    assert development.status == "Info only"


def test_opex_info_only_row_identical_both_sides(icp_library, copex_library):
    comparison = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    info_row = next(r for r in comparison.opex_rows if not r.comparable and "TOTAL" not in r.label)
    assert info_row.ours_keur == pytest.approx(info_row.aurora_keur)
    assert info_row.status == "Info only"


def test_grid_connection_not_comparable_when_mode_is_not_library(icp_library, copex_library):
    comparison = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
        connection_capex_mode="manual",
    )
    grid = next(r for r in comparison.capex_rows if r.label == "Grid connection")
    assert grid.comparable is False
    assert grid.status == "Info only"
    assert any("connection_capex_mode='manual'" in note for note in comparison.notes)


def test_status_thresholds_ok_watch_large_gap():
    row_ok = copex_comparison.CopexComparisonRow("x", 105.0, 100.0, True)
    row_watch = copex_comparison.CopexComparisonRow("x", 115.0, 100.0, True)
    row_large_gap = copex_comparison.CopexComparisonRow("x", 130.0, 100.0, True)
    assert row_ok.status == "OK"
    assert row_watch.status == "Watch"
    assert row_large_gap.status == "Large gap"


def test_htb3_falls_back_to_aurora_on_both_sides(icp_library, copex_library):
    """HTB3 n'a jamais eu de colonne ICP - les 2 cotes doivent retomber sur
    la meme valeur Aurora (ou 0/0 si le fixture COPEX_library lui-meme n'a
    pas de colonne HTB3 - voir docs/specs/copex_comparison.md)."""
    comparison = copex_comparison.compare_capex_opex(
        tension="HTB3",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    total = next(r for r in comparison.capex_rows if r.label == "TOTAL CAPEX")
    assert total.ours_keur == pytest.approx(total.aurora_keur)


def test_repowering_not_covered_note_present(icp_library, copex_library):
    comparison = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    assert any("Repowering" in note for note in comparison.notes)
