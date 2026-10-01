"""Courbe SoH (State of Health) reelle d'une batterie BESS, par duree (2h/4h) -
lit `config/soh_degradation.xlsx` (fourni par l'utilisateur, 2026-10-01,
feuille "Hypotheses BESS" : 2 blocs "BESS 2h"/"BESS 4h", chacun avec les
colonnes HTA et HTB2 - verifie identiques a la decimale entre les 2 segments,
donc UNE seule courbe par duree, pas de dimension tension).

Pourquoi ce module : `core/aur_cases.py` modelise la degradation du *revenu*
(`DegFactor`/`DegFactor_noRepo`, depuis `AU_Store`) mais ce n'est PAS le SoH -
verifie le 2026-10-01 : a l'annee 15 (= `RepowOpYear` AU_Store, l'annee ou
Aurora repowere dans son scenario central), `DegFactor_noRepo` vaut 83.9 %
tres loin du "SoH de 66 %" qu'Aurora cite explicitement comme le declencheur
du repowering (PDF Aurora Q2 2026, p.11 : "Aurora estimates a 12.8% IRR if
repowered at a SoH of 66%", 2h ; `AU_Store!SoH1 triggering repowering` donne
66.00 %/68.67 % pour 2h/4h) - `DegFactor` et SoH sont deux grandeurs Aurora
distinctes, pas interchangeables. Ce module fournit la vraie courbe SoH pour
pouvoir forcer un repowering quand le SoH (pas le DegFactor) devient trop bas
- voir `core/portfolio.py` `max_op_year_before_forced_repowering`.

La table source ne couvre que l'annee 0 (BoL) a 15 (`RepowOpYear`) - Aurora
n'a jamais eu besoin d'aller plus loin, son scenario central repowere
toujours a 15 ans. Au-dela, `soh_at_op_year` extrapole lineairement (demande
explicite de l'utilisateur) a partir de la pente observee sur la queue de
courbe deja lineaire (annees 11-15 - la partie la plus recente et la plus
stable, pas une regression sur toute la courbe 1-15 qui est legerement
concave en debut de vie - fade initial plus rapide, cf. physique Li-ion -et
biaiserait l'extrapolation vers une pente trop forte)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import openpyxl

DEFAULT_SOH_PATH = Path(__file__).resolve().parent.parent / "config" / "soh_degradation.xlsx"
SOH_SHEET = "Hypotheses BESS"

# Aurora Q2 2026 PDF, p.11/162 ("Aurora estimates a 12.8% IRR if repowered at
# a SoH of 66%") + AU_Store "SoH1 triggering repowering, %" (66.00 %/68.67 %
# pour 2h/4h) - le seuil de SoH en dessous duquel Aurora elle-meme dit qu'un
# repowering est necessaire. Pas confirme par QEF independamment, source
# Aurora uniquement - a ajuster si une meilleure donnee devient disponible.
SOH_TRIGGER_REPOWERING_PCT: dict[int, float] = {2: 0.66, 4: 0.6867}

# Nombre de points en fin de courbe connue utilises pour la pente
# d'extrapolation (voir docstring module) - 5 points = annees 11 a 15.
_EXTRAPOLATION_TAIL_POINTS = 5


@dataclass(frozen=True)
class SohCurve:
    soh_by_op_year: dict[int, float]  # 0 (BoL) a 15 (RepowOpYear)


def _find_header_rows(ws) -> list[int]:
    """Lignes dont la colonne B vaut "Annee" (en-tete d'un bloc duree) -
    recherche par libelle, pas par adresse fixe (meme discipline que le reste
    de l'app - voir docs/specs/bp_parsing.md)."""
    rows = []
    for row in range(1, ws.max_row + 1):
        if ws.cell(row=row, column=2).value == "Annee":
            rows.append(row)
    return rows


def _duration_label_above(ws, header_row: int) -> str:
    """Le libelle "BESS 2h - ..."/"BESS 4h - ..." se trouve 1 a 2 lignes
    au-dessus de l'en-tete "Annee" (voir structure du fichier source)."""
    for row in range(header_row - 1, max(header_row - 4, 0), -1):
        value = ws.cell(row=row, column=2).value
        if isinstance(value, str) and "BESS" in value:
            return value
    raise ValueError(f"No 'BESS Xh' label found above header row {header_row}.")


def _read_soh_block(ws, header_row: int) -> dict[int, float]:
    soh_by_op_year: dict[int, float] = {}
    row = header_row + 1
    while True:
        year_cell = ws.cell(row=row, column=2).value
        soh_cell = ws.cell(row=row, column=3).value
        if year_cell == "BoL":
            op_year = 0
        elif isinstance(year_cell, (int, float)):
            op_year = int(year_cell)
        else:
            break
        if isinstance(soh_cell, (int, float)):
            soh_by_op_year[op_year] = float(soh_cell)
        row += 1
    return soh_by_op_year


def load_soh_curves(path: Path = DEFAULT_SOH_PATH) -> dict[int, SohCurve]:
    """Retourne `{duree_h: SohCurve}` (2 et 4) depuis `config/soh_degradation.xlsx`.
    Leve une erreur explicite si une duree attendue est absente plutot que de
    retomber silencieusement sur une courbe vide (brief section 7, "zero zero
    silencieux")."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[SOH_SHEET]

    curves: dict[int, SohCurve] = {}
    for header_row in _find_header_rows(ws):
        label = _duration_label_above(ws, header_row)
        if "BESS 2h" in label:
            duree_h = 2
        elif "BESS 4h" in label:
            duree_h = 4
        else:
            continue
        if duree_h in curves:
            continue  # 2e colonne (HTB2) du meme bloc duree - identique a HTA, ignoree
        curves[duree_h] = SohCurve(soh_by_op_year=_read_soh_block(ws, header_row))

    missing = {2, 4} - curves.keys()
    if missing:
        raise ValueError(f"SoH curve(s) missing from {path}: {sorted(missing)}h.")
    return curves


@lru_cache(maxsize=1)
def _cached_soh_curves(path_str: str) -> dict[int, SohCurve]:
    return load_soh_curves(Path(path_str))


def load_soh_curves_cached(path: Path = DEFAULT_SOH_PATH) -> dict[int, SohCurve]:
    """Comme `load_soh_curves`, memoise (fichier source stable, pas besoin de
    le relire a chaque appel de `max_op_year_before_forced_repowering`)."""
    return _cached_soh_curves(str(path))


def _linear_fit(points: list[tuple[int, float]]) -> tuple[float, float]:
    """Regression lineaire (moindres carres) `y = slope * x + intercept`."""
    n = len(points)
    sum_x = sum(x for x, _ in points)
    sum_y = sum(y for _, y in points)
    sum_xx = sum(x * x for x, _ in points)
    sum_xy = sum(x * y for x, y in points)
    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x * sum_x)
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def soh_at_op_year(curve: SohCurve, op_year: int) -> float:
    """SoH a `op_year` - valeur connue si couverte par la table source (0 a
    15), sinon extrapolation lineaire a partir de la pente observee sur les
    `_EXTRAPOLATION_TAIL_POINTS` dernieres annees connues (voir docstring
    module - la partie la plus recente et la plus lineaire de la courbe,
    jamais une regression sur toute la courbe qui est concave en debut de
    vie)."""
    if op_year in curve.soh_by_op_year:
        return curve.soh_by_op_year[op_year]
    known_years = sorted(curve.soh_by_op_year)
    tail_years = known_years[-_EXTRAPOLATION_TAIL_POINTS:]
    tail_points = [(year, curve.soh_by_op_year[year]) for year in tail_years]
    slope, intercept = _linear_fit(tail_points)
    return slope * op_year + intercept


def max_op_year_before_forced_repowering(
    duree_h: int, curves: dict[int, SohCurve] | None = None
) -> int:
    """Dernier op-year (entier) ou le SoH extrapole reste >= au seuil Aurora
    (`SOH_TRIGGER_REPOWERING_PCT`) pour cette duree - un repowering doit etre
    en place AU PLUS TARD l'annee suivante. Recherche bornee a 200 ans
    (largement suffisant, la pente d'extrapolation est negative donc le seuil
    est toujours atteint - garde-fou contre une boucle infinie si jamais la
    pente s'averait nulle/positive sur une future mise a jour du fichier
    source)."""
    curves = curves if curves is not None else load_soh_curves_cached()
    if duree_h not in curves:
        raise ValueError(f"No SoH curve for duree_h={duree_h} (available: {sorted(curves)}).")
    if duree_h not in SOH_TRIGGER_REPOWERING_PCT:
        raise ValueError(f"No SoH trigger threshold for duree_h={duree_h}.")
    curve = curves[duree_h]
    threshold = SOH_TRIGGER_REPOWERING_PCT[duree_h]
    op_year = 0
    while soh_at_op_year(curve, op_year + 1) >= threshold and op_year < 200:
        op_year += 1
    return op_year
