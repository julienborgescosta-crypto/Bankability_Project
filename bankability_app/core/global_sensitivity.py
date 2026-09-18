"""Analyse globale (Phase 5) : enumeration complete de l'espace des configs
Aurora (18 configs x annees de COD valides x structure contractuelle) -> KPI
par cas, exploitable en table triable/filtrable + heatmaps/coupes - voir
docs/adr/0003 et docs/specs/aur_v2_methodology.md section 5.

Espace fini et petit (pas un balayage classique variable-par-variable comme
core/sensitivity.py) : tout est calcule une fois, l'UI ne fait que
filtrer/pivoter la table deja en cache (`st.cache_data` cote appelant)."""

from __future__ import annotations

from dataclasses import dataclass

from . import aur_cases, config_space, contract_overlay, portfolio
from .aur_cases import AuStoreConfig, AuStoreLibrary
from .contract_overlay import ContractStructure
from .dev_case import CopexLibrary

DEFAULT_POWER_MW = 10.0
DEFAULT_OPERATING_YEARS = 20
DEFAULT_CONTRACT_KINDS = [
    contract_overlay.FULL_MERCHANT,
    contract_overlay.FLOOR,
    contract_overlay.TOLLING,
]
# Prix/duree floor-tolling representatifs pour le balayage global (pas une
# donnee Aurora, pas encore confirmes comme les autres hypotheses business -
# voir docs/specs/global_sensitivity.md "Questions ouvertes").
DEFAULT_FLOOR_TOLLING_PRICE_KEUR_PER_MW_PER_YEAR = 80.0
DEFAULT_FLOOR_TOLLING_DURATION_YEARS = 10
DEFAULT_FLOOR_REVENUE_SHARING_PCT = 0.4


@dataclass(frozen=True)
class GlobalSensitivityRow:
    """Un cas de l'espace des configs, avec ses dimensions et son KPI calcule -
    la jointure entre `ProjectConfig` et `PortfolioRow` que `portfolio.py` seul
    n'expose pas (necessaire pour filtrer/pivoter par dimension dans l'UI sans
    re-parser `config_label`)."""

    duree_h: int
    tension: str
    turpe_type: str
    gabarit: bool
    cod_year: int
    contract_kind: str
    row: portfolio.PortfolioRow


def valid_cod_years_for_calendar(au_store: AuStoreLibrary, operating_years: int) -> list[int]:
    """Toutes les annees de COD pour lesquelles les `operating_years` tombent
    entierement dans la couverture calendaire d'AU_Store (borne commune a
    toutes les configs, ex. 2027-2060)."""
    calendar_years = {year for curve in au_store.raw_by_key.values() for year in curve}
    calendar_min, calendar_max = min(calendar_years), max(calendar_years)
    last_valid_cod = calendar_max - operating_years + 1
    return list(range(calendar_min, last_valid_cod + 1))


def _contract_structure_for(
    kind: str, *, duration_years: int, price: float, sharing_pct: float
) -> ContractStructure:
    if kind == contract_overlay.FULL_MERCHANT:
        return ContractStructure(kind=kind)
    return ContractStructure(
        kind=kind,
        price_keur_per_mw_per_year=price,
        duration_years=duration_years,
        revenue_sharing_above_floor_pct=sharing_pct if kind == contract_overlay.FLOOR else 0.0,
    )


