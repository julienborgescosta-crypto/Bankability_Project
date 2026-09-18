"""Lit `AU_Store` (18 configurations Aurora standalone Q2 2026) et construit un
`ProjectInputs` par config/COD/puissance - voir `docs/specs/aur_cases.md` et
`docs/specs/aur_v2_methodology.md` pour la methodologie complete.

Delibirement independant de `dev_case.py`/`CF Aurora` (bibliotheque Aurora distincte,
granularite differente - voir CONTEXT.md "Source de prix (Source BP)") - seules les
fonctions publiques de calcul CAPEX/OPEX depuis `COPEX_library` sont reutilisees,
puisque c'est la meme table pour les deux chemins de donnee."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .bp_parser import _normalize, load_grid
from .dev_case import CopexLibrary, DevCaseParams, escalated_unit_cost, voltage_duration_key
from .dev_case import capex_total_keur as _dev_case_capex_total_keur
from .dev_case import opex_year1_keur as _dev_case_opex_year1_keur
from .models import ProjectInputs

AU_STORE_SHEET = "AU_Store"
DEFAULT_FINANCING_TERMS_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "aur_financing_terms.yaml"
)

_DUREE_PATTERN = re.compile(r"(\d+)\s*h", re.IGNORECASE)

# Repowering (Round du 2026-09-18, confirme par l'utilisateur) : cout = Battery
# system + Inverter (PCS) de COPEX_library, values a l'annee civile du
# repowering - plafonnees sur le dernier delta d'escalade connu si cette annee
# depasse la couverture de la table (voir dev_case.escalated_unit_cost). Pas
# les autres postes CAPEX (Balance of system/Development/EPC/raccordement) :
# seuls les composants qui degradent physiquement sont remplaces au repowering.
REPOWERING_CAPEX_LINE_ITEMS = ["Battery system", "Inverter"]


class AuroraConfigError(ValueError):
    """Config Aurora introuvable, cle invalide ou COD hors garde-fou - jamais un
    repli silencieux sur 0 (voir brief section 7 "zero zero silencieux")."""


@dataclass(frozen=True)
class AuStoreConfig:
    """Une ligne de la table de metadonnees `AU_Store!AP:AV`."""

    drop_key: str  # libelle humain (Source BP!B3), ex. "4h HTB2 Injection g1 (COD2030)"
    austore_key: str  # cle technique des courbes RAW/TURPE, ex. "4h HTB2 injection gabarit"
    duree_h: int
    tension: str  # HTA / HTB1 / HTB2 / HTB3 - deja le meme libelle que ProjectInputs.segment
    turpe_type: str  # Classique / Injection / Soutirage
    gabarit: bool
    valide_cod: int | None  # None = valide pour tout COD ("toute") ; sinon COD exige


@dataclass(frozen=True)
class AuStoreLibrary:
    configs: list[AuStoreConfig]
    raw_by_key: dict[str, dict[int, float]]  # austore_key -> {annee civile: RAW €/kW}
    turpe_by_key: dict[
        str, dict[int, float]
    ]  # austore_key -> {annee civile: TURPE €/kW, deja negatif}
    degradation: dict[int, float]  # op-year -> DegFactor (reset repowering)
    degradation_no_repo: dict[int, float]  # op-year -> DegFactor_noRepo
    repowering_op_year: int
    eol_per_kw: float

    def config_by_drop_key(self, drop_key: str) -> AuStoreConfig:
        for config in self.configs:
            if config.drop_key == drop_key:
                return config
        raise AuroraConfigError(
            f"Config Aurora introuvable pour DropKey '{drop_key}' "
            f"(disponibles : {[c.drop_key for c in self.configs]})."
        )

    def config_by_attributes(
        self, *, duree_h: int, tension: str, turpe_type: str, gabarit: bool
    ) -> AuStoreConfig:
        for config in self.configs:
            if (
                config.duree_h == duree_h
                and config.tension == tension
                and config.turpe_type == turpe_type
                and config.gabarit == gabarit
            ):
                return config
        raise AuroraConfigError(
            f"Aucune config Aurora pour {duree_h}h {tension} {turpe_type} "
            f"gabarit={gabarit} (Aurora n'a pas modelise toutes les combinaisons - "
            f"disponibles : {[(c.duree_h, c.tension, c.turpe_type, c.gabarit) for c in self.configs]})."
        )


@dataclass(frozen=True)
class AggregatorFeeTerms:
    """Mecanisme complet de frais d'agregateur (I-Project!42-46) - paliers
    avant/apres seuil, pas un taux plat. `net_of_turpe` determine si le TURPE
    est deduit de l'assiette avant d'appliquer les taux. `net_of_energy_costs`
    est extrait tel quel mais n'a pas d'effet distinct implemente ici : la
    courbe RAW d'AU_Store est deja nette des couts d'energie par construction
    (voir CONTEXT.md "AU_Store"), donc ce toggle ne change rien de plus sur ce
    seul exemple - a revisiter si un cas reel l'active en desaccord avec RAW."""

    rate_before_threshold: float
    rate_after_threshold: float
    yearly_threshold_keur_per_mw: float
    net_of_energy_costs: bool = True
    net_of_turpe: bool = True


