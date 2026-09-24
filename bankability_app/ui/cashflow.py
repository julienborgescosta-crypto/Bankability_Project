from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.models import ProjectInputs, ProjectResults
from ui import chart_theme


def render(inputs: ProjectInputs, result: ProjectResults) -> None:
    df = pd.DataFrame(
        {
            "Year": [y.year for y in result.yearly],
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
    fig.add_bar(
        x=df["Year"], y=df["Revenues"], name="Revenues", marker_color=chart_theme.ENTITY["revenue"]
    )
    fig.add_bar(x=df["Year"], y=df["OPEX"], name="OPEX", marker_color=chart_theme.ENTITY["opex"])
    fig.add_bar(x=df["Year"], y=df["TURPE"], name="TURPE", marker_color=chart_theme.ENTITY["turpe"])
    fig.add_bar(x=df["Year"], y=df["CAPEX"], name="CAPEX", marker_color=chart_theme.ENTITY["capex"])
    fig.add_trace(
        go.Scatter(
            x=df["Year"],
            y=df["Net Cashflow"],
            name="Net Cashflow",
            mode="lines+markers",
            line={"color": chart_theme.ENTITY["net_cashflow"], "width": 3},
        )
    )
    fig.update_layout(barmode="relative", title="Annual cashflow (k€, nominal)")
    chart_theme.apply_layout(fig)
    st.plotly_chart(fig, use_container_width=True)

    fig_dscr = go.Figure()
    fig_dscr.add_trace(
        go.Scatter(
            x=df["Year"],
            y=df["DSCR"],
            mode="lines+markers",
            name="DSCR",
            line={"color": chart_theme.ENTITY["single_series"]},
        )
    )
    fig_dscr.add_hline(
        y=1.30,
        line_dash="dash",
        line_color=chart_theme.MUTED_INK,
        annotation_text="Usual bank threshold 1.30x",
    )
    fig_dscr.update_layout(title="Annual DSCR", yaxis_title="DSCR (x)", showlegend=False)
    chart_theme.apply_layout(fig_dscr)
    st.plotly_chart(fig_dscr, use_container_width=True)

    st.dataframe(df.set_index("Year"), use_container_width=True)
