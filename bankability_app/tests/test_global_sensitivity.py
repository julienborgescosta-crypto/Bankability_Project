from core import contract_overlay, global_sensitivity


def test_valid_cod_years_for_calendar_matches_au_store_range(au_store):
    years = global_sensitivity.valid_cod_years_for_calendar(au_store, operating_years=20)
    assert years[0] == 2027
    assert years[-1] == 2060 - 20 + 1


def test_enumerate_configs_excludes_configs_without_cost_data(au_store, copex_library):
    """HTB3 est modelise par AU_Store mais absent de COPEX_library - exclu de
    l'enumeration en amont (docs/specs/global_sensitivity.md), pas genere pour
    echouer au calcul (voir aussi test_run_global_sensitivity_* ci-dessous)."""
    entries = global_sensitivity.enumerate_configs(
        au_store, copex_library, contract_kinds=[contract_overlay.FULL_MERCHANT]
    )
    au_configs_seen = {(e[0].duree_h, e[0].tension, e[0].turpe_type, e[0].gabarit) for e in entries}
    au_configs_expected = {
        (c.duree_h, c.tension, c.turpe_type, c.gabarit)
        for c in au_store.configs
        if c.tension != "HTB3"
    }
    assert au_configs_seen == au_configs_expected
    assert not any(tension == "HTB3" for _, tension, _, _ in au_configs_seen)


def test_enumerate_configs_respects_cod2030_only_guard(au_store, copex_library):
    entries = global_sensitivity.enumerate_configs(
        au_store, copex_library, contract_kinds=[contract_overlay.FULL_MERCHANT]
    )
    cod2030_only_cod_years = {
        project_config.cod_year
        for au_config, _, project_config in entries
        if au_config.valide_cod is not None
    }
    assert cod2030_only_cod_years == {2030}


def test_enumerate_configs_sweeps_all_contract_kinds_by_default(au_store, copex_library):
    entries = global_sensitivity.enumerate_configs(au_store, copex_library)
    kinds_seen = {kind for _, kind, _ in entries}
    assert kinds_seen == {
        contract_overlay.FULL_MERCHANT,
        contract_overlay.FLOOR,
        contract_overlay.TOLLING,
    }


def test_run_global_sensitivity_reports_htb3_exclusion_once(au_store, copex_library):
    rows, skipped = global_sensitivity.run_global_sensitivity(
        au_store, copex_library, operating_years=10, contract_kinds=[contract_overlay.FULL_MERCHANT]
    )
    assert all(r.tension != "HTB3" for r in rows)
    assert len(skipped) == 1
    assert "HTB3" in skipped[0]
    assert "COPEX_library" in skipped[0]


def test_run_global_sensitivity_rows_have_computed_kpis(au_store, copex_library):
    rows, _ = global_sensitivity.run_global_sensitivity(
        au_store,
        copex_library,
        operating_years=10,
        contract_kinds=[contract_overlay.FULL_MERCHANT],
    )
    assert rows
    assert all(r.row.project_irr is not None for r in rows)
