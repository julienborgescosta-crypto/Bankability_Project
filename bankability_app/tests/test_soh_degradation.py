import pytest

from core import soh_degradation


@pytest.fixture(scope="module")
def soh_curves():
    return soh_degradation.load_soh_curves()


def test_load_soh_curves_covers_both_durations(soh_curves):
    assert set(soh_curves) == {2, 4}


def test_soh_curves_start_at_bol_and_go_to_repowering_year(soh_curves):
    for duree_h in (2, 4):
        years = soh_curves[duree_h].soh_by_op_year
        assert min(years) == 0
        assert years[0] == pytest.approx(1.0)
        assert max(years) == 15


def test_2h_degrades_faster_than_4h(soh_curves):
    """1.5 cycle/jour (2h) contre 1 cycle/jour (4h) - cf. Aurora PDF, donc le
    2h doit avoir un SoH plus bas que le 4h a chaque annee commune."""
    for op_year in range(1, 16):
        assert soh_curves[2].soh_by_op_year[op_year] < soh_curves[4].soh_by_op_year[op_year]


def test_soh_at_op_year_returns_known_value_within_table(soh_curves):
    assert soh_degradation.soh_at_op_year(soh_curves[2], 15) == pytest.approx(0.69)
    assert soh_degradation.soh_at_op_year(soh_curves[4], 10) == pytest.approx(0.81)


def test_soh_at_op_year_extrapolates_linearly_beyond_table(soh_curves):
    """Pente de la queue de courbe (annees 11-15), verifiee manuellement :
    -0.015/an pour 2h (0.75->0.69 de 11 a 15), -0.01/an pour 4h
    (0.80->0.76)."""
    assert soh_degradation.soh_at_op_year(soh_curves[2], 20) == pytest.approx(0.69 - 0.015 * 5)
    assert soh_degradation.soh_at_op_year(soh_curves[4], 20) == pytest.approx(0.76 - 0.01 * 5)


def test_max_op_year_before_forced_repowering_matches_hand_computed_crossing(soh_curves):
    """SoH(17) = 0.69 - 0.015*2 = 0.66 = seuil 2h exact -> 17 reste sur,
    SoH(18) = 0.645 < 0.66 -> 18 ne l'est plus. Meme logique 4h (seuil
    0.6867, atteint entre 22 et 23)."""
    assert soh_degradation.max_op_year_before_forced_repowering(2, soh_curves) == 17
    assert soh_degradation.max_op_year_before_forced_repowering(4, soh_curves) == 22


def test_2h_crosses_threshold_before_4h():
    """Cycle plus intensif (1.5/jour vs 1/jour) -> degradation plus rapide ->
    seuil SoH atteint plus tot, meme si le seuil lui-meme (66% vs 68.67%) est
    legerement plus bas pour 2h."""
    assert soh_degradation.max_op_year_before_forced_repowering(
        2
    ) < soh_degradation.max_op_year_before_forced_repowering(4)
