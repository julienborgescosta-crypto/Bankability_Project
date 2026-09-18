"""Portefeuille multi-projets (Phase 4) : execute les 3 strategies sur N projets
Aurora et agrege les KPI en une table comparable - voir
docs/specs/aur_v2_methodology.md section 4, docs/adr/0005."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import aur_cases, contract_overlay, strategy
from .aur_cases import AuStoreLibrary
from .contract_overlay import ContractStructure
from .dev_case import CopexLibrary
from .models import ProjectInputs


@dataclass(frozen=True)
class ProjectConfig:
    """Un projet du Configurateur - toutes les caracteristiques necessaires pour
    construire un `ProjectInputs` Aurora et executer les 3 strategies. Les
    overrides restent optionnels : `None` = utiliser le defaut de
    `config/aur_financing_terms.yaml`/`aur_cases.devex_keur_for_tension`."""

    name: str
    duree_h: int
    tension: str
    turpe_type: str
    gabarit: bool
    cod_year: int
    power_mw: float
    operating_years: int = 20
    contract_structure: ContractStructure = field(
        default_factory=lambda: ContractStructure(kind=contract_overlay.FULL_MERCHANT)
    )
    gearing_pct_override: float | None = None
    interest_rate_override: float | None = None
    dsa_keur_override: float | None = None
    devex_keur_override: float | None = None
    carry_months_override: int | None = None
    carry_rate_override: float | None = None
    # Ajustement global (%) sur le CAPEX/OPEX Aurora - 0.0 = pas d'ajustement, +0.10 = +10%,
    # -0.10 = -10%. Applique directement a la serie ProjectInputs (pas seulement au run
    # financial_engine) pour que toutes les lectures downstream soient coherentes, y compris
    # compute_cod_resale_value_keur qui lit inputs.opex_keur directement, hors compute_results.
    capex_adjustment_pct: float = 0.0
    opex_adjustment_pct: float = 0.0


@dataclass(frozen=True)
class PortfolioRow:
    name: str
    config_label: str
    cod_year: int
    power_mw: float
    project_irr: float | None
    equity_irr: float | None
    npv_keur: float | None
    capex_total_keur: float
    opex_total_keur: float
    revenue_total_keur: float
    dscr_avg: float | None
    dscr_min: float | None
    gearing_used_pct: float
    debt_tenor_years: int
    target_dscr_used: float
    dsa_keur: float
    spa_keur: float
    tsp_keur: float
    devex_keur: float
    net_margin_keur: float
    resale_value_cod_keur: float
    build_and_flip_carry_cost_keur: float
    build_and_flip_net_return_keur: float


def build_project_inputs(
    config: ProjectConfig,
    au_store: AuStoreLibrary,
    copex_library: CopexLibrary,
    financing_terms: dict,
) -> tuple[ProjectInputs, list[float]]:
    """Construit le `ProjectInputs` Aurora pour ce projet : revenu de base
    (`aur_cases`), overlay contractuel (`contract_overlay`), puis frais
    d'agregateur sur la seule part merchant du revenu ajuste (docs/adr/0005).
    Retourne `(inputs, revenu_securise)` - le revenu securise sert ensuite au
    tiering DSCR/TRI cible (`core.contract_overlay`)."""
    au_config = au_store.config_by_attributes(
        duree_h=config.duree_h,
        tension=config.tension,
        turpe_type=config.turpe_type,
        gabarit=config.gabarit,
    )
    base_inputs = aur_cases.build_project_inputs(
        au_store,
        au_config,
        copex_library,
        cod_year=config.cod_year,
        power_mw=config.power_mw,
        operating_years=config.operating_years,
        name=config.name,
    )
    operating_revenue = base_inputs.revenues_keur[1:]
    operating_turpe = base_inputs.turpe_keur[1:]
    adjusted_revenue, secured_revenue = contract_overlay.apply_contract_overlay(
        operating_revenue, config.power_mw, config.contract_structure
    )
    merchant_revenue = [a - s for a, s in zip(adjusted_revenue, secured_revenue, strict=True)]
    fee_terms = aur_cases.aggregator_fee_terms_from_config(financing_terms)
    fees = aur_cases.aggregator_fee_series(
        merchant_revenue, operating_turpe, config.power_mw, fee_terms
    )
    final_operating_revenue = [a + f for a, f in zip(adjusted_revenue, fees, strict=True)]
    revenues_keur = [0.0] + final_operating_revenue

    # Ajustement global CAPEX/OPEX (%) - multiplie directement les series (deja
    # signees negatives) et les magnitudes scalaires "info" correspondantes,
    # pour que toute lecture downstream (compute_results, mais aussi
    # compute_cod_resale_value_keur qui lit inputs.opex_keur directement) soit
    # coherente.
    capex_keur = [c * (1 + config.capex_adjustment_pct) for c in base_inputs.capex_keur]
    opex_keur = [o * (1 + config.opex_adjustment_pct) for o in base_inputs.opex_keur]
    capex_initial_keur = base_inputs.capex_initial_keur * (1 + config.capex_adjustment_pct)
    capex_repowering_keur = base_inputs.capex_repowering_keur * (1 + config.capex_adjustment_pct)
    opex_year1_keur = base_inputs.opex_year1_keur * (1 + config.opex_adjustment_pct)

    net_cashflow_keur = [
        c + o + t + r + e
        for c, o, t, r, e in zip(
            capex_keur,
            opex_keur,
            base_inputs.turpe_keur,
            revenues_keur,
            base_inputs.end_of_life_keur,
            strict=True,
        )
    ]
    inputs = replace(
        base_inputs,
        capex_keur=capex_keur,
        opex_keur=opex_keur,
        capex_initial_keur=capex_initial_keur,
        capex_repowering_keur=capex_repowering_keur,
        opex_year1_keur=opex_year1_keur,
        revenues_keur=revenues_keur,
        net_cashflow_keur=net_cashflow_keur,
    )
    return inputs, secured_revenue


def _financing_kwargs(
    config: ProjectConfig, secured_revenue: list[float], operating_revenue: list[float], terms: dict
) -> dict:
    target_dscr = contract_overlay.blended_target_dscr(
        secured_revenue,
        operating_revenue,
        target_dscr_secured=terms["target_dscr_secured"],
        target_dscr_merchant=terms["target_dscr_merchant"],
    )
    tenor = contract_overlay.debt_maturity_years(
        config.contract_structure,
        maturity_full_merchant_years=terms["maturity_full_merchant_years"],
        maturity_years_added_after_ppa=terms["maturity_years_added_after_ppa"],
    )
    gearing_pct = config.gearing_pct_override if config.gearing_pct_override is not None else 0.70
    interest_rate = (
        config.interest_rate_override if config.interest_rate_override is not None else 0.05
    )
    return {
        "gearing_pct": gearing_pct,
        "interest_rate": interest_rate,
        "debt_tenor_years": tenor,
        "debt_sizing_mode": "dscr",
        "target_dscr": target_dscr,
    }


def _buyer_target_equity_irr(
    config: ProjectConfig, secured_revenue: list[float], operating_revenue: list[float], terms: dict
) -> float:
    return contract_overlay.blended_buyer_target_equity_irr(
        secured_revenue,
        operating_revenue,
        target_irr_secured=terms["buyer_target_equity_irr_secured"],
        target_irr_merchant=terms["buyer_target_equity_irr_merchant"],
    )


def run_portfolio(
    configs: list[ProjectConfig],
    au_store: AuStoreLibrary,
    copex_library: CopexLibrary,
    financing_terms: dict | None = None,
) -> list[PortfolioRow]:
    """Execute les 3 strategies pour chaque projet et agrege les KPI en une
    table comparable. `financing_terms` defaut a
    `aur_cases.load_financing_terms()` si non fourni."""
    terms = financing_terms if financing_terms is not None else aur_cases.load_financing_terms()
    rows = []
    for config in configs:
        inputs, secured_revenue = build_project_inputs(config, au_store, copex_library, terms)
        operating_revenue = inputs.revenues_keur[1:]
        financing_kwargs = _financing_kwargs(config, secured_revenue, operating_revenue, terms)
        buyer_target_equity_irr = _buyer_target_equity_irr(
            config, secured_revenue, operating_revenue, terms
        )
        devex_keur = (
            config.devex_keur_override
            if config.devex_keur_override is not None
            else aur_cases.devex_keur_for_tension(config.tension, terms)
        )
        dsa_keur = (
            config.dsa_keur_override
            if config.dsa_keur_override is not None
            else aur_cases.dsa_default_keur(
                duree_h=config.duree_h, power_mw=config.power_mw, devex_keur=devex_keur, terms=terms
            )
        )
        carry_months = (
            config.carry_months_override
            if config.carry_months_override is not None
            else terms["portage_duration_months"]
        )
        carry_rate = (
            config.carry_rate_override
            if config.carry_rate_override is not None
            else terms["carry_rate_pct"]
        )

        hold_result = strategy.compute_hold_and_operate(inputs, financing_kwargs=financing_kwargs)
        dev_sell_result = strategy.compute_dev_and_sell(
            inputs,
            dsa_keur=dsa_keur,
            buyer_target_equity_irr=buyer_target_equity_irr,
            devex_keur=devex_keur,
            financing_kwargs=financing_kwargs,
        )
        build_and_flip_result = strategy.compute_build_and_flip(
            inputs,
            dsa_keur=dsa_keur,
            buyer_target_equity_irr_at_rtb=buyer_target_equity_irr,
            resale_target_irr=buyer_target_equity_irr,
            carry_months=carry_months,
            carry_rate=carry_rate,
            financing_kwargs=financing_kwargs,
        )

        config_label = (
            f"{config.duree_h}h {config.tension} {config.turpe_type}"
            f"{' gabarit' if config.gabarit else ''} COD{config.cod_year}"
        )
        rows.append(
            PortfolioRow(
                name=config.name,
                config_label=config_label,
                cod_year=config.cod_year,
                power_mw=config.power_mw,
                project_irr=hold_result.project_irr,
                equity_irr=hold_result.equity_irr,
                npv_keur=hold_result.npv_keur,
                capex_total_keur=hold_result.capex_total_keur,
                opex_total_keur=-sum(inputs.opex_keur),
                revenue_total_keur=sum(inputs.revenues_keur),
                dscr_avg=hold_result.dscr_avg,
                dscr_min=hold_result.dscr_min,
                gearing_used_pct=financing_kwargs["gearing_pct"],
                debt_tenor_years=financing_kwargs["debt_tenor_years"],
                target_dscr_used=financing_kwargs["target_dscr"],
                dsa_keur=dev_sell_result.dsa_keur,
                spa_keur=dev_sell_result.spa_keur,
                tsp_keur=dev_sell_result.tsp_keur,
                devex_keur=dev_sell_result.devex_keur,
                net_margin_keur=dev_sell_result.net_margin_keur,
                resale_value_cod_keur=build_and_flip_result.resale_value_cod_keur,
                build_and_flip_carry_cost_keur=build_and_flip_result.carry_cost_keur,
                build_and_flip_net_return_keur=build_and_flip_result.net_return_keur,
            )
        )
    return rows
