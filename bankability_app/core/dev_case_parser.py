from __future__ import annotations

import re
from typing import Any

import openpyxl

from .bp_parser import _normalize, _scalar_value, load_grid
from .dev_case import AuroraLibrary, CopexLibrary, DevCaseParams

DEV_CASE_SHEETS = {"Inputs Dev", "COPEX_library", "CF Aurora"}
# Un seul chiffre, immédiatement avant le "h" - pas `\d+` (plusieurs chiffres) :
# certaines sections de CF Aurora préfixent le label par "STHTB1"/"STHTB2" sans
# séparateur (ex. "STHTB12h1MW"), où un `\d+` gourmand happe le "1" final du
# préfixe et lit "12h" (durée 12, inexistante) au lieu de "2h" (durée 2) - bug
# trouvé en validant les durées disponibles par combo sur le fichier réel.
_DURATION_PATTERN = re.compile(r"(\d)h", re.IGNORECASE)


def has_dev_case_sheets(file_or_path) -> bool:
    """True si le classeur contient les 3 onglets nécessaires à l'onglet "Cas de
    développement" (`Inputs Dev`, `COPEX_library`, `CF Aurora`) - en plus,
    éventuellement, des onglets du format complet standard."""
    workbook = openpyxl.load_workbook(file_or_path, read_only=True)
    sheets = set(workbook.sheetnames)
    workbook.close()
    if hasattr(file_or_path, "seek"):
        file_or_path.seek(0)
    return DEV_CASE_SHEETS.issubset(sheets)


def _find_row_index(grid: list[list[Any]], predicate) -> int | None:
    for i, row in enumerate(grid):
        if predicate(row):
            return i
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_segment_keyed_table(
    grid: list[list[Any]], header_row_idx: int, num_cols: int = 7
) -> dict[str, dict[str, float]]:
    """Lit une table 'label | valeur_segment_1 | ... | valeur_segment_N' (ex.
    COPEX_library 'Hypothèses CAPEX BP' ou 'OPEX assumptions - AURORA') en
    `dict[segment][label] = valeur`. S'arrête à la 1ère ligne dont la colonne A
    est vide (fin de table). Segments dupliqués (ex. 2 colonnes 'DSO') : la
    1ère valeur rencontrée est conservée."""
    header = grid[header_row_idx]
    col_labels = [
        " ".join(str(c).strip().split()) if c is not None else "" for c in header[1 : 1 + num_cols]
    ]
    result: dict[str, dict[str, float]] = {}
    for row in grid[header_row_idx + 1 :]:
        label_cell = row[0] if row else None
        if label_cell is None or (isinstance(label_cell, str) and not label_cell.strip()):
            break
        label = " ".join(str(label_cell).strip().split())
        values = row[1 : 1 + num_cols]
        for col_label, value in zip(col_labels, values, strict=False):
            if not col_label or not _is_number(value):
                continue
            result.setdefault(col_label, {})
            result[col_label].setdefault(label, float(value))
    return result


def _parse_escalation_table(
    grid: list[list[Any]], header_row_idx: int, num_cols: int = 7
) -> dict[str, dict[int, float]]:
    """Lit le bloc "Forecast price factor (selon année de COD)" à droite de la
    même table (après la colonne de base + les `num_cols` segments + 1 colonne
    vide de séparation) en `dict[label][année] = delta relatif au coût de base
    2028`. L'année de base (colonne A de la ligne d'en-tête) est ajoutée avec
    un delta de 0.0. Retourne un dict vide si la table source n'a pas ce bloc
    (pas d'erreur - l'escalade reste alors simplement non appliquée, voir
    `dev_case.escalated_unit_cost`)."""
    header = grid[header_row_idx]
    base_year = header[0] if header and _is_number(header[0]) else None
    escalation_start = 1 + num_cols + 1
    escalation_years = [c for c in header[escalation_start:] if _is_number(c)]
    result: dict[str, dict[int, float]] = {}
    if not escalation_years:
        return result
    for row in grid[header_row_idx + 1 :]:
        label_cell = row[0] if row else None
        if label_cell is None or (isinstance(label_cell, str) and not label_cell.strip()):
            break
        label = " ".join(str(label_cell).strip().split())
        values = row[escalation_start : escalation_start + len(escalation_years)]
        year_deltas: dict[int, float] = {}
        if base_year is not None:
            year_deltas[int(base_year)] = 0.0
        for year, value in zip(escalation_years, values, strict=False):
            if _is_number(value):
                year_deltas[int(year)] = float(value)
        if year_deltas:
            result[label] = year_deltas
    return result


