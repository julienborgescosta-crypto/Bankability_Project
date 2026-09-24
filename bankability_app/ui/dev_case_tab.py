from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from core import dev_case, financial_engine
from core.models import ProjectInputs, ProjectResults

# Un cas de développement construit de zéro n'a pas de covenant DSCR propre au
# projet (target_dscr) comme un BP déjà chiffré (I-Project) - le mode "dscr" du
# sidebar (hérité du BP principal éventuellement uploadé) n'est donc pas
# applicable ici ; on ne réutilise que gearing/taux/tenor du sidebar.
_SAFE_DEBT_KEYS = {
    "gearing_pct",
    "interest_rate",
    "debt_tenor_years",
    "repowering_gearing_pct",
    "repowering_interest_rate",
    "repowering_debt_tenor_years",
}


def _safe_debt_kwargs(debt_kwargs: dict) -> dict:
    return {k: v for k, v in debt_kwargs.items() if k in _SAFE_DEBT_KEYS}


def _fmt_keur(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f} k€".replace(",", " ")


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _cash_profile_chart(result: ProjectResults) -> go.Figure:
    years = [y.year for y in result.yearly]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=years, y=[y.revenue_keur for y in result.yearly], name="Revenue", mode="lines")
    )
    fig.add_trace(
        go.Scatter(x=years, y=[y.cfads_keur for y in result.yearly], name="CFADS", mode="lines")
    )
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[y.debt_service_keur for y in result.yearly],
            name="Debt service",
            mode="lines",
        )
    )
    fig.update_layout(title="Annual cash profile (k€)", legend={"orientation": "h"})
    return fig


def _render_form(
    defaults: dev_case.DevCaseParams, aurora_library: dev_case.AuroraLibrary
) -> dev_case.DevCaseParams:
    year_range = aurora_library.year_range()
    c1, c2, c3 = st.columns(3)
    with c1:
        if year_range is not None:
            min_year, max_year = year_range
            cod_year = st.number_input(
                "COD year",
                value=min(max(defaults.cod_year, min_year), max_year),
                min_value=min_year,
                max_value=max_year,
                step=1,
            )
            st.caption(
                f"CF Aurora revenue available {min_year}-{max_year}. CAPEX/OPEX escalated up "
                "to 2034 (capped beyond, see docs/specs/dev_case.md)."
            )
        else:
            cod_year = st.number_input("COD year", value=defaults.cod_year, step=1)
        power_mw = st.number_input("Power (MW)", value=defaults.power_mw, min_value=0.1)
        duration_h = st.selectbox(
            "BESS duration (h)", [2, 4], index=[2, 4].index(defaults.duration_h)
        )
    with c2:
        connection_type = st.selectbox(
            "Connection type",
            dev_case.CONNECTION_TYPES,
            index=(
                dev_case.CONNECTION_TYPES.index(defaults.connection_type)
                if defaults.connection_type in dev_case.CONNECTION_TYPES
                else 0
            ),
        )
        voltage_class_override = None
        if connection_type.startswith("Industrial"):
            voltage_class_override = st.selectbox(
                "Voltage class (industrial connection)", dev_case.VOLTAGE_CLASSES
            )
        turpe_type = st.selectbox(
            "TURPE type",
            dev_case.TURPE_TYPES,
            index=(
                dev_case.TURPE_TYPES.index(defaults.turpe_type)
                if defaults.turpe_type in dev_case.TURPE_TYPES
                else 0
            ),
        )
        gabarit = st.checkbox("Gabarit", value=defaults.gabarit)
        repowering = st.checkbox("Repowering", value=defaults.repowering)
    with c3:
        operating_years = st.number_input(
            "Operating life (years)", value=defaults.operating_years, min_value=1, step=1
        )
        land_lease_opex_keur = st.number_input(
            "Land lease OPEX (k€/yr)", value=defaults.land_lease_opex_keur
        )
        connection_capex_mode = st.selectbox(
            "Grid connection CAPEX mode",
            dev_case.CONNECTION_CAPEX_MODES,
            index=dev_case.CONNECTION_CAPEX_MODES.index(defaults.connection_capex_mode),
            format_func=lambda m: {
                "library": "Library (segment/duration)",
                "manual": "Manual value",
                "distance_rte": "Distance to RTE substation",
                "distance_rte_and_substation": "Distance to RTE + HV substation",
            }[m],
        )
        distance_rte_km = defaults.distance_rte_km
        distance_substation_km = defaults.distance_substation_km
        manual_connection_capex_keur = defaults.manual_connection_capex_keur
        if connection_capex_mode == "manual":
            manual_connection_capex_keur = st.number_input(
                "Manual grid connection CAPEX (k€)", value=defaults.manual_connection_capex_keur
            )
        elif connection_capex_mode in ("distance_rte", "distance_rte_and_substation"):
            distance_rte_km = st.number_input(
                "Distance to RTE substation (km)", value=defaults.distance_rte_km, min_value=0.0
            )
            if connection_capex_mode == "distance_rte_and_substation":
                distance_substation_km = st.number_input(
                    "Distance to HV substation (km)",
                    value=defaults.distance_substation_km,
                    min_value=0.0,
                )

    return dev_case.DevCaseParams(
        cod_year=int(cod_year),
        power_mw=float(power_mw),
        duration_h=int(duration_h),
        connection_type=connection_type,
        turpe_type=turpe_type,
        gabarit=gabarit,
        repowering=repowering,
        operating_years=int(operating_years),
        connection_capex_mode=connection_capex_mode,
        distance_rte_km=distance_rte_km,
        distance_substation_km=distance_substation_km,
        manual_connection_capex_keur=manual_connection_capex_keur,
        land_lease_opex_keur=land_lease_opex_keur,
        voltage_class_override=voltage_class_override,
        name=defaults.name,
        location=defaults.location,
    )


