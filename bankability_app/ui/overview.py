from __future__ import annotations

import streamlit as st

from core.models import ProjectInputs, ProjectResults


def _fmt_keur(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f} k€".replace(",", " ")


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def render(inputs: ProjectInputs, result: ProjectResults) -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Projet", inputs.name or "n/a")
        st.metric("Segment tarifaire", inputs.segment or "n/a")
        st.metric("Localisation", inputs.location or "n/a")
    with col2:
        st.metric("Puissance utile", f"{inputs.usable_power_mw:.0f} MW")
        st.metric("Énergie utile", f"{inputs.usable_energy_mwh:.0f} MWh")
        st.metric("Durée d'exploitation", f"{inputs.operating_years} ans")
    with col3:
        st.metric("CAPEX initial", _fmt_keur(inputs.capex_initial_keur))
        if inputs.reported_capex_i_project_keur is not None:
            st.caption(f"CAPEX selon I-Project : {_fmt_keur(inputs.reported_capex_i_project_keur)}")
        st.metric("CAPEX repowering", _fmt_keur(inputs.capex_repowering_keur))
        st.metric("Repowering prévu", "Oui" if inputs.repowering else "Non")

    st.divider()
    st.subheader("Résultats économiques (hypothèses de financement actuelles)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Project IRR", _fmt_pct(result.project_irr))
    if inputs.reported_irr is not None:
        c1.caption(f"IRR déclaré dans le BP : {inputs.reported_irr:.2%}")
    c2.metric("Equity IRR", _fmt_pct(result.equity_irr))
    if inputs.reported_equity_irr is not None:
        c2.caption(f"Equity IRR déclaré dans le BP : {inputs.reported_equity_irr:.2%}")
    c3.metric("NPV (projet)", _fmt_keur(result.npv_keur))
    if inputs.reported_npv_keur is not None:
        c3.caption(f"NPV déclarée dans le BP : {_fmt_keur(inputs.reported_npv_keur)}")
    c4.metric("DSCR min", f"{result.dscr_min:.2f}x" if result.dscr_min is not None else "n/a")
    captions = []
    if inputs.reported_dscr_min is not None:
        captions.append(
            f"BP (dette réelle sculptée) : DSCR moyen {inputs.reported_dscr_avg:.2f}x, "
            f"min {inputs.reported_dscr_min:.2f}x"
        )
    if inputs.target_dscr is not None:
        captions.append(f"Target DSCR du projet (I-Project) : {inputs.target_dscr:.2f}x")
    if captions:
        c4.caption(" — ".join(captions))

    st.divider()
    st.subheader("Structure de financement")
    c1, c2, c3 = st.columns(3)
    c1.metric("CAPEX total", _fmt_keur(result.capex_total_keur))
    c2.metric("Dette", _fmt_keur(result.debt_amount_keur))
    c3.metric("Fonds propres", _fmt_keur(result.equity_amount_keur))

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
