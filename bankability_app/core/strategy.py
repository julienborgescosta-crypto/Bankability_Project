"""Les 3 strategies (developper & vendre au RtB / garder & exploiter / racheter
RtB & vendre au COD) - trois lectures du meme moteur financier, jamais trois
moteurs differents. Voir docs/specs/aur_v2_methodology.md section 3,
docs/adr/0002 (revente au COD) et docs/adr/0004 (DSA/SPA/TSP)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import financial_engine
from .acquisition import compute_acquisition_valuation
from .models import ProjectInputs, ProjectResults


@dataclass(frozen=True)
class DevAndSellResult:
    """`buyer_equity_irr_at_dsa_only` : le TRI equity reel de l'acheteur s'il ne
    payait que le DSA (avant SPA) - un diagnostic, pas une valeur affichee comme
    le prix. `result_at_dsa_only` : le detail annuel complet a ce stade (DSA deja
    inclus dans le CAPEX finance), utile pour les onglets Cashflow/Risk Dashboard
    existants sans recalcul. `devex_keur`/`net_margin_keur` : cout de
    developpement reel de QEF et marge nette (`TSP - DEVEX`) - distinct de TSP
    (le revenu brut/prix percu), jamais affiche a la place de TSP (voir
    CONTEXT.md "TSP")."""

    dsa_keur: float
    spa_keur: float
    tsp_keur: float
    buyer_equity_irr_at_dsa_only: float | None
    result_at_dsa_only: ProjectResults
    devex_keur: float = 0.0
    net_margin_keur: float = 0.0


def _inputs_with_extra_capex(inputs: ProjectInputs, extra_capex_keur: float) -> ProjectInputs:
    """Ajoute `extra_capex_keur` (montant positif) a la 1ere annee de sortie CAPEX
    de la serie - fait rejoindre le DSA a l'assiette de financement geree, comme
    les ajouts DSRA/frais de financement deja geres pour le CAPEX (docs/adr/0001,
    docs/adr/0004) : le DSA est finance par emprunt exactement comme le CAPEX."""
    capex_keur = list(inputs.capex_keur)
    first_capex_index = next((i for i, c in enumerate(capex_keur) if c < 0), None)
    if first_capex_index is None:
        raise ValueError("Pas de sortie CAPEX dans la serie - impossible d'y ajouter le DSA.")
    capex_keur[first_capex_index] -= extra_capex_keur
    net_cashflow_keur = [
        c + o + t + r + e
        for c, o, t, r, e in zip(
            capex_keur,
            inputs.opex_keur,
            inputs.turpe_keur,
            inputs.revenues_keur,
            inputs.end_of_life_keur,
            strict=True,
        )
    ]
    return replace(inputs, capex_keur=capex_keur, net_cashflow_keur=net_cashflow_keur)


def compute_dev_and_sell(
    inputs: ProjectInputs,
    *,
    dsa_keur: float,
    buyer_target_equity_irr: float,
    devex_keur: float = 0.0,
    financing_kwargs: dict | None = None,
) -> DevAndSellResult:
    """Developper & vendre au RtB. DSA fixe + SPA resolu (docs/adr/0004) : le DSA
    rejoint l'assiette CAPEX (geree comme le reste), le SPA est le complement de
    prix qui ramene le TRI equity reel de l'acheteur exactement a sa cible - meme
    calcul que `acquisition.compute_acquisition_valuation`, applique a des
    cashflows qui incluent deja le DSA. `TSP = DSA + SPA` peut rester positif
    meme si SPA est negatif (DSA trop eleve pour la rentabilite du projet) -
    toujours afficher les deux composantes separement, jamais seulement TSP.
    `devex_keur` (cout de developpement reel de QEF, optionnel) donne
    `net_margin_keur = TSP - DEVEX` - le profit reel de QEF, distinct du revenu
    brut TSP."""
    inputs_with_dsa = _inputs_with_extra_capex(inputs, dsa_keur)
    result = financial_engine.compute_results(inputs_with_dsa, **(financing_kwargs or {}))
    valuation = compute_acquisition_valuation(result, buyer_target_equity_irr)
    spa_keur = valuation.max_acquisition_premium_keur
    tsp_keur = dsa_keur + spa_keur
    return DevAndSellResult(
        dsa_keur=dsa_keur,
        spa_keur=spa_keur,
        tsp_keur=tsp_keur,
        buyer_equity_irr_at_dsa_only=result.equity_irr,
        result_at_dsa_only=result,
        devex_keur=devex_keur,
        net_margin_keur=tsp_keur - devex_keur,
    )


def compute_hold_and_operate(
    inputs: ProjectInputs, *, financing_kwargs: dict | None = None
) -> ProjectResults:
    """Garder & exploiter : le moteur actuel, sans changement - TRI projet, TRI
    equity, NPV sur la duree d'exploitation."""
    return financial_engine.compute_results(inputs, **(financing_kwargs or {}))


