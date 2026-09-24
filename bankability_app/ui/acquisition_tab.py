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
        "Reframes the analysis as an M&A question: how much can you pay to acquire this "
        "project (SPV), rather than developing it in-house — solves for the maximum "
        "acquisition premium instead of assuming it."
    )
    acquisition_mode = st.checkbox("Analyze as an acquisition (M&A)")
    if not acquisition_mode:
        st.info("Check the box to run the acquisition analysis on this project.")
        return

    target_irr = st.slider("Target equity return (buyer)", 5.0, 25.0, 12.0, step=0.5) / 100
    valuation = acquisition.compute_acquisition_valuation(result, target_irr)

    st.subheader("Maximum acquisition premium")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Base equity required", _fmt_keur(valuation.base_equity_keur))
    c2.metric("PV of future equity cashflows", _fmt_keur(valuation.pv_future_equity_cashflows_keur))
    c3.metric(
        "Max acquisition premium (headroom)", _fmt_keur(valuation.max_acquisition_premium_keur)
    )
    c4.metric("Max total equity check", _fmt_keur(valuation.max_total_equity_check_keur))
    st.caption(
        f"Project Equity IRR (current financing): {_fmt_pct(valuation.actual_equity_irr)} "
        f"— buyer target: {_fmt_pct(target_irr)}."
    )

    if valuation.max_acquisition_premium_keur < 0:
        st.warning(
            "Negative premium: at the base equity amount, the project doesn't cover the "
            "target return. You'd need to pay **less** than the base equity (a discount), "
            "not a premium — or revisit the target return / financing assumptions."
        )
    else:
        st.success(
            "You can pay up to this premium above the base equity while still hitting the "
            "target return."
        )

    st.caption(
        "Formula: Purchase Price + Base Equity Investment ≤ PV of future equity cashflows "
        "@ target return. The premium is never an input assumption — it's a residual value "
        "that moves with the project's economics."
    )

    st.divider()
    st.subheader("Acquisition premium sensitivity")
    st.caption(
        "Same logic as the Sensitivity Analysis tab, but on the acquisition premium rather "
        "than Equity IRR/DSCR. 'OPEX' is the closest proxy for a grid cost shock in this model."
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
    st.subheader("Market benchmarks (context, not calculated)")
    st.caption(
        "Indicative external benchmarks by development stage — useful as a reference, but "
        "not your ceiling: your ceiling is what the calculation above says you can pay."
    )
    benchmarks_table = pd.DataFrame(
        {
            "Stage": [b["stage"] for b in acquisition.STAGE_BENCHMARKS],
            "Example": [b["example"] for b in acquisition.STAGE_BENCHMARKS],
            "Benchmark": [b["benchmark"] for b in acquisition.STAGE_BENCHMARKS],
            "Note": [b["note"] for b in acquisition.STAGE_BENCHMARKS],
        }
    )
    st.dataframe(benchmarks_table, hide_index=True, use_container_width=True)
