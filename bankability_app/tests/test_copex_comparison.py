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
    core = next(r for r in comparison.capex_rows if r.label.startswith("Core equipment"))
    development = next(r for r in comparison.capex_rows if r.label == "Development")
    grid_combined = next(
        r for r in comparison.capex_rows if r.label.startswith("Grid connection &")
    )
    assert total.ours_keur == pytest.approx(
        core.ours_keur + development.ours_keur + grid_combined.ours_keur
    )
    assert total.aurora_keur == pytest.approx(
        core.aurora_keur + development.aurora_keur + grid_combined.aurora_keur
    )


def test_total_capex_unaffected_by_core_substation_reallocation(icp_library, copex_library):
    """Reallouer les 3 postes HV/MV substation du bucket "core" vers "grid"
    ne doit rien changer au TOTAL CAPEX - seule la ventilation poste par
    poste change (voir docs/specs/copex_comparison.md)."""
    comparison = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    total = next(r for r in comparison.capex_rows if r.label == "TOTAL CAPEX")
    expected_total, _ = copex_icp.icp_capex_total_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    ptf_only_keur, _ = copex_icp.icp_connection_capex_keur(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    assert total.ours_keur == pytest.approx(expected_total + ptf_only_keur)


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
    grid = next(r for r in comparison.capex_rows if r.label == "Grid connection (PTF only)")
    grid_combined = next(
        r for r in comparison.capex_rows if r.label.startswith("Grid connection &")
    )
    assert grid.comparable is False
    assert grid.status == "Info only"
    assert grid_combined.comparable is False
    assert any("connection_capex_mode='manual'" in note for note in comparison.notes)


def test_grid_connection_manual_mode_shows_actual_applied_value_not_library_estimate(
    icp_library, copex_library
):
    """Bug signale par l'utilisateur, 2026-10-01 : un projet en mode "manual"
    avec un raccordement reel de 17 k€ affichait quand meme l'estimation ICP
    bibliotheque (plusieurs millions d'euros) dans la colonne "Ours" - le
    nombre ne correspondait pas a ce que le moteur applique reellement a ce
    projet (`aur_cases.capex_and_opex_keur` respecte deja le mode, seul ce
    module de comparaison l'ignorait)."""
    comparison_manual = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
        connection_capex_mode="manual",
        manual_connection_capex_keur=17.0,
    )
    comparison_library = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
        connection_capex_mode="library",
    )
    grid_manual = next(
        r for r in comparison_manual.capex_rows if r.label == "Grid connection (PTF only)"
    )
    grid_library = next(
        r for r in comparison_library.capex_rows if r.label == "Grid connection (PTF only)"
    )
    assert grid_manual.ours_keur == pytest.approx(17.0)
    assert grid_manual.ours_keur != pytest.approx(grid_library.ours_keur)
    assert grid_library.ours_keur > 100  # l'estimation bibliotheque reste bien plus elevee ici

    # TOTAL CAPEX doit refleter le vrai raccordement manuel, pas l'estimation
    # bibliotheque - meme bug, plus grave, sur la ligne agregee.
    total_manual = next(r for r in comparison_manual.capex_rows if r.label == "TOTAL CAPEX")
    total_library = next(r for r in comparison_library.capex_rows if r.label == "TOTAL CAPEX")
    assert total_manual.ours_keur < total_library.ours_keur
    assert total_manual.ours_keur == pytest.approx(
        total_library.ours_keur - grid_library.ours_keur + 17.0
    )


def test_land_lease_manual_override_replaces_aurora_estimate(icp_library, copex_library):
    """Bug signale par l'utilisateur, 2026-10-01 (2 corrections le meme jour) :
    un projet avec un loyer foncier manuel (ex. 300 k€/an) ressortait d'abord
    avec exactement le meme OPEX "Ours" qu'Aurora (le loyer manuel n'etait pas
    repris par ce module), puis - une fois cette 1ere correction faite - avec
    Aurora + le loyer manuel ADDITIONNES (ex. 130 k€ Aurora + 300 k€ manuel =
    430 k€), alors que le loyer manuel doit REMPLACER l'estimation Aurora, pas
    s'y ajouter (un projet ne paie pas 2 loyers fonciers empiles)."""
    comparison_with_lease = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
        land_lease_opex_keur=300.0,
    )
    comparison_without_lease = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    land_lease_with = next(
        r for r in comparison_with_lease.opex_rows if r.label.startswith("Land lease")
    )
    land_lease_without = next(
        r for r in comparison_without_lease.opex_rows if r.label.startswith("Land lease")
    )
    # Le loyer manuel REMPLACE la valeur "Ours" - Aurora reste inchange des 2 cotes.
    assert land_lease_with.ours_keur == pytest.approx(300.0)
    assert land_lease_with.ours_keur != pytest.approx(land_lease_without.ours_keur + 300.0)
    assert land_lease_with.aurora_keur == pytest.approx(land_lease_without.aurora_keur)
    assert land_lease_with.comparable is True

    total_with = next(r for r in comparison_with_lease.opex_rows if r.label == "TOTAL OPEX")
    total_without = next(r for r in comparison_without_lease.opex_rows if r.label == "TOTAL OPEX")
    assert total_with.ours_keur == pytest.approx(
        total_without.ours_keur - land_lease_without.ours_keur + 300.0
    )
    assert total_with.aurora_keur == pytest.approx(total_without.aurora_keur)
    # Sans override, "Ours" et Aurora doivent rester identiques sur le loyer
    # (ligne non couverte par ICP, repli Aurora des 2 cotes par construction).
    assert land_lease_without.ours_keur == pytest.approx(land_lease_without.aurora_keur)


def test_grid_connection_distance_rte_mode_shows_actual_applied_value(icp_library, copex_library):
    comparison = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
        connection_capex_mode="distance_rte",
        distance_rte_km=10.0,
    )
    grid = next(r for r in comparison.capex_rows if r.label == "Grid connection (PTF only)")
    assert grid.ours_keur == pytest.approx(4650.7 * 10.0**0.239)


def test_grid_connection_bucket_includes_private_substation_cost(icp_library, copex_library):
    """Aurora compterait le poste de livraison/sous-station privee dans son
    "Grid connection" (a confirmer - voir docs/specs/copex_comparison.md,
    l'ecart s'aggrave plutot que se resorber sur HTB1/HTB2). HTA (segment
    DSO) a un cout de sous-station MV non nul dans le fichier ICP - la ligne
    "Private substation" doit etre strictement positive et le bucket
    combine strictement superieur au raccordement PTF seul."""
    comparison = copex_comparison.compare_capex_opex(
        tension="HTA",
        duree_h=2,
        cod_year=2028,
        power_mw=40.0,
        icp_library=icp_library,
        aurora_library=copex_library,
    )
    ptf_only = next(r for r in comparison.capex_rows if r.label == "Grid connection (PTF only)")
    substation = next(r for r in comparison.capex_rows if r.label.startswith("Private substation"))
    grid_combined = next(
        r for r in comparison.capex_rows if r.label.startswith("Grid connection &")
    )
    assert substation.ours_keur > 0
    assert grid_combined.ours_keur == pytest.approx(ptf_only.ours_keur + substation.ours_keur)
    assert grid_combined.ours_keur > ptf_only.ours_keur


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
