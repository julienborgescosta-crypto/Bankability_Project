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
    # Repowering (demande de l'utilisateur, 2026-09-24, suite au constat qu'un
    # repowering force a l'op-year 15 sur un projet de 20 ans ne laisse que 5
    # ans pour en profiter) : desormais un choix explicite, pas un defaut subi.
    # Desactive automatiquement si operating_years < MIN_OPERATING_YEARS_FOR_REPOWERING
    # (voir repowering_candidate_years) - inutile de repowerer un projet trop court.
    #
    # Defaut dataclass = "manual"/15 (comportement identique a avant ce
    # changement) plutot que "auto", pour ne pas ralentir silencieusement
    # `global_sensitivity.py` (enumere ~22 configs x ~30 CODs - passer chaque
    # combo en mode "auto" multiplierait son cout par ~9, le nombre de
    # candidats balayes par `find_best_repowering_op_year`). Le formulaire
    # interactif du Configurateur (`ui/configurateur_tab.py`, ajout d'UN
    # projet a la fois) pre-selectionne "auto" explicitement dans son widget -
    # seul ce chemin paie le cout du balayage, la ou l'utilisateur en profite
    # reellement.
    repowering_enabled: bool = True
    repowering_year_mode: str = "manual"  # "auto" | "manual"
    repowering_op_year_manual: int = 15  # utilise seulement si repowering_year_mode == "manual"


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
    repowering_op_year_used: int | None
    repowering_auto_optimized: bool


# Repowering (demande de l'utilisateur, 2026-09-24) : un projet plus court
# que MIN_OPERATING_YEARS_FOR_REPOWERING n'offre pas la fonctionnalite (pas
# assez de vie pour que remplacer la batterie ait un sens). Les annees
# candidates balayees pour le mode "auto" vont de MIN_REPOWERING_OP_YEAR (pas
# de repowering avant 10 ans - la batterie n'a pas encore assez degrade pour
# le justifier) a `operating_years - MIN_REPOWERING_BENEFIT_YEARS` (garder au
# moins 2 ans pour profiter du reset apres repowering, sinon on paie le CAPEX
# juste avant d'arreter le projet - exactement le cas signale par
# l'utilisateur : repowering a l'annee 15 d'un projet de 15 ans).
MIN_OPERATING_YEARS_FOR_REPOWERING = 15
MIN_REPOWERING_OP_YEAR = 10
MIN_REPOWERING_BENEFIT_YEARS = 2


def repowering_candidate_years(operating_years: int) -> list[int]:
    """Annees op-year candidates pour le mode 'auto' - liste vide si le
    projet est trop court pour que le repowering ait un sens (voir les
    constantes ci-dessus)."""
    if operating_years < MIN_OPERATING_YEARS_FOR_REPOWERING:
        return []
    upper = operating_years - MIN_REPOWERING_BENEFIT_YEARS
    if upper < MIN_REPOWERING_OP_YEAR:
        return []
    return list(range(MIN_REPOWERING_OP_YEAR, upper + 1))


def find_best_repowering_op_year(
    config: ProjectConfig,
    au_store: AuStoreLibrary,
    copex_library: CopexLibrary,
    financing_terms: dict,
) -> tuple[int | None, float | None, list[tuple[int, float | None]]]:
    """Balaie `repowering_candidate_years(config.operating_years)` et retourne
    celle qui maximise l'Equity IRR de la strategie Garder & exploiter
    (confirme par l'utilisateur, 2026-09-24 - c'est la strategie ou le choix
    de l'annee de repowering a le plus d'impact direct). Retourne
    `(meilleure_annee, son_equity_irr, detail_par_annee)` -
    `(None, None, [])` si le projet est trop court pour offrir le repowering.

    Chaque candidat force `repowering_year_mode='manual'` pour eviter toute
    recursion avec ce meme balayage."""
    candidates = repowering_candidate_years(config.operating_years)
    if not candidates:
        return None, None, []

    details: list[tuple[int, float | None]] = []
    for candidate_year in candidates:
        candidate_config = replace(
            config,
            repowering_enabled=True,
            repowering_year_mode="manual",
            repowering_op_year_manual=candidate_year,
        )
        inputs, secured_revenue, _ = build_project_inputs(
            candidate_config, au_store, copex_library, financing_terms
        )
        operating_revenue = inputs.revenues_keur[1:]
        financing_kwargs = _financing_kwargs(
            candidate_config, secured_revenue, operating_revenue, financing_terms
        )
        hold_result = strategy.compute_hold_and_operate(inputs, financing_kwargs=financing_kwargs)
        details.append((candidate_year, hold_result.equity_irr))

    valid = [(year, irr) for year, irr in details if irr is not None]
    if not valid:
        return None, None, details
    best_year, best_irr = max(valid, key=lambda item: item[1])
    return best_year, best_irr, details


def _effective_repowering_op_year(
    config: ProjectConfig,
    au_store: AuStoreLibrary,
    copex_library: CopexLibrary,
    financing_terms: dict,
) -> tuple[int | None, bool]:
    """Resout l'annee de repowering a utiliser pour CE projet - retourne
    `(annee_ou_None, auto_optimisee)`. `None` = repowering desactive (case
    decochee, ou mode auto sans candidat valide car projet trop court)."""
    if not config.repowering_enabled:
        return None, False
    if config.repowering_year_mode == "manual":
        return config.repowering_op_year_manual, False
    best_year, _, _ = find_best_repowering_op_year(config, au_store, copex_library, financing_terms)
    return best_year, True


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
    `_resolve_au_config`/`core.config_extrapolation`). L'annee de repowering
    (si active) est resolue ici - manuelle telle quelle, ou optimisee via
    `find_best_repowering_op_year` en mode 'auto' (2026-09-24)."""
    resolved = _resolve_au_config(config, au_store)
    repowering_op_year, _auto_optimized = _effective_repowering_op_year(
        config, au_store, copex_library, financing_terms
    )
    base_inputs = aur_cases.build_project_inputs(
        resolved.library,
        resolved.config,
        copex_library,
        cod_year=config.cod_year,
        power_mw=config.power_mw,
        operating_years=config.operating_years,
        name=config.name,
        with_repowering=repowering_op_year is not None,
        repowering_op_year_override=repowering_op_year,
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
                repowering_op_year_used=inputs.repowering_op_year,
                repowering_auto_optimized=(
                    config.repowering_enabled
                    and config.repowering_year_mode == "auto"
                    and inputs.repowering_op_year is not None
                ),
            )
        )
    return rows
