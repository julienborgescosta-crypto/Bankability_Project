from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .models import ProjectInputs, ProjectResults

DEFAULT_THRESHOLDS_PATH = Path(__file__).resolve().parent.parent / "config" / "risk_thresholds.yaml"


@dataclass
class RiskFlag:
    label: str
    level: str  # "green" | "amber" | "red"
    message: str


def load_thresholds(path: Path = DEFAULT_THRESHOLDS_PATH) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def evaluate_risks(
    inputs: ProjectInputs, result: ProjectResults, thresholds: Optional[dict] = None
) -> list[RiskFlag]:
    thresholds = thresholds or load_thresholds()
    flags: list[RiskFlag] = []

    dscr_min = result.dscr_min
    if dscr_min is None:
        flags.append(RiskFlag("DSCR min", "amber", "DSCR non calculable (pas de dette ou pas d'annees d'exploitation)."))
    elif dscr_min < thresholds["dscr_min_red"]:
        flags.append(RiskFlag("DSCR min", "red", f"DSCR min {dscr_min:.2f}x sous le seuil critique {thresholds['dscr_min_red']:.2f}x."))
    elif dscr_min < thresholds["dscr_min_amber"]:
        flags.append(RiskFlag("DSCR min", "amber", f"DSCR min {dscr_min:.2f}x sous le seuil bancaire usuel {thresholds['dscr_min_amber']:.2f}x."))
    else:
        flags.append(RiskFlag("DSCR min", "green", f"DSCR min {dscr_min:.2f}x au-dessus des seuils bancaires."))

    if result.equity_irr is None:
        flags.append(RiskFlag("Equity IRR", "amber", "Equity IRR non calculable."))
    elif result.equity_irr < thresholds["equity_irr_hurdle"]:
        flags.append(RiskFlag("Equity IRR", "red", f"Equity IRR {result.equity_irr:.1%} sous le hurdle rate {thresholds['equity_irr_hurdle']:.1%}."))
    else:
        flags.append(RiskFlag("Equity IRR", "green", f"Equity IRR {result.equity_irr:.1%} au-dessus du hurdle rate."))

    if result.project_irr is not None:
        margin = result.project_irr - inputs.wacc
        if margin < thresholds["project_irr_vs_wacc_margin"]:
            flags.append(RiskFlag("Project IRR vs WACC", "red", f"Project IRR {result.project_irr:.2%} < WACC {inputs.wacc:.2%}."))
        else:
            flags.append(RiskFlag("Project IRR vs WACC", "green", f"Project IRR {result.project_irr:.2%} >= WACC {inputs.wacc:.2%} (marge {margin:.2%})."))

    return flags