def _find_numeric_header_row_after(grid: list[list[Any]], start_idx: int) -> int | None:
    """Les tables 'CAPEX assumptions - AURORA' et 'OPEX assumptions - AURORA' de
    COPEX_library ont un titre suivi (après un nombre variable de lignes vides)
    d'une ligne d'en-tête dont la colonne A est une année nue (ex. 2028) plutôt
    qu'un libellé - repérée ainsi plutôt que par un décalage de ligne fixe."""
    for i in range(start_idx, len(grid)):
        row = grid[i]
        if row and _is_number(row[0]):
            return i
    return None


def parse_copex_library(grid: list[list[Any]]) -> CopexLibrary:
    """Lit les 2 tables de COPEX_library indexées par classe de tension x durée
    (même taxonomie que CF Aurora - voir `dev_case.voltage_duration_key`) :
    'CAPEX assumptions - AURORA (base 2028)' (validé exactement contre le
    fichier réel, voir `dev_case.CAPEX_LINE_ITEMS`) et 'OPEX assumptions -
    AURORA'. La table 'Hypothèses CAPEX BP' (7 segments CAPEX) n'est
    volontairement pas lue : ses valeurs se sont révélées être déjà totalisées
    pour le projet courant plutôt qu'une bibliothèque de taux réutilisable
    (voir docs/specs/dev_case.md)."""
    capex_title_idx = _find_row_index(
        grid, lambda row: bool(row) and _normalize(row[0]).startswith("capex assumptions")
    )
    if capex_title_idx is None:
        raise ValueError("Section 'CAPEX assumptions - AURORA' not found in COPEX_library.")
    capex_header_idx = _find_numeric_header_row_after(grid, capex_title_idx + 1)
    if capex_header_idx is None:
        raise ValueError("Header row of 'CAPEX assumptions - AURORA' not found.")
    capex_unit_costs = _parse_segment_keyed_table(grid, capex_header_idx, num_cols=7)
    capex_escalation = _parse_escalation_table(grid, capex_header_idx, num_cols=7)

    opex_title_idx = _find_row_index(
        grid, lambda row: bool(row) and _normalize(row[0]).startswith("opex assumptions")
    )
    if opex_title_idx is None:
        raise ValueError("Section 'OPEX assumptions - AURORA' not found in COPEX_library.")
    opex_header_idx = _find_numeric_header_row_after(grid, opex_title_idx + 1)
    if opex_header_idx is None:
        raise ValueError("Header row of 'OPEX assumptions - AURORA' not found.")
    opex_unit_costs = _parse_segment_keyed_table(grid, opex_header_idx, num_cols=7)
    opex_escalation = _parse_escalation_table(grid, opex_header_idx, num_cols=7)

    return CopexLibrary(
        capex_unit_costs=capex_unit_costs,
        opex_unit_costs=opex_unit_costs,
        capex_escalation=capex_escalation,
        opex_escalation=opex_escalation,
    )


def _extract_duration_h(configuration_label: str) -> int | None:
    match = _DURATION_PATTERN.search(configuration_label)
    return int(match.group(1)) if match else None


def _leading_numeric_run(row: list[Any], start: int) -> list[Any]:
    """Chaque ligne de CF Aurora (en-tête comme donnée) ne contient pas 1 mais
    **4 blocs juxtaposés** sur la même ligne physique - un run "Aurora"
    (colonnes E+) puis 3 runs "Clean Horizon" décalés d'1 an chacun (utilisés
    pour la comparaison Aurora vs CH d'Advise Dev), séparés par 3 colonnes
    vides puis 3 colonnes de labels (configuration/price/stream) répétés.
    Ne garder que le 1er run (le seul qu'on utilise) : s'arrêter à la 1ère
    cellule non numérique plutôt que de filtrer les blancs sur toute la ligne
    - sinon les années du run 1 se retrouvent zippées avec des valeurs du run
    2/3/4 après le 1er blanc (bug trouvé lors de la validation : une année se
    voyait attribuer la valeur d'une tout autre année, décalage cumulatif)."""
    result = []
    for cell in row[start:]:
        if not _is_number(cell):
            break
        result.append(cell)
    return result


