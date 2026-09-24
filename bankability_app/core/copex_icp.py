"""Lit `config/copex_icp.xlsx` (onglet `CAPEX_library`, "Hypothesys CAPEX BP
from ICP") - couts unitaires QEF reels (Internal Cost Pricing), mis a jour
mensuellement par l'utilisateur en remplacant ce fichier (meme nom, nouveau
contenu - pas de changement de code requis a chaque mise a jour). Devient la
source primaire du CAPEX/OPEX BESS, a la place de la bibliotheque Aurora
`COPEX_library` (qui reste utilisee comme repli pour les postes qu'ICP ne
couvre pas). Voir docs/specs/copex_icp.md pour les decisions de mapping et
d'agregation (confirmees par l'utilisateur, 2026-09-24)."""

from __future__ import annotations

from dataclasses import dataclass
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
ICP_SHEET = "CAPEX_library"

# Mapping tension -> segment ICP, reprenant le mapping deja etabli ailleurs
# dans l'app (DSO -> HTA, TSO 63kV/90kV -> HTB1, TSO 225kV -> HTB2 - voir
# docs/specs/dev_case.md "Deux taxonomies de segment coexistent"). TSO 90kV
# retenu comme representant HTB1 (63kV et 90kV ne different que sur HV
# Transformer/HV substation, ecart <12% - voir docs/specs/copex_icp.md).
# HTB3 n'a pas de colonne ICP (le fichier n'en a jamais eu) - reste
# entierement source par Aurora, comme avant ce changement.
TENSION_TO_ICP_SEGMENT = {"HTA": "DSO", "HTB1": "TSO 90kV", "HTB2": "TSO 225kV"}

SEGMENT_COLUMNS = {
    "Industrial-New trench": 3,
    "Industrial-Existing trench": 4,
    "TSO 63kV": 5,
    "TSO 90kV": 6,
    "TSO 225kV": 7,
    "DSO": 8,
    "Hybrid PV": 9,
}

_YEAR_ROW = 4
_FIRST_YEAR_COL = 12
_LAST_YEAR_COL = 16

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
_BATTERY_LABEL = "Batteries and PCS"
_GUARANTEES_LABEL = "OPEX - Guarantees"
_GUARANTEES_AMORTIZATION_YEARS = 15


@dataclass(frozen=True)
class IcpCostCell:
    value: float
    unit: str  # 'eur_per_mwh' | 'eur_per_mw' | 'keur_flat' | 'percent' | 'keur_per_mwh_per_year'


@dataclass(frozen=True)
class IcpPowerLawCost:
    """cout_unitaire_eur_per_kwh(mwh) = base * mwh**exponent ; cout_total_keur
    = cout_unitaire * mwh, escalade par annee (multiplicateur, pas un delta -
    voir `_icp_escalation_factor`).

    `base` est en EUR/**kWh** malgre le libelle Excel "€/MWh" des 2 lignes
    concernees (Batteries and PCS, OPEX - Guarantees) - bug de mislabeling
    du fichier source, confirme par l'utilisateur le 2026-09-24 : lu comme
    €/MWh, `base=156.37` donnait un cout Batteries+PCS de ~10 k€ pour 80 MWh
    (40 MW/2h), soit ~0.12 €/kWh installe - physiquement impossible pour une
    batterie (plage reelle : 100-300+ €/kWh). Lu comme €/kWh, ce meme
    coefficient tombe a moins de 1% de la valeur Aurora HTA validee
    (18 670 k€), qui sert de point de recoupement independant - voir
    docs/specs/copex_icp.md."""

    base: float
    exponent: float
    escalation: dict[int, float]


