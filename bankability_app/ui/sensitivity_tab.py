from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import sensitivity
from core.models import ProjectInputs


def _tornado_chart(
    rows: list[dict], metric: str, base_value: float, title: str, fmt: str
) -> go.Figure:
    labels = [r["variable"] for r in rows]
    low = [r[-0.20][metric] - base_value for r in rows]
    high = [r[0.20][metric] - base_value for r in rows]

    fig = go.Figure()
    fig.add_bar(y=labels, x=low, orientation="h", name="-20%", marker_color="#f4a6a6")
    fig.add_bar(y=labels, x=high, orientation="h", name="+20%", marker_color="#a6c8f4")
    fig.update_layout(barmode="relative", title=title, xaxis_title=f"Delta vs base ({fmt})")
    return fig


def _npv_heatmap(grid: list[list[float | None]]) -> go.Figure:
    text = [
        [(f"{v:+,.0f}".replace(",", " ") if v is not None else "n/a") for v in row] for row in grid
    ]
    fig = go.Figure(
        data=go.Heatmap(
            z=grid,
            x=[f"{r:.1%}" for r in sensitivity.NPV_DISCOUNT_RATES],
            y=[f"{s:+.0%}" for s in sensitivity.NPV_REVENUE_SHOCKS],
            text=text,
            texttemplate="%{text}",
            colorscale="RdYlGn",
            zmid=0,
            colorbar={"title": "NPV (k€)"},
        )
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        title="Project NPV sensitivity (k€)",
        xaxis_title="Discount rate",
        yaxis_title="Revenue shock",
    )
    return fig


def render(inputs: ProjectInputs, debt_kwargs: dict) -> None:
    base, rows = sensitivity.run_sensitivity(inputs, debt_kwargs)

    st.subheader("Base Case Values")
    base_df = pd.DataFrame(
        {
            "Variable": [
                "Project Capacity",
                "CAPEX Total",
                "OPEX Total",
                "Revenue Total",
                "Equity IRR (Base)",
                "DSCR (Base)",
            ],
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
                    f"{r[shock]['equity_irr']:.1%}" if r[shock]["equity_irr"] is not None else "n/a"
                    for r in rows
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
                    f"{r[shock]['dscr_min']:.2f}x" if r[shock]["dscr_min"] is not None else "n/a"
                    for r in rows
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
    st.subheader("Project NPV Sensitivity (Revenue x Discount rate)")
    grid = sensitivity.run_npv_sensitivity_grid(inputs, debt_kwargs)
    st.plotly_chart(_npv_heatmap(grid), use_container_width=True)
    st.caption(
        "Grid independent of the project's current WACC: each column recalculates NPV at a "
        "different discount rate, each row applies the same revenue shock as the tornado "
        "above — useful to see at which rate NPV turns negative."
    )

    st.divider()
    st.caption(
        "Detailed market sensitivities (DAM Spread, ID Spread, Cycles, Capacity Price): "
        + ", ".join(sensitivity.DETAILED_VARIABLES)
        + " — available once the per-flow revenue detail is extracted from the full multi-sheet workbook."
    )
