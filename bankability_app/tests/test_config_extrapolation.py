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


def test_resolve_config_oro_extrapolation_keeps_full_calendar_year_coverage(au_store):
    """La seule reference ORO reelle pour 4h (HTB2 Soutirage, voir
    `_oro_raw_factor`) est verrouillee sur COD2030 : ses valeurs sont a 0
    hors de 2030-2059. Avant le fix (2026-09-24, bug signale par
    l'utilisateur), une config extrapolee via un ratio par annee calcule sur
    cette reference (ex. HTA 4h Soutirage gabarit ORO) perdait silencieusement
    2027-2029 - `revenue_and_turpe_series` levait ensuite "Year 2029 is
    outside the AU_Store range" pour n'importe quel COD < 2030, alors que la
    config n'est pourtant pas verrouillee sur un COD (`valide_cod` reste
    None, "toute"). Depuis le passage a un ratio moyen (2026-10-01, voir
    docstring du module), ce probleme ne peut plus se produire : le ratio
    moyen s'applique a toutes les annees de la courbe de depart, sans notion
    de "couverture" a preserver."""
    resolved = config_extrapolation.resolve_config(
        au_store, duree_h=4, tension="HTA", turpe_type="Soutirage", gabarit=True, oro=True
    )
    assert resolved.config.extrapolated is True
    assert resolved.config.valide_cod is None
    raw = resolved.library.raw_by_key[resolved.config.austore_key]
    assert min(raw) == 2027
    assert max(raw) == 2060


def test_resolve_config_oro_extrapolation_usable_for_cod_before_2030(au_store, copex_library):
    """Meme scenario que ci-dessus, verifie de bout en bout via
    build_project_inputs (COD=2029 aurait leve AuroraConfigError avant le
    fix, alors que rien dans la config elle-meme n'interdit ce COD)."""
    from core import aur_cases

    resolved = config_extrapolation.resolve_config(
        au_store, duree_h=4, tension="HTA", turpe_type="Soutirage", gabarit=True, oro=True
    )
    inputs = aur_cases.build_project_inputs(
        resolved.library,
        resolved.config,
        copex_library,
        cod_year=2029,
        power_mw=10.0,
        operating_years=5,
    )
    # index 0 = annee de construction (COD-1), legitimement a 0 - le premier
    # revenu reel est a l'index 1 (meme convention que
    # test_resolve_config_extrapolated_curve_usable_downstream ci-dessus).
    assert inputs.revenues_keur[1] > 0.0


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


def test_gabarit_raw_factor_same_order_of_magnitude_regardless_of_duration(au_store):
    """Retour utilisateur, 2026-10-01 : le TRI extrapole doit rester du meme
    ordre de grandeur que le TRI reel Aurora, quelle que soit la duree -
    avant le passage a un ratio moyen (plutot qu'un ratio par annee), le
    ratio gabarit 4h (calibre sur une reference HTB2 verrouillee sur
    COD2030) pouvait s'ecarter fortement du ratio 2h (calibre sur une
    reference non verrouillee) a cause d'un artefact propre au cas 4h,
    alors que les 2 durees devraient donner un effet gabarit du meme ordre
    (voir docs/specs/config_extrapolation.md, "Benchmark de reference")."""
    factor_2h = config_extrapolation._gabarit_raw_factor(
        au_store, duree_h=2, turpe_type="Injection"
    )
    factor_4h = config_extrapolation._gabarit_raw_factor(
        au_store, duree_h=4, turpe_type="Injection"
    )
    assert factor_2h == pytest.approx(factor_4h, abs=0.05)