@dataclass(frozen=True)
class IcpCostLibrary:
    update_date: Any
    inflation_rate: float
    line_items: dict[str, dict[str, IcpCostCell]]  # label -> segment -> cellule
    escalation: dict[str, dict[int, float]]  # label -> annee -> multiplicateur
    battery_pcs: dict[int, IcpPowerLawCost]  # duree_h -> formule
    opex_guarantees: dict[int, IcpPowerLawCost]  # duree_h -> formule
    insurance_construction_pct: dict[str, float]  # segment -> %
    epc_margin_pct: dict[str, float]  # segment -> %


def _unit_from_number_format(fmt: str) -> str:
    """Ne jamais deduire l'unite de la valeur brute (une meme ligne melange
    parfois €/MW et k€ forfait selon la colonne, ex. 'Grid connection') -
    toujours lire le suffixe entre guillemets du format Excel (demande de
    l'utilisateur, 2026-09-24)."""
    if "%" in fmt:
        return "percent"
    if "MWh" in fmt and "/an" in fmt:
        return "keur_per_mwh_per_year"
    if "/MWh" in fmt:
        return "eur_per_mwh"
    if "/MW" in fmt:
        return "eur_per_mw"
    return "keur_flat"


def _find_row(ws, label_substring: str, *, after_row: int = 1) -> int:
    for row in range(after_row, ws.max_row + 1):
        value = ws.cell(row=row, column=1).value
        if isinstance(value, str) and label_substring in value:
            return row
    raise ValueError(f"Row '{label_substring}' not found in sheet {ICP_SHEET}.")


def _read_escalation(ws, row: int) -> dict[int, float]:
    escalation: dict[int, float] = {}
    for col in range(_FIRST_YEAR_COL, _LAST_YEAR_COL + 1):
        year = ws.cell(row=_YEAR_ROW, column=col).value
        multiplier = ws.cell(row=row, column=col).value
        if isinstance(year, (int, float)) and isinstance(multiplier, (int, float)):
            escalation[int(year)] = float(multiplier)
    return escalation


def _read_line_item_row(ws, row: int) -> dict[str, IcpCostCell]:
    by_segment: dict[str, IcpCostCell] = {}
    for segment, col in SEGMENT_COLUMNS.items():
        cell = ws.cell(row=row, column=col)
        if not isinstance(cell.value, (int, float)):
            continue  # ex. "= TSO 63/90/225" (texte de renvoi, pas une valeur exploitable)
        by_segment[segment] = IcpCostCell(
            value=float(cell.value), unit=_unit_from_number_format(cell.number_format)
        )
    return by_segment


def _read_power_law(ws, row: int) -> IcpPowerLawCost:
    base = float(ws.cell(row=row, column=8).value)  # colonne H
    exponent = float(ws.cell(row=row, column=10).value)  # colonne J
    return IcpPowerLawCost(base=base, exponent=exponent, escalation=_read_escalation(ws, row))


def load_icp_library(path: Path = DEFAULT_ICP_PATH) -> IcpCostLibrary:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False, keep_links=False)
    ws = wb[ICP_SHEET]

    update_date = ws.cell(row=2, column=3).value
    inflation_rate = float(ws.cell(row=2, column=15).value)

    battery_row_2h = _find_row(ws, _BATTERY_LABEL)
    battery_pcs = {
        2: _read_power_law(ws, battery_row_2h),
        4: _read_power_law(ws, battery_row_2h + 1),
    }

    guarantees_row_2h = _find_row(ws, _GUARANTEES_LABEL)
    opex_guarantees = {
        2: _read_power_law(ws, guarantees_row_2h),
        4: _read_power_law(ws, guarantees_row_2h + 1),
    }

    flat_labels = [*_DIRECT_CAPEX_LABELS, _OM_LABEL, _GRID_CONNECTION_LABEL]
    line_items: dict[str, dict[str, IcpCostCell]] = {}
    escalation: dict[str, dict[int, float]] = {}
    for label in flat_labels:
        row = _find_row(ws, label)
        line_items[label] = _read_line_item_row(ws, row)
        escalation[label] = _read_escalation(ws, row)

    insurance_by_segment = _read_line_item_row(ws, _find_row(ws, _INSURANCE_LABEL))
    epc_by_segment = _read_line_item_row(ws, _find_row(ws, _EPC_MARGIN_LABEL))

    return IcpCostLibrary(
        update_date=update_date,
        inflation_rate=inflation_rate,
        line_items=line_items,
        escalation=escalation,
        battery_pcs=battery_pcs,
        opex_guarantees=opex_guarantees,
        insurance_construction_pct={seg: c.value for seg, c in insurance_by_segment.items()},
        epc_margin_pct={seg: c.value for seg, c in epc_by_segment.items()},
    )


