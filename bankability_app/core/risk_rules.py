from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def revenue_weighted_dscr_threshold(inputs: ProjectInputs, thresholds: dict) -> float | None:
    """Lenders don't credit contracted and merchant revenue equally when sizing
    debt: a euro of PPA/capacity revenue is more bankable than a euro of merchant
    (arbitrage/ancillary) revenue. In the absence of a real per-tranche covenant,
    blend the DSCR comfort threshold by revenue mix: dscr_min_amber_contracted
    (1.30x default) weighted by the contracted revenue share, dscr_min_amber_merchant
    (1.50x default) weighted by the merchant share - a 100% merchant project is held
    to a stricter DSCR floor than a 100% contracted one, proportionally in between
    otherwise. Requires the full-format BP's revenue_detail (PPA/Capacity/Merchant
    sub-lines of O-Financials) - None when unavailable (summary format, or the
    sub-lines are all zero)."""
    detail = inputs.revenue_detail
    if detail is None or detail.contracted_keur is None or detail.merchant_keur is None:
        return None
    total_contracted = sum(detail.contracted_keur)
    total_merchant = sum(detail.merchant_keur)
    total = total_contracted + total_merchant
    if total <= 0:
        return None
    contracted_share = total_contracted / total
    merchant_share = total_merchant / total
    return (
        contracted_share * thresholds["dscr_min_amber_contracted"]
        + merchant_share * thresholds["dscr_min_amber_merchant"]
    )


def evaluate_risks(
    inputs: ProjectInputs, result: ProjectResults, thresholds: dict | None = None
) -> list[RiskFlag]:
    thresholds = thresholds or load_thresholds()
    flags: list[RiskFlag] = []

    # Seuil DSCR "confortable" (amber), par ordre de priorite decroissant :
    # 1. Target DSCR du projet (I-Project) - le vrai covenant negocie avec le preteur.
    # 2. Seuil pondere par mix de revenus contracte/merchant (O-Financials) - a
    #    defaut du vrai covenant, une estimation tenant compte de la qualite du revenu.
    # 3. Seuil generique de la config (dscr_min_amber).
    # Le seuil "critique" (dscr_min_red), lui, reste toujours generique : le BP
    # n'expose pas de covenant de defaut distinct du target DSCR de sizing.
    weighted_threshold = revenue_weighted_dscr_threshold(inputs, thresholds)
    if inputs.target_dscr is not None:
        dscr_min_amber = inputs.target_dscr
        amber_label = "cible du projet (I-Project)"
    elif weighted_threshold is not None:
        dscr_min_amber = weighted_threshold
        amber_label = "pondere par mix de revenu contracte/merchant"
    else:
        dscr_min_amber = thresholds["dscr_min_amber"]
        amber_label = "bancaire usuel"

    dscr_min = result.dscr_min
    if dscr_min is None:
        flags.append(
            RiskFlag(
                "DSCR min",
                "amber",
                "DSCR non calculable (pas de dette ou pas d'annees d'exploitation).",
            )
        )
    elif dscr_min < thresholds["dscr_min_red"]:
        flags.append(
            RiskFlag(
                "DSCR min",
                "red",
                f"DSCR min {dscr_min:.2f}x sous le seuil critique {thresholds['dscr_min_red']:.2f}x.",
            )
        )
    elif dscr_min < dscr_min_amber:
        flags.append(
            RiskFlag(
                "DSCR min",
                "amber",
                f"DSCR min {dscr_min:.2f}x sous le seuil {amber_label} {dscr_min_amber:.2f}x.",
            )
        )
    else:
        flags.append(
            RiskFlag(
                "DSCR min",
                "green",
                f"DSCR min {dscr_min:.2f}x au-dessus du seuil {amber_label} {dscr_min_amber:.2f}x.",
            )
        )

    if result.equity_irr is None:
        flags.append(RiskFlag("Equity IRR", "amber", "Equity IRR non calculable."))
    elif result.equity_irr < thresholds["equity_irr_hurdle"]:
        flags.append(
            RiskFlag(
                "Equity IRR",
                "red",
                f"Equity IRR {result.equity_irr:.1%} sous le hurdle rate {thresholds['equity_irr_hurdle']:.1%}.",
            )
        )
    else:
        flags.append(
            RiskFlag(
                "Equity IRR",
                "green",
                f"Equity IRR {result.equity_irr:.1%} au-dessus du hurdle rate.",
            )
        )

    if result.project_irr is not None:
        margin = result.project_irr - inputs.wacc
        if margin < thresholds["project_irr_vs_wacc_margin"]:
            flags.append(
                RiskFlag(
                    "Project IRR vs WACC",
                    "red",
                    f"Project IRR {result.project_irr:.2%} < WACC {inputs.wacc:.2%}.",
                )
            )
        else:
            flags.append(
                RiskFlag(
                    "Project IRR vs WACC",
                    "green",
                    f"Project IRR {result.project_irr:.2%} >= WACC {inputs.wacc:.2%} (marge {margin:.2%}).",
                )
            )

    return flags