def parse_cf_aurora(grid: list[list[Any]]) -> AuroraLibrary:
    """CF Aurora est organisé en 15 sections (3 classes de tension x 5 variantes
    TURPE/gabarit), chacune contenant 2 blocs de config (2h/4h), chacun listant
    ~15-17 lignes de flux par année calendaire (plus, sur chaque ligne, 3 blocs
    "Clean Horizon" supplémentaires décalés d'1 an - voir `_leading_numeric_run`).
    Repéré par balayage séquentiel (pas d'adresse de cellule fixe, cohérent avec
    `bp_parser.py`) :
    - colonne A non vide + colonne B vide -> titre de section (ex. "HTA injection")
    - colonne B == "configuration" -> ligne d'en-tête (années en colonnes E+)
    - colonne B non vide (sinon) -> ligne de donnée (config en B, flux en D,
      valeurs annuelles en E+)."""
    combos: dict[str, dict[int, dict[int, dict[str, float]]]] = {}
    current_combo_key: str | None = None
    year_columns: list[int] = []

    for row in grid:
        col0 = row[0] if len(row) > 0 else None
        col1 = row[1] if len(row) > 1 else None

        if col1 is not None and _normalize(col1) == "configuration":
            year_columns = _leading_numeric_run(row, 4)
            continue

        if isinstance(col0, str) and col0.strip() and col1 is None:
            current_combo_key = " ".join(col0.strip().split())
            continue

        if (
            isinstance(col1, str)
            and col1.strip()
            and current_combo_key is not None
            and year_columns
        ):
            duration_h = _extract_duration_h(col1)
            stream = row[3] if len(row) > 3 else None
            if duration_h is None or not stream:
                continue
            values = row[4 : 4 + len(year_columns)]
            year_map = combos.setdefault(current_combo_key, {}).setdefault(duration_h, {})
            for year, value in zip(year_columns, values, strict=False):
                if not _is_number(value):
                    continue
                year_map.setdefault(int(year), {})[str(stream).strip()] = float(value)

    return AuroraLibrary(combos=combos)


def parse_inputs_dev(grid: list[list[Any]]) -> DevCaseParams:
    """Valeurs actuelles du formulaire `Inputs Dev` - sert à pré-remplir le
    formulaire Streamlit avec la config du projet déjà en place dans le
    classeur, plutôt que de partir de zéro."""

    def scalar(label: str, default: Any) -> Any:
        value = _scalar_value(grid, label, offset=1)
        return default if value is None else value

    power_mw = float(scalar("Puissance Nominale", 1.0))
    energy_mwh = float(scalar("Capacité énergétique", power_mw * 2))
    duration_h = max(1, round(energy_mwh / power_mw)) if power_mw else 2

    return DevCaseParams(
        cod_year=int(float(scalar("Entry year (COD)", 2028))),
        power_mw=power_mw,
        duration_h=duration_h,
        connection_type=str(scalar("Network (Segment)", "TSO 90kV")),
        turpe_type=str(scalar("Type TURPE", "Classique")),
        gabarit=bool(scalar("Gabarit", 0)),
        repowering=bool(scalar("Repowering", 0)),
        connection_capex_mode="library",
        distance_rte_km=float(scalar("Option 2 - Distance racco RTE", 0.0)),
        distance_substation_km=float(scalar("Option 3 - Distance HV Substation - BESS", 0.0)),
        manual_connection_capex_keur=float(scalar("Option 1 - Valeur manuelle", 0.0)),
        land_lease_opex_keur=float(scalar("OPEX Loyer foncier", 0.0)),
    )


def load_dev_case_grids(file_or_path) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
    """Charge les 3 grilles (Inputs Dev, COPEX_library, CF Aurora) depuis le
    fichier uploadé, en repositionnant le curseur du fichier entre chaque
    lecture (même contrainte que `bp_parser.parse_full_bp` sur un fichier en
    mémoire type `UploadedFile` de Streamlit)."""
    grids = []
    for sheet_name in ("Inputs Dev", "COPEX_library", "CF Aurora"):
        if hasattr(file_or_path, "seek"):
            file_or_path.seek(0)
        grids.append(load_grid(file_or_path, sheet_name=sheet_name))
    return tuple(grids)  # type: ignore[return-value]
