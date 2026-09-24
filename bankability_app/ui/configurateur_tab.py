"""Configurateur Aurora : saisie directe de N projets (sans upload de BP) ->
core.portfolio.run_portfolio -> tableau de KPI comparatif. Voir
docs/specs/aurora_v2_methodology.md section 4, docs/specs/portfolio.md.

Les courbes de revenu/TURPE (AU_Store) viennent de l'asset statique
`config/aurora_curves_22configs.json` (core.aur_cases.load_aurora_curves) -
universelles, memes valeurs pour tout projet, verifiees a la decimale contre
le databook Aurora Q2 2026 brut (voir docs/specs/aur_cases.md) - pas re-parsees
depuis un classeur uploade. COPEX_library (CAPEX/OPEX), lui, reste lu depuis le
fixture Aurora commite (bibliotheque partagee, la meme pour tous les projets
du portefeuille, mais un poste distinct des courbes de revenu).

Textes UI en anglais depuis le 2026-09-24 (demande de l'utilisateur) - TURPE/
HTA/HTB1/HTB2/HTB3/gabarit/ORO restent en francais (vocabulaire reglementaire
reseau francais sans equivalent anglais propre), une note l'explique dans le
formulaire. Commentaires/docstrings du code restent en francais (langue de
travail du projet, pas une donnee UI)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import (
    aur_cases,
    config_extrapolation,
    config_space,
    contract_overlay,
    copex_icp,
    portfolio,
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
    from core.dev_case_parser import load_dev_case_grids, parse_copex_library

    au_store = aur_cases.load_aurora_curves()
    _, copex_grid, _ = load_dev_case_grids(SAMPLE_AURORA_BP_PATH)
    copex_library = parse_copex_library(copex_grid)
    financing_terms = aur_cases.load_financing_terms()
    return au_store, copex_library, financing_terms


def _fmt_keur(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f} k€".replace(",", " ")


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _render_add_project_form(
    au_store: aur_cases.AuStoreLibrary, copex_library, financing_terms: dict
) -> None:
    st.subheader("Add a project")
    st.caption(
        "TURPE, HTA/HTB1/HTB2/HTB3, Gabarit and ORO are French grid regulatory terms with no "
        "direct English equivalent, kept as-is — TURPE is the French grid usage tariff; "
        "HTA/HTB1/HTB2/HTB3 are French grid voltage tiers (HTA ≈ medium voltage, "
        "HTB1/2/3 ≈ increasing high-voltage tiers); Gabarit is a French grid connection profile "
        "option; ORO (Offre de Raccordement Optimisé) is a non-firm connection offer capped at "
        "~3000h/year of curtailment."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        name = st.text_input(
            "Project name", value=f"Project {len(st.session_state['portfolio_projects']) + 1}"
        )
        duree_h = st.selectbox("BESS duration (h)", config_space.durations(au_store))
        tension = st.selectbox(
            "Voltage (Tension)",
            config_space.tensions(au_store, duree_h=duree_h, copex_library=copex_library),
        )
    with c2:
        turpe_type = st.selectbox(
            "TURPE type", config_space.turpe_types(au_store, duree_h=duree_h, tension=tension)
        )
        gabarit_options = config_space.gabarit_options(
            au_store, duree_h=duree_h, tension=tension, turpe_type=turpe_type
        )
        gabarit = st.selectbox(
            "Gabarit", gabarit_options, format_func=lambda g: "Yes" if g else "No"
        )
        if gabarit_options == [False]:
            st.caption('Gabarit "Yes" unavailable for TURPE Classique (never combined).')
        oro_options = config_space.oro_options(turpe_type=turpe_type)
        oro_requested = st.checkbox(
            "ORO (injection/consumption capped at 3000h/year)",
            key=f"oro_{name}",
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
                value=3000,
                min_value=500,
                max_value=4000,
                step=500,
                key=f"oro_hours_{name}",
            )
        power_mw = st.number_input("Power (MW)", value=10.0, min_value=0.1)
    with c3:
        cod_year = st.number_input("COD year", value=2027, min_value=2027, max_value=2060, step=1)
        operating_years = st.number_input("Operating life (years)", value=20, min_value=1, step=1)

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
    c1, c2, c3 = st.columns(3)
    with c1:
        contract_kind = st.selectbox(
            "Structure",
            [contract_overlay.FULL_MERCHANT, contract_overlay.FLOOR, contract_overlay.TOLLING],
            format_func=lambda k: _CONTRACT_LABELS[k],
        )
    price = 0.0
    duration_years = 0
    sharing_pct = 0.0
    if contract_kind != contract_overlay.FULL_MERCHANT:
        with c2:
            price = st.number_input("Price (k€/MW/yr)", value=80.0, min_value=0.0)
            duration_years = st.number_input(
                "Contract duration (years)",
                value=10,
                min_value=1,
                max_value=int(operating_years),
                step=1,
            )
        if contract_kind == contract_overlay.FLOOR:
            with c3:
                sharing_pct = (
                    st.number_input(
                        "Aggregator sharing above the floor (%)",
                        value=0.0,
                        min_value=0.0,
                        max_value=100.0,
                    )
                    / 100
                )

    st.markdown("**Repowering** (Battery+PCS replacement, degradation reset)")
    min_years_for_repowering = portfolio.MIN_OPERATING_YEARS_FOR_REPOWERING
    repowering_candidates = portfolio.repowering_candidate_years(int(operating_years))
    if not repowering_candidates:
        st.caption(
            f"Unavailable for an operating life < {min_years_for_repowering} years "
            f"(currently {int(operating_years)} years) — not enough remaining life for a "
            "battery replacement to make economic sense."
        )
        repowering_enabled = False
        repowering_year_mode = "auto"
        repowering_op_year_manual = 15
    else:
        repowering_enabled = st.checkbox(
            "Enable repowering", value=True, key=f"repo_enabled_{name}"
        )
        repowering_year_mode = "auto"
        repowering_op_year_manual = repowering_candidates[len(repowering_candidates) // 2]
        if repowering_enabled:
            repowering_year_mode = st.radio(
                "Repowering year",
                ["auto", "manual"],
                format_func=lambda m: {
                    "auto": "Automatically optimized (best Equity IRR)",
                    "manual": "Manual",
                }[m],
                key=f"repo_mode_{name}",
                horizontal=True,
            )
            if repowering_year_mode == "manual":
                repowering_op_year_manual = st.number_input(
                    "Repowering year (op-year since COD)",
                    value=repowering_op_year_manual,
                    min_value=repowering_candidates[0],
                    max_value=repowering_candidates[-1],
                    step=1,
                    key=f"repo_year_{name}",
                )
            else:
                st.caption(
                    f"Sweeps op-years {repowering_candidates[0]} to "
                    f"{repowering_candidates[-1]} and keeps whichever maximizes the Equity IRR "
                    "(Hold & Operate) — the chosen year is shown in the results."
                )

    with st.expander("Advanced overrides"):
        o1, o2, o3, o4 = st.columns(4)
        with o1:
            override_gearing = st.checkbox("Override gearing", key=f"ov_gear_{name}")
            gearing_pct_override = (
                st.number_input("Gearing (%)", value=70.0, min_value=0.0, max_value=100.0) / 100
                if override_gearing
                else None
            )
        with o2:
            override_rate = st.checkbox("Override interest rate", key=f"ov_rate_{name}")
            interest_rate_override = (
                st.number_input("Interest rate (%)", value=5.0, min_value=0.0) / 100
                if override_rate
                else None
            )
        with o4:
            override_devex = st.checkbox("Override DEVEX", key=f"ov_devex_{name}")
            default_devex_keur = aur_cases.devex_keur_for_tension(tension, financing_terms)
            devex_keur_override = (
                st.number_input("DEVEX (k€)", value=default_devex_keur, min_value=0.0)
                if override_devex
                else None
            )
        with o3:
            override_dsa = st.checkbox("Override DSA", key=f"ov_dsa_{name}")
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
                st.number_input("DSA (k€)", value=default_dsa_keur, min_value=0.0)
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
        a1, a2 = st.columns(2)
        with a1:
            connection_capex_mode = st.selectbox(
                "Grid connection CAPEX mode",
                ["library", "manual", "distance_rte"],
                format_func=lambda m: {
                    "library": "Library (segment/duration)",
                    "manual": "Manual value",
                    "distance_rte": "Distance to RTE substation",
                }[m],
                key=f"conn_mode_{name}",
            )
            manual_connection_capex_keur = 0.0
            distance_rte_km = 0.0
            if connection_capex_mode == "manual":
                manual_connection_capex_keur = st.number_input(
                    "Manual grid connection CAPEX (k€)", value=0.0, min_value=0.0
                )
            elif connection_capex_mode == "distance_rte":
                distance_rte_km = st.number_input(
                    "Distance to RTE substation (km)", value=1.0, min_value=0.0
                )
                st.caption(
                    f"= 4650.7 × distance^0.239 = {_fmt_keur(4650.7 * distance_rte_km**0.239)}"
                )
        with a2:
            land_lease_opex_keur = st.number_input(
                "Land lease OPEX (k€/yr)", value=0.0, min_value=0.0
            )

    if st.button("Add the project", type="primary", disabled=cod_invalid):
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
            oro_requested=bool(oro_requested),
            curtailment_hours=int(curtailment_hours) if curtailment_hours is not None else None,
        )
        st.session_state["portfolio_projects"].append(project)
        st.rerun()


def _render_project_list() -> None:
    projects: list[portfolio.ProjectConfig] = st.session_state["portfolio_projects"]
    if not projects:
        st.caption("No project added yet.")
        return
    st.subheader(f"Portfolio projects ({len(projects)})")
    for i, project in enumerate(projects):
        c1, c2 = st.columns([5, 1])
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
            if not project.repowering_enabled:
                adjustments.append("repowering disabled")
            elif project.repowering_year_mode == "manual":
                adjustments.append(f"repowering year {project.repowering_op_year_manual}")
            else:
                adjustments.append("repowering auto-optimized")
            adjustment_suffix = f" ({', '.join(adjustments)})" if adjustments else ""
            st.write(
                f"**{project.name}** — {project.duree_h}h {project.tension} {project.turpe_type}"
                f"{' gabarit' if project.gabarit else ''}{' ORO' if project.oro_requested else ''}"
                f", COD {project.cod_year}, "
                f"{project.power_mw:.1f} MW, {_CONTRACT_LABELS[project.contract_structure.kind]}"
                f"{adjustment_suffix}"
            )
        with c2:
            if st.button("Remove", key=f"remove_{i}"):
                projects.pop(i)
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


def _render_hold_and_operate(rows: list[portfolio.PortfolioRow]) -> None:
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
    df = pd.DataFrame(
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
                    "disabled"
                    if r.repowering_op_year_used is None
                    else f"year {r.repowering_op_year_used}"
                    + (" (optimized)" if r.repowering_auto_optimized else "")
                ),
            }
            for r in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
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
    au_store: aur_cases.AuStoreLibrary, copex_library, financing_terms: dict
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

    _render_best_configs(rows)
    st.divider()

    tab1, tab2, tab3 = st.tabs(["Hold & Operate", "Develop & sell at RtB", "Buy RtB & sell at COD"])
    with tab1:
        _render_hold_and_operate(rows)
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
    au_store, copex_library, financing_terms = load_library()

    _render_add_project_form(au_store, copex_library, financing_terms)
    st.divider()
    _render_project_list()
    _render_results(au_store, copex_library, financing_terms)
