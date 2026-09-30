"""Compare le CAPEX/OPEX effectivement applique par le moteur Aurora v2 (ICP
+ repli Aurora, voir `copex_icp.py`) a ce que la bibliotheque Aurora
`COPEX_library` aurait donne seule, poste par poste - demande de
l'utilisateur (2026-09-30), sur le modele d'une macro VBA equivalente deja
utilisee sur le vrai BP Excel (`ModAuroraComparison`, sections "ECARTS CAPEX
BP vs AURORA"/"ECARTS OPEX BP vs AURORA"). Objectif : voir si nos CAPEX/OPEX
sont en dessous ou au-dessus des hypotheses Aurora, poste par poste et au
total.

Difference avec la macro VBA source : celle-ci reconciliait 2 taxonomies de
bucket differentes (I-Project du BP vs `COPEX_library`), d'ou sa mise en
garde sur l'allocation HT/MT EPC/Grid qui se compense entre les 2 sources.
Ici, ICP (`copex_icp.py`) ne partage pas non plus la taxonomie d'Aurora (ICP
detaille Electrical works/Civil works/HV Transformer/.../EPC Margin/
Insurance construction ; Aurora a 5 lignes forfaitaires en €/kW) - la
comparaison se limite donc aux 2 niveaux ou les 2 sources sont clairement du
meme perimetre :

- **Construction CAPEX** (Battery+PCS+BoS+EPC soft costs, hors Development et
  hors raccordement) : ICP = poste direct x (1+marge EPC) x (1+assurance
  construction) ; Aurora = somme des 4 lignes `CAPEX_LINE_ITEMS` correspondantes
  (hors Development, qui est toujours = Aurora des 2 cotes, affiche a part).
- **Grid connection (raccordement)** : ligne dediee, comparable directement
  UNIQUEMENT si `connection_capex_mode="library"` (sinon le projet n'utilise
  pas cette valeur, `comparable=False`).
- **OPEX O&M** : ICP O&M + Guarantees/15 ans annualisees (poste ICP sans
  equivalent Aurora, note explicitement) vs Aurora "Fixed O&M" seul.
- **TOTAL CAPEX/OPEX** : la vraie somme appliquee par le moteur (mode
  "library") vs la somme Aurora pure equivalente - la ligne a regarder en
  priorite, les postes eclates servent a comprendre POURQUOI.

Les autres postes (CAPEX Development ; OPEX Insurance/Grid charges/Land
lease bibliotheque/Accise/Other) restent **toujours** = Aurora (ICP ne les
couvre pas) - affiches pour information (`comparable=False`), jamais comme
un ecart a interpreter (un ecart de 0% n'est pas un signal, c'est la meme
donnee des 2 cotes par construction).

Attention (meme mise en garde que la macro VBA source) : "Grid charges" ne
represente que la part FIXE du TURPE (+ CTA) - le TURPE VARIABLE (charge
reseau liee a l'energie) est modelise separement, cote revenu, par
`aur_cases.revenue_and_turpe_series` (colonne TURPE d'AU_Store, "Storage
volume-related network charges" - voir docs/specs/aur_cases.md). Pas de
double-compte entre les 2, mais aussi pas de rapprochement possible : ce
module ne couvre que le CAPEX/OPEX, jamais le TURPE variable revenu.

Limite connue : le repowering (2e tranche CAPEX) n'est pas couvert par cette
comparaison - seul le CAPEX/OPEX initial (a la COD) l'est. Voir
docs/specs/copex_comparison.md, "Questions ouvertes"."""

from __future__ import annotations

from dataclasses import dataclass

from .copex_icp import (
    _OM_LABEL,
    TENSION_TO_ICP_SEGMENT,
    IcpCostLibrary,
    _icp_line_item_keur,
    icp_capex_total_keur,
    icp_connection_capex_keur,
    icp_opex_guarantees_annualized_keur,
)
from .dev_case import (
    CAPEX_GRID_CONNECTION_LABEL,
    CopexLibrary,
    escalated_unit_cost,
    voltage_duration_key,
)

