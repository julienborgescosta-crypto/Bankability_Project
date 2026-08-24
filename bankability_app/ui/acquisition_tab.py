from __future__ import annotations

import pandas as pd
import streamlit as st

from core import acquisition
from core.models import ProjectInputs, ProjectResults


def _fmt_keur(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f} k€".replace(",", " ")


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def render(inputs: ProjectInputs, result: ProjectResults, debt_kwargs: dict) -> None:
    st.caption(
        "Reformule l'analyse en question M&A : combien peut-on payer pour acquérir ce "
        "projet (SPV), plutôt que de le développer en interne — on résout pour la prime "
        "d'acquisition maximale au lieu de la supposer."
    )
    acquisition_mode = st.checkbox("Analyser comme une acquisition (M&A)")
    if not acquisition_mode:
        st.info("Cochez la case pour lancer l'analyse d'acquisition sur ce projet.")
        return

    target_irr = st.slider("Rendement equity cible (acheteur)", 5.0, 25.0, 12.0, step=0.5) / 100
    valuation = acquisition.compute_acquisition_valuation(result, target_irr)

    st.subheader("Prime d'acquisition maximale")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Equity de base requis", _fmt_keur(valuation.base_equity_keur))
    c2.metric("VA des flux equity futurs", _fmt_keur(valuation.pv_future_equity_cashflows_keur))
    c3.metric(
        "Prime d'acquisition max (headroom)", _fmt_keur(valuation.max_acquisition_premium_keur)
    )
    c4.metric("Ticket equity total maximal", _fmt_keur(valuation.max_total_equity_check_keur))
    st.caption(
        f"Equity IRR du projet (financement actuel) : {_fmt_pct(valuation.actual_equity_irr)} "
        f"— cible acheteur : {_fmt_pct(target_irr)}."
    )

    if valuation.max_acquisition_premium_keur < 0:
        st.warning(
            "Prime négative : au montant d'equity de base, le projet ne couvre pas le "
            "rendement cible. Il faudrait payer **moins** que l'equity de base (décote), "
            "pas une prime — ou revoir le rendement cible / les hypothèses de financement."
        )
    else:
        st.success(
            "Vous pouvez payer jusqu'à cette prime au-dessus de l'equity de base tout en "
            "tenant le rendement cible."
        )

    st.caption(
        "Formule : Purchase Price + Base Equity Investment ≤ VA des flux equity futurs "
        "@ rendement cible. La prime n'est jamais une hypothèse en entrée — c'est une "
        "valeur résiduelle qui bouge avec l'économie du projet."
    )

    st.divider()
    st.subheader("Sensibilité de la prime d'acquisition")
    st.caption(
        "Même logique que l'onglet Sensitivity Analysis, mais sur la prime d'acquisition "
        "plutôt que sur l'Equity IRR/DSCR. 'OPEX' est le proxy le plus proche d'un choc de "
        "coût réseau (grid cost) dans ce modèle."
    )
    rows = acquisition.run_acquisition_sensitivity(inputs, debt_kwargs, target_irr)
    sensitivity_table = pd.DataFrame(
        {
            "Variable": [r["variable"] for r in rows],
            **{
                f"{shock:+.0%}": [f"{r[shock]:,.0f} k€".replace(",", " ") for r in rows]
                for shock in acquisition.SHOCKS
            },
        }
    )
    st.dataframe(sensitivity_table, hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("Repères de marché (contexte, non calculé)")
    st.caption(
        "Benchmarks externes indicatifs par stade de développement — utiles comme "
        "référence, mais ce ne sont pas votre plafond : votre plafond est ce que le "
        "calcul ci-dessus dit que vous pouvez payer."
    )
    benchmarks_table = pd.DataFrame(
        {
            "Stade": [b["stage"] for b in acquisition.STAGE_BENCHMARKS],
            "Exemple": [b["example"] for b in acquisition.STAGE_BENCHMARKS],
            "Repère": [b["benchmark"] for b in acquisition.STAGE_BENCHMARKS],
            "Note": [b["note"] for b in acquisition.STAGE_BENCHMARKS],
        }
    )
    st.dataframe(benchmarks_table, hide_index=True, use_container_width=True)
