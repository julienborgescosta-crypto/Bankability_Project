import numpy_financial as npf
import pytest

from core import financial_engine


def test_annuity_payment_matches_formula():
    # 500 k€ @ 5% sur 2 ans : formule standard verifiee hors code.
    expected = 500.0 * 0.05 / (1 - (1.05) ** -2)
    assert financial_engine.annuity_payment(500.0, 0.05, 2) == pytest.approx(expected)


def test_annuity_payment_zero_rate_is_straight_line():
    assert financial_engine.annuity_payment(600.0, 0.0, 3) == pytest.approx(200.0)


def test_annuity_payment_no_principal_or_no_tenor_is_zero():
    assert financial_engine.annuity_payment(0.0, 0.05, 5) == 0.0
    assert financial_engine.annuity_payment(500.0, 0.05, 0) == 0.0


def test_present_value_matches_manual_discounting():
    pv = financial_engine.present_value([100.0, 100.0], 0.10)
    assert pv == pytest.approx(100 / 1.10 + 100 / 1.10**2)


def test_present_value_zero_rate_is_plain_sum():
    assert financial_engine.present_value([50.0, 30.0, 20.0], 0.0) == pytest.approx(100.0)


def test_sculpt_debt_service_hits_target_every_year():
    service = financial_engine.sculpt_debt_service([300.0, 600.0], 1.5)
    assert service == pytest.approx([200.0, 400.0])


def test_sculpt_debt_service_non_positive_target_is_zero():
    assert financial_engine.sculpt_debt_service([300.0, 600.0], 0.0) == [0.0, 0.0]


def test_capitalized_construction_interest_single_year_is_half_year_convention():
    idc = financial_engine.capitalized_construction_interest([1000.0], 0.05)
    assert idc == pytest.approx(1000.0 * ((1.05**0.5) - 1))


def test_capitalized_construction_interest_earlier_draws_accrue_more():
    idc = financial_engine.capitalized_construction_interest([500.0, 500.0], 0.05)
    idc_first_only = 500.0 * ((1.05**1.5) - 1)
    idc_second_only = 500.0 * ((1.05**0.5) - 1)
    assert idc == pytest.approx(idc_first_only + idc_second_only)
    assert idc_first_only > idc_second_only


def test_capitalized_construction_interest_no_draws_is_zero():
    assert financial_engine.capitalized_construction_interest([], 0.05) == 0.0