def enumerate_configs(
    au_store: AuStoreLibrary,
    copex_library: CopexLibrary,
    *,
    operating_years: int = DEFAULT_OPERATING_YEARS,
    power_mw: float = DEFAULT_POWER_MW,
    contract_kinds: list[str] | None = None,
    floor_tolling_price_keur_per_mw_per_year: float = DEFAULT_FLOOR_TOLLING_PRICE_KEUR_PER_MW_PER_YEAR,
    floor_tolling_duration_years: int = DEFAULT_FLOOR_TOLLING_DURATION_YEARS,
    floor_revenue_sharing_pct: float = DEFAULT_FLOOR_REVENUE_SHARING_PCT,
) -> list[tuple[AuStoreConfig, str, portfolio.ProjectConfig]]:
    """Enumere tous les `(config_aurora, structure_contractuelle, ProjectConfig)`
    valides - garde-fou COD2030 applique automatiquement (`config_space`).
    Exclut en amont les configs sans donnees CAPEX/OPEX dans `copex_library`
    (ex. HTB3 - voir `config_space.has_cost_data`) plutot que de les generer
    pour les voir echouer une par une au calcul."""
    contract_kinds = contract_kinds or DEFAULT_CONTRACT_KINDS
    candidate_cod_years = valid_cod_years_for_calendar(au_store, operating_years)
    duration_years = min(floor_tolling_duration_years, operating_years)

    entries: list[tuple[AuStoreConfig, str, portfolio.ProjectConfig]] = []
    for au_config in au_store.configs:
        if not config_space.has_cost_data(au_config, copex_library):
            continue
        cod_years = config_space.valid_cod_years(au_config, candidate_cod_years)
        for cod_year in cod_years:
            for kind in contract_kinds:
                structure = _contract_structure_for(
                    kind,
                    duration_years=duration_years,
                    price=floor_tolling_price_keur_per_mw_per_year,
                    sharing_pct=floor_revenue_sharing_pct,
                )
                project_config = portfolio.ProjectConfig(
                    name=f"{au_config.drop_key} COD{cod_year} {kind}",
                    duree_h=au_config.duree_h,
                    tension=au_config.tension,
                    turpe_type=au_config.turpe_type,
                    gabarit=au_config.gabarit,
                    cod_year=cod_year,
                    power_mw=power_mw,
                    operating_years=operating_years,
                    contract_structure=structure,
                )
                entries.append((au_config, kind, project_config))
    return entries


def run_global_sensitivity(
    au_store: AuStoreLibrary,
    copex_library: CopexLibrary,
    financing_terms: dict | None = None,
    **enumerate_kwargs,
) -> tuple[list[GlobalSensitivityRow], list[str]]:
    """Calcule le KPI de chaque cas de l'espace des configs. A mettre en cache
    par l'appelant (ex. `st.cache_data`) : le resultat ne depend d'aucun projet
    saisi par l'utilisateur, seulement des hypotheses de balayage.

    Retourne `(rows, skipped)` - les configs Aurora sans donnees CAPEX/OPEX
    (ex. HTB3, absent de `COPEX_library` malgre sa presence dans `AU_Store` -
    voir `config_space.has_cost_data`) sont exclues en amont de l'enumeration
    (`enumerate_configs`) et resumees en **une** entree explicite dans
    `skipped`, plutot qu'une entree par cas COD/structure genere pour rien.
    Un cas qui echoue malgre tout au calcul y est aussi ajoute individuellement
    - jamais silencieusement absent du resultat sans trace (brief section 7,
    "zero zero silencieux")."""
    terms = financing_terms if financing_terms is not None else aur_cases.load_financing_terms()

    skipped: list[str] = []
    excluded_configs = [
        c for c in au_store.configs if not config_space.has_cost_data(c, copex_library)
    ]
    if excluded_configs:
        skipped.append(
            f"{len(excluded_configs)} config(s) Aurora exclue(s) (pas de donnees CAPEX/OPEX "
            f"dans COPEX_library) : {', '.join(c.drop_key for c in excluded_configs)}."
        )

    entries = enumerate_configs(au_store, copex_library, **enumerate_kwargs)

    rows: list[GlobalSensitivityRow] = []
    for au_config, kind, project_config in entries:
        try:
            row = portfolio.run_portfolio([project_config], au_store, copex_library, terms)[0]
        except aur_cases.AuroraConfigError as exc:
            skipped.append(f"{project_config.name} : {exc}")
            continue
        rows.append(
            GlobalSensitivityRow(
                duree_h=au_config.duree_h,
                tension=au_config.tension,
                turpe_type=au_config.turpe_type,
                gabarit=au_config.gabarit,
                cod_year=project_config.cod_year,
                contract_kind=kind,
                row=row,
            )
        )
    return rows, skipped
