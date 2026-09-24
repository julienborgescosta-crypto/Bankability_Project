"""Portefeuille multi-projets (Phase 4) : execute les 3 strategies sur N projets
Aurora et agrege les KPI en une table comparable - voir
docs/specs/aur_v2_methodology.md section 4, docs/adr/0005."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import aur_cases, config_extrapolation, contract_overlay, strategy
from .aur_cases import AuStoreLibrary
from .config_extrapolation import ResolvedConfig
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
    # Seuls 2 postes CAPEX/OPEX sont challengeables individuellement - pas un
    # ajustement global en % (retire le 2026-09-23 suite a un retour negatif,
    # voir docs/specs/portfolio.md) : le CAPEX de raccordement (comme dans le
    # BP Stockage Standalone 160926 - I-Project) et l'OPEX loyer foncier.
    connection_capex_mode: str = "library"  # "library" | "manual" | "distance_rte"
    manual_connection_capex_keur: float = 0.0  # utilise si connection_capex_mode == "manual"
    distance_rte_km: float = 0.0  # utilise si connection_capex_mode == "distance_rte"
    land_lease_opex_keur: float = 0.0  # ajoute tel quel a l'OPEX (non couvert par COPEX_library)
    # Limitation non-firm 3000h/an (Offre de Raccordement Optimise) - demande de
    # l'utilisateur, 2026-09-23 (les 6 cas ORO du databook Aurora partageaient la
    # cle de la variante standard et etaient ecartes en silence, voir
    # docs/specs/aur_cases.md). N'importe quelle combinaison duree/tension/type
    # TURPE/gabarit/ORO/heures de curtailment est desormais acceptee : reelle si
    # Aurora l'a modelisee, sinon estimee par `core.config_extrapolation`
    # (2026-09-24) - jamais un repli silencieux sur la courbe standard, jamais
    # un blocage pour une simple donnee manquante (`PortfolioRow.extrapolated`/
    # `extrapolation_notes` exposent toujours si et comment une estimation a
    # ete utilisee).
    oro_requested: bool = False
    curtailment_hours: int | None = None  # utilise seulement si oro_requested ; None = 3000h


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
    oro_requested: bool
    extrapolated: bool
    extrapolation_notes: tuple[str, ...]


def _resolve_au_config(config: ProjectConfig, au_store: AuStoreLibrary) -> ResolvedConfig:
    """Delegue a `config_extrapolation.resolve_config` : reel si Aurora a
    modelise exactement cette combinaison, sinon estime (jamais un blocage ni
    un repli silencieux - voir docs/specs/portfolio.md)."""
    return config_extrapolation.resolve_config(
        au_store,
        duree_h=config.duree_h,
        tension=config.tension,
        turpe_type=config.turpe_type,
        gabarit=config.gabarit,
        oro=config.oro_requested,
        curtailment_hours=config.curtailment_hours if config.oro_requested else None,
    )


def build_project_inputs(
    config: ProjectConfig,
    au_store: AuStoreLibrary,
    copex_library: CopexLibrary,
    financing_terms: dict,
) -> tuple[ProjectInputs, list[float], ResolvedConfig]:
    """Construit le `ProjectInputs` Aurora pour ce projet : revenu de base
    (`aur_cases`), overlay contractuel (`contract_overlay`), puis frais
    d'agregateur sur la seule part merchant du revenu ajuste (docs/adr/0005).
    Retourne `(inputs, revenu_securise, resolved)` - le revenu securise sert
    ensuite au tiering DSCR/TRI cible (`core.contract_overlay`), `resolved`
    porte la config Aurora effectivement utilisee (reelle ou extrapolee, voir
    `_resolve_au_config`/`core.config_extrapolation`)."""
    resolved = _resolve_au_config(config, au_store)
    base_inputs = aur_cases.build_project_inputs(
        resolved.library,
        resolved.config,
        copex_library,
        cod_year=config.cod_year,
        power_mw=config.power_mw,
        operating_years=config.operating_years,
        name=config.name,
        connection_capex_mode=config.connection_capex_mode,
        manual_connection_capex_keur=config.manual_connection_capex_keur,
        distance_rte_km=config.distance_rte_km,
        land_lease_opex_keur=config.land_lease_opex_keur,
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

    net_cashflow_keur = [
        c + o + t + r + e
        for c, o, t, r, e in zip(
            base_inputs.capex_keur,
            base_inputs.opex_keur,
            base_inputs.turpe_keur,
            revenues_keur,
            base_inputs.end_of_life_keur,
            strict=True,
        )
    ]
    inputs = replace(base_inputs, revenues_keur=revenues_keur, net_cashflow_keur=net_cashflow_keur)
    return inputs, secured_revenue, resolved


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
        inputs, secured_revenue, resolved = build_project_inputs(
            config, au_store, copex_library, terms
        )
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
            f"{' gabarit' if config.gabarit else ''}{' ORO' if config.oro_requested else ''}"
            f"{' (extrapolé)' if resolved.config.extrapolated else ''} COD{config.cod_year}"
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
                oro_requested=config.oro_requested,
                extrapolated=resolved.config.extrapolated,
                extrapolation_notes=tuple(resolved.notes),
            )
        )
    return rows
