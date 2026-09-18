"""Configurateur Aurora : saisie directe de N projets (sans upload de BP) ->
core.portfolio.run_portfolio -> tableau de KPI comparatif. Voir
docs/specs/aurora_v2_methodology.md section 4, docs/specs/portfolio.md.

Les courbes AU_Store/COPEX_library sont chargees depuis le fixture Aurora
commite (pas un BP par-projet a uploader - c'est une bibliotheque partagee,
la meme pour tous les projets du portefeuille)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import aur_cases, config_space, contract_overlay, portfolio

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

    au_store = aur_cases.load_au_store(SAMPLE_AURORA_BP_PATH)
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
    st.subheader("Ajouter un projet")
    c1, c2, c3 = st.columns(3)
    with c1:
        name = st.text_input(
            "Nom du projet", value=f"Projet {len(st.session_state['portfolio_projects']) + 1}"
        )
        duree_h = st.selectbox("Durée BESS (h)", config_space.durations(au_store))
        tension = st.selectbox(
            "Tension",
            config_space.tensions(au_store, duree_h=duree_h, copex_library=copex_library),
        )
    with c2:
        turpe_type = st.selectbox(
            "Type TURPE", config_space.turpe_types(au_store, duree_h=duree_h, tension=tension)
        )
        gabarit_options = config_space.gabarit_options(
            au_store, duree_h=duree_h, tension=tension, turpe_type=turpe_type
        )
        gabarit = st.selectbox(
            "Gabarit", gabarit_options, format_func=lambda g: "Oui" if g else "Non"
        )
        if gabarit_options == [False]:
            st.caption(
                'Gabarit "Oui" indisponible ici : Aurora ne l\'a modélisé que pour TURPE '
                "Injection/Soutirage, en HTA ou HTB2 (jamais Classique, jamais HTB1/HTB3)."
            )
        power_mw = st.number_input("Puissance (MW)", value=10.0, min_value=0.1)
    with c3:
        cod_year = st.number_input(
            "Année de COD", value=2027, min_value=2027, max_value=2060, step=1
        )
        operating_years = st.number_input(
            "Durée d'exploitation (ans)", value=20, min_value=1, step=1
        )

    try:
        au_config = au_store.config_by_attributes(
            duree_h=duree_h, tension=tension, turpe_type=turpe_type, gabarit=gabarit
        )
        if not config_space.is_cod_valid(au_config, int(cod_year)):
            st.warning(
                f"Cette config n'est modélisée par Aurora que pour COD={au_config.valide_cod} "
                "- ajuste l'année de COD ci-dessus avant d'ajouter le projet."
            )
    except aur_cases.AuroraConfigError as exc:
        st.error(f"Combinaison non modélisée par Aurora : {exc}")
        return

    st.markdown("**Structure contractuelle**")
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
            price = st.number_input("Prix (k€/MW/an)", value=80.0, min_value=0.0)
            duration_years = st.number_input(
                "Durée du contrat (ans)",
                value=10,
                min_value=1,
                max_value=int(operating_years),
                step=1,
            )
        if contract_kind == contract_overlay.FLOOR:
            with c3:
                sharing_pct = (
                    st.number_input(
                        "Partage agrégateur au-dessus du floor (%)",
                        value=40.0,
                        min_value=0.0,
                        max_value=100.0,
                    )
                    / 100
                )

    with st.expander("Overrides avancés (sinon défauts de config/aur_financing_terms.yaml)"):
        o1, o2, o3, o4 = st.columns(4)
        with o1:
            override_gearing = st.checkbox("Override gearing", key=f"ov_gear_{name}")
            gearing_pct_override = (
                st.number_input("Gearing (%)", value=70.0, min_value=0.0, max_value=100.0) / 100
                if override_gearing
                else None
            )
        with o2:
            override_rate = st.checkbox("Override taux d'intérêt", key=f"ov_rate_{name}")
            interest_rate_override = (
                st.number_input("Taux d'intérêt (%)", value=5.0, min_value=0.0) / 100
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
                f"Défaut : {_fmt_keur(default_dsa_keur)} (marge cible {margin_per_mw:.0f} k€/MW "
                f"× {power_mw:.0f} MW + DEVEX {_fmt_keur(effective_devex_keur)})."
            )

        st.markdown(
            "**Ajustement global CAPEX/OPEX** (stress test rapide, sans changer les hypothèses)"
        )
        a1, a2 = st.columns(2)
        with a1:
            capex_adjustment_pct = (
                st.number_input(
                    "Ajustement CAPEX (%)", value=0.0, min_value=-90.0, max_value=200.0, step=5.0
                )
                / 100
            )
        with a2:
            opex_adjustment_pct = (
                st.number_input(
                    "Ajustement OPEX (%)", value=0.0, min_value=-90.0, max_value=200.0, step=5.0
                )
                / 100
            )

    if st.button("Ajouter le projet", type="primary"):
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
            capex_adjustment_pct=float(capex_adjustment_pct),
            opex_adjustment_pct=float(opex_adjustment_pct),
        )
        st.session_state["portfolio_projects"].append(project)
        st.rerun()


def _render_project_list() -> None:
    projects: list[portfolio.ProjectConfig] = st.session_state["portfolio_projects"]
    if not projects:
        st.caption("Aucun projet ajouté pour l'instant.")
        return
    st.subheader(f"Projets du portefeuille ({len(projects)})")
    for i, project in enumerate(projects):
        c1, c2 = st.columns([5, 1])
        with c1:
            adjustments = []
            if project.capex_adjustment_pct != 0.0:
                adjustments.append(f"CAPEX {project.capex_adjustment_pct:+.0%}")
            if project.opex_adjustment_pct != 0.0:
                adjustments.append(f"OPEX {project.opex_adjustment_pct:+.0%}")
            adjustment_suffix = f" ({', '.join(adjustments)})" if adjustments else ""
            st.write(
                f"**{project.name}** — {project.duree_h}h {project.tension} {project.turpe_type}"
                f"{' gabarit' if project.gabarit else ''}, COD {project.cod_year}, "
                f"{project.power_mw:.1f} MW, {_CONTRACT_LABELS[project.contract_structure.kind]}"
                f"{adjustment_suffix}"
            )
        with c2:
            if st.button("Supprimer", key=f"remove_{i}"):
                projects.pop(i)
                st.rerun()


def _bar_chart(
    labels: list[str], values: list[float | None], *, y_title: str, pct: bool = False
) -> go.Figure:
    fig = go.Figure(go.Bar(x=labels, y=[v if v is not None else 0.0 for v in values]))
    fig.update_layout(
        yaxis_title=y_title,
        yaxis_tickformat=".0%" if pct else None,
        margin={"t": 20, "b": 20},
    )
    return fig


def _render_hold_and_operate(rows: list[portfolio.PortfolioRow]) -> None:
    st.caption(
        "Garder & exploiter : le projet reste dans le portefeuille QEF sur toute la durée "
        "d'exploitation — rendement projet et actionnaire, sans transaction."
    )
    df = pd.DataFrame(
        [
            {
                "Projet": r.name,
                "Config": r.config_label,
                "Project IRR": _fmt_pct(r.project_irr),
                "Equity IRR": _fmt_pct(r.equity_irr),
                "NPV (k€)": _fmt_keur(r.npv_keur),
                "CAPEX (k€)": _fmt_keur(r.capex_total_keur),
                "Revenu total (k€)": _fmt_keur(r.revenue_total_keur),
                "DSCR moy/min": (
                    f"{r.dscr_avg:.2f}x / {r.dscr_min:.2f}x"
                    if r.dscr_avg is not None and r.dscr_min is not None
                    else "n/a"
                ),
                "Cible DSCR utilisée": f"{r.target_dscr_used:.2f}x",
                "Gearing utilisé": _fmt_pct(r.gearing_used_pct),
                "Maturité (ans)": r.debt_tenor_years,
            }
            for r in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(
        "Cible DSCR et maturité reflètent déjà la conséquence du floor/tolling sur la dette "
        "(tiering sécurisé 1,20x/10 ans vs merchant 1,40x/PPA+3 ans, docs/adr/... section 2.2 de "
        "aur_v2_methodology.md) — pas une hypothèse à part."
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
        "Développer & vendre au RtB : l'intérêt pour QEF est la marge captée (DSA + SPA - DEVEX), "
        "repère marché 50-100 k€/MW."
    )
    df = pd.DataFrame(
        [
            {
                "Projet": r.name,
                "Config": r.config_label,
                "DSA (k€)": _fmt_keur(r.dsa_keur),
                "SPA (k€)": _fmt_keur(r.spa_keur),
                "TSP = DSA+SPA (k€)": _fmt_keur(r.tsp_keur),
                "DEVEX (k€)": _fmt_keur(r.devex_keur),
                "Marge nette (k€)": _fmt_keur(r.net_margin_keur),
                "Marge nette (k€/MW)": _fmt_keur(
                    r.net_margin_keur / r.power_mw if r.power_mw else None
                ),
            }
            for r in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
    margin_per_mw = [r.net_margin_keur / r.power_mw if r.power_mw else None for r in rows]
    fig = _bar_chart([r.name for r in rows], margin_per_mw, y_title="Marge nette (k€/MW)")
    fig.add_hline(y=50, line_dash="dot", annotation_text="Repère bas (50 k€/MW)")
    fig.add_hline(y=100, line_dash="dot", annotation_text="Repère haut (100 k€/MW)")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        'TRI cible acheteur RtB "revenu sécurisé" (floor/tolling) encore **provisoire** '
        "(9 %, à confirmer) — voir docs/specs/aur_v2_methodology.md section 3.4."
    )


def _render_build_and_flip(rows: list[portfolio.PortfolioRow]) -> None:
    st.caption(
        "Racheter RtB & vendre au COD : QEF paie le prix RtB, construit, revend l'actif en "
        "exploitation. Rendement = valeur de revente − prix RtB − CAPEX − coût de portage."
    )
    df = pd.DataFrame(
        [
            {
                "Projet": r.name,
                "Config": r.config_label,
                "Prix d'achat RtB (k€)": _fmt_keur(r.tsp_keur),
                "CAPEX construction (k€)": _fmt_keur(r.capex_total_keur),
                "Coût de portage (k€)": _fmt_keur(r.build_and_flip_carry_cost_keur),
                "Valeur revente COD (k€)": _fmt_keur(r.resale_value_cod_keur),
                "Rendement net (k€)": _fmt_keur(r.build_and_flip_net_return_keur),
            }
            for r in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.plotly_chart(
        _bar_chart(
            [r.name for r in rows],
            [r.build_and_flip_net_return_keur for r in rows],
            y_title="Rendement net (k€)",
        ),
        use_container_width=True,
    )
    st.caption(
        "Valeur de revente non-levérisée (PV des cashflows post-COD au TRI cible acheteur, pas "
        "de dette re-dimensionnée) — sous-estime la valeur réelle de marché, voir docs/adr/0002."
    )


def _render_best_configs(rows: list[portfolio.PortfolioRow]) -> None:
    st.subheader("Meilleures configs")
    with_project_irr = [r for r in rows if r.project_irr is not None]
    c1, c2, c3 = st.columns(3)
    with c1:
        if with_project_irr:
            best = max(with_project_irr, key=lambda r: r.project_irr)
            st.metric(
                "Meilleur Project IRR (garder & exploiter)", _fmt_pct(best.project_irr), best.name
            )
        else:
            st.metric("Meilleur Project IRR (garder & exploiter)", "n/a")
    with c2:
        best = max(rows, key=lambda r: r.net_margin_keur)
        st.metric(
            "Meilleure marge nette (développer & vendre)",
            _fmt_keur(best.net_margin_keur),
            best.name,
        )
    with c3:
        best = max(rows, key=lambda r: r.build_and_flip_net_return_keur)
        st.metric(
            "Meilleur rendement build-and-flip",
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
    st.subheader("Résultats du portefeuille")
    try:
        rows = portfolio.run_portfolio(projects, au_store, copex_library, financing_terms)
    except aur_cases.AuroraConfigError as exc:
        st.error(f"Erreur de calcul : {exc}")
        return

    _render_best_configs(rows)
    st.divider()

    tab1, tab2, tab3 = st.tabs(
        ["Garder & exploiter", "Développer & vendre au RtB", "Racheter RtB & vendre au COD"]
    )
    with tab1:
        _render_hold_and_operate(rows)
    with tab2:
        _render_dev_and_sell(rows)
    with tab3:
        _render_build_and_flip(rows)


def render() -> None:
    st.caption(
        "Saisis directement les caractéristiques de chaque projet (pas de Business Plan à "
        "uploader) — le revenu vient des Business Cases Aurora (AU_Store), le CAPEX/OPEX de "
        "COPEX_library. Voir docs/specs/aur_v2_methodology.md."
    )
    st.session_state.setdefault("portfolio_projects", [])
    au_store, copex_library, financing_terms = load_library()

    _render_add_project_form(au_store, copex_library, financing_terms)
    st.divider()
    _render_project_list()
    _render_results(au_store, copex_library, financing_terms)
