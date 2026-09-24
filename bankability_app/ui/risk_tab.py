from __future__ import annotations

import streamlit as st

from core import risk_rules
from core.models import ProjectInputs, ProjectResults

_RENDER = {"red": st.error, "amber": st.warning, "green": st.success}


def render(inputs: ProjectInputs, result: ProjectResults) -> None:
    st.caption(
        "Alerts generated automatically when thresholds are crossed (config/risk_thresholds.yaml)."
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
                f"Revenue mix (PPA + Capacity market vs Merchant): "
                f"{total_contracted / total:.0%} contracted / {total_merchant / total:.0%} merchant — "
                f"DSCR threshold weighted accordingly when the project's own covenant isn't available."
            )

    with st.expander("Applied thresholds"):
        st.json(thresholds)
