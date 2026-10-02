"""Regenere `config/copex_library_q2_2026.json` depuis l'onglet 'Costs assumptions'
du databook Aurora Q2 2026 (fichier confidentiel, hors repo - chemin en argument).

Usage :
    .venv\\Scripts\\python.exe sample_data/build_copex_library_q2_2026.py <databook.xlsm>

Valeurs de base = annee 2028 ; escalade = ecart relatif a 2028, moyenne sur toutes les
combinaisons duree/tension portant le meme poste (tendance identique d'une combinaison a
l'autre, verifiee par le script). Couvre toute la plage du databook (2026-2060) : la
version precedente du JSON s'arretait en 2035, ce qui plafonnait a tort le cout de
repowering et la valeur de fin de vie des projets longs (voir docs/specs/aur_cases.md)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

OUTPUT = Path(__file__).resolve().parent.parent / "config" / "copex_library_q2_2026.json"
SHEET = "Costs assumptions"
BASE_YEAR = 2028
TENSIONS = ("HTA", "HTB1", "HTB2", "HTB3")  # BT jamais utilise par l'app
# Quelques postes OPEX (Fixed O&M, Insurance) ont une tendance 2h/4h legerement differente
# (< 1 pt d'ecart relatif, ex. Insurance 2051 : -18.4 % vs -19.0 %, soit ~0.02 EUR/kW/an) -
# la moyenne reste la methode de la version d'origine du JSON ; ne bloque qu'au-dela.
TREND_TOLERANCE = 0.02


def _normalize_label(label: str) -> str:
    label = label.strip()
    for prefix in ("Grid connection", "Grid charges"):
        if label.startswith(prefix):
            return prefix
    return "Total" if label.startswith("Total") else label


def _read_block(ws, title: str) -> tuple[dict[str, dict[str, dict[int, float]]], list[int]]:
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=45, values_only=True))
    start = next(i for i, r in enumerate(rows) if isinstance(r[0], str) and r[0].startswith(title))
    header = rows[start + 1]
    years = [y for y in header[5:] if isinstance(y, int)]
    block: dict[str, dict[str, dict[int, float]]] = {}
    key = None
    for r in rows[start + 2 :]:
        if isinstance(r[0], str):  # titre du bloc suivant / END
            break
        if isinstance(r[1], str) and " - " in r[1]:
            key = r[1].strip()
        if key is None or not isinstance(r[2], str):
            continue
        values = {
            y: v
            for y, v in zip(years, r[5 : 5 + len(years)], strict=True)
            if isinstance(v, (int, float))
        }
        if values:
            block.setdefault(key, {})[_normalize_label(r[2])] = values
    return block, years


def _base_and_escalation(block, years):
    keys = [k for k in block if k.split(" - ")[1] in TENSIONS]
    unit_costs = {k: {label: s[BASE_YEAR] for label, s in block[k].items()} for k in keys}
    escalation: dict[str, dict[str, float]] = {}
    labels = sorted({label for k in keys for label in block[k]})
    worst = (0.0, "", 0)
    for label in labels:
        escalation[label] = {}
        for year in years:
            deltas = [
                block[k][label][year] / block[k][label][BASE_YEAR] - 1
                for k in keys
                if label in block[k] and block[k][label].get(BASE_YEAR)
            ]
            spread = max(deltas) - min(deltas)
            if label != "Total" and spread > worst[0]:
                worst = (spread, label, year)
            if label != "Total" and spread > TREND_TOLERANCE:
                raise ValueError(f"Divergent trend for '{label}' in {year}: {deltas}")
            escalation[label][str(year)] = sum(deltas) / len(deltas)
    print(
        f"Largest trend spread across tensions/durations: {worst[0]:.4f} ({worst[1]}, {worst[2]})"
    )
    return unit_costs, escalation


def build(databook: Path) -> dict:
    wb = openpyxl.load_workbook(databook, read_only=True, data_only=True)
    ws = wb[SHEET]
    capex_block, capex_years = _read_block(ws, "CAPEX assumptions")
    opex_block, opex_years = _read_block(ws, "OPEX assumptions")
    capex_unit_costs, capex_escalation = _base_and_escalation(capex_block, capex_years)
    opex_unit_costs, opex_escalation = _base_and_escalation(opex_block, opex_years)
    return {
        "_provenance": (
            f"{databook.name}, sheet '{SHEET}' (CAPEX/OPEX assumptions - lithium ion battery). "
            f"Base year {BASE_YEAR}, escalation = mean relative gap to {BASE_YEAR} across all "
            "tension/duration combinations sharing that cost label (identical trend checked by "
            f"sample_data/build_copex_library_q2_2026.py), years {capex_years[0]}-{capex_years[-1]}."
        ),
        "capex_unit_costs": capex_unit_costs,
        "opex_unit_costs": opex_unit_costs,
        "capex_escalation": capex_escalation,
        "opex_escalation": opex_escalation,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    data = build(Path(sys.argv[1]))
    OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written {OUTPUT}")
