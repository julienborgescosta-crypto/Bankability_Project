"""Overlays contractuels (full merchant / floor / tolling) : ajustent la serie de
revenu et derivent la cible DSCR + la maturite de dette qui en decoulent (tiering
securise/merchant, maturite PPA+3) - voir docs/specs/aur_v2_methodology.md
section 2.2 et CONTEXT.md "Tiering DSCR securise/merchant (Aurora)" / "Maturite
PPA+3". Independant de `financial_engine.py` : ce module derive les valeurs
(`target_dscr`, `debt_tenor_years`) a passer telles quelles a
`financial_engine.compute_results(..., debt_sizing_mode="dscr")`, sans modifier
le moteur lui-meme."""

from __future__ import annotations

from dataclasses import dataclass

FULL_MERCHANT = "full_merchant"
FLOOR = "floor"
TOLLING = "tolling"


@dataclass(frozen=True)
class ContractStructure:
    """`price_keur_per_mw_per_year`/`duration_years` : I-Project!53/58 (floor/tolling
    price) et la duree PPA (I-Project!49-50). `revenue_sharing_above_floor_pct` :
    I-Project!54, floor uniquement (partage de l'excedent au-dessus du floor avec
    l'agregateur - la tolling n'a pas d'excedent puisqu'elle remplace le revenu par
    un prix fixe)."""

    kind: str  # FULL_MERCHANT | FLOOR | TOLLING
    price_keur_per_mw_per_year: float = 0.0
    duration_years: int = 0
    revenue_sharing_above_floor_pct: float = 0.0


def apply_contract_overlay(
    revenue_keur: list[float],
    power_mw: float,
    structure: ContractStructure,
) -> tuple[list[float], list[float]]:
    """Retourne `(revenu_ajuste, revenu_securise)`, meme longueur que
    `revenue_keur` (annees d'exploitation alignees a partir du COD).

    - "full_merchant" : les deux series valent le revenu merchant brut (rien de
      securise).
    - "tolling" : pendant `duration_years`, le revenu est REMPLACE par le prix de
      tolling (fixe, independant du merchant) - integralement securise ; au-dela,
      retour au merchant brut.
    - "floor" : pendant `duration_years`, le revenu est plancher au floor (le
      manque a gagner est couvert) et l'excedent au-dessus du floor est partage
      avec l'agregateur (`revenue_sharing_above_floor_pct`) - le floor lui-meme
      est la part securisee, le partage au-dessus reste au risque merchant."""
    if structure.kind == FULL_MERCHANT:
        return list(revenue_keur), [0.0] * len(revenue_keur)
    if structure.kind not in (FLOOR, TOLLING):
        raise ValueError(f"Structure contractuelle inconnue : '{structure.kind}'.")

    guaranteed_keur = structure.price_keur_per_mw_per_year * power_mw
    adjusted: list[float] = []
    secured: list[float] = []
    for i, merchant_revenue in enumerate(revenue_keur):
        if i >= structure.duration_years:
            adjusted.append(merchant_revenue)
            secured.append(0.0)
            continue
        if structure.kind == TOLLING:
            adjusted.append(guaranteed_keur)
        else:  # FLOOR
            upside = max(merchant_revenue - guaranteed_keur, 0.0)
            adjusted.append(
                guaranteed_keur + (1 - structure.revenue_sharing_above_floor_pct) * upside
            )
        secured.append(guaranteed_keur)
    return adjusted, secured


def _secured_revenue_share(
    secured_revenue_keur: list[float], total_revenue_keur: list[float]
) -> float:
    total = sum(total_revenue_keur)
    if total <= 0:
        return 0.0
    return min(max(sum(secured_revenue_keur) / total, 0.0), 1.0)


def blended_target_dscr(
    secured_revenue_keur: list[float],
    total_revenue_keur: list[float],
    *,
    target_dscr_secured: float,
    target_dscr_merchant: float,
) -> float:
    """Cible DSCR ponderee par le mix de revenu securise/merchant sur la fenetre
    consideree - meme principe que `risk_rules.revenue_weighted_dscr_threshold`
    (ponderation par part de revenu), mais generalise a une serie annuelle plutot
    qu'au `RevenueBreakdown` extrait du BP reel. Les deux tierings DSCR restent
    distincts (l'un flagge un risque affiche, l'autre dimensionne reellement la
    dette) - voir CONTEXT.md."""
    share = _secured_revenue_share(secured_revenue_keur, total_revenue_keur)
    return share * target_dscr_secured + (1 - share) * target_dscr_merchant


def blended_buyer_target_equity_irr(
    secured_revenue_keur: list[float],
    total_revenue_keur: list[float],
    *,
    target_irr_secured: float,
    target_irr_merchant: float,
) -> float:
    """Meme ponderation que `blended_target_dscr`, appliquee au TRI equity cible de
    l'acheteur au RtB (docs/specs/aur_v2_methodology.md section 3.4) : un
    revenu securise (floor/tolling) justifie un TRI cible plus bas qu'un projet
    full merchant - `target_irr_merchant` (confirme, 11 %) et `target_irr_secured`
    (provisoire, 9 % - tolling/floor) sont les deux ancres, un floor partiel
    interpole entre les deux selon sa part de revenu securise."""
    share = _secured_revenue_share(secured_revenue_keur, total_revenue_keur)
    return share * target_irr_secured + (1 - share) * target_irr_merchant


def debt_maturity_years(
    structure: ContractStructure,
    *,
    maturity_full_merchant_years: int,
    maturity_years_added_after_ppa: int,
) -> int:
    if structure.kind == FULL_MERCHANT:
        return maturity_full_merchant_years
    return structure.duration_years + maturity_years_added_after_ppa