def load_financing_terms(path: Path = DEFAULT_FINANCING_TERMS_PATH) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def aggregator_fee_terms_from_config(terms: dict) -> AggregatorFeeTerms:
    return AggregatorFeeTerms(
        rate_before_threshold=terms["aggregator_fee_rate_before_threshold"],
        rate_after_threshold=terms["aggregator_fee_rate_after_threshold"],
        yearly_threshold_keur_per_mw=terms["aggregator_fee_yearly_threshold_keur_per_mw"],
        net_of_energy_costs=terms["aggregator_fee_net_of_energy_costs"],
        net_of_turpe=terms["aggregator_fee_net_of_turpe"],
    )


def devex_keur_for_tension(tension: str, terms: dict) -> float:
    """DEVEX forfaitaire (cout de developpement reel de QEF, strategie 1) par
    classe de tension - HTA a son propre forfait, HTB1/HTB2/HTB3 partagent le
    meme (pas de distinction fournie par l'utilisateur, voir
    config/aur_financing_terms.yaml). Forfaitaire par projet, pas un taux par
    MW (couts largement fixes : etudes de raccordement, permitting, foncier)."""
    if tension == "HTA":
        return terms["devex_flat_keur_hta"]
    return terms["devex_flat_keur_htb"]


def dsa_default_keur(*, duree_h: int, power_mw: float, devex_keur: float, terms: dict) -> float:
    """DSA par defaut = marge de dev cible (par MW, par duree BESS) + DEVEX
    (confirme par l'utilisateur, 2026-09-18 - voir config/aur_financing_terms.yaml).
    `devex_keur` est deja resolu par l'appelant (defaut ou override) : si le
    DEVEX d'un projet est override, le DSA par defaut en tient compte
    automatiquement, pour que `net_margin_keur = TSP - DEVEX` retombe
    exactement sur la marge cible quand SPA = 0 (voir docs/specs/strategy.md)."""
    key = f"target_margin_keur_per_mw_{duree_h}h"
    if key not in terms:
        raise AuroraConfigError(
            f"Pas de marge de dev cible par defaut pour une duree de {duree_h}h "
            f"(durees disponibles : 2h, 4h)."
        )
    return terms[key] * power_mw + devex_keur


def _find_col(header: list[Any], label: str) -> int:
    target = _normalize(label)
    for i, cell in enumerate(header):
        if _normalize(cell) == target:
            return i
    raise AuroraConfigError(f"Colonne '{label}' introuvable dans l'en-tete AU_Store.")


def _find_scalar_by_label(grid: list[list[Any]], label: str) -> Any:
    target = _normalize(label)
    for row in grid:
        for i, cell in enumerate(row):
            if _normalize(cell) == target and i + 1 < len(row):
                return row[i + 1]
    raise AuroraConfigError(f"Libelle '{label}' introuvable dans AU_Store.")


def _contiguous_labels(header: list[Any], start_col: int) -> list[str]:
    labels = []
    col = start_col
    while col < len(header) and header[col] is not None:
        labels.append(str(header[col]).strip())
        col += 1
    return labels


def _next_non_empty_col(header: list[Any], after_col: int) -> int:
    col = after_col
    while col < len(header) and header[col] is None:
        col += 1
    if col >= len(header):
        raise AuroraConfigError("Bloc TURPE introuvable apres le bloc RAW dans AU_Store.")
    return col


def _parse_duree_h(value: Any) -> int:
    match = _DUREE_PATTERN.search(str(value))
    if match is None:
        raise AuroraConfigError(f"Duree Aurora illisible : '{value}' (attendu ex. '2h', '4h').")
    return int(match.group(1))


