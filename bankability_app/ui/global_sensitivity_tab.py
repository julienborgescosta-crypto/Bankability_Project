"""Analyse globale (Phase 5) : balaie tout l'espace des configs Aurora
(indépendant des projets saisis dans le Configurateur) -> table
triable/filtrable + heatmap sur 2 dimensions au choix. Voir docs/adr/0003,
docs/specs/global_sensitivity.md."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import aur_cases, contract_overlay, global_sensitivity
from ui.configurateur_tab import load_library

_CONTRACT_LABELS = {
    contract_overlay.FULL_MERCHANT: "Full merchant",
    contract_overlay.FLOOR: "Floor",
    contract_overlay.TOLLING: "Tolling",
}

_DIMENSIONS = {
    "Tension": "tension",
    "Type TURPE": "turpe_type",
    "Gabarit": "gabarit",
    "ORO": "oro",
    "Durée BESS (h)": "duree_h",
    "Année de COD": "cod_year",
    "Structure contractuelle": "contract_kind",
}

_METRICS = {
    "Project IRR": ("project_irr", True),
    "Equity IRR": ("equity_irr", True),
    "NPV (k€)": ("npv_keur", False),
    "Marge nette RtB (k€)": ("net_margin_keur", False),
    "Rendement build-and-flip (k€)": ("build_and_flip_net_return_keur", False),
}


@st.cache_data
def _run_cached(
    _au_store,
    _copex_library,
    _financing_terms: dict,
    operating_years: int,
    power_mw: float,
    contract_kinds: tuple[str, ...],
    floor_tolling_price: float,
    floor_tolling_duration: int,
    floor_sharing_pct: float,
):
    return global_sensitivity.run_global_sensitivity(
        _au_store,
        _copex_library,
        _financing_terms,
        operating_years=operating_years,
        power_mw=power_mw,
        contract_kinds=list(contract_kinds),
        floor_tolling_price_keur_per_mw_per_year=floor_tolling_price,
        floor_tolling_duration_years=floor_tolling_duration,
        floor_revenue_sharing_pct=floor_sharing_pct,
    )


def _rows_to_dataframe(rows: list[global_sensitivity.GlobalSensitivityRow]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "tension": r.tension,
                "turpe_type": r.turpe_type,
                "gabarit": "Oui" if r.gabarit else "Non",
                "oro": "Oui" if r.oro else "Non",
                "duree_h": r.duree_h,
                "cod_year": r.cod_year,
                "contract_kind": _CONTRACT_LABELS[r.contract_kind],
                "project_irr": r.row.project_irr,
                "equity_irr": r.row.equity_irr,
                "npv_keur": r.row.npv_keur,
                "net_margin_keur": r.row.net_margin_keur,
                "build_and_flip_net_return_keur": r.row.build_and_flip_net_return_keur,
            }
            for r in rows
        ]
    )


def _render_controls(au_store: aur_cases.AuStoreLibrary) -> dict:
    c1, c2, c3 = st.columns(3)
    with c1:
        operating_years = st.number_input(
            "Durée d'exploitation de référence (ans)", value=20, min_value=1, step=1
        )
        power_mw = st.number_input(
            "Puissance de référence (MW)",
            value=10.0,
            min_value=0.1,
            help="Fixée pour comparer les configs à taille égale — les métriques en k€ "
            "(NPV, marge, rendement) en dépendent, pas les TRI.",
        )
    with c2:
        contract_kinds = st.multiselect(
            "Structures contractuelles à balayer",
            [contract_overlay.FULL_MERCHANT, contract_overlay.FLOOR, contract_overlay.TOLLING],
            default=[
                contract_overlay.FULL_MERCHANT,
                contract_overlay.FLOOR,
                contract_overlay.TOLLING,
            ],
            format_func=lambda k: _CONTRACT_LABELS[k],
        )
    with c3:
        st.caption("Hypothèses floor/tolling (représentatives, **non confirmées**) :")
        floor_tolling_price = st.number_input(
            "Prix floor/tolling (k€/MW/an)", value=80.0, min_value=0.0
        )
        floor_tolling_duration = st.number_input(
            "Durée du contrat (ans)", value=10, min_value=1, step=1
        )
        floor_sharing_pct = (
            st.number_input(
                "Partage agrégateur au-dessus du floor (%)",
                value=40.0,
                min_value=0.0,
                max_value=100.0,
            )
            / 100
        )
    return {
        "operating_years": int(operating_years),
        "power_mw": float(power_mw),
        "contract_kinds": tuple(contract_kinds) or (contract_overlay.FULL_MERCHANT,),
        "floor_tolling_price": float(floor_tolling_price),
        "floor_tolling_duration": int(floor_tolling_duration),
        "floor_sharing_pct": float(floor_sharing_pct),
    }


def _render_table_and_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.subheader("Table complète (triable, filtrable)")
    st.caption(
        "Ces filtres s'appliquent aussi à la heatmap ci-dessous — sans filtre sur une "
        "dimension, la heatmap la moyenne (ex. filtrer Gabarit = Oui isole les configs "
        "gabarit sans les mélanger avec les configs sans limitation)."
    )
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        tensions = st.multiselect("Tension", sorted(df["tension"].unique()))
    with c2:
        turpe_types = st.multiselect("Type TURPE", sorted(df["turpe_type"].unique()))
    with c3:
        gabarits = st.multiselect("Gabarit", sorted(df["gabarit"].unique()))
    with c4:
        oros = st.multiselect("ORO", sorted(df["oro"].unique()))
    with c5:
        durees = st.multiselect("Durée BESS (h)", sorted(df["duree_h"].unique()))
    with c6:
        kinds = st.multiselect("Structure", sorted(df["contract_kind"].unique()))

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

    metric_label = st.selectbox("Seuil sur", list(_METRICS.keys()), key="threshold_metric")
    metric_col, is_pct = _METRICS[metric_label]
    # Sliders Streamlit utilisent un format sprintf - "%.1f%%" (litteral) est valide,
    # "%.1%" ne l'est pas (pas de caractere de conversion) et casse le rendu JS. Pour un
    # ratio (0.094 = 9.4 %), on affiche/saisit en points de pourcentage puis on reconvertit.
    scale = 100.0 if is_pct else 1.0
    threshold_scaled = st.slider(
        f"{metric_label} minimum",
        min_value=float(df[metric_col].min(skipna=True)) * scale,
        max_value=float(df[metric_col].max(skipna=True)) * scale,
        value=float(df[metric_col].min(skipna=True)) * scale,
        format="%.1f%%" if is_pct else "%.0f",
    )
    threshold = threshold_scaled / scale
    filtered = filtered[filtered[metric_col] >= threshold]

    display = filtered.rename(
        columns={
            "tension": "Tension",
            "turpe_type": "Type TURPE",
            "gabarit": "Gabarit",
            "oro": "ORO",
            "duree_h": "Durée (h)",
            "cod_year": "COD",
            "contract_kind": "Structure",
            "project_irr": "Project IRR",
            "equity_irr": "Equity IRR",
            "npv_keur": "NPV (k€)",
            "net_margin_keur": "Marge nette RtB (k€)",
            "build_and_flip_net_return_keur": "Rendement build-and-flip (k€)",
        }
    )
    st.dataframe(
        display.style.format({"Project IRR": "{:.1%}", "Equity IRR": "{:.1%}"}, na_rep="n/a"),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"{len(filtered)} / {len(df)} cas affichés.")
    return filtered


_FACET_CANDIDATES = [
    "Tension",
    "Type TURPE",
    "Gabarit",
    "ORO",
    "Durée BESS (h)",
    "Structure contractuelle",
]


def _single_heatmap(
    df: pd.DataFrame, *, x_col: str, y_col: str, metric_col: str, is_pct: bool, title: str
) -> go.Figure:
    pivot = df.pivot_table(values=metric_col, index=y_col, columns=x_col, aggfunc="mean")
    counts = df.pivot_table(values=metric_col, index=y_col, columns=x_col, aggfunc="count")
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[str(c) for c in pivot.columns],
            y=[str(i) for i in pivot.index],
            customdata=counts.values,
            hovertemplate="%{x} / %{y} : %{z}<br>%{customdata} cas moyennés<extra></extra>",
            colorscale="RdYlGn",
            colorbar={"tickformat": ".0%" if is_pct else None},
            zmid=0.0 if not is_pct else None,
        )
    )
    fig.update_layout(title=title, margin={"t": 40, "b": 20})
    return fig


def _render_heatmap(df: pd.DataFrame) -> None:
    st.subheader("Coupe 2 variables (heatmap)")
    st.caption(
        "Utilise les mêmes filtres que la table ci-dessus. Une case moyenne les cas restants "
        'sur toute dimension non choisie ici et non filtrée au-dessus — utilise "Séparer par" '
        "pour comparer des sous-sections (ex. Injection vs Soutirage vs Classique) sans les "
        "mélanger dans une même moyenne."
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        x_label = st.selectbox("Axe X", list(_DIMENSIONS.keys()), index=4)
    with c2:
        y_label = st.selectbox("Axe Y", list(_DIMENSIONS.keys()), index=0)
    with c3:
        metric_label = st.selectbox("Métrique", list(_METRICS.keys()), key="heatmap_metric")
    with c4:
        facet_choices = [d for d in _FACET_CANDIDATES if d not in (x_label, y_label)]
        facet_label = st.selectbox(
            "Séparer par (petits multiples)", ["Aucun", *facet_choices], key="heatmap_facet"
        )

    x_col, y_col = _DIMENSIONS[x_label], _DIMENSIONS[y_label]
    metric_col, is_pct = _METRICS[metric_label]
    if x_col == y_col:
        st.caption("Choisis deux dimensions différentes pour l'axe X et l'axe Y.")
        return

    if facet_label == "Aucun":
        fig = _single_heatmap(
            df,
            x_col=x_col,
            y_col=y_col,
            metric_col=metric_col,
            is_pct=is_pct,
            title=f"{metric_label} (moyenne sur les autres dimensions)",
        )
        st.plotly_chart(fig, use_container_width=True)
        return

    facet_col = _DIMENSIONS[facet_label]
    facet_values = sorted(df[facet_col].unique())
    if not facet_values:
        st.caption("Aucune valeur disponible pour cette séparation avec les filtres actuels.")
        return
    cols = st.columns(len(facet_values))
    for col, value in zip(cols, facet_values, strict=True):
        subset = df[df[facet_col] == value]
        with col:
            if subset.empty:
                st.caption(f"{facet_label} = {value} : aucun cas.")
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
        "Balaie l'espace des 22 configs Aurora (`AU_Store`, dont 4 ORO) x années de COD valides x "
        "structure contractuelle, indépendamment des projets saisis dans le Configurateur — pour "
        'répondre à "quelles configs/COD/segment/TURPE permettent d\'atteindre un TRI cible ?". '
        "Voir docs/specs/aur_v2_methodology.md section 5."
    )
    au_store, copex_library, financing_terms = load_library()
    controls = _render_controls(au_store)

    rows, skipped = _run_cached(
        au_store,
        copex_library,
        financing_terms,
        controls["operating_years"],
        controls["power_mw"],
        controls["contract_kinds"],
        controls["floor_tolling_price"],
        controls["floor_tolling_duration"],
        controls["floor_sharing_pct"],
    )
    if skipped:
        with st.expander(f"{len(skipped)} cas ignorés (données manquantes)"):
            for reason in skipped:
                st.write(f"- {reason}")

    if not rows:
        st.warning("Aucun cas calculable avec ces paramètres.")
        return

    df = _rows_to_dataframe(rows)
    st.divider()
    filtered = _render_table_and_filters(df)
    st.divider()
    if filtered.empty:
        st.warning("Aucun cas ne correspond aux filtres actuels.")
    else:
        _render_heatmap(filtered)