def test_compute_results_yearly_breakdown(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    expected_ds = 500.0 * 0.05 / (1 - 1.05**-2)

    construction, year1, year2 = result.yearly

    # Annee de construction : equity finance 100% du CAPEX (gearing 50% -> equity_share = -500),
    # pas de DSCR.
    assert construction.capex_keur == pytest.approx(-1000.0)
    assert construction.dscr is None
    assert construction.equity_cashflow_keur == pytest.approx(-500.0)

    # Annees d'exploitation : CFADS = 500 - 100 - 20 = 380, service de la dette identique
    # chaque annee (tenor=2), DSCR = CFADS / service.
    for year_result in (year1, year2):
        assert year_result.cfads_keur == pytest.approx(380.0)
        assert year_result.debt_service_keur == pytest.approx(expected_ds)
        assert year_result.dscr == pytest.approx(380.0 / expected_ds)
        assert year_result.equity_cashflow_keur == pytest.approx(380.0 - expected_ds)


def test_compute_results_aggregates(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    expected_ds = 500.0 * 0.05 / (1 - 1.05**-2)

    assert result.capex_total_keur == pytest.approx(1000.0)
    assert result.debt_amount_keur == pytest.approx(500.0)
    assert result.equity_amount_keur == pytest.approx(500.0)
    assert result.debt_service_keur == pytest.approx(expected_ds)
    assert result.dscr_min == pytest.approx(380.0 / expected_ds)
    assert result.dscr_avg == pytest.approx(380.0 / expected_ds)


def test_compute_results_irr_matches_hand_derived_cashflows(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    expected_ds = 500.0 * 0.05 / (1 - 1.05**-2)

    expected_project_irr = npf.irr([-1000.0, 380.0, 380.0])
    expected_equity_irr = npf.irr([-500.0, 380.0 - expected_ds, 380.0 - expected_ds])

    assert result.project_irr == pytest.approx(expected_project_irr)
    assert result.equity_irr == pytest.approx(expected_equity_irr)


def test_npv_uses_wacc_and_undiscounted_year_zero(simple_inputs):
    result = financial_engine.compute_results(simple_inputs)
    expected_npv = npf.npv(simple_inputs.wacc, [-1000.0, 380.0, 380.0])
    assert result.npv_keur == pytest.approx(expected_npv)


def test_multipliers_move_results_in_expected_direction(simple_inputs):
    base = financial_engine.compute_results(simple_inputs)
    higher_revenue = financial_engine.compute_results(simple_inputs, revenue_multiplier=1.2)
    higher_capex = financial_engine.compute_results(simple_inputs, capex_multiplier=1.2)
    higher_opex = financial_engine.compute_results(simple_inputs, opex_multiplier=1.2)

    assert higher_revenue.project_irr > base.project_irr
    assert higher_capex.project_irr < base.project_irr
    assert higher_opex.project_irr < base.project_irr


def test_interest_rate_adj_increases_debt_service(simple_inputs):
    base = financial_engine.compute_results(simple_inputs)
    stressed = financial_engine.compute_results(simple_inputs, interest_rate_adj=0.05)
    assert stressed.debt_service_keur > base.debt_service_keur
    assert stressed.dscr_min < base.dscr_min


def test_degradation_multipliers_reduce_revenue_and_dscr(simple_inputs):
    base = financial_engine.compute_results(simple_inputs)
    degraded = financial_engine.compute_results(
        simple_inputs, degradation_multipliers=[1.0, 0.5, 0.5]
    )
    assert degraded.yearly[1].revenue_keur == pytest.approx(base.yearly[1].revenue_keur * 0.5)
    assert degraded.dscr_min < base.dscr_min


def test_ramp_up_year_without_capex_or_revenue_has_no_debt_service(ramp_up_inputs):
    """Regression : une annee sans CAPEX mais aussi sans revenu (ramp-up avant la
    vraie mise en service) ne doit pas etre comptee comme une annee d'exploitation -
    sinon le DSCR de cette annee devient absurdement negatif (CFADS negatif / service
    de dette positif)."""
    result = financial_engine.compute_results(ramp_up_inputs)
    construction, ramp_up, op_year1, op_year2 = result.yearly

    assert ramp_up.capex_keur == 0.0
    assert ramp_up.revenue_keur == 0.0
    assert ramp_up.cfads_keur == pytest.approx(-10.0)
    assert ramp_up.debt_service_keur == 0.0
    assert ramp_up.dscr is None
    # Le CFADS negatif de l'annee de ramp-up est absorbe par l'equity, pas par la dette.
    assert ramp_up.equity_cashflow_keur == pytest.approx(-10.0)

    # Le service de la dette ne demarre qu'a la 1ere vraie annee d'exploitation.
    assert op_year1.debt_service_keur > 0
    assert op_year1.dscr is not None
    assert op_year1.dscr > 0


def test_equity_irr_is_none_without_equity(simple_inputs):
    result = financial_engine.compute_results(simple_inputs, gearing_pct=1.0)
    assert result.equity_amount_keur == pytest.approx(0.0)
    assert result.equity_irr is None


def test_annuity_inversion_round_trip():
    principal = financial_engine.debt_amount_from_annuity(183.60, 0.05, 3)
    assert financial_engine.annuity_payment(principal, 0.05, 3) == pytest.approx(183.60)


def test_debt_amount_from_annuity_zero_payment_or_tenor():
    assert financial_engine.debt_amount_from_annuity(0.0, 0.05, 5) == 0.0
    assert financial_engine.debt_amount_from_annuity(100.0, 0.05, 0) == 0.0


def test_dscr_sizing_requires_target_dscr(simple_inputs):
    assert simple_inputs.target_dscr is None
    with pytest.raises(ValueError, match="target_dscr"):
        financial_engine.compute_results(simple_inputs, debt_sizing_mode="dscr")


def test_unknown_debt_sizing_mode_raises(simple_inputs):
    with pytest.raises(ValueError, match="debt_sizing_mode"):
        financial_engine.compute_results(simple_inputs, debt_sizing_mode="sculpted-ish")


def test_dscr_sizing_hits_target_exactly_when_not_gearing_capped(simple_inputs):
    """CFADS constant (380) sur les 2 annees d'exploitation -> la dette dimensionnee
    pour target_dscr=1.5 doit produire un DSCR strictement egal a 1.5 chaque annee
    (pas juste >=), puisque le pire CFADS de la fenetre EST le CFADS de chaque annee."""
    result = financial_engine.compute_results(
        simple_inputs, debt_sizing_mode="dscr", target_dscr=1.5
    )
    assert result.dscr_min == pytest.approx(1.5)
    assert result.dscr_avg == pytest.approx(1.5)
    # Le gearing (50%) n'est pas la contrainte active ici : la dette dimensionnee
    # par DSCR doit rester sous le plafond de gearing.
    assert result.debt_amount_initial_keur < 0.5 * result.capex_total_initial_keur


def test_dscr_sizing_capped_by_gearing_when_target_is_lax(simple_inputs):
    """Un target_dscr tres bas impliquerait une dette superieure au plafond de
    gearing (50%) -> la dette est plafonnee (au plafond gearing x (CAPEX + IDC),
    pas juste gearing x CAPEX), et le DSCR resultant est alors MEILLEUR que le
    target (puisqu'on ne peut pas lever plus)."""
    result = financial_engine.compute_results(
        simple_inputs, debt_sizing_mode="dscr", target_dscr=0.5
    )
    draw = 0.5 * 1000.0  # gearing x CAPEX de l'annee de construction
    idc = financial_engine.capitalized_construction_interest([draw], 0.05)
    expected_cap = 0.5 * (result.capex_total_initial_keur + idc)
    assert result.debt_amount_initial_keur == pytest.approx(expected_cap)
    assert result.dscr_min > 0.5


def test_dscr_sizing_matches_gearing_mode_debt_amount_at_equivalent_target(simple_inputs):
    """Sanity check inter-mode : au meme montant de dette, les deux modes doivent
    produire le meme DSCR (le DSCR est une propriete du montant de dette, pas de
    la maniere dont on l'a choisi)."""
    dscr_result = financial_engine.compute_results(
        simple_inputs, debt_sizing_mode="dscr", target_dscr=1.5
    )
    gearing_equiv = dscr_result.debt_amount_initial_keur / dscr_result.capex_total_initial_keur
    gearing_result = financial_engine.compute_results(simple_inputs, gearing_pct=gearing_equiv)
    assert gearing_result.dscr_min == pytest.approx(dscr_result.dscr_min)


def test_dscr_sculpting_tracks_varying_cfads(varying_cfads_inputs):
    """CFADS varie chaque annee (200, 400, 300) - le service de la dette doit
    suivre cette variation (sculpting reel : CFADS_annee / target chaque annee),
    pas rester plat comme le ferait une annuite constante plafonnee par la pire
    annee. DSCR doit rester exactement egal a la cible chaque annee, meme si le
    service, lui, varie."""
    result = financial_engine.compute_results(
        varying_cfads_inputs, debt_sizing_mode="dscr", target_dscr=1.5
    )
    services = [y.debt_service_keur for y in result.yearly[1:4]]
    assert services[0] == pytest.approx(200.0 / 1.5)
    assert services[1] == pytest.approx(400.0 / 1.5)
    assert services[2] == pytest.approx(300.0 / 1.5)
    # Le service N'EST PAS constant : preuve que ce n'est pas une annuite deguisee.
    assert len({round(s, 2) for s in services}) == 3

    for year_result in result.yearly[1:4]:
        assert year_result.dscr == pytest.approx(1.5)

    # Verifie que ce n'est pas plafonne par le gearing (sinon DSCR > 1.5 partout).
    draw = 0.7 * 1000.0
    idc = financial_engine.capitalized_construction_interest([draw], 0.05)
    expected_principal = financial_engine.present_value(services, 0.05)
    assert expected_principal < 0.7 * (1000.0 + idc)
    assert result.debt_amount_initial_keur == pytest.approx(expected_principal)


def test_upfront_fee_increases_the_gearing_cap(simple_inputs):
    """Avec un target_dscr assez bas pour etre plafonne par le gearing, un
    upfront fee non nul doit AUGMENTER le plafond : le fee est finance au meme
    ratio de gearing que le CAPEX, donc gonfle le besoin de financement total."""
    without_fee = financial_engine.compute_results(
        simple_inputs, debt_sizing_mode="dscr", target_dscr=0.5
    )
    simple_inputs.senior_debt_upfront_fee_pct = 0.02
    with_fee = financial_engine.compute_results(
        simple_inputs, debt_sizing_mode="dscr", target_dscr=0.5
    )
    assert with_fee.debt_amount_initial_keur > without_fee.debt_amount_initial_keur


def test_gearing_mode_ignores_upfront_fee_and_idc(simple_inputs):
    """Le mode gearing fixe doit rester totalement insensible aux frais/IDC
    ajoutes pour le mode dscr - aucune regression de comportement attendue."""
    baseline = financial_engine.compute_results(simple_inputs, gearing_pct=0.5)
    simple_inputs.senior_debt_upfront_fee_pct = 0.05
    still_same = financial_engine.compute_results(simple_inputs, gearing_pct=0.5)
    assert still_same.debt_amount_initial_keur == pytest.approx(baseline.debt_amount_initial_keur)
    assert still_same.dscr_min == pytest.approx(baseline.dscr_min)


def test_dscr_sizing_two_tranches_sequential(repowering_inputs):
    """target_dscr assez strict (3.0) pour ne pas etre plafonne par le gearing sur
    aucune des deux tranches -> les deux doivent atteindre exactement ce DSCR
    dans leur fenetre respective (CFADS constant = 380 dans les deux fenetres)."""
    repowering_inputs.target_dscr = 3.0
    result = financial_engine.compute_results(repowering_inputs, debt_sizing_mode="dscr")

    assert result.debt_amount_initial_keur < 0.5 * result.capex_total_initial_keur
    assert result.debt_amount_repowering_keur < 0.6 * result.capex_total_repowering_keur

    # Annees 2026-2028 (indices 1-3) : tranche initiale active, DSCR == target.
    for i in (1, 2, 3):
        assert result.yearly[i].dscr == pytest.approx(3.0)
    # Annees 2029-2030 (indices 4-5) : tenor initial (3 ans) expire, pas encore de repowering.
    for i in (4, 5):
        assert result.yearly[i].dscr is None
    # Annees 2032-2033 (indices 7-8) : tranche repowering active, DSCR == target.
    for i in (7, 8):
        assert result.yearly[i].dscr == pytest.approx(3.0)
    # Annees 2034-2035 (indices 9-10) : tenor repowering (2 ans) expire.
    for i in (9, 10):
        assert result.yearly[i].dscr is None


def test_no_repowering_tranche_when_single_capex_year(simple_inputs):
    """simple_inputs n'a qu'une seule sortie de CAPEX -> pas de tranche repowering,
    comportement identique a avant l'introduction de la 2e tranche (non-regression)."""
    result = financial_engine.compute_results(simple_inputs)
    assert result.capex_total_repowering_keur == 0.0
    assert result.debt_amount_repowering_keur == 0.0
    assert result.debt_service_repowering_keur == 0.0
    assert result.capex_total_initial_keur == pytest.approx(result.capex_total_keur)


def test_repowering_tranche_uses_its_own_financing_terms(repowering_inputs):
    result = financial_engine.compute_results(repowering_inputs)

    assert result.capex_total_initial_keur == pytest.approx(1000.0)
    assert result.capex_total_repowering_keur == pytest.approx(600.0)
    assert result.debt_amount_initial_keur == pytest.approx(500.0)  # gearing 0.5
    assert result.debt_amount_repowering_keur == pytest.approx(360.0)  # gearing 0.6

    expected_ds_initial = financial_engine.annuity_payment(500.0, 0.05, 3)
    expected_ds_repowering = financial_engine.annuity_payment(360.0, 0.08, 2)
    assert result.debt_service_initial_keur == pytest.approx(expected_ds_initial)
    assert result.debt_service_repowering_keur == pytest.approx(expected_ds_repowering)


def test_repowering_year_is_capex_financed_by_repowering_equity(repowering_inputs):
    result = financial_engine.compute_results(repowering_inputs)
    repowering_year = result.yearly[6]  # 2031, index 6

    assert repowering_year.capex_keur == pytest.approx(-600.0)
    assert repowering_year.dscr is None
    # equity repowering = 600 - 360 = 240, finance 100% de cette annee de CAPEX.
    assert repowering_year.equity_cashflow_keur == pytest.approx(-240.0)


def test_debt_service_windows_dont_overlap_after_initial_tenor_expires(repowering_inputs):
    result = financial_engine.compute_results(repowering_inputs)
    # Index: 0=2025 construction, 1-5=2026-2030, 6=2031 repowering, 7-10=2032-2035.
    initial_ds = financial_engine.annuity_payment(500.0, 0.05, 3)
    repowering_ds = financial_engine.annuity_payment(360.0, 0.08, 2)

    # Tenor initial = 3 ans -> seules les 3 premieres annees d'exploitation (2026-2028) paient.
    for i in (1, 2, 3):
        assert result.yearly[i].debt_service_keur == pytest.approx(initial_ds)
    # 2029-2030 : dette initiale eteinte, dette repowering pas encore ouverte -> aucun service.
    for i in (4, 5):
        assert result.yearly[i].debt_service_keur == pytest.approx(0.0)
        assert result.yearly[i].dscr is None
    # 2032-2033 : dette repowering (tenor 2 ans).
    for i in (7, 8):
        assert result.yearly[i].debt_service_keur == pytest.approx(repowering_ds)
    # 2034-2035 : dette repowering eteinte -> aucun service.
    for i in (9, 10):
        assert result.yearly[i].debt_service_keur == pytest.approx(0.0)


def test_repowering_tranche_backward_compatible_with_debt_kwargs_override(repowering_inputs):
    """Les overrides passes en kwargs (comme le fait l'UI) doivent primer sur les
    valeurs de repowering_inputs, exactement comme pour la tranche initiale."""
    result = financial_engine.compute_results(
        repowering_inputs, repowering_gearing_pct=0.9, repowering_interest_rate=0.20
    )
    assert result.debt_amount_repowering_keur == pytest.approx(0.9 * 600.0)