def load_au_store(file_or_path) -> AuStoreLibrary:
    grid = load_grid(file_or_path, sheet_name=AU_STORE_SHEET)
    header = grid[0]

    year_col = _find_col(header, "Year")
    raw_start = year_col + 1
    raw_labels = _contiguous_labels(header, raw_start)
    turpe_start = _next_non_empty_col(header, raw_start + len(raw_labels))
    turpe_labels = _contiguous_labels(header, turpe_start)
    if turpe_labels != raw_labels:
        raise AuroraConfigError(
            "Les configs du bloc TURPE d'AU_Store ne correspondent pas au bloc RAW "
            f"(RAW={raw_labels}, TURPE={turpe_labels})."
        )

    raw_by_key: dict[str, dict[int, float]] = {label: {} for label in raw_labels}
    turpe_by_key: dict[str, dict[int, float]] = {label: {} for label in raw_labels}
    for row in grid[1:]:
        year = row[year_col] if year_col < len(row) else None
        if not isinstance(year, (int, float)):
            break
        year = int(year)
        for offset, label in enumerate(raw_labels):
            raw_value = row[raw_start + offset]
            if raw_value is not None:
                raw_by_key[label][year] = float(raw_value)
            turpe_value = row[turpe_start + offset]
            if turpe_value is not None:
                turpe_by_key[label][year] = float(turpe_value)

    dropkey_col = _find_col(header, "DropKey")
    metadata_labels = [_normalize(label) for label in _contiguous_labels(header, dropkey_col)]
    expected_metadata = [
        "dropkey",
        "austorekey",
        "duree",
        "tension",
        "turpe",
        "gabarit",
        "validecod",
    ]
    if metadata_labels != expected_metadata:
        raise AuroraConfigError(
            f"Colonnes de metadonnees AU_Store inattendues : {metadata_labels} "
            f"(attendu : {expected_metadata})."
        )
    configs: list[AuStoreConfig] = []
    for row in grid[1:]:
        drop_key = row[dropkey_col] if dropkey_col < len(row) else None
        if drop_key is None or (isinstance(drop_key, str) and not drop_key.strip()):
            break
        valide_cod_raw = row[dropkey_col + 6]
        configs.append(
            AuStoreConfig(
                drop_key=str(drop_key).strip(),
                austore_key=str(row[dropkey_col + 1]).strip(),
                duree_h=_parse_duree_h(row[dropkey_col + 2]),
                tension=str(row[dropkey_col + 3]).strip(),
                turpe_type=str(row[dropkey_col + 4]).strip(),
                gabarit=bool(row[dropkey_col + 5]),
                valide_cod=(
                    int(valide_cod_raw) if isinstance(valide_cod_raw, (int, float)) else None
                ),
            )
        )
    if not configs:
        raise AuroraConfigError("Aucune config Aurora trouvee dans la table AU_Store!AP:AV.")

    opyear_col = _find_col(header, "OpYear")
    degradation: dict[int, float] = {}
    degradation_no_repo: dict[int, float] = {}
    for row in grid[1:]:
        op_year = row[opyear_col] if opyear_col < len(row) else None
        if not isinstance(op_year, (int, float)):
            break
        op_year = int(op_year)
        deg_value = row[opyear_col + 1]
        deg_norepo_value = row[opyear_col + 2]
        if deg_value is not None:
            degradation[op_year] = float(deg_value)
        if deg_norepo_value is not None:
            degradation_no_repo[op_year] = float(deg_norepo_value)

    repowering_op_year = int(_find_scalar_by_label(grid, "RepowOpYear"))
    eol_per_kw = float(_find_scalar_by_label(grid, "EoL_perkW"))

    return AuStoreLibrary(
        configs=configs,
        raw_by_key=raw_by_key,
        turpe_by_key=turpe_by_key,
        degradation=degradation,
        degradation_no_repo=degradation_no_repo,
        repowering_op_year=repowering_op_year,
        eol_per_kw=eol_per_kw,
    )


def validate_cod(config: AuStoreConfig, cod_year: int) -> None:
    if config.valide_cod is not None and config.valide_cod != cod_year:
        raise AuroraConfigError(
            f"La config '{config.drop_key}' n'est valide que pour COD={config.valide_cod} "
            f"(COD demande : {cod_year})."
        )


