"""Regenere `config/aurora_degradation_and_cm.json` depuis le databook Aurora Q2 2026
(onglets 'Undegraded batteries' / 'Degraded batteries').

Usage : .venv\\Scripts\\python.exe sample_data/build_aurora_degradation_and_cm.py <databook.xlsm>

- `degradation_no_repo_2h` : ratio revenu degrade / non degrade (energie + services systeme
  + mecanisme de capacite, hors network charges) par op-year, moyenne des cas standalone
  Central 2h a COD 2027 (HTA a HTB3), jusqu'au repowering Aurora ; extrapole lineairement
  au-dela (pente des 5 derniers points). La table `DegFactor_noRepo` d'aurora_curves_22configs
  est celle des 4h - l'appliquer aux 2h surestimait leur revenu (cyclage 1,5/jour contre 1).
- `capacity_mechanism` : mecanisme de capacite (EUR/kW, par annee civile) par duree, tel
  qu'inclus dans la courbe RAW (cas COD 2027 non degrade) - identique quelle que soit la
  tension/TURPE/gabarit/ORO, jamais degrade par Aurora. Sert a l'exclure de l'assiette des
  frais de trading, comme Aurora.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "config" / "aurora_degradation_and_cm.json"
TENSIONS = ("HTA", "HTB1", "HTB2", "HTB3")
ENTRY_YEAR = 2027
TAIL_POINTS = 5
LAST_OP_YEAR = 30
_REVENUE_LINES = (
    "Storage total energy-based cashflow",
    "Storage total ancillary services capacity cashflow",
    "Storage Capacity Mechanism cashflow",
)
_CM_LINE = "Storage Capacity Mechanism cashflow"


def _read_blocks(ws) -> dict[str, dict]:
    years = None
    blocks: dict[str, dict] = {}
    current = None
    for r, row in enumerate(ws.iter_rows(min_row=1, values_only=True), start=1):
        if r == 7:
            years = list(row[5:40])
        if isinstance(row[1], str) and row[1].startswith("Case ") and " - " in row[1]:
            current = row[1].split(" - ")[0].strip()
            blocks[current] = {"label": row[1]}
        if current and isinstance(row[3], str) and row[3] not in blocks[current]:
            blocks[current][row[3]] = dict(zip(years, row[5:40], strict=True))
    return blocks


def _is_reference_case(label: str, duration: str) -> bool:
    parts = [p.strip() for p in label.split(" - ")]
    # "Case N - standalone - 2027 - 2h - HTB2 - Central - standard - no curtailment"
    return (
        parts[1] == "standalone"
        and parts[2] == str(ENTRY_YEAR)
        and parts[3] == duration
        and parts[4] in TENSIONS
        and parts[5] == "Central"
    )


def _revenue(block: dict, year: int) -> float:
    return sum(block[line][year] for line in _REVENUE_LINES)


def _linear_fit(points: list[tuple[int, float]]) -> tuple[float, float]:
    n = len(points)
    sx = sum(x for x, _ in points)
    sy = sum(y for _, y in points)
    sxx = sum(x * x for x, _ in points)
    sxy = sum(x * y for x, y in points)
    slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    return slope, (sy - slope * sx) / n


def build(databook: Path) -> dict:
    wb = openpyxl.load_workbook(databook, read_only=True, data_only=True)
    degraded = _read_blocks(wb["Degraded batteries"])
    undegraded = _read_blocks(wb["Undegraded batteries"])

    ratios_by_op_year: dict[int, list[float]] = {}
    cases_used = []
    for case, block in degraded.items():
        if case not in undegraded or not _is_reference_case(block["label"], "2h"):
            continue
        cases_used.append(case)
        for op_year, year in enumerate(range(ENTRY_YEAR, ENTRY_YEAR + LAST_OP_YEAR), start=1):
            if block["Storage repower count"][year]:
                break
            ratios_by_op_year.setdefault(op_year, []).append(
                _revenue(block, year) / _revenue(undegraded[case], year)
            )
    # Seuls les op-years couverts par TOUS les cas (avant le 1er repowering Aurora) -
    # un op-year couvert par une partie des cas seulement biaiserait la moyenne.
    known = {
        op: sum(v) / len(v)
        for op, v in sorted(ratios_by_op_year.items())
        if len(v) == len(cases_used)
    }
    for op, values in sorted(ratios_by_op_year.items()):
        if op in known:
            print(
                f"  op-year {op:>2}: mean {known[op]:.4f}, min {min(values):.4f}, "
                f"max {max(values):.4f}"
            )
    print(
        f"2h degradation: {len(cases_used)} cases ({', '.join(cases_used)}), "
        f"op-years 1-{max(known)} known, extrapolated beyond"
    )
    tail = [(op, known[op]) for op in sorted(known)[-TAIL_POINTS:]]
    slope, intercept = _linear_fit(tail)
    degradation_2h = [
        round(known[op] if op in known else slope * op + intercept, 6)
        for op in range(1, LAST_OP_YEAR + 1)
    ]

    capacity_mechanism = {}
    for duration in ("2h", "4h"):
        # Les libelles de l'onglet non degrade ne portent pas l'annee d'entree : le cas
        # de reference est choisi sur son libelle degrade.
        case = next(
            c
            for c, b in degraded.items()
            if c in undegraded and _is_reference_case(b["label"], duration)
        )
        cm = undegraded[case][_CM_LINE]
        capacity_mechanism[duration] = {
            str(year): round(value, 6)
            for year, value in cm.items()
            if isinstance(year, int) and year >= ENTRY_YEAR
        }
        print(f"capacity mechanism {duration}: from {case}")

    return {
        "source": (
            "Aurora Q2 2026 FRA Central databook (Undegraded/Degraded batteries) - genere par "
            "sample_data/build_aurora_degradation_and_cm.py"
        ),
        "unit": "ratio (degradation) ; EUR/kW de storage (capacity_mechanism)",
        "degradation_no_repo_2h": {
            "op_years": list(range(1, LAST_OP_YEAR + 1)),
            "values": degradation_2h,
            "known_op_years": max(known),
            "cases": cases_used,
        },
        "capacity_mechanism": capacity_mechanism,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    data = build(Path(sys.argv[1]))
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1)
        handle.write("\n")
    print(f"written: {OUTPUT_PATH}")