@lru_cache(maxsize=4)
def _cached_icp_library(path_str: str) -> IcpCostLibrary:
    return load_icp_library(Path(path_str))


def load_icp_library_cached(path: Path = DEFAULT_ICP_PATH) -> IcpCostLibrary:
    """Comme `load_icp_library`, mais memoise par chemin (le fichier ICP est
    relu a chaque appel de `capex_and_opex_keur`/`repowering_capex_keur`,
    potentiellement des milliers de fois pendant une sensibilite globale -
    voir `core/global_sensitivity.py`)."""
    return _cached_icp_library(str(path))


def _icp_escalation_factor(escalation: dict[int, float], cod_year: int) -> float:
    """Meme philosophie de plafonnement que `dev_case.escalated_unit_cost`,
    mais convention multiplicative (pas un delta) : le fichier ICP donne un
    multiplicateur relatif a l'annee de base (colonne K, ~2026, valeur 1.0),
    pas un pourcentage de variation."""
    if not escalation:
        return 1.0
    if cod_year in escalation:
        return escalation[cod_year]
    years = sorted(escalation)
    if cod_year > years[-1]:
        return escalation[years[-1]]
    return 1.0


def _scaled_cost_keur(cell: IcpCostCell, *, power_mw: float, duree_h: int) -> float:
    mwh = power_mw * duree_h
    if cell.unit == "eur_per_mwh":
        return cell.value * mwh / 1000.0
    if cell.unit == "eur_per_mw":
        return cell.value * power_mw / 1000.0
    if cell.unit == "keur_flat":
        return cell.value
    if cell.unit == "keur_per_mwh_per_year":
        return cell.value * mwh
    raise ValueError(f"Unknown ICP unit: '{cell.unit}'.")


def _power_law_cost_keur(
    formula: IcpPowerLawCost, *, power_mw: float, duree_h: int, cod_year: int
) -> float:
    """`formula.base` est en EUR/kWh (voir `IcpPowerLawCost`) : cout total EUR
    = unit_cost(EUR/kWh) x kWh_total(mwh x 1000) ; cout total k€ = /1000 de ce
    montant, donc numeriquement `unit_cost x mwh` (le x1000/1000 s'annule) -
    PAS de division supplementaire par 1000."""
    mwh = power_mw * duree_h
    unit_cost_eur_per_kwh = formula.base * mwh**formula.exponent
    escalation = _icp_escalation_factor(formula.escalation, cod_year)
    return unit_cost_eur_per_kwh * escalation * mwh


def _icp_line_item_keur(
    icp_library: IcpCostLibrary,
    label: str,
    segment: str,
    *,
    power_mw: float,
    duree_h: int,
    cod_year: int,
) -> float | None:
    cell = icp_library.line_items[label].get(segment)
    if cell is None:
        return None
    # `escalation[label]` est {annee: multiplicateur}, le meme pour les 7
    # colonnes d'une ligne (verifie sur le fichier reel) - pas de dimension
    # segment ici, voir `_read_escalation`.
    escalation = _icp_escalation_factor(icp_library.escalation[label], cod_year)
    return _scaled_cost_keur(cell, power_mw=power_mw, duree_h=duree_h) * escalation


