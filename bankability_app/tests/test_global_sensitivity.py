import pytest

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


def test_run_global_sensitivity_excludes_htb3_without_mentioning_it(au_store, copex_library):
    """HTB3 n'a jamais de donnees CAPEX/OPEX (ni Aurora ni ICP) - limite permanente,
    pas une donnee manquante ponctuelle : exclue silencieusement des lignes ET du
    resume `skipped` (demande de l'utilisateur, 2026-09-24 - ne plus mentionner HTB3
    dans l'UI)."""
    rows, skipped = global_sensitivity.run_global_sensitivity(
        au_store, copex_library, operating_years=10, contract_kinds=[contract_overlay.FULL_MERCHANT]
    )
    assert all(r.tension != "HTB3" for r in rows)
    assert not any("HTB3" in message for message in skipped)


def test_run_global_sensitivity_rows_have_computed_kpis(au_store, copex_library):
    rows, _ = global_sensitivity.run_global_sensitivity(
        au_store,
        copex_library,
        operating_years=10,
        contract_kinds=[contract_overlay.FULL_MERCHANT],
    )
    assert rows
    assert all(r.row.project_irr is not None for r in rows)


def test_enumerate_configs_propagates_oro_request_from_au_config(au_store, copex_library):
    """Sans `oro_requested=au_config.oro`, un au_config ORO et son equivalent
    standard (meme duree_h/tension/turpe_type/gabarit) resoudraient tous les
    deux vers la courbe standard - 2 entrees identiques au lieu d'une ligne ORO
    distincte (voir docs/specs/global_sensitivity.md, 2026-09-23)."""
    entries = global_sensitivity.enumerate_configs(
        au_store, copex_library, contract_kinds=[contract_overlay.FULL_MERCHANT]
    )
    oro_entries = [e for e in entries if e[0].oro]
    assert oro_entries
    assert all(project_config.oro_requested for _, _, project_config in oro_entries)
    standard_entries = [e for e in entries if not e[0].oro]
    assert all(not project_config.oro_requested for _, _, project_config in standard_entries)


def test_run_global_sensitivity_oro_row_has_lower_revenue_than_standard_sibling(
    au_store, copex_library
):
    rows, _ = global_sensitivity.run_global_sensitivity(
        au_store,
        copex_library,
        operating_years=5,
        contract_kinds=[contract_overlay.FULL_MERCHANT],
    )
    oro_row = next(
        r
        for r in rows
        if r.oro and r.tension == "HTB2" and r.turpe_type == "Injection" and r.duree_h == 2
    )
    standard_row = next(
        r
        for r in rows
        if not r.oro
        and r.tension == "HTB2"
        and r.turpe_type == "Injection"
        and not r.gabarit
        and r.duree_h == 2
        and r.cod_year == oro_row.cod_year
    )
    assert oro_row.row.revenue_total_keur < standard_row.row.revenue_total_keur


def test_enumerate_configs_uses_a_different_power_per_tension(au_store, copex_library):
    """Retour utilisateur, 2026-10-01 : une seule puissance pour toutes les
    tensions produit des cas incoherents (ex. 50 MW en HTA, un raccordement
    distribution qui ne supporte pas ce calibre) - chaque tension doit garder
    sa propre puissance de reference."""
    entries = global_sensitivity.enumerate_configs(
        au_store,
        copex_library,
        contract_kinds=[contract_overlay.FULL_MERCHANT],
        power_mw_by_tension={"HTA": 7.0, "HTB1": 30.0, "HTB2": 60.0, "HTB3": 60.0},
    )
    power_by_tension = {
        project_config.tension: project_config.power_mw for _, _, project_config in entries
    }
    assert power_by_tension["HTA"] == 7.0
    assert power_by_tension["HTB1"] == 30.0
    assert power_by_tension["HTB2"] == 60.0


def test_enumerate_configs_raises_for_tension_missing_from_power_mw_mapping(
    au_store, copex_library
):
    with pytest.raises(ValueError, match="HTA"):
        global_sensitivity.enumerate_configs(
            au_store,
            copex_library,
            contract_kinds=[contract_overlay.FULL_MERCHANT],
            power_mw_by_tension={"HTB1": 30.0, "HTB2": 60.0, "HTB3": 60.0},
        )


def test_enumerate_configs_defaults_to_default_power_mw_by_tension(au_store, copex_library):
    entries = global_sensitivity.enumerate_configs(
        au_store, copex_library, contract_kinds=[contract_overlay.FULL_MERCHANT]
    )
    for _, _, project_config in entries:
        assert (
            project_config.power_mw
            == global_sensitivity.DEFAULT_POWER_MW_BY_TENSION[project_config.tension]
        )


def test_enumerate_configs_defaults_repowering_to_manual_year_15(au_store, copex_library):
    """Retour utilisateur, 2026-10-01 : sans optimize_repowering, le balayage
    global doit rester sur le defaut ProjectConfig (manual/15) - comportement
    inchange par defaut, pour ne pas ralentir silencieusement le balayage
    complet (voir core/portfolio.py, commentaire sur ProjectConfig.repowering_year_mode)."""
    entries = global_sensitivity.enumerate_configs(
        au_store, copex_library, contract_kinds=[contract_overlay.FULL_MERCHANT]
    )
    assert all(pc.repowering_year_mode == "manual" for _, _, pc in entries)
    assert all(pc.repowering_op_year_manual == 15 for _, _, pc in entries)


def test_enumerate_configs_optimize_repowering_sets_auto_mode(au_store, copex_library):
    """`optimize_repowering=True` doit reproduire le mode "auto" pre-selectionne
    par defaut dans le formulaire du Configurateur (ui/configurateur_tab.py) -
    necessaire pour obtenir des TRI comparables entre Aurora Global Analysis
    et le Configurateur sur une meme config (retour utilisateur, 2026-10-01 :
    un meme cas HTA 2h gabarit Injection COD2028 donnait +5.5% TRI Projet dans
    le Configurateur (repowering optimise) contre -0.9% dans Global Analysis
    (repowering force a l'annee 15))."""
    entries = global_sensitivity.enumerate_configs(
        au_store,
        copex_library,
        contract_kinds=[contract_overlay.FULL_MERCHANT],
        optimize_repowering=True,
    )
    assert all(pc.repowering_year_mode == "auto" for _, _, pc in entries)


def test_run_global_sensitivity_optimize_repowering_exposes_resolved_year(au_store, copex_library):
    """`repowering_auto_optimized` doit etre `True` pour TOUTE ligne calculee
    avec `optimize_repowering=True`, meme quand l'optimisation conclut "pas de
    repowering" (`repowering_op_year_used is None`, qui gagne tres souvent -
    voir core/portfolio.py `find_best_repowering_op_year`, 2026-10-01) - ce
    champ signifie "optimisation appliquee", pas "une annee a ete retenue"."""
    rows, _ = global_sensitivity.run_global_sensitivity(
        au_store,
        copex_library,
        operating_years=20,
        contract_kinds=[contract_overlay.FULL_MERCHANT],
        optimize_repowering=True,
    )
    assert rows
    assert all(r.row.repowering_auto_optimized for r in rows)
