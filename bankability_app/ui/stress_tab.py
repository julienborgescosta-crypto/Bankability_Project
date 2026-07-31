from __future__ import annotations

import pandas as pd
import streamlit as st

from core import stress_test
from core.models import ProjectInputs


def render(inputs: ProjectInputs, debt_kwargs: dict) -> None:
    st.caption(
        "Matrice combinant stress sur les revenus (Bear = -15%) et sur la dégradation "
        "(courbe additionnelle, indépendante de celle déjà intégrée au BP)."
    )
    rows = stress_test.run_stress_matrix(inputs, debt_kwargs)
    df = pd.DataFrame(rows)
    df["Project IRR"] = df["project_irr"].map(lambda v: f"{v:.1%}" if v is not None else "n/a")
    df["Equity IRR"] = df["equity_irr"].map(lambda v: f"{v:.1%}" if v is not None else "n/a")
    df["DSCR min"] = df["dscr_min"].map(lambda v: f"{v:.2f}x" if v is not None else "n/a")
    display = df.rename(
        columns={
            "revenue_case": "Revenue",
            "degradation_case": "Dégradation",
            "combined": "Stress combiné",
        }
    )
    st.dataframe(
        display[
            ["Revenue", "Dégradation", "Stress combiné", "Project IRR", "Equity IRR", "DSCR min"]
        ],
        hide_index=True,
        use_container_width=True,
    )
