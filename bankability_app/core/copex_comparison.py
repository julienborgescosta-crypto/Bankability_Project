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
Insurance construction ; Aurora a 5 lignes forfaitaires en €/kW) - **meme
type de piege de perimetre que la macro VBA**, signale par l'utilisateur le
2026-09-30 : le "Grid connection" d'Aurora couvrirait l'ensemble du cout de
raccordement **y compris le poste de livraison/sous-station privee** (HV
Transformer/HV substation/MV substation), la ou notre ICP les compte a part,
dans le total "construction".

**Attention, verifie le 2026-10-01 : ce n'est PAS un ajustement qui reduit
l'ecart.** Une fois les couts de sous-station ICP (reels, souvent
substantiels sur HTB1/HTB2 - HV Transformer 25-30 k€/MW, HV substation
3.9-4.5 M€ forfait, MV substation 18 k€/MW) ajoutes au raccordement PTF,
l'ecart avec le "Grid connection" d'Aurora (qui reste une ligne forfaitaire
generique, ~3-5 M€ tout compris) **s'aggrave** au lieu de se resorber sur
HTB1/HTB2 - preuve que soit Aurora sous-estime largement ce poste dans son
propre referentiel, soit l'hypothese "meme perimetre" ne tient pas non plus
completement. Plutot que de choisir une seule lecture, ce module affiche les
**3 vues cote a cote** (raccordement PTF seul, sous-station privee seule,
combine) pour que l'utilisateur juge lui-meme laquelle est pertinente pour
son cas plutot que de faire confiance a une hypothese non confirmee :

- **Core equipment** (Battery+PCS+Electrical/Civil works+Communication+
  Integration, hors sous-stations et hors raccordement) : ICP = postes
  directs x (1+marge EPC) x (1+assurance construction) ; Aurora = somme des
  4 lignes `CAPEX_LINE_ITEMS` correspondantes (Battery system+Inverter+
  Balance of system+EPC soft costs).
- **Grid connection (PTF only)** : raccordement seul, comparable directement
  UNIQUEMENT si `connection_capex_mode="library"` (sinon le projet n'utilise
  pas cette valeur, `comparable=False`).
- **Private substation** : cout ICP des 3 postes HV/MV substation seuls
  (charges de la meme marge EPC + assurance construction que le reste de la
  construction) - pas de ligne Aurora equivalente isolable, affiche pour
  information (`comparable=False`), jamais comme un ecart a interpreter.
- **Grid connection & substations (combined)** : somme des 2 lignes
  precedentes vs Aurora "Grid connection" - la lecture qui SUPPOSE que
  l'hypothese de perimetre elargi d'Aurora est correcte ; a confirmer avant
  de la considerer comme la comparaison de reference.
- **OPEX O&M** : ICP O&M + Guarantees/15 ans annualisees (poste ICP sans
  equivalent Aurora, note explicitement) vs Aurora "Fixed O&M" seul.
- **TOTAL CAPEX/OPEX** : la vraie somme appliquee par le moteur (mode
  "library") vs la somme Aurora pure equivalente - la ligne a regarder en
  priorite. Le total ne depend pas de la repartition core/grid/substation -
  seule la lecture poste par poste change.

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
    _DIRECT_CAPEX_LABELS,
    _OM_LABEL,
    TENSION_TO_ICP_SEGMENT,
    IcpCostLibrary,
    _icp_line_item_keur,
    icp_battery_pcs_keur,
    icp_connection_capex_keur,
    icp_opex_guarantees_annualized_keur,
)
from .dev_case import (
    CAPEX_GRID_CONNECTION_LABEL,
    CopexLibrary,
    _connection_cost_from_distance,
    escalated_unit_cost,
    voltage_duration_key,
)

# Les 4 lignes Aurora du meme perimetre que le bucket ICP "core equipment"
# (poste direct x marge EPC x assurance, hors sous-stations) - Development
# est toujours = Aurora des 2 cotes, affiche a part (voir module docstring).
_CAPEX_CORE_LABELS = ["Battery system", "Inverter", "Balance of system", "EPC soft costs"]
_CAPEX_DEVELOPMENT_LABEL = "Development"
# Postes ICP a reallouer du bucket "construction" vers "Grid connection" -
# Aurora compte le poste de livraison/sous-station privee dans son "Grid
# connection", nous les comptions avec le reste de la construction (voir
# module docstring).
_ICP_SUBSTATION_LABELS = ["HV Transformer", "HV substation", "MV substation"]
_ICP_CORE_LABELS = [label for label in _DIRECT_CAPEX_LABELS if label not in _ICP_SUBSTATION_LABELS]
_OPEX_FIXED_OM_LABEL = "Fixed O&M"
_OPEX_LAND_LEASE_LABEL = "Land lease"
# "Land lease" sorti de cette liste (2026-10-01) : seul poste OPEX challengeable
# individuellement (`land_lease_opex_keur`), il a sa propre ligne comparable -
# voir compare_capex_opex.
_OPEX_INFO_ONLY_LABELS = ["Insurance", "Grid charges", "Accise", "Other"]

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


