from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import sensitivity
from core.models import ProjectInputs


def _tornado_chart(rows: list[dict], metric: str, base_value: float, title: str, fmt: str) -> go.Figure:
    labels = [r["variable"] for r in rows]
    low = [r[-0.20][metric] - base_value for r in rows]
    high = [r[0.20][metric] - base_value for r in rows]

    fig = go.Figure()
    fig.add_bar(y=labels, x=low, orientation="h", name="-20%", marker_color="#f4a6a6")
    fig.add_bar(y=labels, x=high, orientation="h", name="+20%", marker_color="#a6c8f4")
    fig.update_layout(barmode="relative", title=title, xaxis_title=f"Écart vs base ({fmt})")
    return fig


def render(inputs: ProjectInputs, debt_kwargs: dict) -> None:
    base, rows = sensitivity.run_sensitivity(inputs, debt_kwargs)

    st.subheader("Base Case Values")
    base_df = pd.DataFrame(
        {
            "Variable": ["Project Capacity", "CAPEX Total", "OPEX Total", "Revenue Total", "Equity IRR (Base)", "DSCR (Base)"],
            "Value": [
                f"{inputs.usable_power_mw:.0f} MW",
                f"{base.capex_total_keur:,.0f} k€".replace(",", " "),
                f"{abs(sum(y.opex_keur for y in base.yearly)):,.0f} k€".replace(",", " "),
                f"{sum(y.revenue_keur for y in base.yearly):,.0f} k€".replace(",", " "),
                f"{base.equity_irr:.1%}" if base.equity_irr is not None else "n/a",
                f"{base.dscr_min:.2f}x" if base.dscr_min is not None else "n/a",
            ],
        }
    )
    st.dataframe(base_df, hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("One-Way Sensitivity: Impact on Equity IRR")
    irr_table = pd.DataFrame(
        {
            "Variable": [r["variable"] for r in rows],
            **{
                f"{shock:+.0%}": [
                    f"{r[shock]['equity_irr']:.1%}" if r[shock]["equity_irr"] is not None else "n/a" for r in rows
                ]
                for shock in sensitivity.SHOCKS
            },
        }
    )
    st.dataframe(irr_table, hide_index=True, use_container_width=True)
    if base.equity_irr is not None:
        st.plotly_chart(
            _tornado_chart(rows, "equity_irr", base.equity_irr, "Tornado — Equity IRR", "pts"),
            use_container_width=True,
        )

    st.divider()
    st.subheader("One-Way Sensitivity: Impact on DSCR")
    dscr_table = pd.DataFrame(
        {
            "Variable": [r["variable"] for r in rows],
            **{
                f"{shock:+.0%}": [
                    f"{r[shock]['dscr_min']:.2f}x" if r[shock]["dscr_min"] is not None else "n/a" for r in rows
                ]
                for shock in sensitivity.SHOCKS
            },
        }
    )
    st.dataframe(dscr_table, hide_index=True, use_container_width=True)
    if base.dscr_min is not None:
        st.plotly_chart(
            _tornado_chart(rows, "dscr_min", base.dscr_min, "Tornado — DSCR min", "x"),
            use_container_width=True,
        )

    st.divider()
    st.caption(
        "Sensibilités marché détaillées (DAM Spread, ID Spread, Cycles, Capacity Price) : "
        + ", ".join(sensitivity.DETAILED_VARIABLES)
        + " — disponibles une fois le détail par flux de revenu extrait du classeur multi-onglets complet."
    )
