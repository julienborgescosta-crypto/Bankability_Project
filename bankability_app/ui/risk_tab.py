from __future__ import annotations

import streamlit as st

from core import risk_rules
from core.models import ProjectInputs, ProjectResults

_RENDER = {"red": st.error, "amber": st.warning, "green": st.success}


def render(inputs: ProjectInputs, result: ProjectResults) -> None:
    st.caption("Alertes générées automatiquement par franchissement de seuils (config/risk_thresholds.yaml).")
    thresholds = risk_rules.load_thresholds()
    flags = risk_rules.evaluate_risks(inputs, result, thresholds)
    for flag in flags:
        _RENDER[flag.level](f"**{flag.label}** — {flag.message}")

    with st.expander("Seuils appliqués"):
        st.json(thresholds)