def compute_cod_resale_value_keur(inputs: ProjectInputs, *, resale_target_irr: float) -> float:
    """Valeur de revente au COD (docs/adr/0002, version amendee) = PV des
    cashflows non-levérisés post-COD (revenue+opex+turpe+eol des seules annees
    d'exploitation, la construction est deja payee) actualises au TRI cible de
    l'acheteur a la revente. Pas de dette re-dimensionnee (voir l'ADR pour la
    raison : le mode "dscr" existant plafonne le principal par une assiette liee
    au CAPEX, qui vaut 0 une fois l'actif construit)."""
    post_cod_cfads = [
        revenue + opex + turpe + eol
        for capex, revenue, opex, turpe, eol in zip(
            inputs.capex_keur,
            inputs.revenues_keur,
            inputs.opex_keur,
            inputs.turpe_keur,
            inputs.end_of_life_keur,
            strict=True,
        )
        if capex == 0.0
    ]
    return financial_engine.present_value(post_cod_cfads, resale_target_irr)


@dataclass(frozen=True)
class BuildAndFlipResult:
    rtb_price_keur: float  # cf. DevAndSellResult.tsp_keur, cote acheteur = QEF cette fois
    construction_capex_keur: float
    carry_cost_keur: float
    resale_value_cod_keur: float
    net_return_keur: float


def compute_build_and_flip(
    inputs: ProjectInputs,
    *,
    dsa_keur: float,
    buyer_target_equity_irr_at_rtb: float,
    resale_target_irr: float,
    carry_months: int,
    carry_rate: float,
    financing_kwargs: dict | None = None,
) -> BuildAndFlipResult:
    """Racheter RtB & vendre au COD. QEF paie le prix RtB (meme calcul que
    `compute_dev_and_sell`, cote acheteur = QEF cette fois), finance la
    construction, revend au COD. Rendement = valeur de revente - prix d'achat RtB
    - CAPEX construction - cout de portage (interets composes sur le capital
    immobilise entre l'achat RtB et le COD, `carry_months` = 18 par defaut - voir
    docs/specs/aur_v2_methodology.md section 3.3/3.4)."""
    dev_sell = compute_dev_and_sell(
        inputs,
        dsa_keur=dsa_keur,
        buyer_target_equity_irr=buyer_target_equity_irr_at_rtb,
        financing_kwargs=financing_kwargs,
    )
    rtb_price = dev_sell.tsp_keur
    construction_capex = inputs.capex_initial_keur
    carry_base = rtb_price + construction_capex
    carry_cost = carry_base * ((1 + carry_rate) ** (carry_months / 12) - 1)
    resale_value = compute_cod_resale_value_keur(inputs, resale_target_irr=resale_target_irr)
    net_return = resale_value - rtb_price - construction_capex - carry_cost
    return BuildAndFlipResult(
        rtb_price_keur=rtb_price,
        construction_capex_keur=construction_capex,
        carry_cost_keur=carry_cost,
        resale_value_cod_keur=resale_value,
        net_return_keur=net_return,
    )
