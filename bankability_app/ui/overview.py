from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from core.models import ProjectInputs, ProjectResults


def _fmt_keur(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f} k€".replace(",", " ")


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _cash_profile_chart(result: ProjectResults) -> go.Figure:
    years = [y.year for y in result.yearly]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[y.revenue_keur for y in result.yearly],
            name="Revenue",
            mode="lines",
            line={"color": "#1f77b4", "width": 2.5},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[y.cfads_keur for y in result.yearly],
            name="CFADS",
            mode="lines",
            line={"color": "#ff7f0e", "width": 2.5},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[y.debt_service_keur for y in result.yearly],
            name="Debt service",
            mode="lines",
            line={"color": "#2ca02c", "width": 2.5},
        )
    )
    fig.update_layout(
        title="Annual cash profile (k€)",
        yaxis_title="k€",
        legend={"orientation": "h"},
    )
    return fig


def render(
    inputs: ProjectInputs, result: ProjectResults, debt_sizing_mode: str = "gearing"
) -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Projet", inputs.name or "n/a")
        st.metric("Segment tarifaire", inputs.segment or "n/a")
        st.metric("Localisation", inputs.location or "n/a")
    with col2:
        st.metric("Puissance utile", f"{inputs.usable_power_mw:.0f} MW")
        st.metric("Énergie utile", f"{inputs.usable_energy_mwh:.0f} MWh")
        st.metric("Mise en service (COD)", inputs.cod or "n/a")
        st.metric("Durée d'exploitation", f"{inputs.operating_years} ans")
    with col3:
        st.metric("CAPEX initial", _fmt_keur(inputs.capex_initial_keur))
        if inputs.reported_capex_i_project_keur is not None:
            st.caption(f"CAPEX selon I-Project : {_fmt_keur(inputs.reported_capex_i_project_keur)}")
        st.metric("CAPEX repowering", _fmt_keur(inputs.capex_repowering_keur))
        st.metric("Repowering prévu", "Oui" if inputs.repowering else "Non")

    st.divider()
    mode_label = "dette dimensionnée par DSCR" if debt_sizing_mode == "dscr" else "gearing fixe"
    st.subheader(f"Résultats économiques ({mode_label})")
    c1, c2, c3, c4 = st.columns(4)
    with c1.container(border=True):
        st.metric("Project IRR", _fmt_pct(result.project_irr))
        if inputs.reported_irr is not None:
            st.caption(f"IRR déclaré dans le BP : {inputs.reported_irr:.2%}")
    with c2.container(border=True):
        st.metric("Equity IRR", _fmt_pct(result.equity_irr))
        if inputs.reported_equity_irr is not None:
            st.caption(f"Equity IRR déclaré dans le BP : {inputs.reported_equity_irr:.2%}")
    with c3.container(border=True):
        st.metric("DSCR min", f"{result.dscr_min:.2f}x" if result.dscr_min is not None else "n/a")
        captions = []
        if inputs.reported_dscr_min is not None:
            captions.append(
                f"BP (dette réelle sculptée) : DSCR moyen {inputs.reported_dscr_avg:.2f}x, "
                f"min {inputs.reported_dscr_min:.2f}x"
            )
        if inputs.target_dscr is not None:
            captions.append(f"Target DSCR du projet (I-Project) : {inputs.target_dscr:.2f}x")
        if captions:
            st.caption(" — ".join(captions))
    with c4.container(border=True):
        st.metric("NPV (projet)", _fmt_keur(result.npv_keur))
        if inputs.reported_npv_keur is not None:
            st.caption(f"NPV déclarée dans le BP : {_fmt_keur(inputs.reported_npv_keur)}")

    st.divider()
    st.subheader("Profil de cashflow annuel")
    st.plotly_chart(_cash_profile_chart(result), use_container_width=True)
    st.caption(
        "Revenue, CFADS et service de la dette par année — le service de la dette retombe à "
        "zéro une fois le tenor écoulé ; un creux de CFADS marque une année de repowering "
        "(CAPEX, pas d'exploitation) si le projet en a une."
    )

    st.divider()
    st.subheader("Structure de financement")
    c1, c2, c3 = st.columns(3)
    c1.metric("CAPEX total", _fmt_keur(result.capex_total_keur))
    c2.metric("Dette", _fmt_keur(result.debt_amount_keur))
    c3.metric("Fonds propres", _fmt_keur(result.equity_amount_keur))
    if result.funding_uses_addon_initial_keur > 0:
        st.caption(
            "Dette + Fonds propres dépassent le CAPEX total de "
            f"{_fmt_keur(result.funding_uses_addon_initial_keur)} : le mode gearing applique "
            "le gearing à CAPEX + DSRA + frais de financement construction + cash minimum "
            '(bloc "Uses & Sources" de O-Control), pas au CAPEX seul.'
        )

    if result.capex_total_repowering_keur > 0:
        st.caption("Répartie en 2 tranches (dette initiale + dette de repowering) :")
        r1, r2 = st.columns(2)
        with r1:
            st.markdown("**Tranche initiale**")
            st.metric("CAPEX", _fmt_keur(result.capex_total_initial_keur))
            st.metric("Dette", _fmt_keur(result.debt_amount_initial_keur))
        with r2:
            st.markdown("**Tranche repowering**")
            st.metric("CAPEX", _fmt_keur(result.capex_total_repowering_keur))
            st.metric("Dette", _fmt_keur(result.debt_amount_repowering_keur))
