import pytest

from core import contract_overlay as co


def test_full_merchant_leaves_revenue_unchanged_and_nothing_secured():
    revenue = [100.0, 110.0, 120.0]
    adjusted, secured = co.apply_contract_overlay(
        revenue, power_mw=10.0, structure=co.ContractStructure(kind=co.FULL_MERCHANT)
    )
    assert adjusted == revenue
    assert secured == [0.0, 0.0, 0.0]


def test_tolling_replaces_revenue_during_duration_then_reverts_to_merchant():
    revenue = [100.0, 110.0, 120.0, 130.0]
    structure = co.ContractStructure(
        kind=co.TOLLING, price_keur_per_mw_per_year=8.0, duration_years=2
    )
    adjusted, secured = co.apply_contract_overlay(revenue, power_mw=10.0, structure=structure)
    assert adjusted == [80.0, 80.0, 120.0, 130.0]
    assert secured == [80.0, 80.0, 0.0, 0.0]


def test_floor_tops_up_shortfall_and_shares_upside():
    # floor = 8 keur/MW/an x 10 MW = 80 keur.
    revenue = [50.0, 100.0]  # annee 1 sous le floor, annee 2 au-dessus
    structure = co.ContractStructure(
        kind=co.FLOOR,
        price_keur_per_mw_per_year=8.0,
        duration_years=2,
        revenue_sharing_above_floor_pct=0.4,
    )
    adjusted, secured = co.apply_contract_overlay(revenue, power_mw=10.0, structure=structure)
    # annee 1 : 50 < 80 -> plancher a 80. annee 2 : 80 + (1-0.4)*(100-80) = 92.
    assert adjusted == pytest.approx([80.0, 92.0])
    assert secured == pytest.approx([80.0, 80.0])


def test_floor_reverts_to_merchant_after_duration():
    revenue = [50.0, 50.0]
    structure = co.ContractStructure(
        kind=co.FLOOR, price_keur_per_mw_per_year=8.0, duration_years=1
    )
    adjusted, secured = co.apply_contract_overlay(revenue, power_mw=10.0, structure=structure)
    assert adjusted == pytest.approx([80.0, 50.0])
    assert secured == pytest.approx([80.0, 0.0])


def test_unknown_structure_kind_raises():
    with pytest.raises(ValueError):
        co.apply_contract_overlay(
            [100.0], power_mw=1.0, structure=co.ContractStructure(kind="bogus")
        )


def test_blended_target_dscr_full_merchant():
    dscr = co.blended_target_dscr(
        [0.0, 0.0], [100.0, 100.0], target_dscr_secured=1.20, target_dscr_merchant=1.40
    )
    assert dscr == pytest.approx(1.40)


def test_blended_target_dscr_fully_secured():
    dscr = co.blended_target_dscr(
        [100.0, 100.0], [100.0, 100.0], target_dscr_secured=1.20, target_dscr_merchant=1.40
    )
    assert dscr == pytest.approx(1.20)


def test_blended_target_dscr_mixed_revenue():
    # 50% securise -> pile au milieu.
    dscr = co.blended_target_dscr(
        [50.0, 50.0], [100.0, 100.0], target_dscr_secured=1.20, target_dscr_merchant=1.40
    )
    assert dscr == pytest.approx(1.30)


def test_blended_target_dscr_zero_revenue_falls_back_to_merchant():
    dscr = co.blended_target_dscr([0.0], [0.0], target_dscr_secured=1.20, target_dscr_merchant=1.40)
    assert dscr == pytest.approx(1.40)


def test_blended_buyer_target_equity_irr_full_merchant():
    irr = co.blended_buyer_target_equity_irr(
        [0.0, 0.0], [100.0, 100.0], target_irr_secured=0.09, target_irr_merchant=0.11
    )
    assert irr == pytest.approx(0.11)


def test_blended_buyer_target_equity_irr_fully_secured():
    irr = co.blended_buyer_target_equity_irr(
        [100.0, 100.0], [100.0, 100.0], target_irr_secured=0.09, target_irr_merchant=0.11
    )
    assert irr == pytest.approx(0.09)


def test_blended_buyer_target_equity_irr_mixed_revenue():
    irr = co.blended_buyer_target_equity_irr(
        [50.0, 50.0], [100.0, 100.0], target_irr_secured=0.09, target_irr_merchant=0.11
    )
    assert irr == pytest.approx(0.10)


def test_debt_maturity_full_merchant():
    maturity = co.debt_maturity_years(
        co.ContractStructure(kind=co.FULL_MERCHANT),
        maturity_full_merchant_years=10,
        maturity_years_added_after_ppa=3,
    )
    assert maturity == 10


def test_debt_maturity_tolling_is_ppa_plus_3():
    maturity = co.debt_maturity_years(
        co.ContractStructure(kind=co.TOLLING, duration_years=8),
        maturity_full_merchant_years=10,
        maturity_years_added_after_ppa=3,
    )
    assert maturity == 11
