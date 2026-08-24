from __future__ import annotations

import streamlit as st

from core import risk_rules
from core.models import ProjectInputs, ProjectResults

_RENDER = {"red": st.error, "amber": st.warning, "green": st.success}


def render(inputs: ProjectInputs, result: ProjectResults) -> None:
    st.caption(
        "Alertes générées automatiquement par franchissement de seuils (config/risk_thresholds.yaml)."
    )
    thresholds = risk_rules.load_thresholds()
    flags = risk_rules.evaluate_risks(inputs, result, thresholds)
    for flag in flags:
        _RENDER[flag.level](f"**{flag.label}** — {flag.message}")

    detail = inputs.revenue_detail
    if (
        detail is not None
        and detail.contracted_keur is not None
        and detail.merchant_keur is not None
    ):
        total_contracted = sum(detail.contracted_keur)
        total_merchant = sum(detail.merchant_keur)
        total = total_contracted + total_merchant
        if total > 0:
            st.caption(
                f"Mix de revenu (PPA + Capacity market vs Merchant) : "
                f"{total_contracted / total:.0%} contracté / {total_merchant / total:.0%} merchant — "
                f"seuil DSCR pondéré en conséquence quand le covenant du projet n'est pas disponible."
            )

    with st.expander("Seuils appliqués"):
        st.json(thresholds)
