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

st.set_page_config(page_title="Bancabilité BESS", layout="wide")

mode = st.sidebar.radio(
    "Mode",
    [
        "Analyser un Business Plan",
        "Configurateur Aurora (multi-projets)",
        "Analyse globale Aurora",
    ],
)
st.sidebar.divider()

if mode == "Configurateur Aurora (multi-projets)":
    st.title("Configurateur Aurora — portefeuille multi-projets")
    configurateur_tab.render()
    st.stop()

if mode == "Analyse globale Aurora":
    st.title("Analyse globale Aurora — espace des configs")
    global_sensitivity_tab.render()
    st.stop()

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
    "Format détecté : classeur complet (O-Financials / O-Control)"
    if bp_format == "full"
    else "Format détecté : onglet résumé"
)

with st.sidebar:
    st.header("Hypothèses de financement")
    if bp_format == "full":
        st.caption(
            "Valeurs par défaut extraites du BP (gearing, taux, maturité) — ajustables ci-dessous."
        )
    else:
        st.caption("Non extraites du BP — à définir ici (ou par défaut).")
    gearing_pct = (
        st.slider("Gearing (dette / CAPEX)", 0, 95, int(inputs.gearing_pct * 100), step=5) / 100
    )
    interest_rate = (
        st.slider("Taux d'intérêt de la dette", 1.0, 10.0, inputs.interest_rate * 100, step=0.1)
        / 100
    )
    debt_tenor = st.slider("Tenor de la dette (années)", 5, 20, inputs.debt_tenor_years, step=1)
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
            "Dimensionnement de la dette",
            options=["gearing", "dscr"],
            format_func=lambda m: (
                "Gearing fixe"
                if m == "gearing"
                else f"Dimensionné par DSCR (cible {inputs.target_dscr:.2f}x)"
            ),
        )
        if debt_sizing_mode == "dscr":
            st.caption(
                "La dette est calculée (sculptée) pour que CFADS / service ≥ DSCR cible chaque "
                "année, plafonnée par le gearing ci-dessus — comme dans votre BP source. Le "
                "gearing devient un plafond, pas un montant fixe."
            )
        else:
            st.caption(
                "La dette est un montant fixe : gearing × CAPEX (+ DSRA/frais de financement/cash "
                "minimum si extraits du BP). Le DSCR devient alors un résultat, pas une cible — il "
                "peut sortir en dessous du Target DSCR ci-dessus si le CFADS est trop faible face à "
                "ce montant de dette."
            )
        debt_kwargs["debt_sizing_mode"] = debt_sizing_mode
    else:
        st.caption(
            "Dimensionnement par DSCR indisponible (pas de Target DSCR extrait du BP) — "
            "gearing fixe utilisé."
        )

    has_repowering_capex = sum(1 for c in inputs.capex_keur if c < 0) > 1
    if has_repowering_capex:
        st.divider()
        st.header("Dette de repowering")
        st.caption(
            "Facility séparée de la dette initiale (2e sortie de CAPEX détectée dans le BP)."
        )
        repowering_gearing_pct = (
            st.slider("Gearing repowering", 0, 95, int(inputs.repowering_gearing_pct * 100), step=5)
            / 100
        )
        repowering_interest_rate = (
            st.slider(
                "Taux d'intérêt repowering",
                1.0,
                10.0,
                inputs.repowering_interest_rate * 100,
                step=0.1,
            )
            / 100
        )
        repowering_debt_tenor = st.slider(
            "Tenor repowering (années)", 5, 20, inputs.repowering_debt_tenor_years, step=1
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
    "Vue Projet",
    "Cashflow",
    "Scenario Analysis",
    "Sensitivity Analysis",
    "Stress-Test",
    "Risk Dashboard",
    "Acquisition (M&A)",
]
if has_dev_case:
    tab_labels = ["Cas de développement"] + tab_labels
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
            # Un cas de développement synthétique n'a pas de covenant DSCR
            # propre au projet (target_dscr) - repli sur le gearing fixe pour
            # les autres onglets, quel que soit le mode choisi dans le sidebar
            # (qui reflète les hypothèses du BP principal éventuellement uploadé).
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