def revenue_and_turpe_series(
    library: AuStoreLibrary,
    config: AuStoreConfig,
    *,
    cod_year: int,
    operating_years: int,
    power_mw: float,
    with_repowering: bool = True,
) -> tuple[list[int], list[float], list[float]]:
    """Lit la courbe RAW/TURPE **par annee civile** a partir du COD, x facteur de
    degradation par op-year, x puissance - la courbe elle-meme ne depend jamais
    du COD (voir CONTEXT.md "AU_Store" : courbe COD-independante x degradation
    par op-year, ne jamais re-indexer la courbe RAW). Le TURPE n'est pas degrade
    (charges reseau non liees a la degradation de la batterie - hypothese non
    verifiee faute de point de validation exact, voir docs/specs/aur_cases.md)."""
    validate_cod(config, cod_year)
    if config.austore_key not in library.raw_by_key:
        raise AuroraConfigError(
            f"Cle Aurora '{config.austore_key}' introuvable dans les courbes AU_Store "
            f"(disponibles : {sorted(library.raw_by_key)})."
        )
    raw_curve = library.raw_by_key[config.austore_key]
    turpe_curve = library.turpe_by_key[config.austore_key]
    deg_table = library.degradation if with_repowering else library.degradation_no_repo

    calendar_years = [cod_year + i for i in range(operating_years)]
    revenue_series = []
    turpe_series = []
    for i, year in enumerate(calendar_years):
        op_year = i + 1
        if year not in raw_curve:
            raise AuroraConfigError(
                f"Annee {year} hors de la plage AU_Store pour '{config.austore_key}' "
                f"(plage couverte : {min(raw_curve)}-{max(raw_curve)})."
            )
        deg = deg_table.get(op_year)
        if deg is None:
            raise AuroraConfigError(
                f"Pas de facteur de degradation pour l'op-year {op_year} "
                f"(plage couverte : 1-{max(deg_table)})."
            )
        revenue_series.append(raw_curve[year] * deg * power_mw)
        turpe_series.append(turpe_curve[year] * power_mw)
    return calendar_years, revenue_series, turpe_series


def _tiered_fee(
    base_keur: float, threshold_keur: float, rate_before: float, rate_after: float
) -> float:
    if base_keur <= threshold_keur:
        return rate_before * base_keur
    return rate_before * threshold_keur + rate_after * (base_keur - threshold_keur)


def aggregator_fee_series(
    revenue_keur: list[float],
    turpe_keur: list[float],
    power_mw: float,
    terms: AggregatorFeeTerms,
) -> list[float]:
    """Serie de frais d'agregateur (negatifs), a ajouter au revenu. Mecanisme
    complet a paliers (pas un taux plat) : assiette = revenu (net du TURPE si
    `net_of_turpe`), taux `rate_before_threshold` jusqu'au seuil annuel puis
    `rate_after_threshold` au-dela (voir I-Project!42-46 / CONTEXT.md)."""
    threshold_keur = terms.yearly_threshold_keur_per_mw * power_mw
    fees = []
    for revenue, turpe in zip(revenue_keur, turpe_keur, strict=True):
        base = revenue + turpe if terms.net_of_turpe else revenue
        fees.append(
            _tiered_fee(
                base, threshold_keur, terms.rate_before_threshold, terms.rate_after_threshold
            )
        )
    return fees


def capex_and_opex_keur(
    *, tension: str, duree_h: int, cod_year: int, power_mw: float, copex_library: CopexLibrary
) -> tuple[float, float]:
    """CAPEX/OPEX total depuis `COPEX_library` (meme table que `dev_case.py`,
    reutilisee telle quelle - voir Round 1 Q5 de la session de cadrage,
    docs/specs/aur_v2_methodology.md section 1.2). `DevCaseParams` sert
    uniquement de vehicule de calcul ici (voltage_class_override court-circuite
    tout besoin de connection_type).

    `dev_case.capex_total_keur`/`opex_year1_keur` retournent silencieusement 0
    si la cle tension/duree est absente de `COPEX_library` (`dict.get(key, {})`)
    - sans consequence pour `dev_case.py` lui-meme (VOLTAGE_CLASSES n'expose que
    HTA/HTB1/HTB2, qui existent tous dans la table). AU_Store, lui, modelise
    aussi HTB3 - absent de COPEX_library (verifie : seules HTA/HTB1/HTB2 y sont
    presentes) - d'ou ce garde-fou explicite plutot que de laisser passer un
    CAPEX/OPEX a 0 (brief section 7, "zero zero silencieux")."""
    key = voltage_duration_key(tension, duree_h)
    if key not in copex_library.capex_unit_costs or key not in copex_library.opex_unit_costs:
        raise AuroraConfigError(
            f"Pas de donnees CAPEX/OPEX dans COPEX_library pour '{key}' "
            f"(tensions disponibles : {sorted({k.split(' - ')[1] for k in copex_library.capex_unit_costs})})."
        )
    params = DevCaseParams(
        cod_year=cod_year,
        power_mw=power_mw,
        duration_h=duree_h,
        connection_type="",
        voltage_class_override=tension,
        connection_capex_mode="library",
    )
    return (
        _dev_case_capex_total_keur(params, copex_library),
        _dev_case_opex_year1_keur(params, copex_library),
    )