def _icp_core_and_substation_keur(
    icp_library: IcpCostLibrary, *, segment: str, duree_h: int, cod_year: int, power_mw: float
) -> tuple[float, float, list[str]]:
    """Scinde le total ICP "construction" (voir `copex_icp.icp_capex_total_keur`)
    en (core equipment, sous-stations HV/MV) - meme marge EPC + assurance
    construction appliquee aux 2, seule la repartition des postes directs
    change (voir module docstring)."""
    missing: list[str] = []

    def _sum(labels: list[str]) -> float:
        total = 0.0
        for label in labels:
            item_cost = _icp_line_item_keur(
                icp_library, label, segment, power_mw=power_mw, duree_h=duree_h, cod_year=cod_year
            )
            if item_cost is None:
                missing.append(label)
                continue
            total += item_cost
        return total

    core_direct_keur = _sum(_ICP_CORE_LABELS) + icp_battery_pcs_keur(
        icp_library, duree_h=duree_h, power_mw=power_mw, cod_year=cod_year
    )
    substation_direct_keur = _sum(_ICP_SUBSTATION_LABELS)

    epc_margin = icp_library.epc_margin_pct.get(segment, 0.0)
    insurance_pct = icp_library.insurance_construction_pct.get(segment, 0.0)
    factor = (1 + epc_margin) * (1 + insurance_pct)
    return core_direct_keur * factor, substation_direct_keur * factor, missing


