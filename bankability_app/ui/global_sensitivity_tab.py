"""Analyse globale (Phase 5) : balaie tout l'espace des configs Aurora
(indépendant des projets saisis dans le Configurateur) -> table
triable/filtrable + heatmap sur 2 dimensions au choix. Voir docs/adr/0003,
docs/specs/global_sensitivity.md.

Textes UI en anglais depuis le 2026-09-24 - TURPE/HTA/HTB1/HTB2/HTB3/gabarit/ORO
restent en francais (voir ui/configurateur_tab.py, meme convention)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import aur_cases, contract_overlay, global_sensitivity
from ui import chart_theme
from ui.configurateur_tab import load_library

_CONTRACT_LABELS = {
    contract_overlay.FULL_MERCHANT: "Full merchant",
    contract_overlay.FLOOR: "Floor",
    contract_overlay.TOLLING: "Tolling",
}

_DIMENSIONS = {
    "Voltage (Tension)": "tension",
    "TURPE type": "turpe_type",
    "Gabarit": "gabarit",
    "ORO": "oro",
    "BESS duration (h)": "duree_h",
    "COD year": "cod_year",
    "Contract structure": "contract_kind",
}

_METRICS = {
    "Project IRR": ("project_irr", True),
    "Equity IRR": ("equity_irr", True),
    "NPV (k€)": ("npv_keur", False),
    "Net margin RtB (k€)": ("net_margin_keur", False),
    "Build-and-flip return (k€)": ("build_and_flip_net_return_keur", False),
}


@st.cache_data
def _run_cached(
    _au_store,
    _copex_library,
    _financing_terms: dict,
    operating_years: int,
    power_mw_by_tension: tuple[tuple[str, float], ...],
    contract_kinds: tuple[str, ...],
    floor_tolling_price: float,
    floor_tolling_duration: int,
    floor_sharing_pct: float,
    optimize_repowering: bool,
    include_extrapolated: bool,
    capex_opex_source: str,
):
    return global_sensitivity.run_global_sensitivity(
        _au_store,
        _copex_library,
        _financing_terms,
        capex_opex_source=capex_opex_source,
        operating_years=operating_years,
        power_mw_by_tension=dict(power_mw_by_tension),
        contract_kinds=list(contract_kinds),
        floor_tolling_price_keur_per_mw_per_year=floor_tolling_price,
        floor_tolling_duration_years=floor_tolling_duration,
        floor_revenue_sharing_pct=floor_sharing_pct,
        optimize_repowering=optimize_repowering,
        include_extrapolated=include_extrapolated,
    )


def _rows_to_dataframe(rows: list[global_sensitivity.GlobalSensitivityRow]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "tension": r.tension,
                "turpe_type": r.turpe_type,
                "gabarit": "Yes" if r.gabarit else "No",
                "oro": "Yes" if r.oro else "No",
                "duree_h": r.duree_h,
                "cod_year": r.cod_year,
                "contract_kind": _CONTRACT_LABELS[r.contract_kind],
                "project_irr": r.row.project_irr,
                "equity_irr": r.row.equity_irr,
                "npv_keur": r.row.npv_keur,
                "net_margin_keur": r.row.net_margin_keur,
                "build_and_flip_net_return_keur": r.row.build_and_flip_net_return_keur,
                "repowering_op_year": r.row.repowering_op_year_used,
                "repowering_auto_optimized": r.row.repowering_auto_optimized,
                "extrapolated": "Yes" if r.row.extrapolated else "No",
            }
            for r in rows
        ]
    )


def _render_controls(au_store: aur_cases.AuStoreLibrary) -> dict:
    c1, c2, c3 = st.columns(3)
    with c1:
        operating_years = st.number_input(
            "Reference operating life (years)", value=20, min_value=1, step=1
        )
        st.caption("Reference power (MW), one per voltage class:")
        st.caption(
            "A single power for every voltage class produces cases with no real connection "
            "equivalent (e.g. a 50 MW HTA case - HTA is an Enedis distribution connection, "
            "capped well below what an RTE HTB1/HTB2 connection supports). It also matters "
            "more than it should: the default CAPEX source (ICP) has flat-fee components "
            "(DSO connection, civil works) that make IRR swing heavily at unrealistic sizes - "
            "not just an HTA quirk. Defaults below are indicative connection-capacity "
            "gauges, **not Aurora-confirmed** — adjust freely (docs/specs/global_sensitivity.md)."
        )
        power_mw_by_tension = {}
        for tension, default in global_sensitivity.DEFAULT_POWER_MW_BY_TENSION.items():
            if tension == "HTB3":
                continue  # jamais utilise (HTB3 exclu, pas de donnees CAPEX/OPEX)
            power_mw_by_tension[tension] = st.number_input(
                f"{tension} (MW)", value=default, min_value=0.1, key=f"power_mw_{tension}"
            )
    with c2:
        optimize_repowering = st.checkbox(
            "Optimize repowering year (like Configurator)",
            value=False,
            key="optimize_repowering",
            help=(
                "Off (default): repowering forced at op-year 15 for every case, like the "
                "ProjectConfig default. On: sweeps the candidate repowering years and keeps "
                "whichever maximizes the Equity IRR for each case, same 'auto' mode the "
                "Configurator pre-selects by default — needed to get comparable IRRs between "
                "the two screens. Much slower (multiplies compute time by ~9 at 20 years of "
                "operating life, ~19 at 30 years — one extra full financial run per candidate "
                "year, per case)."
            ),
        )
        contract_kinds = st.multiselect(
            "Contract structures to sweep",
            [contract_overlay.FULL_MERCHANT, contract_overlay.FLOOR, contract_overlay.TOLLING],
            default=[
                contract_overlay.FULL_MERCHANT,
                contract_overlay.FLOOR,
                contract_overlay.TOLLING,
            ],
            format_func=lambda k: _CONTRACT_LABELS[k],
        )
        include_extrapolated = st.checkbox(
            "Include extrapolated configs",
            value=False,
            key="include_extrapolated",
            help=(
                "Off (default): only the 22 configs Aurora directly modelled in AU_Store. "
                "On: also sweeps the full theoretical space (duration x voltage x TURPE type x "
                "gabarit x ORO, HTB3 excluded) that the Configurator already knows how to "
                "extrapolate project-by-project but this screen didn't sweep until now - roughly "
                "2-3x more base cases (HTB2 already has the full real matrix, HTA/HTB1 much less "
                "so). Every extrapolated row is flagged in the 'Extrapolated' column — never "
                "mixed in unmarked with real Aurora data. Slower, proportionally to the extra "
                "cases."
            ),
        )
        capex_opex_source = (
            "aurora"
            if st.checkbox(
                "Use Aurora's own CAPEX/OPEX assumptions",
                value=False,
                key="capex_opex_source_aurora",
                help=(
                    "Off (default): our own costs (ICP real unit costs + Aurora fallback for "
                    "line items ICP doesn't cover - same default as the Configurator). On: "
                    "Aurora's COPEX_library assumptions only, for the whole sweep - same option "
                    "as 'Use Aurora's own CAPEX/OPEX assumptions' in the Configurator, applied "
                    "here to the full table at once rather than a second side-by-side table "
                    "(a full 2nd sweep of 150+ cases would be slow and hard to read)."
                ),
            )
            else "icp"
        )
    with c3:
        st.caption("Floor/tolling assumptions (representative, **not confirmed**):")
        floor_tolling_price = st.number_input(
            "Floor/tolling price (k€/MW/yr)", value=80.0, min_value=0.0
        )
        floor_tolling_duration = st.number_input(
            "Contract duration (years)", value=10, min_value=1, step=1
        )
        floor_sharing_pct = (
            st.number_input(
                "Aggregator sharing above the floor (%)",
                value=0.0,
                min_value=0.0,
                max_value=100.0,
            )
            / 100
        )
    return {
        "operating_years": int(operating_years),
        "power_mw_by_tension": tuple(
            sorted((t, float(mw)) for t, mw in power_mw_by_tension.items())
        ),
        "contract_kinds": tuple(contract_kinds) or (contract_overlay.FULL_MERCHANT,),
        "floor_tolling_price": float(floor_tolling_price),
        "floor_tolling_duration": int(floor_tolling_duration),
        "floor_sharing_pct": float(floor_sharing_pct),
        "optimize_repowering": bool(optimize_repowering),
        "include_extrapolated": bool(include_extrapolated),
        "capex_opex_source": capex_opex_source,
    }


def _render_table_and_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.subheader("Full table (sortable, filterable)")
    st.caption(
        "These filters also apply to the heatmap below — without a filter on a dimension, "
        "the heatmap averages over it (e.g. filtering Gabarit = Yes isolates gabarit configs "
        "instead of mixing them with unrestricted configs)."
    )
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    with c1:
        tensions = st.multiselect("Voltage (Tension)", sorted(df["tension"].unique()))
    with c2:
        turpe_types = st.multiselect("TURPE type", sorted(df["turpe_type"].unique()))
    with c3:
        gabarits = st.multiselect("Gabarit", sorted(df["gabarit"].unique()))
    with c4:
        oros = st.multiselect("ORO", sorted(df["oro"].unique()))
    with c5:
        durees = st.multiselect("BESS duration (h)", sorted(df["duree_h"].unique()))
    with c6:
        kinds = st.multiselect("Structure", sorted(df["contract_kind"].unique()))
    with c7:
        extrapolated_filter = st.multiselect("Extrapolated", sorted(df["extrapolated"].unique()))

    filtered = df.copy()
    if tensions:
        filtered = filtered[filtered["tension"].isin(tensions)]
    if turpe_types:
        filtered = filtered[filtered["turpe_type"].isin(turpe_types)]
    if gabarits:
        filtered = filtered[filtered["gabarit"].isin(gabarits)]
    if oros:
        filtered = filtered[filtered["oro"].isin(oros)]
    if durees:
        filtered = filtered[filtered["duree_h"].isin(durees)]
    if kinds:
        filtered = filtered[filtered["contract_kind"].isin(kinds)]
    if extrapolated_filter:
        filtered = filtered[filtered["extrapolated"].isin(extrapolated_filter)]

    metric_label = st.selectbox("Threshold on", list(_METRICS.keys()), key="threshold_metric")
    metric_col, is_pct = _METRICS[metric_label]
    # Sliders Streamlit utilisent un format sprintf - "%.1f%%" (litteral) est valide,
    # "%.1%" ne l'est pas (pas de caractere de conversion) et casse le rendu JS. Pour un
    # ratio (0.094 = 9.4 %), on affiche/saisit en points de pourcentage puis on reconvertit.
    scale = 100.0 if is_pct else 1.0
    threshold_scaled = st.slider(
        f"Minimum {metric_label}",
        min_value=float(df[metric_col].min(skipna=True)) * scale,
        max_value=float(df[metric_col].max(skipna=True)) * scale,
        value=float(df[metric_col].min(skipna=True)) * scale,
        format="%.1f%%" if is_pct else "%.0f",
    )
    threshold = threshold_scaled / scale
    filtered = filtered[filtered[metric_col] >= threshold]

    display = filtered.rename(
        columns={
            "tension": "Voltage (Tension)",
            "turpe_type": "TURPE type",
            "gabarit": "Gabarit",
            "oro": "ORO",
            "duree_h": "Duration (h)",
            "cod_year": "COD",
            "contract_kind": "Structure",
            "project_irr": "Project IRR",
            "equity_irr": "Equity IRR",
            "npv_keur": "NPV (k€)",
            "net_margin_keur": "Net margin RtB (k€)",
            "build_and_flip_net_return_keur": "Build-and-flip return (k€)",
            "repowering_op_year": "Repowering op-year",
            "repowering_auto_optimized": "Repowering optimized",
            "extrapolated": "Extrapolated",
        }
    )
    st.dataframe(
        display.style.format({"Project IRR": "{:.1%}", "Equity IRR": "{:.1%}"}, na_rep="n/a"),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"{len(filtered)} / {len(df)} cases shown.")
    return filtered


_FACET_CANDIDATES = [
    "Voltage (Tension)",
    "TURPE type",
    "Gabarit",
    "ORO",
    "BESS duration (h)",
    "Contract structure",
]


def _single_heatmap(
    df: pd.DataFrame, *, x_col: str, y_col: str, metric_col: str, is_pct: bool, title: str
) -> go.Figure:
    pivot = df.pivot_table(values=metric_col, index=y_col, columns=x_col, aggfunc="mean")
    counts = df.pivot_table(values=metric_col, index=y_col, columns=x_col, aggfunc="count")
    # Sequentiel (bleu, magnitude) pour les metriques % (toujours positives en
    # pratique) ; divergent bleu<->rouge (skill dataviz, remplace RdYlGn -
    # rouge/vert etant la confusion daltonienne la plus frequente) pour les
    # metriques k€ qui peuvent etre negatives (NPV, marge nette RtB, build-and-flip).
    colorscale = chart_theme.SEQUENTIAL_BLUE if is_pct else chart_theme.DIVERGING
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[str(c) for c in pivot.columns],
            y=[str(i) for i in pivot.index],
            customdata=counts.values,
            hovertemplate="%{x} / %{y}: %{z}<br>%{customdata} cases averaged<extra></extra>",
            colorscale=colorscale,
            colorbar={"tickformat": ".0%" if is_pct else None},
            zmid=0.0 if not is_pct else None,
        )
    )
    # x/y sont des dimensions categorielles (tension, gabarit, duree, annee de
    # COD...), jamais un champ continu - sans ce forcage, Plotly detecte "2"/"4"
    # (duree) ou "2028".."2040" (COD) comme numeriques et bascule l'axe en
    # lineaire, ce qui etale 2 categories sur une echelle 1-5 au lieu de 2
    # bandes egales (repere par l'utilisateur, 2026-09-24).
    fig.update_layout(
        title=title,
        margin={"t": 40, "b": 20},
        xaxis={"type": "category"},
        yaxis={"type": "category"},
    )
    return chart_theme.apply_layout(fig, legend_horizontal=False)


def _render_heatmap(df: pd.DataFrame) -> None:
    st.subheader("2-variable cut (heatmap)")
    st.caption(
        "Uses the same filters as the table above. Each cell averages the remaining cases "
        'over any dimension not chosen here and not filtered above — use "Split by" to '
        "compare sub-sections (e.g. Injection vs Soutirage vs Classique) without mixing "
        "them into a single average."
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        x_label = st.selectbox("X axis", list(_DIMENSIONS.keys()), index=4)
    with c2:
        y_label = st.selectbox("Y axis", list(_DIMENSIONS.keys()), index=0)
    with c3:
        metric_label = st.selectbox("Metric", list(_METRICS.keys()), key="heatmap_metric")
    with c4:
        facet_choices = [d for d in _FACET_CANDIDATES if d not in (x_label, y_label)]
        facet_label = st.selectbox(
            "Split by (small multiples)", ["None", *facet_choices], key="heatmap_facet"
        )

    x_col, y_col = _DIMENSIONS[x_label], _DIMENSIONS[y_label]
    metric_col, is_pct = _METRICS[metric_label]
    if x_col == y_col:
        st.caption("Choose two different dimensions for the X and Y axes.")
        return

    if facet_label == "None":
        fig = _single_heatmap(
            df,
            x_col=x_col,
            y_col=y_col,
            metric_col=metric_col,
            is_pct=is_pct,
            title=f"{metric_label} (averaged over the other dimensions)",
        )
        st.plotly_chart(fig, use_container_width=True)
        return

    facet_col = _DIMENSIONS[facet_label]
    facet_values = sorted(df[facet_col].unique())
    if not facet_values:
        st.caption("No value available for this split with the current filters.")
        return
    cols = st.columns(len(facet_values))
    for col, value in zip(cols, facet_values, strict=True):
        subset = df[df[facet_col] == value]
        with col:
            if subset.empty:
                st.caption(f"{facet_label} = {value}: no case.")
                continue
            fig = _single_heatmap(
                subset,
                x_col=x_col,
                y_col=y_col,
                metric_col=metric_col,
                is_pct=is_pct,
                title=f"{facet_label} = {value}",
            )
            # key explicite : Streamlit deduplique les st.plotly_chart par ID
            # auto-genere (type + parametres d'appel, pas le contenu de la
            # figure) - sans key unique, 2 petits multiples peuvent lever
            # StreamlitDuplicateElementId au lieu de s'afficher.
            st.plotly_chart(fig, use_container_width=True, key=f"heatmap_{facet_col}_{value}")


def render() -> None:
    st.caption(
        "Sweeps the space of 22 Aurora configs (`AU_Store`, including 4 ORO) x valid COD years "
        "x contract structure, independent of the projects entered in the Configurator — to "
        'answer "which configs/COD/segment/TURPE reach a target IRR?". See '
        "docs/specs/aur_v2_methodology.md section 5."
    )
    with st.expander("How to read the metrics"):
        st.markdown(
            "- **Project IRR** / **Equity IRR** / **NPV**: the « Hold & Operate » strategy — "
            "the standard financial engine applied directly to the project (CAPEX as outflow, "
            "net revenue as inflow, debt sized to a target DSCR).\n"
            "- **Net margin RtB (k€)**: the profit of the « Develop & sell at RtB » strategy — "
            "QEF develops up to Ready-to-Build and sells to a buyer who finances and operates "
            "it. Sale price = **DSA** (fixed amount = target development margin + DEVEX) + "
            "**SPA** (a *solved-for* top-up, not an input, so that the buyer's actual equity "
            "IRR lands exactly on their 9% target). Net margin = (DSA + SPA) − DEVEX, QEF's "
            "actual profit.\n"
            "- **Build-and-flip return (k€)**: the profit of the « Buy RtB & sell at COD » "
            "strategy — QEF this time buys the RtB (same DSA + SPA calculation as above), "
            "builds, carries the capital tied up (compound interest on RtB price + CAPEX, 18 "
            "months by default), then resells the operating asset at the present value of its "
            "future cashflows at the final buyer's target IRR. Return = resale value − RtB "
            "price − construction CAPEX − carry cost."
        )
    au_store, copex_library, financing_terms = load_library()
    controls = _render_controls(au_store)

    slow_reasons = []
    if controls["optimize_repowering"]:
        slow_reasons.append("repowering optimization")
    if controls["include_extrapolated"]:
        slow_reasons.append("extrapolated configs")
    spinner_message = (
        f"Running the full sweep with {' and '.join(slow_reasons)} (slower) — please wait..."
        if slow_reasons
        else "Running the full sweep..."
    )
    with st.spinner(spinner_message):
        rows, skipped = _run_cached(
            au_store,
            copex_library,
            financing_terms,
            controls["operating_years"],
            controls["power_mw_by_tension"],
            controls["contract_kinds"],
            controls["floor_tolling_price"],
            controls["floor_tolling_duration"],
            controls["floor_sharing_pct"],
            controls["optimize_repowering"],
            controls["include_extrapolated"],
            controls["capex_opex_source"],
        )
    if skipped:
        with st.expander(f"{len(skipped)} case(s) skipped (missing data)"):
            for reason in skipped:
                st.write(f"- {reason}")

    if not rows:
        st.warning("No calculable case with these parameters.")
        return

    df = _rows_to_dataframe(rows)
    st.divider()
    filtered = _render_table_and_filters(df)
    st.divider()
    if filtered.empty:
        st.warning("No case matches the current filters.")
    else:
        _render_heatmap(filtered)
