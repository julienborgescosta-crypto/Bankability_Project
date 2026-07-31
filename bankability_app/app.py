from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import bp_parser, financial_engine
from ui import cashflow, overview, risk_tab, scenario_tab, sensitivity_tab, stress_tab

st.set_page_config(page_title="Bancabilité BESS", layout="wide")
st.title("Outil de bancabilité BESS")

uploaded = st.file_uploader("Déposer le Business Plan (.xlsx ou .xlsm)", type=["xlsx", "xlsm"])

if uploaded is None:
    st.info("Déposez un fichier Excel de Business Plan pour lancer l'analyse.")
    st.stop()

if st.session_state.get("bp_filename") != uploaded.name:
    try:
        fmt = bp_parser.detect_format(uploaded)
        st.session_state["bp_inputs"] = bp_parser.parse_bp(uploaded)
        st.session_state["bp_filename"] = uploaded.name
        st.session_state["bp_format"] = fmt
    except Exception as exc:
        st.error(f"Erreur de lecture du fichier : {exc}")
        st.stop()

inputs = st.session_state["bp_inputs"]
bp_format = st.session_state.get("bp_format", "summary")
st.caption(
    "Format détecté : classeur complet (O-Financials / O-Control)" if bp_format == "full"
    else "Format détecté : onglet résumé"
)

with st.sidebar:
    st.header("Hypothèses de financement")
    if bp_format == "full":
        st.caption("Valeurs par défaut extraites du BP (gearing, taux, maturité) — ajustables ci-dessous.")
    else:
        st.caption("Non extraites du BP — à définir ici (ou par défaut).")
    gearing_pct = st.slider("Gearing (dette / CAPEX)", 0, 95, int(inputs.gearing_pct * 100), step=5) / 100
    interest_rate = st.slider("Taux d'intérêt de la dette", 1.0, 10.0, inputs.interest_rate * 100, step=0.1) / 100
    debt_tenor = st.slider("Tenor de la dette (années)", 5, 20, inputs.debt_tenor_years, step=1)
    wacc = st.slider("WACC", 1.0, 15.0, inputs.wacc * 100, step=0.1) / 100
    inputs.wacc = wacc

debt_kwargs = dict(gearing_pct=gearing_pct, interest_rate=interest_rate, debt_tenor_years=debt_tenor)
base_result = financial_engine.compute_results(inputs, **debt_kwargs)

tabs = st.tabs(
    ["Vue Projet", "Cashflow", "Scenario Analysis", "Sensitivity Analysis", "Stress-Test", "Risk Dashboard"]
)

with tabs[0]:
    overview.render(inputs, base_result)
with tabs[1]:
    cashflow.render(inputs, base_result)
with tabs[2]:
    scenario_tab.render(inputs, debt_kwargs)
with tabs[3]:
    sensitivity_tab.render(inputs, debt_kwargs)
with tabs[4]:
    stress_tab.render(inputs, debt_kwargs)
with tabs[5]:
    risk_tab.render(inputs, base_result)