# Les 4 lignes Aurora du meme perimetre que le total ICP "construction"
# (poste direct x marge EPC x assurance) - Development est toujours = Aurora
# des 2 cotes, affiche a part (voir module docstring).
_CAPEX_CONSTRUCTION_LABELS = ["Battery system", "Inverter", "Balance of system", "EPC soft costs"]
_CAPEX_DEVELOPMENT_LABEL = "Development"
_OPEX_FIXED_OM_LABEL = "Fixed O&M"
_OPEX_INFO_ONLY_LABELS = ["Insurance", "Grid charges", "Land lease", "Accise", "Other"]

# Seuils de statut - meme esprit que la macro VBA source (OK / Vigilance /
# Ecart fort), pas une constante Aurora documentee ailleurs : choisis par
# analogie avec les seuils observes sur la capture d'ecran fournie par
# l'utilisateur (OK < 10%, Vigilance 10-20%, Ecart fort >= 20%).
_OK_THRESHOLD_PCT = 0.10
_WATCH_THRESHOLD_PCT = 0.20


@dataclass(frozen=True)
class CopexComparisonRow:
    label: str
    ours_keur: float
    aurora_keur: float
    # False = poste "info seulement" (ICP ne le couvre pas, ours == Aurora
    # par construction, ou le projet n'utilise pas ce mode) - jamais un
    # ecart a interpreter, meme si status() renvoie autre chose que OK.
    comparable: bool

    @property
    def delta_keur(self) -> float:
        return self.ours_keur - self.aurora_keur

    @property
    def delta_pct(self) -> float | None:
        if self.aurora_keur == 0:
            return None
        return self.delta_keur / abs(self.aurora_keur)

    @property
    def status(self) -> str:
        if not self.comparable:
            return "Info only"
        pct = self.delta_pct
        if pct is None:
            return "Info only" if self.ours_keur == 0 else "Large gap"
        pct = abs(pct)
        if pct < _OK_THRESHOLD_PCT:
            return "OK"
        if pct < _WATCH_THRESHOLD_PCT:
            return "Watch"
        return "Large gap"


@dataclass(frozen=True)
class CopexComparison:
    capex_rows: list[CopexComparisonRow]
    opex_rows: list[CopexComparisonRow]
    notes: list[str]


def _aurora_capex_item_keur(
    aurora_library: CopexLibrary, key: str, label: str, cod_year: int, power_mw: float
) -> float:
    unit_cost = aurora_library.capex_unit_costs.get(key, {}).get(label, 0.0)
    return (
        escalated_unit_cost(unit_cost, aurora_library.capex_escalation.get(label, {}), cod_year)
        * power_mw
    )


def _aurora_opex_item_keur(
    aurora_library: CopexLibrary, key: str, label: str, cod_year: int, power_mw: float
) -> float:
    unit_cost = aurora_library.opex_unit_costs.get(key, {}).get(label, 0.0)
    return (
        escalated_unit_cost(unit_cost, aurora_library.opex_escalation.get(label, {}), cod_year)
        * power_mw
    )