def compare_capex_opex(
    *,
    tension: str,
    duree_h: int,
    cod_year: int,
    power_mw: float,
    icp_library: IcpCostLibrary,
    aurora_library: CopexLibrary,
    connection_capex_mode: str = "library",
    manual_connection_capex_keur: float = 0.0,
    distance_rte_km: float = 0.0,
    land_lease_opex_keur: float = 0.0,
) -> CopexComparison:
    """CAPEX/OPEX initial (hors repowering, voir module docstring) : nos
    valeurs (ICP + repli Aurora, mode raccordement "library") vs les memes
    postes lus uniquement dans `COPEX_library`.

    `manual_connection_capex_keur`/`distance_rte_km` : valeur reellement
    appliquee au projet quand `connection_capex_mode` n'est pas "library"
    (mirroring `portfolio.ProjectConfig`) - corrige un bug signale par
    l'utilisateur le 2026-10-01 : la ligne "Grid connection (PTF only)"
    affichait TOUJOURS l'estimation ICP bibliotheque (ex. 4 162 k€), meme
    pour un projet en mode "manual" avec un raccordement reel de 17 k€ - le
    nombre affiche dans la colonne "Ours" ne correspondait donc pas a ce que
    le moteur appliquait reellement a ce projet (uniquement marque
    `comparable=False`, pas corrige dans la valeur elle-meme).

    `land_lease_opex_keur` : meme type de correction, meme jour - l'ajout
    manuel de loyer foncier du projet n'etait pas du tout repris ici : la
    ligne OPEX info-only incluait "Land lease" mais avec la MEME valeur
    Aurora des 2 cotes, donc un projet avec par exemple 300 k€/an de loyer
    manuel ressortait avec un OPEX "Ours" identique a Aurora - aucune trace
    du loyer saisi. "Land lease" a sa propre ligne desormais (`ours =
    land_lease_opex_keur si renseigne, sinon l'estimation Aurora` - REMPLACE,
    ne s'ajoute plus, corrige un 2e bug le meme jour dans
    `aur_cases.capex_and_opex_keur` ou l'override s'ajoutait a l'estimation
    Aurora au lieu de la remplacer, voir `_opex_with_land_lease_override`),
    sortie du groupe "Info only" (Insurance/Grid charges/Accise/Other, eux
    toujours non challengeables individuellement, restent groupes)."""
    key = voltage_duration_key(tension, duree_h)
    notes: list[str] = []
    segment = TENSION_TO_ICP_SEGMENT.get(tension)

    development_keur = _aurora_capex_item_keur(
        aurora_library, key, _CAPEX_DEVELOPMENT_LABEL, cod_year, power_mw
    )
    aurora_core_keur = sum(
        _aurora_capex_item_keur(aurora_library, key, label, cod_year, power_mw)
        for label in _CAPEX_CORE_LABELS
    )
    aurora_grid_keur = _aurora_capex_item_keur(
        aurora_library, key, CAPEX_GRID_CONNECTION_LABEL, cod_year, power_mw
    )

    ours_grid_library_keur, grid_source_notes = icp_connection_capex_keur(
        tension=tension,
        duree_h=duree_h,
        cod_year=cod_year,
        power_mw=power_mw,
        icp_library=icp_library,
        aurora_library=aurora_library,
    )
    if connection_capex_mode == "manual":
        ours_grid_only_keur = manual_connection_capex_keur
    elif connection_capex_mode == "distance_rte":
        ours_grid_only_keur = _connection_cost_from_distance(distance_rte_km)
    elif connection_capex_mode == "library":
        ours_grid_only_keur = ours_grid_library_keur
    else:
        raise ValueError(
            f"Unknown connection_capex_mode '{connection_capex_mode}' "
            "(expected 'library', 'manual' or 'distance_rte')."
        )
    if segment is not None:
        ours_core_keur, substation_keur, missing = _icp_core_and_substation_keur(
            icp_library, segment=segment, duree_h=duree_h, cod_year=cod_year, power_mw=power_mw
        )
        if missing:
            notes.append(
                f"ICP items missing for {segment} (Aurora fallback folded into the totals only): "
                f"{', '.join(missing)}."
            )
    else:
        # HTB3 : aucune colonne ICP - tout retombe sur Aurora, comme avant
        # (voir icp_capex_total_keur), donc pas de signal sur ce bucket non plus.
        ours_core_keur = aurora_core_keur
        substation_keur = 0.0
    ours_grid_and_substation_keur = ours_grid_only_keur + substation_keur

    grid_comparable = connection_capex_mode == "library"
    if not grid_comparable:
        notes.append(
            f"Grid connection: project uses connection_capex_mode='{connection_capex_mode}' - "
            f"the value shown ({ours_grid_only_keur:,.0f} k€) is this project's actual applied "
            f"connection cost, not Aurora's library estimate (which would be "
            f"{ours_grid_library_keur:,.0f} k€ at this tension/duration/power if the project "
            "used library mode) - still marked 'Info only' since it isn't sourced the same way "
            "as Aurora's generic €/kW assumption."
        )
    else:
        notes.extend(grid_source_notes)
    notes.append(
        "Aurora's own 'Grid connection' line is assumed to cover the private substation too "
        "(not just the grid operator's connection fee) - shown 3 ways below (PTF alone, "
        "substation alone, combined) so you can judge which reading is the fair comparison for "
        "your case rather than trusting one assumption blindly."
    )

    capex_rows = [
        CopexComparisonRow(
            "Core equipment (Battery+PCS+electrical/civil works+comms+integration)",
            ours_core_keur,
            aurora_core_keur,
            True,
        ),
        CopexComparisonRow("Development", development_keur, development_keur, False),
        CopexComparisonRow(
            "Grid connection (PTF only)", ours_grid_only_keur, aurora_grid_keur, grid_comparable
        ),
        CopexComparisonRow(
            "Private substation (ICP HV/MV Transformer+substation - no separate Aurora line)",
            substation_keur,
            0.0,
            False,
        ),
        CopexComparisonRow(
            "Grid connection & substations (combined - assumes Aurora's scope includes it)",
            ours_grid_and_substation_keur,
            aurora_grid_keur,
            grid_comparable,
        ),
        CopexComparisonRow(
            "TOTAL CAPEX",
            ours_core_keur + development_keur + ours_grid_and_substation_keur,
            aurora_core_keur + development_keur + aurora_grid_keur,
            True,
        ),
    ]

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

    aurora_land_lease_keur = _aurora_opex_item_keur(
        aurora_library, key, _OPEX_LAND_LEASE_LABEL, cod_year, power_mw
    )
    ours_land_lease_keur = land_lease_opex_keur if land_lease_opex_keur else aurora_land_lease_keur
    if land_lease_opex_keur:
        notes.append(
            f"Land lease: project uses a manual {land_lease_opex_keur:,.0f} k€/yr instead of "
            f"Aurora's library estimate ({aurora_land_lease_keur:,.0f} k€/yr) - same convention "
            "as aur_cases.capex_and_opex_keur (replaced, not added)."
        )

    info_total_keur = sum(
        _aurora_opex_item_keur(aurora_library, key, label, cod_year, power_mw)
        for label in _OPEX_INFO_ONLY_LABELS
    )
    ours_total_opex = ours_om_keur + ours_land_lease_keur + info_total_keur
    aurora_total_opex = aurora_om_keur + aurora_land_lease_keur + info_total_keur

    opex_rows = [
        CopexComparisonRow("Fixed O&M (+ ICP Guarantees)", ours_om_keur, aurora_om_keur, True),
        CopexComparisonRow(
            "Land lease (+ manual override)", ours_land_lease_keur, aurora_land_lease_keur, True
        ),
        CopexComparisonRow(
            "Insurance + Grid charges (TURPE fixed part + CTA) + Accise + Other",
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
