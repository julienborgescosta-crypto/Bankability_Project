from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.models import ProjectInputs, ProjectResults


def render(inputs: ProjectInputs, result: ProjectResults) -> None:
    df = pd.DataFrame(
        {
            "Année": [y.year for y in result.yearly],
            "CAPEX": [y.capex_keur for y in result.yearly],
            "OPEX": [y.opex_keur for y in result.yearly],
            "TURPE": [y.turpe_keur for y in result.yearly],
            "Revenues": [y.revenue_keur for y in result.yearly],
            "Net Cashflow": [y.net_cashflow_keur for y in result.yearly],
            "Cashflow Equity": [y.equity_cashflow_keur for y in result.yearly],
            "DSCR": [y.dscr for y in result.yearly],
        }
    )

    fig = go.Figure()
    fig.add_bar(x=df["Année"], y=df["Revenues"], name="Revenues", marker_color="#2f6f4f")
    fig.add_bar(x=df["Année"], y=df["OPEX"], name="OPEX", marker_color="#b23b3b")
    fig.add_bar(x=df["Année"], y=df["TURPE"], name="TURPE", marker_color="#c98a3b")
    fig.add_bar(x=df["Année"], y=df["CAPEX"], name="CAPEX", marker_color="#555555")
    fig.add_trace(
        go.Scatter(x=df["Année"], y=df["Net Cashflow"], name="Net Cashflow", mode="lines+markers", line=dict(color="#1f4e79", width=3))
    )
    fig.update_layout(barmode="relative", title="Cashflow annuel (k€, réel)", legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

    fig_dscr = go.Figure()
    fig_dscr.add_trace(go.Scatter(x=df["Année"], y=df["DSCR"], mode="lines+markers", name="DSCR", line=dict(color="#1f4e79")))
    fig_dscr.add_hline(y=1.30, line_dash="dash", line_color="#c98a3b", annotation_text="Seuil bancaire usuel 1.30x")
    fig_dscr.update_layout(title="DSCR annuel", yaxis_title="DSCR (x)")
    st.plotly_chart(fig_dscr, use_container_width=True)

    st.dataframe(df.set_index("Année"), use_container_width=True)
