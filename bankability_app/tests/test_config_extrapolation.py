import pytest

from core import config_extrapolation
from core.aur_cases import AuroraConfigError


def test_resolve_config_returns_real_config_unextrapolated(au_store):
    resolved = config_extrapolation.resolve_config(
        au_store, duree_h=2, tension="HTB2", turpe_type="Injection", gabarit=False
    )
    assert resolved.config.extrapolated is False
    assert resolved.notes == []
    assert resolved.library is au_store


def test_resolve_config_extrapolates_missing_turpe_type(au_store):
    # HTB1 n'a que Classique g0 dans AU_Store - Injection n'existe pas.
    resolved = config_extrapolation.resolve_config(
        au_store, duree_h=2, tension="HTB1", turpe_type="Injection", gabarit=False
    )
    assert resolved.config.extrapolated is True
    assert resolved.notes
    assert "Injection" in resolved.notes[0]
    raw = resolved.library.raw_by_key[resolved.config.austore_key]
    classique = au_store.config_by_attributes(
        duree_h=2, tension="HTB1", turpe_type="Classique", gabarit=False
    )
    raw_classique = au_store.raw_by_key[classique.austore_key]
    # Le ratio HTB2 Injection/Classique est < 1 (voir docs) - l'extrapolation
    # doit donc rester sous la courbe Classique de HTB1, jamais au-dessus.
    assert raw[2027] < raw_classique[2027]


def test_resolve_config_extrapolated_curve_usable_downstream(au_store, copex_library):
    """La config synthetisee doit etre directement utilisable par
    aur_cases.build_project_inputs, comme n'importe quelle config reelle."""
    from core import aur_cases

    resolved = config_extrapolation.resolve_config(
        au_store, duree_h=2, tension="HTB1", turpe_type="Injection", gabarit=False
    )
    inputs = aur_cases.build_project_inputs(
        resolved.library,
        resolved.config,
        copex_library,
        cod_year=2027,
        power_mw=10.0,
        operating_years=5,
    )
    assert inputs.revenues_keur[1] > 0.0


def test_resolve_config_raises_for_gabarit_with_classique(au_store):
    with pytest.raises(AuroraConfigError):
        config_extrapolation.resolve_config(
            au_store, duree_h=2, tension="HTB1", turpe_type="Classique", gabarit=True
        )


def test_resolve_config_raises_for_oro_with_classique(au_store):
    with pytest.raises(AuroraConfigError):
        config_extrapolation.resolve_config(
            au_store, duree_h=2, tension="HTB1", turpe_type="Classique", gabarit=False, oro=True
        )


def test_resolve_config_raises_for_curtailment_hours_without_oro(au_store):
    with pytest.raises(AuroraConfigError):
        config_extrapolation.resolve_config(
            au_store,
            duree_h=2,
            tension="HTB2",
            turpe_type="Injection",
            gabarit=False,
            oro=False,
            curtailment_hours=2000,
        )


def test_resolve_config_uses_real_oro_curve_when_available(au_store):
    resolved = config_extrapolation.resolve_config(
        au_store, duree_h=2, tension="HTB2", turpe_type="Injection", gabarit=False, oro=True
    )
    assert resolved.config.extrapolated is False
    assert resolved.config.oro is True
    assert resolved.notes == []


def test_resolve_config_extrapolates_oro_for_unmodelled_tension(au_store):
    resolved = config_extrapolation.resolve_config(
        au_store, duree_h=2, tension="HTA", turpe_type="Injection", gabarit=False, oro=True
    )
    assert resolved.config.extrapolated is True
    assert any("ORO" in note for note in resolved.notes)
    raw_oro = resolved.library.raw_by_key[resolved.config.austore_key]
    standard = config_extrapolation.resolve_config(
        au_store, duree_h=2, tension="HTA", turpe_type="Injection", gabarit=False, oro=False
    )
    raw_standard = standard.library.raw_by_key[standard.config.austore_key]
    assert raw_oro[2027] < raw_standard[2027]


def test_resolve_config_combines_turpe_type_and_gabarit_extrapolation(au_store):
    """HTB1 gabarit n'existe nulle part - combine 2 extrapolations (type TURPE
    deja teste plus haut, ici on verifie que gabarit s'applique en plus)."""
    resolved = config_extrapolation.resolve_config(
        au_store, duree_h=2, tension="HTB1", turpe_type="Injection", gabarit=True
    )
    assert resolved.config.extrapolated is True
    assert len(resolved.notes) == 2
    without_gabarit = config_extrapolation.resolve_config(
        au_store, duree_h=2, tension="HTB1", turpe_type="Injection", gabarit=False
    )
    raw_with = resolved.library.raw_by_key[resolved.config.austore_key]
    raw_without = without_gabarit.library.raw_by_key[without_gabarit.config.austore_key]
    assert raw_with[2027] != pytest.approx(raw_without[2027])


def test_curtailment_loss_pct_interpolates_between_grid_points(au_store):
    loss_1000 = config_extrapolation.curtailment_loss_pct(1000)
    loss_1500 = config_extrapolation.curtailment_loss_pct(1500)
    loss_1250 = config_extrapolation.curtailment_loss_pct(1250)
    assert loss_1250[2027] == pytest.approx((loss_1000[2027] + loss_1500[2027]) / 2)


def test_curtailment_loss_pct_exact_grid_point_returned_directly(au_store):
    loss = config_extrapolation.curtailment_loss_pct(3000)
    assert loss[2027] == pytest.approx(0.21500680974603126)


def test_curtailment_loss_pct_raises_outside_analysed_range():
    with pytest.raises(AuroraConfigError):
        config_extrapolation.curtailment_loss_pct(100)
    with pytest.raises(AuroraConfigError):
        config_extrapolation.curtailment_loss_pct(5000)


def test_resolve_config_custom_curtailment_hours_rescales_relative_to_3000h(au_store):
    resolved_3000 = config_extrapolation.resolve_config(
        au_store,
        duree_h=2,
        tension="HTB2",
        turpe_type="Injection",
        gabarit=False,
        oro=True,
        curtailment_hours=3000,
    )
    resolved_1000 = config_extrapolation.resolve_config(
        au_store,
        duree_h=2,
        tension="HTB2",
        turpe_type="Injection",
        gabarit=False,
        oro=True,
        curtailment_hours=1000,
    )
    # 3000h reste la courbe reelle Aurora (pas d'ajustement d'heures) ; 1000h
    # doit etre extrapole et generer moins de curtailment (revenu plus haut).
    assert resolved_3000.config.extrapolated is False
    assert resolved_1000.config.extrapolated is True
    raw_3000 = resolved_3000.library.raw_by_key[resolved_3000.config.austore_key]
    raw_1000 = resolved_1000.library.raw_by_key[resolved_1000.config.austore_key]
    assert raw_1000[2027] > raw_3000[2027]