def repowering_capex_keur(
    *,
    tension: str,
    duree_h: int,
    repowering_year: int,
    power_mw: float,
    copex_library: CopexLibrary,
) -> float:
    """Cout de repowering = Battery system + Inverter (PCS) de `COPEX_library`,
    values a `repowering_year` (l'annee civile du repowering, pas l'annee de
    COD) - seuls les composants qui degradent physiquement sont remplaces,
    pas le CAPEX complet (voir `REPOWERING_CAPEX_LINE_ITEMS`). Reutilise
    `dev_case.escalated_unit_cost`, qui plafonne deja sur le dernier delta
    d'escalade connu si `repowering_year` depasse la couverture de la table
    (2028-2034 sur le fichier reel) - meme comportement que pour le CAPEX
    initial, pas une nouvelle regle. Suppose que la cle tension/duree existe
    dans `copex_library` (verifie en amont par `capex_and_opex_keur`)."""
    key = voltage_duration_key(tension, duree_h)
    unit_costs = copex_library.capex_unit_costs.get(key, {})
    escalation = copex_library.capex_escalation
    total_per_kw = sum(
        escalated_unit_cost(unit_costs.get(label, 0.0), escalation.get(label, {}), repowering_year)
        for label in REPOWERING_CAPEX_LINE_ITEMS
    )
    return total_per_kw * power_mw


def build_project_inputs(
    library: AuStoreLibrary,
    config: AuStoreConfig,
    copex_library: CopexLibrary,
    *,
    cod_year: int,
    power_mw: float,
    operating_years: int = 20,
    with_repowering: bool = True,
    aggregator_fee: AggregatorFeeTerms | None = None,
    name: str = "",
    location: str = "",
) -> ProjectInputs:
    """Construit un `ProjectInputs` pour une config Aurora - meme forme que
    `dev_case.build_project_inputs`, utilisable tel quel par
    `financial_engine.compute_results()` et tous les onglets existants."""
    calendar_years, revenue_series, turpe_series = revenue_and_turpe_series(
        library,
        config,
        cod_year=cod_year,
        operating_years=operating_years,
        power_mw=power_mw,
        with_repowering=with_repowering,
    )
    if aggregator_fee is not None:
        fees = aggregator_fee_series(revenue_series, turpe_series, power_mw, aggregator_fee)
        revenue_series = [r + f for r, f in zip(revenue_series, fees, strict=True)]

    capex_initial, opex_year1 = capex_and_opex_keur(
        tension=config.tension,
        duree_h=config.duree_h,
        cod_year=cod_year,
        power_mw=power_mw,
        copex_library=copex_library,
    )

    length = len(calendar_years) + 1  # +1 pour l'annee de construction (COD - 1)
    years = [cod_year - 1] + calendar_years
    capex_keur = [-capex_initial] + [0.0] * len(calendar_years)
    opex_keur = [0.0] + [-opex_year1] * len(calendar_years)
    revenues_keur = [0.0] + revenue_series
    turpe_keur = [0.0] + turpe_series
    end_of_life_keur = [0.0] * length

    capex_repowering = 0.0
    if with_repowering and operating_years >= library.repowering_op_year:
        # index dans capex_keur/years : la construction occupe l'index 0, donc
        # l'op-year N est a l'index N (pas N-1) - voir revenue_and_turpe_series.
        repowering_index = library.repowering_op_year
        repowering_calendar_year = calendar_years[library.repowering_op_year - 1]
        capex_repowering = repowering_capex_keur(
            tension=config.tension,
            duree_h=config.duree_h,
            repowering_year=repowering_calendar_year,
            power_mw=power_mw,
            copex_library=copex_library,
        )
        capex_keur[repowering_index] -= capex_repowering

    net_cashflow_keur = [
        c + o + t + r + e
        for c, o, t, r, e in zip(
            capex_keur, opex_keur, turpe_keur, revenues_keur, end_of_life_keur, strict=True
        )
    ]

    return ProjectInputs(
        name=name or config.drop_key,
        location=location,
        segment=config.tension,
        cod=f"{cod_year}-01-01",
        operating_years=operating_years,
        usable_power_mw=power_mw,
        usable_energy_mwh=power_mw * config.duree_h,
        capex_initial_keur=capex_initial,
        capex_repowering_keur=capex_repowering,
        repowering=with_repowering,
        opex_year1_keur=opex_year1,
        opex_adjustment_keur=0.0,
        turpe_fixed_eur_per_kw=0.0,
        years=years,
        capex_keur=capex_keur,
        opex_keur=opex_keur,
        end_of_life_keur=end_of_life_keur,
        revenues_keur=revenues_keur,
        turpe_keur=turpe_keur,
        net_cashflow_keur=net_cashflow_keur,
    )
