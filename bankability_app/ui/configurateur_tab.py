"""Configurateur Aurora : saisie directe de N projets (sans upload de BP) ->
core.portfolio.run_portfolio -> tableau de KPI comparatif. Voir
docs/specs/aurora_v2_methodology.md section 4, docs/specs/portfolio.md.

Les courbes de revenu/TURPE (AU_Store) viennent de l'asset statique
`config/aurora_curves_22configs.json` (core.aur_cases.load_aurora_curves) -
universelles, memes valeurs pour tout projet, verifiees a la decimale contre
le databook Aurora Q2 2026 brut (voir docs/specs/aur_cases.md) - pas re-parsees
depuis un classeur uploade. COPEX_library (CAPEX/OPEX) reste la reference
("primary") - demande explicite de l'utilisateur, 2026-10-01 - completee
poste par poste par le databook Aurora Q2 2026 la ou le fixture n'a aucune
donnee (ex. HTB3, jamais couvert par le fixture) - voir
`core.dev_case.merge_copex_libraries`, docs/specs/copex_comparison.md.

Textes UI en anglais depuis le 2026-09-24 (demande de l'utilisateur) - TURPE/
HTA/HTB1/HTB2/HTB3/gabarit/ORO restent en francais (vocabulaire reglementaire
reseau francais sans equivalent anglais propre), une note l'explique dans le
formulaire. Commentaires/docstrings du code restent en francais (langue de
travail du projet, pas une donnee UI)."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import (
    aur_cases,
    config_extrapolation,
    config_space,
    contract_overlay,
    copex_comparison,
    copex_icp,
    portfolio,
    portfolio_import,
)
from ui import chart_theme

SAMPLE_AURORA_BP_PATH = (
    Path(__file__).resolve().parent.parent / "sample_data" / "160926_BP_Stockage_Standalone__.xlsx"
)

_CONTRACT_LABELS = {
    contract_overlay.FULL_MERCHANT: "Full merchant",
    contract_overlay.FLOOR: "Floor",
    contract_overlay.TOLLING: "Tolling",
}


@st.cache_resource
def load_library() -> tuple[aur_cases.AuStoreLibrary, object, dict]:
    """`copex_library` (CAPEX/OPEX Aurora) = fixture `COPEX_library` en
    primaire, complete par le databook Aurora Q2 2026 poste par poste la ou
    le fixture n'a aucune donnee - demande explicite de l'utilisateur,
    2026-10-01 : garder les hypotheses du fixture comme reference, ne
    retomber sur le Q2 2026 que pour combler un trou (ex. HTB3). Voir
    `core.dev_case.merge_copex_libraries`, docs/specs/copex_comparison.md."""
    from core.dev_case import load_copex_library_q2_2026, merge_copex_libraries
    from core.dev_case_parser import load_dev_case_grids, parse_copex_library

    au_store = aur_cases.load_aurora_curves()
    _, copex_grid, _ = load_dev_case_grids(SAMPLE_AURORA_BP_PATH)
    fixture_library = parse_copex_library(copex_grid)
    q2_2026_library = load_copex_library_q2_2026()
    copex_library = merge_copex_libraries(fixture_library, q2_2026_library)
    financing_terms = aur_cases.load_financing_terms()
    return au_store, copex_library, financing_terms


def _fmt_keur(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f} k€".replace(",", " ")


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _df_to_excel_bytes(df: pd.DataFrame, sheet_name: str) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buffer.getvalue()


def _download_results_button(df: pd.DataFrame, *, label: str, filename: str, key: str) -> None:
    st.download_button(
        f"Download {label} results (Excel)",
        data=_df_to_excel_bytes(df, sheet_name=label[:31]),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key,
    )


def _render_bulk_import() -> None:
    """Alternative a la saisie projet par projet (`_render_add_project_form`)
    - demande de l'utilisateur, 2026-09-28 : l'app n'a pas de memoire entre
    sessions, donc plutot que de re-saisir chaque projet a la main a chaque
    ouverture, l'utilisateur maintient sa propre liste dans un fichier Excel
    qu'il reupload. Remplace entierement `portfolio_projects` (pas un ajout)
    - plus simple, pas d'ambiguite sur d'eventuels doublons avec la saisie
    manuelle deja en session."""
    with st.expander("Bulk import from Excel (replaces the list below)"):
        st.caption(
            "One row per project. Download the template for the exact column format and "
            "allowed values (a 'Legend' sheet explains each column)."
        )
        st.download_button(
            "Download template (.xlsx)",
            data=portfolio_import.template_bytes(),
            file_name="aurora_configurator_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        uploaded = st.file_uploader("Upload a filled-in template", type=["xlsx"], key="bulk_import")
        # `file_uploader` keeps its value across reruns until the user picks a
        # new file - sans ce garde-fou, le st.rerun() ci-dessous re-parserait
        # et re-remplacerait la liste en boucle a chaque interaction ulterieure
        # de la page (widget non "consomme" par nature dans Streamlit).
        if uploaded is not None and uploaded.file_id != st.session_state.get(
            "_bulk_import_last_file_id"
        ):
            try:
                projects = portfolio_import.parse_portfolio_excel(uploaded)
            except ValueError as exc:
                st.error(f"Import error: {exc}")
                return
            st.session_state["_bulk_import_last_file_id"] = uploaded.file_id
            st.session_state["portfolio_projects"] = projects
            st.success(f"{len(projects)} project(s) loaded from the file.")
            st.rerun()


def _safe_index(options: list, value) -> int:
    """Index de `value` dans `options`, ou 0 si absent - jamais une exception
    (ex. en mode edition, si l'utilisateur change une dimension en amont -
    duree/tension/TURPE type - et que la valeur sauvegardee du projet edite
    ne fait plus partie des options recalculees pour la nouvelle combo)."""
    return options.index(value) if value in options else 0


def _render_add_project_form(
    au_store: aur_cases.AuStoreLibrary, copex_library, financing_terms: dict
) -> None:
    projects: list[portfolio.ProjectConfig] = st.session_state["portfolio_projects"]
    editing_index = st.session_state.get("editing_project_index")
    editing_project = (
        projects[editing_index]
        if editing_index is not None and editing_index < len(projects)
        else None
    )

    st.subheader("Edit project" if editing_project is not None else "Add a project")
    st.caption(
        "TURPE, HTA/HTB1/HTB2/HTB3, Gabarit and ORO are French grid regulatory terms with no "
        "direct English equivalent, kept as-is — TURPE is the French grid usage tariff; "
        "HTA/HTB1/HTB2/HTB3 are French grid voltage tiers (HTA ≈ medium voltage, "
        "HTB1/2/3 ≈ increasing high-voltage tiers); Gabarit is a French grid connection profile "
        "option; ORO (Offre de Raccordement Optimisé) is a non-firm connection offer capped at "
        "~3000h/year of curtailment."
    )
    # Suffixe de `key` stable pour TOUS les widgets de ce formulaire (ci-dessous) - PAS
    # `name` (bug corrige le 2026-10-01, signale par l'utilisateur : `name` est un
    # `st.text_input` retape a chaque caractere, donc `key=f"..._{name}"` change de cle a
    # CHAQUE frappe - Streamlit traite alors le widget comme neuf et perd sa valeur deja
    # saisie, ex. mode "Manual value" + 250 k€ de raccordement, remis a "library"/0 des
    # que l'utilisateur finit de taper/modifie le nom du projet).
    #
    # En mode edition (2026-10-01, demande utilisateur : "je veux pouvoir editer"),
    # `form_id` est propre a CE projet (`edit{index}`) plutot que base sur le compteur de
    # projets ajoutes - sans ca, les widgets de ce formulaire partageraient leur cle avec
    # le formulaire "Add a project" (ou avec l'edition d'un AUTRE projet), et Streamlit ne
    # les reinitialiserait jamais aux valeurs du projet qu'on vient d'ouvrir en edition
    # (un widget garde son etat tant que sa cle ne change pas, le parametre `value=` n'est
    # qu'un defaut initial, ignore silencieusement une fois l'etat deja present).
    form_id = f"edit{editing_index}" if editing_project is not None else len(projects)

    def _default(attr: str, fallback):
        return getattr(editing_project, attr) if editing_project is not None else fallback

    c1, c2, c3 = st.columns(3)
    with c1:
        name = st.text_input(
            "Project name",
            value=_default("name", f"Project {len(projects) + 1}"),
            key=f"name_{form_id}",
        )
        duree_options = config_space.durations(au_store)
        duree_h = st.selectbox(
            "BESS duration (h)",
            duree_options,
            index=_safe_index(duree_options, _default("duree_h", duree_options[0])),
            key=f"duree_{form_id}",
        )
        tension_options = config_space.tensions(
            au_store, duree_h=duree_h, copex_library=copex_library
        )
        tension = st.selectbox(
            "Voltage (Tension)",
            tension_options,
            index=_safe_index(tension_options, _default("tension", tension_options[0])),
            key=f"tension_{form_id}",
        )
    with c2:
        turpe_type_options = config_space.turpe_types(au_store, duree_h=duree_h, tension=tension)
        turpe_type = st.selectbox(
            "TURPE type",
            turpe_type_options,
            index=_safe_index(turpe_type_options, _default("turpe_type", turpe_type_options[0])),
            key=f"turpe_type_{form_id}",
        )
        gabarit_options = config_space.gabarit_options(
            au_store, duree_h=duree_h, tension=tension, turpe_type=turpe_type
        )
        gabarit = st.selectbox(
            "Gabarit",
            gabarit_options,
            index=_safe_index(gabarit_options, _default("gabarit", gabarit_options[0])),
            format_func=lambda g: "Yes" if g else "No",
            key=f"gabarit_{form_id}",
        )
        if gabarit_options == [False]:
            st.caption('Gabarit "Yes" unavailable for TURPE Classique (never combined).')
        oro_options = config_space.oro_options(turpe_type=turpe_type)
        oro_requested = st.checkbox(
            "ORO (injection/consumption capped at 3000h/year)",
            value=_default("oro_requested", False),
            key=f"oro_{form_id}",
            disabled=oro_options == [False],
        )
        if oro_options == [False]:
            st.caption(
                "ORO unavailable for TURPE Classique (specifically limits injection/consumption)."
            )
        curtailment_hours: int | None = None
        if oro_requested:
            curtailment_hours = st.number_input(
                "ORO curtailment hours (default 3000h)",
                value=_default("curtailment_hours", None) or 3000,
                min_value=500,
                max_value=4000,
                step=500,
                key=f"oro_hours_{form_id}",
            )
        power_mw = st.number_input(
            "Power (MW)", value=_default("power_mw", 10.0), min_value=0.1, key=f"power_{form_id}"
        )
    with c3:
        cod_year = st.number_input(
            "COD year",
            value=_default("cod_year", 2027),
            min_value=2027,
            max_value=2060,
            step=1,
            key=f"cod_{form_id}",
        )
        operating_years = st.number_input(
            "Operating life (years)",
            value=_default("operating_years", 20),
            min_value=1,
            step=1,
            key=f"opyears_{form_id}",
        )

    cod_invalid = False
    try:
        resolved = config_extrapolation.resolve_config(
            au_store,
            duree_h=duree_h,
            tension=tension,
            turpe_type=turpe_type,
            gabarit=gabarit,
            oro=oro_requested,
            curtailment_hours=curtailment_hours,
        )
        au_config = resolved.config
        if resolved.config.extrapolated:
            st.info(
                "⚠️ Combination not directly modelled by Aurora — **extrapolated** curve:\n"
                + "\n".join(f"- {note}" for note in resolved.notes)
            )
        cod_invalid = not config_space.is_cod_valid(au_config, int(cod_year))
        if cod_invalid:
            st.warning(
                f"This config is only modelled by Aurora for COD={au_config.valide_cod} "
                "- adjust the COD year above (the 'Add the project' button is disabled "
                "until then)."
            )
        elif not config_space.is_year_range_covered(
            resolved.library,
            au_config,
            cod_year=int(cod_year),
            operating_years=int(operating_years),
        ):
            cod_invalid = True
            st.warning(
                "This config's data doesn't cover the full COD -> COD + operating life span "
                "- adjust the COD year or the operating life above (the 'Add the project' "
                "button is disabled until then)."
            )
    except aur_cases.AuroraConfigError as exc:
        st.error(f"Combination with no business equivalent: {exc}")
        return

    st.markdown("**Contract structure**")
    existing_structure = _default("contract_structure", None)
    contract_kind_options = [
        contract_overlay.FULL_MERCHANT,
        contract_overlay.FLOOR,
        contract_overlay.TOLLING,
    ]
    c1, c2, c3 = st.columns(3)
    with c1:
        contract_kind = st.selectbox(
            "Structure",
            contract_kind_options,
            index=_safe_index(
                contract_kind_options,
                existing_structure.kind if existing_structure else contract_overlay.FULL_MERCHANT,
            ),
            format_func=lambda k: _CONTRACT_LABELS[k],
            key=f"contract_kind_{form_id}",
        )
    price = 0.0
    duration_years = 0
    sharing_pct = 0.0
    if contract_kind != contract_overlay.FULL_MERCHANT:
        with c2:
            price = st.number_input(
                "Price (k€/MW/yr)",
                value=existing_structure.price_keur_per_mw_per_year if existing_structure else 80.0,
                min_value=0.0,
                key=f"price_{form_id}",
            )
            duration_years = st.number_input(
                "Contract duration (years)",
                value=existing_structure.duration_years if existing_structure else 10,
                min_value=1,
                max_value=int(operating_years),
                step=1,
                key=f"contract_duration_{form_id}",
            )
        if contract_kind == contract_overlay.FLOOR:
            with c3:
                sharing_pct = (
                    st.number_input(
                        "Aggregator sharing above the floor (%)",
                        value=(
                            existing_structure.revenue_sharing_above_floor_pct * 100
                            if existing_structure
                            else 0.0
                        ),
                        min_value=0.0,
                        max_value=100.0,
                        key=f"sharing_{form_id}",
                    )
                    / 100
                )

    st.markdown("**Repowering** (Battery+PCS replacement, degradation reset)")
    min_years_for_repowering = portfolio.MIN_OPERATING_YEARS_FOR_REPOWERING
    repowering_candidates = portfolio.repowering_candidate_years(int(operating_years), duree_h)
    if not repowering_candidates:
        st.caption(
            f"Unavailable for an operating life < {min_years_for_repowering} years "
            f"(currently {int(operating_years)} years) — not enough remaining life for a "
            "battery replacement to make economic sense."
        )
        repowering_enabled = False
        repowering_year_mode = "manual"
        repowering_op_year_manual = 15
    else:
        repowering_enabled = st.checkbox(
            "Enable repowering",
            value=_default("repowering_enabled", True),
            key=f"repo_enabled_{form_id}",
        )
        # Defaut "manual" a mi-vie (operating_years // 2), pas "auto" (retour
        # utilisateur, 2026-10-01) : l'optimisation Equity IRR reste
        # disponible en option, mais plus pre-selectionnee par defaut - elle
        # tend a pousser le repowering le plus tard possible (un artefact
        # IRR, voir core/portfolio.py `MAX_REPOWERING_OP_YEAR`), la ou la
        # moitie de la duree de vie du projet est un repere plus neutre par
        # defaut. Clampee dans la plage valide (le SoH peut la rendre plus
        # etroite que `[10, operating_years//2]` sur un 2h long - voir
        # `core/soh_degradation.py`). En mode edition, part de l'annee deja
        # choisie sur le projet plutot que de la mi-vie (clampee pareil).
        repowering_year_mode = "manual"
        default_manual_year = min(
            max(
                _default("repowering_op_year_manual", int(operating_years) // 2),
                repowering_candidates[0],
            ),
            repowering_candidates[-1],
        )
        repowering_op_year_manual = default_manual_year
        if repowering_enabled:
            repowering_year_mode_options = ["manual", "auto"]
            repowering_year_mode = st.radio(
                "Repowering year",
                repowering_year_mode_options,
                index=_safe_index(
                    repowering_year_mode_options, _default("repowering_year_mode", "manual")
                ),
                format_func=lambda m: {
                    "auto": "Automatically optimized (best Equity IRR)",
                    "manual": "Manual",
                }[m],
                key=f"repo_mode_{form_id}",
                horizontal=True,
            )
            if repowering_year_mode == "manual":
                repowering_op_year_manual = st.number_input(
                    "Repowering year (op-year since COD)",
                    value=default_manual_year,
                    min_value=repowering_candidates[0],
                    max_value=repowering_candidates[-1],
                    step=1,
                    key=f"repo_year_{form_id}",
                )
            else:
                st.caption(
                    f"Sweeps op-years {repowering_candidates[0]} to "
                    f"{repowering_candidates[-1]} and keeps whichever maximizes the Equity IRR "
                    "(Hold & Operate) — the chosen year is shown in the results."
                )

    with st.expander("Advanced overrides"):
        existing_gearing = _default("gearing_pct_override", None)
        existing_rate = _default("interest_rate_override", None)
        existing_devex = _default("devex_keur_override", None)
        existing_dsa = _default("dsa_keur_override", None)
        o1, o2, o3, o4 = st.columns(4)
        with o1:
            override_gearing = st.checkbox(
                "Override gearing", value=existing_gearing is not None, key=f"ov_gear_{form_id}"
            )
            gearing_pct_override = (
                st.number_input(
                    "Gearing (%)",
                    value=(existing_gearing * 100) if existing_gearing is not None else 70.0,
                    min_value=0.0,
                    max_value=100.0,
                    key=f"gear_val_{form_id}",
                )
                / 100
                if override_gearing
                else None
            )
        with o2:
            override_rate = st.checkbox(
                "Override interest rate", value=existing_rate is not None, key=f"ov_rate_{form_id}"
            )
            interest_rate_override = (
                st.number_input(
                    "Interest rate (%)",
                    value=(existing_rate * 100) if existing_rate is not None else 5.0,
                    min_value=0.0,
                    key=f"rate_val_{form_id}",
                )
                / 100
                if override_rate
                else None
            )
        with o4:
            override_devex = st.checkbox(
                "Override DEVEX", value=existing_devex is not None, key=f"ov_devex_{form_id}"
            )
            default_devex_keur = aur_cases.devex_keur_for_tension(tension, financing_terms)
            devex_keur_override = (
                st.number_input(
                    "DEVEX (k€)",
                    value=existing_devex if existing_devex is not None else default_devex_keur,
                    min_value=0.0,
                    key=f"devex_val_{form_id}",
                )
                if override_devex
                else None
            )
        with o3:
            override_dsa = st.checkbox(
                "Override DSA", value=existing_dsa is not None, key=f"ov_dsa_{form_id}"
            )
            # Le DSA par defaut tient compte du DEVEX deja resolu ci-dessus (override ou
            # defaut), pour que marge nette = TSP - DEVEX retombe exactement sur la marge
            # cible quand SPA = 0 (voir aur_cases.dsa_default_keur).
            effective_devex_keur = (
                devex_keur_override if devex_keur_override is not None else default_devex_keur
            )
            default_dsa_keur = aur_cases.dsa_default_keur(
                duree_h=duree_h,
                power_mw=power_mw,
                devex_keur=effective_devex_keur,
                terms=financing_terms,
            )
            dsa_keur_override = (
                st.number_input(
                    "DSA (k€)",
                    value=existing_dsa if existing_dsa is not None else default_dsa_keur,
                    min_value=0.0,
                    key=f"dsa_val_{form_id}",
                )
                if override_dsa
                else None
            )
            margin_per_mw = financing_terms[f"target_margin_keur_per_mw_{duree_h}h"]
            st.caption(
                f"Default: {_fmt_keur(default_dsa_keur)} (target margin {margin_per_mw:.0f} "
                f"k€/MW × {power_mw:.0f} MW + DEVEX {_fmt_keur(effective_devex_keur)})."
            )

        st.markdown(
            "**Grid connection CAPEX & land lease OPEX** (as in the Standalone Storage Business "
            "Plan 160926 — the only CAPEX/OPEX line items challengeable individually)"
        )
        with st.expander("Where do the other CAPEX/OPEX line items come from?"):
            for note in copex_icp.capex_opex_source_notes(tension):
                st.caption(note)
        connection_mode_options = ["library", "manual", "distance_rte"]
        a1, a2 = st.columns(2)
        with a1:
            connection_capex_mode = st.selectbox(
                "Grid connection CAPEX mode",
                connection_mode_options,
                index=_safe_index(
                    connection_mode_options, _default("connection_capex_mode", "library")
                ),
                format_func=lambda m: {
                    "library": "Library (segment/duration)",
                    "manual": "Manual value",
                    "distance_rte": "Distance to RTE substation",
                }[m],
                key=f"conn_mode_{form_id}",
            )
            manual_connection_capex_keur = 0.0
            distance_rte_km = 0.0
            if connection_capex_mode == "manual":
                manual_connection_capex_keur = st.number_input(
                    "Manual grid connection CAPEX (k€)",
                    value=_default("manual_connection_capex_keur", 0.0),
                    min_value=0.0,
                    key=f"manual_conn_val_{form_id}",
                )
            elif connection_capex_mode == "distance_rte":
                distance_rte_km = st.number_input(
                    "Distance to RTE substation (km)",
                    value=_default("distance_rte_km", 1.0) or 1.0,
                    min_value=0.0,
                    key=f"distance_val_{form_id}",
                )
                st.caption(
                    f"= 4650.7 × distance^0.239 = {_fmt_keur(4650.7 * distance_rte_km**0.239)}"
                )
        with a2:
            land_lease_opex_keur = st.number_input(
                "Land lease OPEX (k€/yr)",
                value=_default("land_lease_opex_keur", 0.0),
                min_value=0.0,
                key=f"land_lease_{form_id}",
                help="Replaces (not added to) Aurora's generic COPEX_library 'Land lease' "
                "estimate when set - leave at 0 to keep using that generic estimate.",
            )

        turpe_50pct_reduction = False
        if tension in ("HTB1", "HTB2", "HTB3"):
            turpe_50pct_reduction = st.checkbox(
                "TURPE 50% reduction",
                value=_default("turpe_50pct_reduction", False),
                key=f"turpe50_{form_id}",
                help="Code de l'énergie, annexe art. D.341-9: storage sites connected "
                "directly to RTE or to a ≥50kV infrastructure can get a 50% TURPE "
                "reduction, conditional on >10 GWh/yr of withdrawal and an off-peak "
                "withdrawal share ≥44% - a real BESS dispatch strategy, confirmed "
                "achievable by Aurora in a 2025 internal study they shared with QEF. "
                "This app does NOT verify eligibility (dispatch pattern, volume) - it's "
                "a scenario toggle, applied to BOTH TURPE components: the variable TURPE "
                "on the revenue side (halves core.aur_cases' TURPE series) AND the fixed "
                "part (halves the OPEX-side 'Grid charges' line, which bundles the TURPE "
                "fixed component + CTA) - see docs/specs/turpe_50pct_reduction.md.",
            )

    submit_label = "Save changes" if editing_project is not None else "Add the project"
    button_col, cancel_col = st.columns([3, 1])
    with button_col:
        submitted = st.button(submit_label, type="primary", disabled=cod_invalid)
    with cancel_col:
        if editing_project is not None and st.button("Cancel edit"):
            st.session_state["editing_project_index"] = None
            st.rerun()

    if submitted:
        project = portfolio.ProjectConfig(
            name=name,
            duree_h=int(duree_h),
            tension=tension,
            turpe_type=turpe_type,
            gabarit=gabarit,
            cod_year=int(cod_year),
            power_mw=float(power_mw),
            operating_years=int(operating_years),
            contract_structure=contract_overlay.ContractStructure(
                kind=contract_kind,
                price_keur_per_mw_per_year=float(price),
                duration_years=int(duration_years),
                revenue_sharing_above_floor_pct=float(sharing_pct),
            ),
            gearing_pct_override=gearing_pct_override,
            interest_rate_override=interest_rate_override,
            dsa_keur_override=dsa_keur_override,
            devex_keur_override=devex_keur_override,
            repowering_enabled=bool(repowering_enabled),
            repowering_year_mode=repowering_year_mode,
            repowering_op_year_manual=int(repowering_op_year_manual),
            connection_capex_mode=connection_capex_mode,
            manual_connection_capex_keur=float(manual_connection_capex_keur),
            distance_rte_km=float(distance_rte_km),
            land_lease_opex_keur=float(land_lease_opex_keur),
            turpe_50pct_reduction=bool(turpe_50pct_reduction),
            oro_requested=bool(oro_requested),
            curtailment_hours=int(curtailment_hours) if curtailment_hours is not None else None,
            # Pas exposes dans ce formulaire (seulement via import en masse,
            # voir core/portfolio_import.py) - preserves du projet edite plutot
            # que silencieusement remis a None en sauvegardant un autre champ.
            carry_months_override=_default("carry_months_override", None),
            carry_rate_override=_default("carry_rate_override", None),
        )
        if editing_project is not None:
            projects[editing_index] = project
            st.session_state["editing_project_index"] = None
        else:
            projects.append(project)
        st.rerun()


def _render_project_list() -> None:
    projects: list[portfolio.ProjectConfig] = st.session_state["portfolio_projects"]
    if not projects:
        st.caption("No project added yet.")
        return
    st.subheader(f"Portfolio projects ({len(projects)})")
    editing_index = st.session_state.get("editing_project_index")
    if editing_index is not None and editing_index < len(projects):
        st.info(
            f"Editing **{projects[editing_index].name}** — scroll up to the "
            "'Edit project' form, make your changes, then click 'Save changes'."
        )
    for i, project in enumerate(projects):
        c1, c2, c3 = st.columns([5, 1, 1])
        with c1:
            adjustments = []
            if project.connection_capex_mode == "manual":
                adjustments.append(
                    f"manual connection {_fmt_keur(project.manual_connection_capex_keur)}"
                )
            elif project.connection_capex_mode == "distance_rte":
                adjustments.append(f"connection {project.distance_rte_km:.0f} km")
            if project.land_lease_opex_keur != 0.0:
                adjustments.append(f"land lease {_fmt_keur(project.land_lease_opex_keur)}")
            if project.turpe_50pct_reduction:
                adjustments.append("TURPE 50%")
            if not project.repowering_enabled:
                adjustments.append("repowering disabled")
            elif project.repowering_year_mode == "manual":
                adjustments.append(f"repowering year {project.repowering_op_year_manual}")
            else:
                adjustments.append("repowering auto-optimized")
            adjustment_suffix = f" ({', '.join(adjustments)})" if adjustments else ""
            editing_suffix = " 🖊️ *(editing)*" if i == editing_index else ""
            st.write(
                f"**{project.name}** — {project.duree_h}h {project.tension} {project.turpe_type}"
                f"{' gabarit' if project.gabarit else ''}{' ORO' if project.oro_requested else ''}"
                f", COD {project.cod_year}, "
                f"{project.power_mw:.1f} MW, {_CONTRACT_LABELS[project.contract_structure.kind]}"
                f"{adjustment_suffix}{editing_suffix}"
            )
        with c2:
            if st.button("Edit", key=f"edit_{i}"):
                st.session_state["editing_project_index"] = i
                st.rerun()
        with c3:
            if st.button("Remove", key=f"remove_{i}"):
                projects.pop(i)
                # Garde l'index d'edition coherent avec le decalage de la liste -
                # jamais pointer sur le mauvais projet (ou un index hors limites)
                # apres une suppression.
                if editing_index is not None:
                    if editing_index == i:
                        st.session_state["editing_project_index"] = None
                    elif editing_index > i:
                        st.session_state["editing_project_index"] = editing_index - 1
                st.rerun()


def _bar_chart(
    labels: list[str], values: list[float | None], *, y_title: str, pct: bool = False
) -> go.Figure:
    # Serie unique -> le titre de l'axe nomme la grandeur, pas besoin de
    # legende ni de couleur d'identite distincte (skill dataviz).
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=[v if v is not None else 0.0 for v in values],
            marker_color=chart_theme.ENTITY["single_series"],
        )
    )
    fig.update_layout(
        yaxis_title=y_title,
        yaxis_tickformat=".0%" if pct else None,
        margin={"t": 20, "b": 20},
        showlegend=False,
    )
    return chart_theme.apply_layout(fig)


def _hold_and_operate_df(rows: list[portfolio.PortfolioRow]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Project": r.name,
                "Config": r.config_label,
                "Project IRR": _fmt_pct(r.project_irr),
                "Equity IRR": _fmt_pct(r.equity_irr),
                "NPV (k€)": _fmt_keur(r.npv_keur),
                "CAPEX (k€)": _fmt_keur(r.capex_total_keur),
                "Total revenue (k€)": _fmt_keur(r.revenue_total_keur),
                "DSCR avg/min": (
                    f"{r.dscr_avg:.2f}x / {r.dscr_min:.2f}x"
                    if r.dscr_avg is not None and r.dscr_min is not None
                    else "n/a"
                ),
                "Target DSCR used": f"{r.target_dscr_used:.2f}x",
                "Gearing used": _fmt_pct(r.gearing_used_pct),
                "Tenor (years)": r.debt_tenor_years,
                "Repowering": (
                    ("not worth it (optimized)" if r.repowering_auto_optimized else "disabled")
                    if r.repowering_op_year_used is None
                    else f"year {r.repowering_op_year_used}"
                    + (" (optimized)" if r.repowering_auto_optimized else "")
                ),
            }
            for r in rows
        ]
    )


def _render_hold_and_operate(
    rows: list[portfolio.PortfolioRow],
    *,
    projects: list[portfolio.ProjectConfig],
    au_store: aur_cases.AuStoreLibrary,
    copex_library,
    financing_terms: dict,
) -> None:
    st.caption(
        "Hold & Operate: the project stays in QEF's portfolio for its entire operating life — "
        "project and shareholder returns, no transaction."
    )
    with st.expander("How are these figures calculated?"):
        st.markdown(
            "This is the standard financial engine applied directly to the project, with no "
            "intermediate transaction:\n"
            "- **Project IRR**: IRR on the project's cashflows *before financing* — initial "
            "CAPEX (and any repowering) as outflows, revenue + OPEX + TURPE (CFADS) as inflows "
            "each year.\n"
            "- **Equity IRR**: IRR on *shareholder* cashflows — the equity contribution as the "
            "initial outflow (CAPEX minus the debt-financed share), debt service already "
            "deducted from CFADS as it comes in.\n"
            "- **Debt**: sized either by a fixed gearing ratio or to hold a target DSCR (default "
            "mode) — that target is itself a weighted average based on the secured/merchant "
            "revenue mix of the chosen contract (1.20x if 100% secured by floor/tolling, 1.40x "
            "if 100% merchant).\n"
            "- **NPV**: project cashflows discounted at the WACC.\n"
            "- **DSCR avg/min**: CFADS / debt service ratio, each operating year — the minimum "
            "is the metric lenders watch."
        )
    df = _hold_and_operate_df(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
    _download_results_button(
        df, label="Hold & Operate", filename="hold_and_operate_results.xlsx", key="dl_hold_operate"
    )
    st.caption(
        "Target DSCR and tenor already reflect the floor/tolling contract's effect on debt "
        "(secured tiering 1.20x/10yr vs merchant 1.40x/PPA+3yr, docs/adr/... section 2.2 of "
        "aur_v2_methodology.md) — not a separate assumption. Repowering 'optimized' = the year "
        "chosen automatically among the candidates to maximize Equity IRR."
    )
    names = [r.name for r in rows]
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            _bar_chart(names, [r.project_irr for r in rows], y_title="Project IRR", pct=True),
            use_container_width=True,
        )
    with c2:
        st.plotly_chart(
            _bar_chart(names, [r.equity_irr for r in rows], y_title="Equity IRR", pct=True),
            use_container_width=True,
        )

    st.divider()
    if st.checkbox(
        "Also show results with Aurora's own CAPEX/OPEX assumptions",
        help="Recomputes the table above using Aurora's own CAPEX/OPEX instead of ours "
        "(ICP + Aurora fallback) - same revenue, same financing terms, only the cost source "
        "changes (Aurora Q2 2026 databook, 'Costs assumptions' sheet - same copex_library used "
        "everywhere else in the app). See core/copex_comparison.py for how our costs compare "
        "to Aurora's.",
    ):
        try:
            rows_aurora = portfolio.run_portfolio(
                projects,
                au_store,
                copex_library,
                financing_terms,
                capex_opex_source="aurora",
            )
        except aur_cases.AuroraConfigError as exc:
            st.error(f"Calculation error with Aurora's CAPEX/OPEX assumptions: {exc}")
            return
        st.markdown("**With Aurora's own CAPEX/OPEX assumptions (Aurora Q2 2026 databook)**")
        df_aurora = _hold_and_operate_df(rows_aurora)
        st.dataframe(df_aurora, use_container_width=True, hide_index=True)
        _download_results_button(
            df_aurora,
            label="Hold & Operate (Aurora CAPEX-OPEX)",
            filename="hold_and_operate_results_aurora_costs.xlsx",
            key="dl_hold_operate_aurora",
        )


def _render_dev_and_sell(rows: list[portfolio.PortfolioRow]) -> None:
    st.caption(
        "Develop & sell at RtB: QEF's interest is the margin captured (DSA + SPA - DEVEX), "
        "market benchmark 50-100 k€/MW."
    )
    with st.expander("How are these figures calculated?"):
        st.markdown(
            "QEF develops the project up to Ready-to-Build (permits secured, not built) then "
            "sells it to a buyer who finances and operates it:\n"
            "- **DSA** (Development Services Agreement): the fixed amount paid at sale, "
            "calculated by default as `target development margin (per MW, per BESS duration) "
            "+ DEVEX` — a guaranteed amount, independent of the project's future profitability.\n"
            "- **SPA** (price top-up): never an input assumption — it is *solved for* so that "
            "the buyer's actually-realized equity IRR (who finances the DSA within their CAPEX, "
            "then operates the project) lands exactly on their target IRR (9%, provisional). A "
            "very profitable project gives a positive SPA (the buyer can pay more and still "
            "hit their target); if the DSA alone already exceeds what the profitability "
            "justifies, the SPA turns negative (a discount).\n"
            "- **TSP** (total sale price) = DSA + SPA.\n"
            "- **DEVEX**: the development cost actually incurred by QEF, a flat amount per "
            "voltage class (150 k€ at HTA, 300 k€ at HTB1/HTB2).\n"
            "- **Net margin** = TSP − DEVEX: QEF's actual profit, never to be confused with TSP "
            "(the gross price received)."
        )
    df = pd.DataFrame(
        [
            {
                "Project": r.name,
                "Config": r.config_label,
                "DSA (k€)": _fmt_keur(r.dsa_keur),
                "SPA (k€)": _fmt_keur(r.spa_keur),
                "TSP = DSA+SPA (k€)": _fmt_keur(r.tsp_keur),
                "DEVEX (k€)": _fmt_keur(r.devex_keur),
                "Net margin (k€)": _fmt_keur(r.net_margin_keur),
                "Net margin (k€/MW)": _fmt_keur(
                    r.net_margin_keur / r.power_mw if r.power_mw else None
                ),
            }
            for r in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
    _download_results_button(
        df, label="Develop & sell", filename="develop_and_sell_results.xlsx", key="dl_dev_sell"
    )
    margin_per_mw = [r.net_margin_keur / r.power_mw if r.power_mw else None for r in rows]
    fig = _bar_chart([r.name for r in rows], margin_per_mw, y_title="Net margin (k€/MW)")
    fig.add_hline(
        y=50,
        line_dash="dot",
        line_color=chart_theme.MUTED_INK,
        annotation_text="Low benchmark (50 k€/MW)",
    )
    fig.add_hline(
        y=100,
        line_dash="dot",
        line_color=chart_theme.MUTED_INK,
        annotation_text="High benchmark (100 k€/MW)",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        'RtB "secured revenue" buyer target IRR (floor/tolling) still **provisional** '
        "(9%, to be confirmed) — see docs/specs/aur_v2_methodology.md section 3.4."
    )


def _render_build_and_flip(rows: list[portfolio.PortfolioRow]) -> None:
    st.caption(
        "Buy RtB & sell at COD: QEF pays the RtB price, builds, resells the operating asset. "
        "Return = resale value − RtB price − CAPEX − carry cost."
    )
    with st.expander("How are these figures calculated?"):
        st.markdown(
            "This time QEF is the **buyer** of the Ready-to-Build project, then builds it and "
            "resells it once operating:\n"
            "- **RtB purchase price**: same DSA + SPA calculation as the « Develop & sell » tab "
            "(see its detail), simply from QEF's perspective as buyer.\n"
            "- **Construction CAPEX**: the project's initial CAPEX (excluding financing, "
            "excluding DSA).\n"
            "- **Carry cost**: compound interest on `(RtB price + construction CAPEX)` tied up "
            "between the RtB purchase and COD (18 months by default, 8% rate, provisional) — a "
            "flat estimate, not a detailed construction-debt drawdown schedule.\n"
            "- **Resale value at COD**: present value of the *unlevered* cashflows (before debt) "
            "of the operating phase, discounted at the final buyer's target IRR at resale — with "
            "no debt re-sized at resale, which **understates** the true market value (a buyer "
            "would normally benefit from leverage), see `docs/adr/0002`.\n"
            "- **Net return** = resale value − RtB purchase price − construction CAPEX − carry "
            "cost."
        )
    df = pd.DataFrame(
        [
            {
                "Project": r.name,
                "Config": r.config_label,
                "RtB purchase price (k€)": _fmt_keur(r.tsp_keur),
                "Construction CAPEX (k€)": _fmt_keur(r.capex_total_keur),
                "Carry cost (k€)": _fmt_keur(r.build_and_flip_carry_cost_keur),
                "Resale value at COD (k€)": _fmt_keur(r.resale_value_cod_keur),
                "Net return (k€)": _fmt_keur(r.build_and_flip_net_return_keur),
            }
            for r in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
    _download_results_button(
        df, label="Buy & flip", filename="buy_rtb_and_flip_results.xlsx", key="dl_buy_flip"
    )
    st.plotly_chart(
        _bar_chart(
            [r.name for r in rows],
            [r.build_and_flip_net_return_keur for r in rows],
            y_title="Net return (k€)",
        ),
        use_container_width=True,
    )
    st.caption(
        "Unlevered resale value (PV of post-COD cashflows at the buyer's target IRR, no "
        "debt re-sized) — understates true market value, see docs/adr/0002."
    )


def _copex_rows_to_df(rows: list[copex_comparison.CopexComparisonRow]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Line item": row.label,
                "Ours (k€)": _fmt_keur(row.ours_keur),
                "Aurora (k€)": _fmt_keur(row.aurora_keur),
                "Delta (k€)": _fmt_keur(row.delta_keur),
                "Delta %": f"{row.delta_pct:+.1%}" if row.delta_pct is not None else "n/a",
                "Status": row.status,
            }
            for row in rows
        ]
    )


def _unique_sheet_name(name: str, used: set[str]) -> str:
    # Limite Excel = 31 caracteres, noms uniques par classeur - un projet
    # dont le nom depasse cette limite (ou en collision apres troncature)
    # reste identifiable par un suffixe numerique plutot que d'ecraser une
    # autre feuille silencieusement.
    base = (name or "Project").strip()[:31] or "Project"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base[: 31 - len(str(suffix)) - 1]}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _dfs_to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buffer.getvalue()


def _download_multi_sheet_button(
    sheets: dict[str, pd.DataFrame], *, label: str, filename: str, key: str
) -> None:
    st.download_button(
        f"Download {label} (Excel, one sheet per project)",
        data=_dfs_to_excel_bytes(sheets),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key,
    )


def _render_copex_comparison(projects: list[portfolio.ProjectConfig], copex_library) -> None:
    """Compare notre CAPEX/OPEX (ICP + repli Aurora, deja applique par le
    moteur) a ce que la bibliotheque Aurora COPEX_library aurait donne
    seule - demande de l'utilisateur, 2026-09-30, sur le modele d'une macro
    VBA equivalente (`ModAuroraComparison`) deja utilisee sur le vrai BP
    Excel. Export Excel seul (un onglet CAPEX/OPEX par projet + un onglet
    Notes), rien affiche a l'ecran - demande de l'utilisateur, 2026-10-01
    ("pas la peine de faire apparaitre tous les tableaux dans la web app,
    juste le fichier excel d'extract me suffit"). Voir
    core/copex_comparison.py, docs/specs/copex_comparison.md."""
    if not st.checkbox("Aurora COPEX Comparison"):
        return
    st.caption(
        "Is our CAPEX/OPEX (ICP + Aurora fallback, as actually applied) below or above Aurora's "
        "own COPEX_library assumption? Download the Excel export below (one CAPEX/OPEX sheet per "
        "project, plus a Notes sheet)."
    )
    icp_library = copex_icp.load_icp_library_cached()
    all_notes: list[str] = []
    sheets: dict[str, pd.DataFrame] = {}
    used_sheet_names: set[str] = set()
    for project in projects:
        comparison = copex_comparison.compare_capex_opex(
            tension=project.tension,
            duree_h=project.duree_h,
            cod_year=project.cod_year,
            power_mw=project.power_mw,
            icp_library=icp_library,
            aurora_library=copex_library,
            connection_capex_mode=project.connection_capex_mode,
            manual_connection_capex_keur=project.manual_connection_capex_keur,
            distance_rte_km=project.distance_rte_km,
            land_lease_opex_keur=project.land_lease_opex_keur,
        )
        capex_df = _copex_rows_to_df(comparison.capex_rows)
        opex_df = _copex_rows_to_df(comparison.opex_rows)
        sheet_df = pd.concat(
            [
                pd.DataFrame([{"Line item": "CAPEX"}]),
                capex_df,
                pd.DataFrame([{"Line item": ""}, {"Line item": "OPEX"}]),
                opex_df,
            ],
            ignore_index=True,
        )
        sheets[_unique_sheet_name(project.name, used_sheet_names)] = sheet_df

        for note in comparison.notes:
            if note not in all_notes:
                all_notes.append(note)

    sheets["Notes"] = pd.DataFrame({"Note": all_notes})
    _download_multi_sheet_button(
        sheets,
        label="Aurora COPEX Comparison",
        filename="aurora_copex_comparison.xlsx",
        key="dl_copex_comp",
    )


def _render_best_configs(rows: list[portfolio.PortfolioRow]) -> None:
    st.subheader("Best configs")
    with_project_irr = [r for r in rows if r.project_irr is not None]
    c1, c2, c3 = st.columns(3)
    with c1:
        if with_project_irr:
            best = max(with_project_irr, key=lambda r: r.project_irr)
            st.metric("Best Project IRR (Hold & Operate)", _fmt_pct(best.project_irr), best.name)
        else:
            st.metric("Best Project IRR (Hold & Operate)", "n/a")
    with c2:
        best = max(rows, key=lambda r: r.net_margin_keur)
        st.metric(
            "Best net margin (Develop & sell)",
            _fmt_keur(best.net_margin_keur),
            best.name,
        )
    with c3:
        best = max(rows, key=lambda r: r.build_and_flip_net_return_keur)
        st.metric(
            "Best build-and-flip return",
            _fmt_keur(best.build_and_flip_net_return_keur),
            best.name,
        )


def _render_results(
    au_store: aur_cases.AuStoreLibrary,
    copex_library,
    financing_terms: dict,
) -> None:
    projects: list[portfolio.ProjectConfig] = st.session_state["portfolio_projects"]
    if not projects:
        return
    st.divider()
    st.subheader("Portfolio results")
    try:
        rows = portfolio.run_portfolio(projects, au_store, copex_library, financing_terms)
    except aur_cases.AuroraConfigError as exc:
        st.error(f"Calculation error: {exc}")
        return

    extrapolated_rows = [r for r in rows if r.extrapolated]
    if extrapolated_rows:
        with st.expander(
            f"⚠️ {len(extrapolated_rows)} project(s) with an extrapolated curve "
            "(not directly modelled by Aurora)",
            expanded=False,
        ):
            for r in extrapolated_rows:
                st.write(f"**{r.name}** ({r.config_label}):")
                for note in r.extrapolation_notes:
                    st.caption(f"- {note}")

    _render_copex_comparison(projects, copex_library)
    st.divider()

    _render_best_configs(rows)
    st.divider()

    tab1, tab2, tab3 = st.tabs(["Hold & Operate", "Develop & sell at RtB", "Buy RtB & sell at COD"])
    with tab1:
        _render_hold_and_operate(
            rows,
            projects=projects,
            au_store=au_store,
            copex_library=copex_library,
            financing_terms=financing_terms,
        )
    with tab2:
        _render_dev_and_sell(rows)
    with tab3:
        _render_build_and_flip(rows)


def render() -> None:
    st.caption(
        "Enter each project's characteristics directly — revenue comes from the Aurora "
        "Business Cases (AU_Store), CAPEX/OPEX from real unit costs (ICP), completed by "
        "Aurora for line items it doesn't cover. See docs/specs/aur_v2_methodology.md."
    )
    st.session_state.setdefault("portfolio_projects", [])
    st.session_state.setdefault("editing_project_index", None)
    au_store, copex_library, financing_terms = load_library()

    _render_bulk_import()
    st.divider()
    _render_add_project_form(au_store, copex_library, financing_terms)
    st.divider()
    _render_project_list()
    _render_results(au_store, copex_library, financing_terms)
