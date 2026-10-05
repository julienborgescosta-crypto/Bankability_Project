"""Lit `config/copex_icp.xlsx` (COPEX Library QEF, onglet `COPEX_library`, table
"Hypotheses CAPEX BP - BESS Standalone") - couts unitaires QEF reels, mis a jour
par l'utilisateur en remplacant ce fichier (meme nom, nouveau contenu - pas de
changement de code requis a chaque mise a jour). Source primaire du CAPEX/OPEX
BESS, a la place de la bibliotheque Aurora `COPEX_library` (qui reste utilisee
comme repli pour les postes que la COPEX Library ne couvre pas). Voir
docs/specs/copex_icp.md pour les decisions de mapping et d'agregation.

Lecture par libelle, jamais par adresse fixe : ligne d'en-tete "Case" (segments
puis annees du "Forecast price factor"), lignes reperees par leur libelle en
colonne A, unite lue dans le format de chaque cellule."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import openpyxl

from .dev_case import (
    CAPEX_GRID_CONNECTION_LABEL,
    CAPEX_LINE_ITEMS,
    OPEX_LINE_ITEMS,
    CopexLibrary,
    escalated_unit_cost,
    voltage_duration_key,
)

DEFAULT_ICP_PATH = Path(__file__).resolve().parent.parent / "config" / "copex_icp.xlsx"
ICP_SHEETS = ("COPEX_library", "CAPEX_library")

# Mapping tension -> segment ICP, reprenant le mapping deja etabli ailleurs
# dans l'app (DSO -> HTA, TSO 63kV/90kV -> HTB1, TSO 225kV -> HTB2 - voir
# docs/specs/dev_case.md "Deux taxonomies de segment coexistent"). TSO 90kV
# retenu comme representant HTB1 (63kV et 90kV ne different que sur HV
# Transformer/HV substation/Grid connection - voir docs/specs/copex_icp.md).
# HTB3 n'a pas de colonne ICP (le fichier n'en a jamais eu) - reste
# entierement source par Aurora.
TENSION_TO_ICP_SEGMENT = {"HTA": "DSO", "HTB1": "TSO 90kV", "HTB2": "TSO 225kV"}

_HEADER_LABEL = "Case"
_DIRECT_CAPEX_LABELS = [
    "Electrical works and studies",
    "Civil Works and miscellaneous",
    "HV Transformer",
    "HV substation",
    "MV substation",
    "Communication",
    "Other BoP cost",
    "Integration",
]
_OM_LABEL = "OPEX - O&M (annual cost)"
_GRID_CONNECTION_LABEL = "Grid connection"
_INSURANCE_LABEL = "Insurances during construction"
_EPC_MARGIN_LABEL = "EPC Margin"
_EPC_CONTINGENCY_LABEL = "EPC Contingency"
_BATTERY_LABEL = "Batteries and PCS"
_GUARANTEES_LABEL = "OPEX - Guarantees"
_DURATIONS_H = (2, 4)
GUARANTEES_DURATION_YEARS = 15
# "Forecast price factor (selon annee de NTP)" : les couts sont indexes sur
# l'annee de debut de construction, l'annee avant la mise en service (decision
# de l'utilisateur, 2026-10-05 - meme convention que le paiement du CAPEX).
NTP_YEARS_BEFORE_COD = 1

# =794.13*'[2]I-Project'!$G$28^(-0.61)*1000 : coefficient en €/kWh x MWh^exposant,
# x1000 pour passer en €/MWh. La reference (taille du BP lie) est ignoree - la
# formule est re-evaluee a la taille de chaque projet.
_POWER_LAW_FORMULA = re.compile(
    r"^=\s*(?P<coef>\d+(?:\.\d+)?)\s*\*.+\^\s*\(\s*(?P<exp>-?\d+(?:\.\d+)?)\s*\)\s*\*\s*1000\s*$"
)


@dataclass(frozen=True)
class IcpPowerLaw:
    """cout unitaire (€/kWh) = coefficient x MWh**exposant, MWh = taille du projet."""

    coefficient_eur_per_kwh: float
    exponent: float


@dataclass(frozen=True)
class IcpCostCell:
    value: float
    unit: str  # 'eur_per_mwh' | 'eur_per_mw' | 'keur_flat' | 'percent' | 'keur_per_mwh_per_year'
    power_law: IcpPowerLaw | None = None


@dataclass(frozen=True)
class IcpCostLibrary:
    version: Any
    line_items: dict[str, dict[str, IcpCostCell]]  # label -> segment -> cellule
    escalation: dict[str, dict[int, float]]  # label -> annee de NTP -> multiplicateur
    insurance_construction_pct: dict[str, float]  # segment -> %
    epc_margin_pct: dict[str, float]  # segment -> %
    epc_contingency_pct: dict[str, float] = field(default_factory=dict)  # segment -> %


def _unit_from_number_format(fmt: str) -> str:
    """Ne jamais deduire l'unite de la valeur brute (une meme ligne melange
    parfois €/MW et k€ forfait selon la colonne, ex. 'Grid connection') -
    toujours lire le suffixe entre guillemets du format Excel (demande de
    l'utilisateur, 2026-09-24)."""
    if "%" in fmt:
        return "percent"
    if "MWh" in fmt and ("/an" in fmt or "/y" in fmt):
        return "keur_per_mwh_per_year"
    if "/MWh" in fmt:
        return "eur_per_mwh"
    if "/MW" in fmt:
        return "eur_per_mw"
    if "/an" in fmt or "/y" in fmt:
        return "keur_per_year"
    return "keur_flat"


def _sheet(wb):
    for name in ICP_SHEETS:
        if name in wb.sheetnames:
            return wb[name]
    raise ValueError(f"None of the sheets {ICP_SHEETS} found (available: {wb.sheetnames}).")


def _find_row(ws, *label_parts: str) -> int:
    """1re ligne dont le libelle (colonne A) contient tous les morceaux - le
    bloc ICP precede les blocs Aurora de reference du meme onglet, qui
    reutilisent certains libelles ('Grid connection')."""
    for row in range(1, ws.max_row + 1):
        value = ws.cell(row=row, column=1).value
        if isinstance(value, str) and all(part in value for part in label_parts):
            return row
    raise ValueError(f"Row {' + '.join(repr(p) for p in label_parts)} not found in {ws.title}.")


def _header(ws) -> tuple[int, dict[int, str], dict[int, int]]:
    """(ligne d'en-tete, {colonne: segment}, {colonne: annee}) - les segments
    precedent la 1re annee du "Forecast price factor" sur la ligne "Case"."""
    row = next(
        (
            r
            for r in range(1, ws.max_row + 1)
            if isinstance(ws.cell(r, 1).value, str) and ws.cell(r, 1).value.strip() == _HEADER_LABEL
        ),
        None,
    )
    if row is None:
        raise ValueError(f"Header row '{_HEADER_LABEL}' not found in {ws.title}.")
    segments: dict[int, str] = {}
    years: dict[int, int] = {}
    for col in range(2, ws.max_column + 1):
        value = ws.cell(row, col).value
        if isinstance(value, (int, float)) and 2000 <= value <= 2100:
            years[col] = int(value)
        elif isinstance(value, str) and value.strip() and not years:
            segments[col] = value.strip()
    return row, segments, years


def _read_escalation(ws, row: int, years: dict[int, int]) -> dict[int, float]:
    return {
        year: float(ws.cell(row, col).value)
        for col, year in years.items()
        if isinstance(ws.cell(row, col).value, (int, float))
    }


def _read_line_item_row(
    ws_values, ws_formulas, row: int, segments: dict[int, str]
) -> dict[str, IcpCostCell]:
    """Une cellule par segment. 2 colonnes peuvent porter le meme segment
    ('DSO' 2h/4h) : acceptees seulement si elles sont identiques, jamais un
    choix silencieux entre 2 valeurs differentes."""
    by_segment: dict[str, IcpCostCell] = {}
    for col, segment in segments.items():
        cell = ws_values.cell(row, col)
        formula = ws_formulas.cell(row, col).value
        match = _POWER_LAW_FORMULA.match(formula) if isinstance(formula, str) else None
        if match:
            parsed = IcpCostCell(
                value=float(cell.value) if isinstance(cell.value, (int, float)) else 0.0,
                unit="eur_per_mwh",
                power_law=IcpPowerLaw(float(match["coef"]), float(match["exp"])),
            )
        elif isinstance(cell.value, (int, float)):
            parsed = IcpCostCell(
                value=float(cell.value), unit=_unit_from_number_format(cell.number_format)
            )
        else:
            continue  # texte de renvoi (ex. "= TSO 63/90/225"), pas une valeur exploitable
        previous = by_segment.get(segment)
        if previous is not None and (
            previous.power_law != parsed.power_law
            or (parsed.power_law is None and previous != parsed)
        ):
            raise ValueError(
                f"{ws_values.title}!{cell.coordinate}: two '{segment}' columns with different "
                f"values ({previous} vs {parsed}) - the app maps one column per segment."
            )
        by_segment.setdefault(segment, parsed)
    return by_segment


def _version(ws) -> Any:
    """Version du fichier (ex. 'V1_20261001' en B1) ou date de mise a jour."""
    for row in ws.iter_rows(min_row=1, max_row=3):
        for cell in row:
            if hasattr(cell.value, "year"):
                return cell.value
            if isinstance(cell.value, str) and re.match(r"^V\d", cell.value.strip()):
                return cell.value.strip()
    return None


def load_icp_library(path: Path = DEFAULT_ICP_PATH) -> IcpCostLibrary:
    ws = _sheet(openpyxl.load_workbook(path, data_only=True, keep_links=False))
    ws_formulas = _sheet(openpyxl.load_workbook(path, data_only=False, keep_links=False))
    _, segments, years = _header(ws)

    rows = {
        label: _find_row(ws, label) for label in [*_DIRECT_CAPEX_LABELS, _GRID_CONNECTION_LABEL]
    }
    rows[_OM_LABEL] = _find_row(ws, _OM_LABEL)
    for duree_h in _DURATIONS_H:
        rows[battery_label(duree_h)] = _find_row(ws, _BATTERY_LABEL, f"- {duree_h}h")
        rows[guarantees_label(duree_h)] = _find_row(ws, _GUARANTEES_LABEL, f"- {duree_h}h")

    line_items: dict[str, dict[str, IcpCostCell]] = {}
    escalation: dict[str, dict[int, float]] = {}
    for label, row in rows.items():
        line_items[label] = _read_line_item_row(ws, ws_formulas, row, segments)
        escalation[label] = _read_escalation(ws, row, years)
    # O&M en "k€/y" (V1_20261001) : 2 k€/an pour tout un projet n'a pas de sens - c'est
    # la meme valeur que la version precedente, en k€/MWh/an (decision 2026-10-05, a
    # confirmer par l'equipe OPEX - voir docs/specs/copex_icp.md).
    line_items[_OM_LABEL] = {
        segment: (
            IcpCostCell(cell.value, "keur_per_mwh_per_year")
            if cell.unit == "keur_per_year"
            else cell
        )
        for segment, cell in line_items[_OM_LABEL].items()
    }

    def _pct(label: str) -> dict[str, float]:
        try:
            row = _find_row(ws, label)
        except ValueError:
            return {}
        return {
            seg: c.value for seg, c in _read_line_item_row(ws, ws_formulas, row, segments).items()
        }

    return IcpCostLibrary(
        version=_version(ws),
        line_items=line_items,
        escalation=escalation,
        insurance_construction_pct=_pct(_INSURANCE_LABEL),
        epc_margin_pct=_pct(_EPC_MARGIN_LABEL),
        epc_contingency_pct=_pct(_EPC_CONTINGENCY_LABEL),
    )


def battery_label(duree_h: int) -> str:
    return f"{_BATTERY_LABEL} - {duree_h}h"


def guarantees_label(duree_h: int) -> str:
    return f"{_GUARANTEES_LABEL} - {duree_h}h"


@lru_cache(maxsize=4)
def _cached_icp_library(path_str: str) -> IcpCostLibrary:
    return load_icp_library(Path(path_str))


def load_icp_library_cached(path: Path = DEFAULT_ICP_PATH) -> IcpCostLibrary:
    """Comme `load_icp_library`, mais memoise par chemin (le fichier ICP est
    relu a chaque appel de `capex_and_opex_keur`/`repowering_capex_keur`,
    potentiellement des milliers de fois pendant une sensibilite globale -
    voir `core/global_sensitivity.py`)."""
    return _cached_icp_library(str(path))


def _icp_escalation_factor(escalation: dict[int, float], ntp_year: int) -> float:
    """Multiplicateur du "Forecast price factor" pour cette annee de NTP - 1.0
    avant la 1re annee de la table (annee de base), plafonne sur la derniere
    annee connue au-dela (meme philosophie que `dev_case.escalated_unit_cost`)."""
    if not escalation:
        return 1.0
    if ntp_year in escalation:
        return escalation[ntp_year]
    years = sorted(escalation)
    if ntp_year > years[-1]:
        return escalation[years[-1]]
    return 1.0


def _scaled_cost_keur(cell: IcpCostCell, *, power_mw: float, duree_h: int) -> float:
    mwh = power_mw * duree_h
    if cell.power_law is not None:
        # €/kWh x MWh = k€
        return cell.power_law.coefficient_eur_per_kwh * mwh**cell.power_law.exponent * mwh
    if cell.unit == "eur_per_mwh":
        return cell.value * mwh / 1000.0
    if cell.unit == "eur_per_mw":
        return cell.value * power_mw / 1000.0
    if cell.unit in ("keur_flat", "keur_per_year"):
        return cell.value
    if cell.unit == "keur_per_mwh_per_year":
        return cell.value * mwh
    raise ValueError(f"Unknown ICP unit: '{cell.unit}'.")


def _icp_line_item_keur(
    icp_library: IcpCostLibrary,
    label: str,
    segment: str,
    *,
    power_mw: float,
    duree_h: int,
    cod_year: int,
) -> float | None:
    """Cout k€ d'une ligne pour une mise en service en `cod_year`, indexe sur
    l'annee de NTP (`cod_year - NTP_YEARS_BEFORE_COD`). `None` si la ligne n'a
    pas de valeur pour ce segment."""
    cell = icp_library.line_items[label].get(segment)
    if cell is None:
        return None
    escalation = _icp_escalation_factor(
        icp_library.escalation[label], cod_year - NTP_YEARS_BEFORE_COD
    )
    return _scaled_cost_keur(cell, power_mw=power_mw, duree_h=duree_h) * escalation


def icp_battery_pcs_keur(
    icp_library: IcpCostLibrary, *, segment: str, duree_h: int, power_mw: float, cod_year: int
) -> float:
    label = battery_label(duree_h)
    if label not in icp_library.line_items:
        raise ValueError(f"No ICP Batteries and PCS line for {duree_h}h.")
    cost = _icp_line_item_keur(
        icp_library, label, segment, power_mw=power_mw, duree_h=duree_h, cod_year=cod_year
    )
    if cost is None:
        raise ValueError(f"No ICP Batteries and PCS value for {duree_h}h / {segment}.")
    return cost


def icp_opex_guarantees_annualized_keur(
    icp_library: IcpCostLibrary, *, segment: str, duree_h: int, power_mw: float, cod_year: int
) -> float:
    """Garanties & maintenance preventive : la valeur du fichier est un cout total
    sur 15 ans (decision de l'utilisateur, 2026-10-05, malgre le libelle
    "(annual)" de la V1_20261001), etale sur 15 ans et paye chaque annee de la vie
    du projet (decision du 2026-10-02)."""
    label = guarantees_label(duree_h)
    if label not in icp_library.line_items:
        raise ValueError(f"No ICP OPEX Guarantees line for {duree_h}h.")
    total_15y = _icp_line_item_keur(
        icp_library, label, segment, power_mw=power_mw, duree_h=duree_h, cod_year=cod_year
    )
    if total_15y is None:
        raise ValueError(f"No ICP OPEX Guarantees value for {duree_h}h / {segment}.")
    return total_15y / GUARANTEES_DURATION_YEARS


def construction_markup_factor(icp_library: IcpCostLibrary, segment: str) -> float:
    """(1 + marge EPC) x (1 + aleas EPC) x (1 + assurance construction) - appliques
    aux postes directs de construction, jamais au raccordement ni au developpement."""
    return (
        (1 + icp_library.epc_margin_pct.get(segment, 0.0))
        * (1 + icp_library.epc_contingency_pct.get(segment, 0.0))
        * (1 + icp_library.insurance_construction_pct.get(segment, 0.0))
    )


def icp_capex_total_keur(
    *,
    tension: str,
    duree_h: int,
    cod_year: int,
    power_mw: float,
    icp_library: IcpCostLibrary,
    aurora_library: CopexLibrary,
    development_keur: float | None = None,
) -> tuple[float, list[str]]:
    """CAPEX generique (hors raccordement, gere separement comme avant par
    `connection_capex_mode` - voir `icp_connection_capex_keur`) :

    (somme des postes directs ICP : Batteries+PCS, Electrical works, Civil
    works, HV Transformer, HV/MV substation, Communication, Other BoP,
    Integration) x (1 + EPC Margin) x (1 + EPC Contingency) x (1 + Insurance
    during construction) - voir `construction_markup_factor` - + Development (additif, hors perimetre EPC/assurance construction - couts
    de developpement/origination, pas de construction - voir
    docs/specs/copex_icp.md) : `development_keur` si fourni (le DSA du projet,
    voir `portfolio.resolved_devex_and_dsa_keur`), sinon la ligne Aurora.

    Assurance appliquee sur le total incluant la marge EPC (convention
    "Total Capex" = travaux + marge EPC, assurance Construction All Risks
    classique - confirme par l'utilisateur, 2026-09-24 ; numeriquement
    equivalent a l'ordre inverse par commutativite, l'ecart entre les 2
    conventions - assurance sur le direct seul vs sur le total incl. EPC -
    est de l'ordre de 0.05% du CAPEX).

    Retourne (capex_keur, notes) - `notes` liste les postes venant d'Aurora
    en repli, pour affichage explicite dans l'UI (jamais un repli silencieux)."""
    segment = TENSION_TO_ICP_SEGMENT.get(tension)
    if segment is None:
        # HTB3 : ICP n'a jamais eu de colonne pour cette tension - tout Aurora,
        # comme avant ce changement (garde-fou tension/COPEX_library inchange,
        # gere en amont par aur_cases.capex_and_opex_keur).
        key = voltage_duration_key(tension, duree_h)
        total_keur = _aurora_capex_total_keur_for_key(aurora_library, key, cod_year, power_mw)
        notes = [
            f"{tension} : aucune colonne ICP - CAPEX entierement source depuis Aurora COPEX_library."
        ]
        if development_keur is not None:
            aurora_development_keur = (
                escalated_unit_cost(
                    aurora_library.capex_unit_costs.get(key, {}).get("Development", 0.0),
                    aurora_library.capex_escalation.get("Development", {}),
                    cod_year,
                )
                * power_mw
            )
            total_keur += development_keur - aurora_development_keur
            notes.append("Development : DSA du projet (marge de dev cible + DEVEX).")
        return total_keur, notes

    direct_keur = 0.0
    missing: list[str] = []
    for label in _DIRECT_CAPEX_LABELS:
        item_cost = _icp_line_item_keur(
            icp_library, label, segment, power_mw=power_mw, duree_h=duree_h, cod_year=cod_year
        )
        if item_cost is None:
            missing.append(label)
            continue
        direct_keur += item_cost
    direct_keur += icp_battery_pcs_keur(
        icp_library, segment=segment, duree_h=duree_h, power_mw=power_mw, cod_year=cod_year
    )

    construction_keur = direct_keur * construction_markup_factor(icp_library, segment)

    if development_keur is None:
        key = voltage_duration_key(tension, duree_h)
        development_keur = (
            escalated_unit_cost(
                aurora_library.capex_unit_costs.get(key, {}).get("Development", 0.0),
                aurora_library.capex_escalation.get("Development", {}),
                cod_year,
            )
            * power_mw
        )
        notes = ["Development : source Aurora COPEX_library (absent d'ICP)."]
    else:
        notes = ["Development : DSA du projet (marge de dev cible + DEVEX)."]
    if missing:
        notes.append(f"Postes ICP absents pour {segment} (repli Aurora) : {', '.join(missing)}.")

    return construction_keur + development_keur, notes


def icp_eol_eligible_capex_keur(
    *,
    tension: str,
    duree_h: int,
    cod_year: int,
    power_mw: float,
    icp_library: IcpCostLibrary,
    aurora_library: CopexLibrary,
) -> float:
    """Base CAPEX eligible a la valeur de fin de vie (Aurora PDF Q2 2026,
    "Technology assumptions" CAPEX : "the end-of-life value is made up of 5%
    of the battery system, inverter and balance of system costs... while
    development and soft costs are considered sunk costs") - demande de
    l'utilisateur, 2026-10-01 (voir `core/aur_cases.py` `end_of_life_value_keur`
    pour l'application du taux 5%/100% et `docs/specs/aur_cases.md`).

    Le MEME `direct_keur` que `icp_capex_total_keur` calcule en interne
    (Batteries+PCS + les 8 postes directs ICP), mais AVANT marge EPC et
    assurance construction - ce ne sont pas des couts d'equipement physique
    (donc pas revendables), mais du financement/overhead de mise en oeuvre.
    Exclut toujours Development (source Aurora, jamais dans ICP) - "sunk" par
    construction, jamais eligible, meme cote Aurora pur (voir `_eol_...`
    ci-dessous pour HTB3/repli Aurora)."""
    segment = TENSION_TO_ICP_SEGMENT.get(tension)
    if segment is None:
        key = voltage_duration_key(tension, duree_h)
        unit_costs = aurora_library.capex_unit_costs.get(key, {})
        return sum(
            escalated_unit_cost(
                unit_costs.get(label, 0.0), aurora_library.capex_escalation.get(label, {}), cod_year
            )
            * power_mw
            for label in ("Battery system", "Inverter", "Balance of system")
        )
    direct_keur = sum(
        cost
        for label in _DIRECT_CAPEX_LABELS
        if (
            cost := _icp_line_item_keur(
                icp_library, label, segment, power_mw=power_mw, duree_h=duree_h, cod_year=cod_year
            )
        )
        is not None
    )
    direct_keur += icp_battery_pcs_keur(
        icp_library, segment=segment, duree_h=duree_h, power_mw=power_mw, cod_year=cod_year
    )
    return direct_keur


def _aurora_capex_total_keur_for_key(
    aurora_library: CopexLibrary, key: str, cod_year: int, power_mw: float
) -> float:
    unit_costs = aurora_library.capex_unit_costs.get(key, {})
    return sum(
        escalated_unit_cost(
            unit_costs.get(label, 0.0), aurora_library.capex_escalation.get(label, {}), cod_year
        )
        * power_mw
        for label in CAPEX_LINE_ITEMS
    )


def icp_connection_capex_keur(
    *,
    tension: str,
    duree_h: int,
    cod_year: int,
    power_mw: float,
    icp_library: IcpCostLibrary,
    aurora_library: CopexLibrary,
) -> tuple[float, list[str]]:
    """Ligne 'Grid connection' pour le mode `connection_capex_mode='library'`
    (les 3 autres modes - manual/distance_rte/distance_rte_and_substation -
    remplacent deja cette ligne en amont, inchange)."""
    segment = TENSION_TO_ICP_SEGMENT.get(tension)
    if segment is not None:
        cost = _icp_line_item_keur(
            icp_library,
            _GRID_CONNECTION_LABEL,
            segment,
            power_mw=power_mw,
            duree_h=duree_h,
            cod_year=cod_year,
        )
        if cost is not None:
            return cost, []
    key = voltage_duration_key(tension, duree_h)
    unit_cost = escalated_unit_cost(
        aurora_library.capex_unit_costs.get(key, {}).get(CAPEX_GRID_CONNECTION_LABEL, 0.0),
        aurora_library.capex_escalation.get(CAPEX_GRID_CONNECTION_LABEL, {}),
        cod_year,
    )
    return unit_cost * power_mw, [
        "Grid connection : source Aurora COPEX_library (absent d'ICP pour cette tension)."
    ]


def icp_opex_year1_keur(
    *,
    tension: str,
    duree_h: int,
    cod_year: int,
    power_mw: float,
    icp_library: IcpCostLibrary,
    aurora_library: CopexLibrary,
) -> tuple[float, list[str]]:
    """OPEX annuel (hors loyer foncier utilisateur, ajoute a part comme avant) :

    ICP O&M (remplace le 'Fixed O&M' Aurora) + ICP Guarantees/15 ans (nouveau
    poste, pas d'equivalent Aurora) + Aurora Insurance/Grid charges/Land
    lease(ligne bibliotheque)/Accise/Other (ICP ne couvre aucun de ces 5
    postes - voir docs/specs/copex_icp.md)."""
    segment = TENSION_TO_ICP_SEGMENT.get(tension)
    key = voltage_duration_key(tension, duree_h)
    aurora_unit_costs = aurora_library.opex_unit_costs.get(key, {})

    if segment is None:
        total = (
            sum(
                escalated_unit_cost(
                    aurora_unit_costs.get(label, 0.0),
                    aurora_library.opex_escalation.get(label, {}),
                    cod_year,
                )
                for label in OPEX_LINE_ITEMS
            )
            * power_mw
        )
        return total, [
            f"{tension} : aucune colonne ICP - OPEX entierement source depuis Aurora COPEX_library."
        ]

    om_cost = _icp_line_item_keur(
        icp_library, _OM_LABEL, segment, power_mw=power_mw, duree_h=duree_h, cod_year=cod_year
    )
    notes: list[str] = []
    if om_cost is None:
        om_cost = (
            escalated_unit_cost(
                aurora_unit_costs.get("Fixed O&M", 0.0),
                aurora_library.opex_escalation.get("Fixed O&M", {}),
                cod_year,
            )
            * power_mw
        )
        notes.append(
            "OPEX O&M : source Aurora COPEX_library (poste ICP absent pour cette tension)."
        )

    guarantees_cost = icp_opex_guarantees_annualized_keur(
        icp_library, segment=segment, duree_h=duree_h, power_mw=power_mw, cod_year=cod_year
    )

    fallback_labels = ["Insurance", "Grid charges", "Land lease", "Accise", "Other"]
    fallback_cost = (
        sum(
            escalated_unit_cost(
                aurora_unit_costs.get(label, 0.0),
                aurora_library.opex_escalation.get(label, {}),
                cod_year,
            )
            for label in fallback_labels
        )
        * power_mw
    )
    notes.append(
        "Insurance/Grid charges/Land lease(bibliotheque)/Accise/Other : source Aurora "
        "COPEX_library (absents d'ICP)."
    )

    return om_cost + guarantees_cost + fallback_cost, notes


def icp_repowering_capex_keur(
    *,
    tension: str,
    duree_h: int,
    repowering_year: int,
    power_mw: float,
    icp_library: IcpCostLibrary,
    aurora_library: CopexLibrary,
) -> tuple[float, list[str]]:
    """Cout de repowering (Battery+PCS uniquement, meme perimetre que
    `aur_cases.REPOWERING_CAPEX_LINE_ITEMS` avant ce changement) - source ICP
    pour coherence avec le CAPEX initial (le meme composant remplace doit
    utiliser le meme modele de cout, pas un cout Aurora fige pendant que le
    CAPEX initial suit ICP)."""
    segment = TENSION_TO_ICP_SEGMENT.get(tension)
    if segment is not None:
        cost = icp_battery_pcs_keur(
            icp_library,
            segment=segment,
            duree_h=duree_h,
            power_mw=power_mw,
            cod_year=repowering_year,
        )
        return cost, []
    key = voltage_duration_key(tension, duree_h)
    unit_costs = aurora_library.capex_unit_costs.get(key, {})
    from .aur_cases import REPOWERING_CAPEX_LINE_ITEMS

    total = (
        sum(
            escalated_unit_cost(
                unit_costs.get(label, 0.0),
                aurora_library.capex_escalation.get(label, {}),
                repowering_year,
            )
            for label in REPOWERING_CAPEX_LINE_ITEMS
        )
        * power_mw
    )
    return total, [f"{tension} : repowering source depuis Aurora COPEX_library (absent d'ICP)."]


def capex_opex_source_notes(tension: str) -> list[str]:
    """Note statique pour l'UI (pres des controles CAPEX raccordement/OPEX
    loyer foncier, demande de l'utilisateur 2026-09-24) - quels postes
    viennent d'ICP vs d'Aurora pour une tension donnee, independamment d'un
    calcul precis."""
    if tension not in TENSION_TO_ICP_SEGMENT:
        return [
            f"{tension} : Aurora n'a pas modelise de raccordement ICP pour cette tension - "
            "tout le CAPEX/OPEX (y compris raccordement et loyer) reste source depuis Aurora "
            "COPEX_library."
        ]
    return [
        "CAPEX (Batteries+PCS, travaux electriques/civils, postes HV/MV, communication, "
        "raccordement, marge et aleas EPC, assurance construction) : source COPEX Library "
        f"(config/copex_icp.xlsx, segment '{TENSION_TO_ICP_SEGMENT[tension]}'), indexe sur "
        "l'annee de NTP (COD - 1).",
        "CAPEX Development : DSA du projet (marge de dev cible par MW selon la duree + DEVEX "
        "selon la tension, ou l'override DSA) - absent d'ICP. Jamais en OPEX.",
        "OPEX O&M + garanties/maintenance preventive (15 ans, etalees) : source ICP.",
        "OPEX Insurance/Grid charges/Land lease(bibliotheque)/Accise/Other : source Aurora "
        "COPEX_library (absents d'ICP) - le loyer foncier saisi manuellement ci-dessous "
        "remplace la ligne Land lease de la bibliotheque.",
    ]