def icp_battery_pcs_keur(
    icp_library: IcpCostLibrary, *, duree_h: int, power_mw: float, cod_year: int
) -> float:
    if duree_h not in icp_library.battery_pcs:
        raise ValueError(f"No ICP Batteries and PCS formula for {duree_h}h.")
    return _power_law_cost_keur(
        icp_library.battery_pcs[duree_h], power_mw=power_mw, duree_h=duree_h, cod_year=cod_year
    )


def icp_opex_guarantees_annualized_keur(
    icp_library: IcpCostLibrary, *, duree_h: int, power_mw: float, cod_year: int
) -> float:
    """Cout total de garantie/maintenance preventive sur 15 ans (confirme par
    l'utilisateur, 2026-09-24), etale lineairement sur ces 15 ans - le moteur
    financier n'a pas de notion d'OPEX variable dans le temps aujourd'hui
    (`opex_year1_keur` est repete identique chaque annee), donc cet etalement
    devient une addition CONSTANTE a l'OPEX annuel plutot qu'une charge
    limitee aux 15 premieres annees - simplification documentee, voir
    docs/specs/copex_icp.md "Questions ouvertes"."""
    if duree_h not in icp_library.opex_guarantees:
        raise ValueError(f"No ICP OPEX Guarantees formula for {duree_h}h.")
    total_15y = _power_law_cost_keur(
        icp_library.opex_guarantees[duree_h], power_mw=power_mw, duree_h=duree_h, cod_year=cod_year
    )
    return total_15y / _GUARANTEES_AMORTIZATION_YEARS


def icp_capex_total_keur(
    *,
    tension: str,
    duree_h: int,
    cod_year: int,
    power_mw: float,
    icp_library: IcpCostLibrary,
    aurora_library: CopexLibrary,
) -> tuple[float, list[str]]:
    """CAPEX generique (hors raccordement, gere separement comme avant par
    `connection_capex_mode` - voir `icp_connection_capex_keur`) :

    (somme des postes directs ICP : Batteries+PCS, Electrical works, Civil
    works, HV Transformer, HV/MV substation, Communication, Other BoP,
    Integration) x (1 + EPC Margin) x (1 + Insurance during construction)
    + Development (Aurora, additif, hors perimetre EPC/assurance construction
    - couts de developpement/origination, pas de construction - voir
    docs/specs/copex_icp.md).

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
        return _aurora_capex_total_keur_for_key(aurora_library, key, cod_year, power_mw), [
            f"{tension} : aucune colonne ICP - CAPEX entierement source depuis Aurora COPEX_library."
        ]

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
        icp_library, duree_h=duree_h, power_mw=power_mw, cod_year=cod_year
    )

    epc_margin = icp_library.epc_margin_pct.get(segment, 0.0)
    insurance_pct = icp_library.insurance_construction_pct.get(segment, 0.0)
    construction_keur = direct_keur * (1 + epc_margin) * (1 + insurance_pct)

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
    if missing:
        notes.append(f"Postes ICP absents pour {segment} (repli Aurora) : {', '.join(missing)}.")

    return construction_keur + development_keur, notes


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
        icp_library, duree_h=duree_h, power_mw=power_mw, cod_year=cod_year
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
            icp_library, duree_h=duree_h, power_mw=power_mw, cod_year=repowering_year
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
        "raccordement, marge EPC, assurance construction) : source ICP "
        f"(config/copex_icp.xlsx, segment '{TENSION_TO_ICP_SEGMENT[tension]}').",
        "CAPEX Development : source Aurora COPEX_library (absent d'ICP).",
        "OPEX O&M + garanties/maintenance preventive (15 ans, etalees) : source ICP.",
        "OPEX Insurance/Grid charges/Land lease(bibliotheque)/Accise/Other : source Aurora "
        "COPEX_library (absents d'ICP) - le loyer foncier saisi manuellement ci-dessous "
        "s'ajoute par-dessus, comme avant.",
    ]