def render(
    defaults: dev_case.DevCaseParams,
    aurora_library: dev_case.AuroraLibrary,
    copex_library: dev_case.CopexLibrary,
    debt_kwargs: dict,
) -> tuple[ProjectInputs, ProjectResults] | None:
    """Formulaire de cas de développement -> cas de base -> leviers de
    sensibilité structurels. Retourne (inputs, result) du cas de base si la
    case "Analyse bancabilité complète" est cochée (pour activer les autres
    onglets sur ce cas), sinon None."""
    st.caption(
        "Builds a base case from development assumptions (COD, power, duration, grid "
        "segment, TURPE type...), pulling revenue from CF Aurora and CAPEX/OPEX from "
        "COPEX_library — rather than starting from an already-priced Business Plan."
    )
    params = _render_form(defaults, aurora_library)
    debt_kwargs = _safe_debt_kwargs(debt_kwargs)

    year_range = aurora_library.year_range()
    if year_range is not None:
        _, max_year = year_range
        last_operating_year = params.cod_year + params.operating_years - 1
        if last_operating_year > max_year:
            st.warning(
                f"The operating life extends beyond CF Aurora's coverage ({max_year}): years "
                f"{max_year + 1}-{last_operating_year} will have zero revenue instead of a "
                "real forecast. Reduce the COD or the operating life to stay within the "
                "covered range."
            )

    try:
        inputs = dev_case.build_project_inputs(params, aurora_library, copex_library)
    except ValueError as exc:
        st.error(f"Unable to build the base case: {exc}")
        return None

    result = financial_engine.compute_results(inputs, **debt_kwargs)

    st.divider()
    st.subheader("Base case")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total CAPEX", _fmt_keur(result.capex_total_keur))
    c2.metric("Project IRR", _fmt_pct(result.project_irr))
    c3.metric("Equity IRR", _fmt_pct(result.equity_irr))
    c4.metric("DSCR min", f"{result.dscr_min:.2f}x" if result.dscr_min is not None else "n/a")
    st.plotly_chart(_cash_profile_chart(result), use_container_width=True)

    st.divider()
    st.subheader("Sensitivity levers")

    st.markdown("**IRR vs distance to RTE substation**")
    distances = [0.0, 1.0, 2.0, 5.0, 10.0, 20.0]
    try:
        distance_rows = dev_case.run_distance_sensitivity(
            params, aurora_library, copex_library, distances, compute_kwargs=debt_kwargs
        )
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=[r["distance_km"] for r in distance_rows],
                y=[r["project_irr"] for r in distance_rows],
                mode="lines+markers",
                name="Project IRR",
            )
        )
        fig.update_layout(
            xaxis_title="Distance (km)", yaxis_title="Project IRR", yaxis_tickformat=".0%"
        )
        st.plotly_chart(fig, use_container_width=True)
    except ValueError as exc:
        st.caption(f"Not available: {exc}")

    st.markdown("**IRR vs BESS duration (2h / 4h)**")
    try:
        duration_rows = dev_case.run_duration_sensitivity(
            params, aurora_library, copex_library, [2, 4], compute_kwargs=debt_kwargs
        )
        for row in duration_rows:
            st.write(f"{row['duration_h']}h: Project IRR = {_fmt_pct(row['project_irr'])}")
    except ValueError as exc:
        st.caption(f"Not available: {exc}")

    st.markdown("**Config comparison (segment/TURPE/gabarit/repowering)**")
    configs = [
        {},
        {"turpe_type": "Injection"},
        {"turpe_type": "Soutirage"},
        {"gabarit": not params.gabarit},
        {"repowering": not params.repowering},
    ]
    try:
        config_rows = dev_case.run_config_sensitivity(
            params, aurora_library, copex_library, configs, compute_kwargs=debt_kwargs
        )
        for row in config_rows:
            st.write(f"{row['label']}: Project IRR = {_fmt_pct(row['project_irr'])}")
    except ValueError as exc:
        st.caption(f"Not available: {exc}")

    st.markdown("**IRR vs COD year**")
    cod_years = [params.cod_year + i for i in range(-2, 3)]
    if year_range is not None:
        min_year, max_year = year_range
        cod_years = [y for y in cod_years if min_year <= y <= max_year]
    try:
        cod_rows = dev_case.run_cod_year_sensitivity(
            params, aurora_library, copex_library, cod_years, compute_kwargs=debt_kwargs
        )
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=[r["cod_year"] for r in cod_rows],
                y=[r["project_irr"] for r in cod_rows],
                mode="lines+markers",
                name="Project IRR",
            )
        )
        fig.update_layout(xaxis_title="COD year", yaxis_title="Project IRR", yaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)
    except ValueError as exc:
        st.caption(f"Not available: {exc}")

    st.divider()
    full_analysis = st.checkbox(
        "Full bankability analysis (on the base case)",
        help="Activates the Cashflow/Scenario/Sensitivity/Stress-Test/Risk/Acquisition tabs "
        "on this built base case, as if it came from an already-priced Business Plan.",
    )
    if full_analysis:
        return inputs, result
    return None