def compare_capex_opex(
    *,
    tension: str,
    duree_h: int,
    cod_year: int,
    power_mw: float,
    icp_library: IcpCostLibrary,
    aurora_library: CopexLibrary,
    connection_capex_mode: str = "library",
) -> CopexComparison:
    """CAPEX/OPEX initial (hors repowering, voir module docstring) : nos
    valeurs (ICP + repli Aurora, mode raccordement "library") vs les memes
    postes lus uniquement dans `COPEX_library`."""
    key = voltage_duration_key(tension, duree_h)
    notes: list[str] = []

    ours_total_capex, _ = icp_capex_total_keur(
        tension=tension,
        duree_h=duree_h,
        cod_year=cod_year,
        power_mw=power_mw,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    development_keur = _aurora_capex_item_keur(
        aurora_library, key, _CAPEX_DEVELOPMENT_LABEL, cod_year, power_mw
    )
    ours_construction_keur = ours_total_capex - development_keur
    aurora_construction_keur = sum(
        _aurora_capex_item_keur(aurora_library, key, label, cod_year, power_mw)
        for label in _CAPEX_CONSTRUCTION_LABELS
    )

    ours_grid_keur, grid_source_notes = icp_connection_capex_keur(
        tension=tension,
        duree_h=duree_h,
        cod_year=cod_year,
        power_mw=power_mw,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    aurora_grid_keur = _aurora_capex_item_keur(
        aurora_library, key, CAPEX_GRID_CONNECTION_LABEL, cod_year, power_mw
    )
    grid_comparable = connection_capex_mode == "library"
    if not grid_comparable:
        notes.append(
            f"Grid connection: project uses connection_capex_mode='{connection_capex_mode}', "
            "not the library value - comparison shown for reference only, not applied to this project."
        )
    notes.extend(grid_source_notes)

    capex_rows = [
        CopexComparisonRow(
            "Construction (Battery+PCS+BoS+EPC soft costs)",
            ours_construction_keur,
            aurora_construction_keur,
            True,
        ),
        CopexComparisonRow("Development", development_keur, development_keur, False),
        CopexComparisonRow("Grid connection", ours_grid_keur, aurora_grid_keur, grid_comparable),
        CopexComparisonRow(
            "TOTAL CAPEX",
            ours_construction_keur + development_keur + ours_grid_keur,
            aurora_construction_keur + development_keur + aurora_grid_keur,
            True,
        ),
    ]

    segment = TENSION_TO_ICP_SEGMENT.get(tension)
    om_icp = (
        _icp_line_item_keur(
            icp_library, _OM_LABEL, segment, power_mw=power_mw, duree_h=duree_h, cod_year=cod_year
        )
        if segment is not None
        else None
    )
    aurora_om_keur = _aurora_opex_item_keur(
        aurora_library, key, _OPEX_FIXED_OM_LABEL, cod_year, power_mw
    )
    guarantees_keur = (
        icp_opex_guarantees_annualized_keur(
            icp_library, duree_h=duree_h, power_mw=power_mw, cod_year=cod_year
        )
        if segment is not None
        else 0.0
    )
    ours_om_keur = (om_icp if om_icp is not None else aurora_om_keur) + guarantees_keur
    if guarantees_keur:
        notes.append(
            "OPEX O&M includes ICP 'Guarantees & preventive maintenance' (annualized over 15 "
            "years), a line item with no Aurora COPEX_library equivalent."
        )

    info_total_keur = sum(
        _aurora_opex_item_keur(aurora_library, key, label, cod_year, power_mw)
        for label in _OPEX_INFO_ONLY_LABELS
    )
    ours_total_opex = ours_om_keur + info_total_keur
    aurora_total_opex = aurora_om_keur + info_total_keur

    opex_rows = [
        CopexComparisonRow("Fixed O&M (+ ICP Guarantees)", ours_om_keur, aurora_om_keur, True),
        CopexComparisonRow(
            "Insurance + Grid charges (TURPE fixed part + CTA) + Land lease + Accise + Other",
            info_total_keur,
            info_total_keur,
            False,
        ),
        CopexComparisonRow("TOTAL OPEX", ours_total_opex, aurora_total_opex, True),
    ]
    notes.append(
        "Grid charges is Aurora's fixed TURPE + CTA component only - the variable TURPE "
        "(network charge on energy) is modeled separately on the revenue side "
        "(aur_cases.revenue_and_turpe_series), not covered here."
    )
    notes.append("Repowering CAPEX (2nd tranche) is not covered by this comparison.")

    return CopexComparison(capex_rows=capex_rows, opex_rows=opex_rows, notes=notes)
