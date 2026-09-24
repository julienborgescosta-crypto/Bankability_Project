from core import config_space


def test_durations(au_store):
    assert config_space.durations(au_store) == [2, 4]


def test_tensions_for_duration(au_store):
    assert config_space.tensions(au_store, duree_h=2) == ["HTA", "HTB1", "HTB2", "HTB3"]


def test_tensions_excludes_htb3_when_copex_library_given(au_store, copex_library):
    tensions = config_space.tensions(au_store, duree_h=2, copex_library=copex_library)
    assert "HTB3" not in tensions
    assert tensions == ["HTA", "HTB1", "HTB2"]


def test_has_cost_data_false_for_htb3(au_store, copex_library):
    config = au_store.config_by_drop_key("2h HTB3 Classique g0")
    assert config_space.has_cost_data(config, copex_library) is False


def test_has_cost_data_true_for_hta(au_store, copex_library):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    assert config_space.has_cost_data(config, copex_library) is True


def test_turpe_types_for_htb2_2h(au_store):
    assert config_space.turpe_types(au_store, duree_h=2, tension="HTB2") == [
        "Classique",
        "Injection",
        "Soutirage",
    ]


def test_gabarit_options_classique_is_g0_only(au_store):
    assert config_space.gabarit_options(
        au_store, duree_h=2, tension="HTA", turpe_type="Classique"
    ) == [False]


def test_gabarit_options_htb2_injection_has_both(au_store):
    assert config_space.gabarit_options(
        au_store, duree_h=2, tension="HTB2", turpe_type="Injection"
    ) == [
        False,
        True,
    ]


def test_valid_cod_years_unrestricted_config(au_store):
    config = au_store.config_by_drop_key("2h HTA Classique g0")
    assert config_space.valid_cod_years(config, [2027, 2028, 2030]) == [2027, 2028, 2030]


def test_valid_cod_years_cod2030_only_config(au_store):
    config = au_store.config_by_drop_key("4h HTB2 Soutirage g1 (COD2030)")
    assert config_space.valid_cod_years(config, [2027, 2028, 2030]) == [2030]


def test_is_cod_valid(au_store):
    config = au_store.config_by_drop_key("4h HTB2 Injection g1 (COD2030)")
    assert config_space.is_cod_valid(config, 2030) is True
    assert config_space.is_cod_valid(config, 2027) is False


def test_turpe_types_always_full_set_even_when_aurora_didnt_model_it(au_store):
    # HTB1 n'a que Classique g0 dans AU_Store - les 3 types restent proposables
    # (extrapoles via core.config_extrapolation si necessaire, 2026-09-24).
    assert config_space.turpe_types(au_store, duree_h=2, tension="HTB1") == [
        "Classique",
        "Injection",
        "Soutirage",
    ]


def test_gabarit_options_always_both_for_non_classique_even_when_unmodelled(au_store):
    assert config_space.gabarit_options(
        au_store, duree_h=2, tension="HTB1", turpe_type="Injection"
    ) == [False, True]


def test_oro_options_classique_is_false_only():
    assert config_space.oro_options(turpe_type="Classique") == [False]


def test_oro_options_injection_has_both():
    assert config_space.oro_options(turpe_type="Injection") == [False, True]
