import pytest

from core import opex_grid_charges


@pytest.fixture(scope="session")
def grid_charges_terms():
    return opex_grid_charges.grid_charges_terms_cached()


@pytest.fixture(scope="session")
def charge_volume_curves():
    return opex_grid_charges.charge_volume_curves_cached()


def test_load_grid_charges_terms_has_all_tensions(grid_charges_terms):
    for tension in ("HTA", "HTB1", "HTB2", "HTB3"):
        assert tension in grid_charges_terms["turpe_power_fixed_fee_keur"]
        assert tension in grid_charges_terms["turpe_power_variable_fee_keur_per_mw"]
        assert tension in grid_charges_terms["cta_rate_pct"]


def test_load_charge_volume_curves_has_8_reference_curves(charge_volume_curves):
    expected_keys = {
        f"{duree_h}h {tension}" for duree_h in (2, 4) for tension in ("HTA", "HTB1", "HTB2", "HTB3")
    }
    assert expected_keys == set(charge_volume_curves)


def test_turpe_power_keur_matches_bp_source_formula(grid_charges_terms):
    """081026_BP_Stockage_Standalone__.xlsm, I-Fixed!E74:E82 - HTA : fixed
    0.88 k€ + variable 14.51 k€/MW, sans escalade (NTP avant la 1re annee de
    la table -> multiplicateur 1.0)."""
    value = opex_grid_charges.turpe_power_keur(
        tension="HTA", power_mw=10.0, cod_year=2026, terms=grid_charges_terms, icp_escalation={}
    )
    assert value == pytest.approx(0.88 + 14.51 * 10.0)


def test_cta_keur_uses_dso_rate_for_hta():
    value = opex_grid_charges.cta_keur(
        tension="HTA",
        turpe_power_value_keur=1000.0,
        terms={"cta_rate_pct": {"HTA": 0.05, "HTB1": 0.15}},
    )
    assert value == pytest.approx(50.0)


def test_cta_keur_uses_tso_rate_for_htb():
    value = opex_grid_charges.cta_keur(
        tension="HTB2",
        turpe_power_value_keur=1000.0,
        terms={"cta_rate_pct": {"HTA": 0.05, "HTB1": 0.15, "HTB2": 0.15}},
    )
    assert value == pytest.approx(150.0)


def test_accise_keur_raises_for_unknown_combo(grid_charges_terms):
    with pytest.raises(ValueError, match="Pas de courbe"):
        opex_grid_charges.accise_keur(
            tension="HTA",
            duree_h=6,
            power_mw=10.0,
            cod_year=2030,
            terms=grid_charges_terms,
            icp_escalation={},
            charge_volume_curves={},
        )


def test_accise_keur_scales_with_power(grid_charges_terms, charge_volume_curves):
    small = opex_grid_charges.accise_keur(
        tension="HTB2",
        duree_h=4,
        power_mw=10.0,
        cod_year=2030,
        terms=grid_charges_terms,
        icp_escalation={},
        charge_volume_curves=charge_volume_curves,
    )
    large = opex_grid_charges.accise_keur(
        tension="HTB2",
        duree_h=4,
        power_mw=20.0,
        cod_year=2030,
        terms=grid_charges_terms,
        icp_escalation={},
        charge_volume_curves=charge_volume_curves,
    )
    assert large == pytest.approx(small * 2)
    assert small > 0.0


def test_accise_keur_excludes_losses_when_disabled(grid_charges_terms, charge_volume_curves):
    terms_with_losses = dict(grid_charges_terms)
    terms_without_losses = {**grid_charges_terms, "accise_includes_losses": False}
    with_losses = opex_grid_charges.accise_keur(
        tension="HTB2",
        duree_h=4,
        power_mw=10.0,
        cod_year=2030,
        terms=terms_with_losses,
        icp_escalation={},
        charge_volume_curves=charge_volume_curves,
    )
    without_losses = opex_grid_charges.accise_keur(
        tension="HTB2",
        duree_h=4,
        power_mw=10.0,
        cod_year=2030,
        terms=terms_without_losses,
        icp_escalation={},
        charge_volume_curves=charge_volume_curves,
    )
    assert without_losses < with_losses


def test_grid_charges_opex_keur_sums_the_3_components(grid_charges_terms, charge_volume_curves):
    total, detail = opex_grid_charges.grid_charges_opex_keur(
        tension="HTA",
        duree_h=2,
        power_mw=10.0,
        cod_year=2030,
        terms=grid_charges_terms,
        icp_escalation={},
        charge_volume_curves=charge_volume_curves,
    )
    assert set(detail) == {"turpe_power_keur", "cta_keur", "accise_keur"}
    assert total == pytest.approx(sum(detail.values()))
    assert all(v > 0.0 for v in detail.values())
