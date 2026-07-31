from __future__ import annotations

import pandas as pd
import streamlit as st

from core import scenarios as scenarios_module
from core.models import ProjectInputs

SCENARIO_ORDER = ["Bear (P10)", "Base (P50)", "Bull (P90)"]
SCENARIO_COLORS = {"Bear (P10)": "#f7d6d6", "Base (P50)": "#d9ead3", "Bull (P90)": "#cfe2f3"}


def render(inputs: ProjectInputs, debt_kwargs: dict) -> None:
    st.caption("Facteurs d'ajustement appliqués aux hypothèses du BP par scénario.")

    defaults = scenarios_module.DEFAULT_SCENARIOS
    factor_df = pd.DataFrame(
        {
            name: [
                factors.revenue_multiplier,
                factors.capex_multiplier,
                factors.opex_multiplier,
                factors.interest_rate_adj,
            ]
            for name, factors in defaults.items()
        },
        index=["Revenue Multiplier (x)", "CAPEX Multiplier (x)", "OPEX Multiplier (x)", "Interest Rate Adj (+/-)"],
    )[SCENARIO_ORDER]

    edited = st.data_editor(factor_df, use_container_width=True, key="scenario_factor_editor")

    custom_scenarios = {
        name: scenarios_module.ScenarioFactors(
            revenue_multiplier=float(edited.loc["Revenue Multiplier (x)", name]),
            capex_multiplier=float(edited.loc["CAPEX Multiplier (x)", name]),
            opex_multiplier=float(edited.loc["OPEX Multiplier (x)", name]),
            interest_rate_adj=float(edited.loc["Interest Rate Adj (+/-)", name]),
        )
        for name in SCENARIO_ORDER
    }

    results = scenarios_module.run_scenarios(inputs, debt_kwargs, custom_scenarios)

    st.divider()
    st.subheader("Scenario Inputs (After Adjustments)")
    rows = {}
    for name in SCENARIO_ORDER:
        factors, result = results[name]
        first_op_year = next((y for y in result.yearly if y.revenue_keur > 0), None)
        rows[name] = {
            "Total Revenue (Y1, k€)": first_op_year.revenue_keur if first_op_year else 0.0,
            "Total CAPEX (k€)": result.capex_total_keur,
            "Total OPEX (Y1, k€)": abs(first_op_year.opex_keur) if first_op_year else 0.0,
            "Interest Rate": debt_kwargs.get("interest_rate", inputs.interest_rate) + factors.interest_rate_adj,
            "Debt Amount (k€)": result.debt_amount_keur,
            "Equity Amount (k€)": result.equity_amount_keur,
        }
    inputs_df = pd.DataFrame(rows)[SCENARIO_ORDER]
    interest_row = inputs_df.loc["Interest Rate"].map(lambda v: f"{v:.2%}")
    display_df = inputs_df.drop(index="Interest Rate").map(lambda v: f"{v:,.0f}".replace(",", " "))
    display_df.loc["Interest Rate"] = interest_row
    st.dataframe(display_df.loc[list(rows[SCENARIO_ORDER[0]].keys())], use_container_width=True)

    st.divider()
    st.subheader("Résultats par scénario")
    cols = st.columns(len(SCENARIO_ORDER))
    for col, name in zip(cols, SCENARIO_ORDER):
        _, result = results[name]
        with col:
            st.markdown(f"**{name}**")
            st.metric("Equity IRR", f"{result.equity_irr:.1%}" if result.equity_irr is not None else "n/a")
            st.metric("Project IRR", f"{result.project_irr:.1%}" if result.project_irr is not None else "n/a")
            st.metric("DSCR min", f"{result.dscr_min:.2f}x" if result.dscr_min is not None else "n/a")
            st.metric("NPV (k€)", f"{result.npv_keur:,.0f}".replace(",", " ") if result.npv_keur is not None else "n/a")
