from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import bp_parser, dev_case_parser, financial_engine
from ui import (
    acquisition_tab,
    cashflow,
    configurateur_tab,
    dev_case_tab,
    global_sensitivity_tab,
    overview,
    risk_tab,
    scenario_tab,
    sensitivity_tab,
    stress_tab,
)

st.set_page_config(page_title="BESS Bankability", layout="wide")

mode = st.sidebar.radio(
    "Mode",
    [
        "Analyze a Business Plan",
        "Aurora Configurator (multi-project)",
        "Aurora Global Analysis",
    ],
)
st.sidebar.divider()

if mode == "Aurora Configurator (multi-project)":
    st.title("Aurora Configurator — multi-project portfolio")
    configurateur_tab.render()
    st.stop()

if mode == "Aurora Global Analysis":
    st.title("Aurora Global Analysis — config space")
    global_sensitivity_tab.render()
    st.stop()

st.title("BESS Bankability Tool")

uploaded = st.file_uploader("Upload the Business Plan (.xlsx or .xlsm)", type=["xlsx", "xlsm"])

if uploaded is None:
    st.info("Upload a Business Plan Excel file to start the analysis.")
    st.stop()

if st.session_state.get("bp_filename") != uploaded.name:
    try:
        fmt = bp_parser.detect_format(uploaded)
        st.session_state["bp_inputs"] = bp_parser.parse_bp(uploaded)
        st.session_state["bp_filename"] = uploaded.name
        st.session_state["bp_format"] = fmt
    except Exception as exc:
        st.error(f"Error reading the file: {exc}")
        st.stop()

    has_dev_case = dev_case_parser.has_dev_case_sheets(uploaded)
    st.session_state["has_dev_case"] = has_dev_case
    if has_dev_case:
        grids = dev_case_parser.load_dev_case_grids(uploaded)
        st.session_state["dev_case_defaults"] = dev_case_parser.parse_inputs_dev(grids[0])
        st.session_state["dev_case_copex_library"] = dev_case_parser.parse_copex_library(grids[1])
        st.session_state["dev_case_aurora_library"] = dev_case_parser.parse_cf_aurora(grids[2])

inputs = st.session_state["bp_inputs"]
has_dev_case = st.session_state.get("has_dev_case", False)
bp_format = st.session_state.get("bp_format", "summary")
st.caption(
    "Detected format: full workbook (O-Financials / O-Control)"
    if bp_format == "full"
    else "Detected format: summary sheet"
)

with st.sidebar:
    st.header("Financing assumptions")
    if bp_format == "full":
        st.caption(
            "Default values extracted from the Business Plan (gearing, rate, tenor) — "
            "adjustable below."
        )
    else:
        st.caption("Not extracted from the Business Plan — set here (or use the defaults).")
    gearing_pct = (
        st.slider("Gearing (debt / CAPEX)", 0, 95, int(inputs.gearing_pct * 100), step=5) / 100
    )
    interest_rate = (
        st.slider("Debt interest rate", 1.0, 10.0, inputs.interest_rate * 100, step=0.1) / 100
    )
    debt_tenor = st.slider("Debt tenor (years)", 5, 20, inputs.debt_tenor_years, step=1)
    wacc = st.slider("WACC", 1.0, 15.0, inputs.wacc * 100, step=0.1) / 100
    inputs.wacc = wacc

    debt_kwargs = {
        "gearing_pct": gearing_pct,
        "interest_rate": interest_rate,
        "debt_tenor_years": debt_tenor,
    }

    st.divider()
    if inputs.target_dscr is not None:
        debt_sizing_mode = st.radio(
            "Debt sizing",
            options=["gearing", "dscr"],
            format_func=lambda m: (
                "Fixed gearing"
                if m == "gearing"
                else f"DSCR-sized (target {inputs.target_dscr:.2f}x)"
            ),
        )
        if debt_sizing_mode == "dscr":
            st.caption(
                "Debt is calculated (sculpted) so that CFADS / debt service ≥ target DSCR every "
                "year, capped by the gearing above — as in your source Business Plan. Gearing "
                "becomes a cap, not a fixed amount."
            )
        else:
            st.caption(
                "Debt is a fixed amount: gearing × CAPEX (+ DSRA/financing fees/minimum cash if "
                "extracted from the Business Plan). DSCR then becomes an output, not a target — "
                "it can come out below the Target DSCR above if CFADS is too low relative to "
                "this debt amount."
            )
        debt_kwargs["debt_sizing_mode"] = debt_sizing_mode
    else:
        st.caption(
            "DSCR sizing unavailable (no Target DSCR extracted from the Business Plan) — "
            "fixed gearing used."
        )

    has_repowering_capex = sum(1 for c in inputs.capex_keur if c < 0) > 1
    if has_repowering_capex:
        st.divider()
        st.header("Repowering debt")
        st.caption(
            "A facility separate from the initial debt (2nd CAPEX outflow detected in the "
            "Business Plan)."
        )
        repowering_gearing_pct = (
            st.slider("Repowering gearing", 0, 95, int(inputs.repowering_gearing_pct * 100), step=5)
            / 100
        )
        repowering_interest_rate = (
            st.slider(
                "Repowering interest rate",
                1.0,
                10.0,
                inputs.repowering_interest_rate * 100,
                step=0.1,
            )
            / 100
        )
        repowering_debt_tenor = st.slider(
            "Repowering tenor (years)", 5, 20, inputs.repowering_debt_tenor_years, step=1
        )
        debt_kwargs.update(
            {
                "repowering_gearing_pct": repowering_gearing_pct,
                "repowering_interest_rate": repowering_interest_rate,
                "repowering_debt_tenor_years": repowering_debt_tenor,
            }
        )
base_result = financial_engine.compute_results(inputs, **debt_kwargs)

tab_labels = [
    "Project Overview",
    "Cashflow",
    "Scenario Analysis",
    "Sensitivity Analysis",
    "Stress-Test",
    "Risk Dashboard",
    "Acquisition (M&A)",
]
if has_dev_case:
    tab_labels = ["Development Case"] + tab_labels
tabs = st.tabs(tab_labels)

offset = 0
if has_dev_case:
    with tabs[0]:
        override = dev_case_tab.render(
            st.session_state["dev_case_defaults"],
            st.session_state["dev_case_aurora_library"],
            st.session_state["dev_case_copex_library"],
            debt_kwargs,
        )
        if override is not None:
            inputs, base_result = override
            # A synthetic development case has no project-specific DSCR covenant
            # (target_dscr) - fall back to fixed gearing for the other tabs,
            # regardless of the mode chosen in the sidebar (which reflects the
            # assumptions of a main Business Plan that may have been uploaded).
            debt_kwargs = {
                k: v for k, v in debt_kwargs.items() if k not in ("debt_sizing_mode", "target_dscr")
            }
    offset = 1

with tabs[offset + 0]:
    overview.render(inputs, base_result, debt_kwargs.get("debt_sizing_mode", "gearing"))
with tabs[offset + 1]:
    cashflow.render(inputs, base_result)
with tabs[offset + 2]:
    scenario_tab.render(inputs, debt_kwargs)
with tabs[offset + 3]:
    sensitivity_tab.render(inputs, debt_kwargs)
with tabs[offset + 4]:
    stress_tab.render(inputs, debt_kwargs)
with tabs[offset + 5]:
    risk_tab.render(inputs, base_result)
with tabs[offset + 6]:
    acquisition_tab.render(inputs, base_result, debt_kwargs)
