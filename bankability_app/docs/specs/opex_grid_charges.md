# `core/opex_grid_charges.py` — TURPE Power + CTA + Accise (postes "Autres OPEX" du BP réel)

## Objectif

Depuis le 2026-10-08, trois postes OPEX du BP réel (`081026_BP_Stockage_Standalone__.xlsm`,
onglets `I-Fixed`/`C-SPV`) — **TURPE Power** (frais réseau fixe + variable par tension), **CTA**
(contribution tarifaire d'acheminement, % de TURPE Power) et **Accise sur l'électricité** (taxe,
base auxiliaires + pertes de stockage) — sont calculés par une formule précise plutôt que lus
depuis l'estimation générique Aurora `COPEX_library` ("Grid charges"/"Accise", voir
`docs/specs/copex_icp.md`). Demande de l'utilisateur : *"il faut inclure les Autres OPEX inclus
dans le BP: TURPE variable, ACCISE sur les auxiliaires, loyer, taxes..."*.

## Décisions

- **Scope exact confirmé par l'utilisateur, 2026-10-08** (3 questions posées, toutes tranchées) :
  1. **"TURPE variable" = "TURPE Power - Variable fee"** (k€/MW par tension, table `I-Fixed`),
     PAS "TURPE Energy" (qui dépend d'une grille tarifaire CRE externe, "tariff_TURPE 7 - HTB1
     Pointe Fixe CU...", non disponible) — "le TURPE Energy tu l'as avec Aurora" : déjà couvert
     par la courbe `AU_Store!TURPE` existante (impact du TURPE sur le revenu de marché, lue par
     `aur_cases.revenue_and_turpe_series`), pas un nouveau poste OPEX.
  2. **Volumes de l'Accise sourcés depuis Aurora** (pas une approximation à ratio constant) : le
     volume d'énergie chargée depuis le réseau (pour les pertes) vient de 8 courbes de référence
     Aurora Flexplorer (1 par duree_h×tension), voir ci-dessous.
  3. **Mapping `TENSION_TO_ICP_SEGMENT` inchangé** malgré un libellé contradictoire dans une
     version intermédiaire de la COPEX Library (voir `docs/specs/copex_icp.md`, "Décisions").
- **Loyer foncier** : déjà couvert par `ProjectConfig.land_lease_opex_keur` (existant depuis
  2026-09-23) — aucun nouveau code.
- **Taxes locales (TFPB/CFE/taxe d'aménagement)** : `ProjectConfig.local_taxes_opex_keur`,
  purement additif (pas de ligne bibliothèque à remplacer, contrairement au loyer foncier) — ces
  taxes dépendent de taux communaux saisis à la main dans le BP (tous à 0 dans l'exemple fourni),
  aucune formule générique possible. Appliqué directement dans `portfolio.build_project_inputs`
  (pas dans `aur_cases.py` : pas de ligne Aurora à isoler/remplacer, inutile de threader un
  paramètre de plus à travers `capex_and_opex_keur`).
- **TURPE Power** : `fixed_fee_keur[tension] + variable_fee_keur_per_mw[tension] × power_mw`,
  escaladé (voir ci-dessous). Table exacte (`I-Fixed!E74:E82`) dans
  `config/aur_opex_grid_charges.yaml`.
- **CTA = taux × TURPE Power TOTAL** (fixe + variable), pas juste la part fixe au sens strict du
  terme — vérifié exactement contre le BP (`C-SPV` : 0,05 × 14 123,575 k€ = 706,179 k€). "TURPE
  Power" est conventionnellement appelé "la part fixe du TURPE" dans le vocabulaire régulé
  français (par opposition à "TURPE Energy", la part variable/consommation) même s'il a lui-même
  une composante au MW. Taux : 5 % DSO (HTA) / 15 % TSO (HTB1/2/3) — `I-Fixed!G86:G87`.
- **Accise = (auxiliaires + pertes) × 26,35 €/MWh réel**, escaladée :
  - Auxiliaires (MWh) = `0,025 × power_mw × duree_h` (ratio fixe, `I-Project!E105` — pas besoin
    de courbe Aurora, c'est une fraction du nameplate du projet).
  - Pertes (MWh) = volume chargé depuis le réseau × (1 − rendement aller-retour 86 %, donné par
    l'utilisateur). Le volume chargé vient de **8 courbes de référence Aurora Flexplorer**
    (`config/aur_charge_volume.yaml`, scénario `FLEX FRA 26 Q2 Central`, cas "standalone, Central,
    2027, Undegraded, standard, no curtailment", somme des volumes direction "imp" tous marchés) —
    **1 seule courbe par (durée, tension)**, réutilisée pour toutes les variantes TURPE/gabarit/ORO
    de cette tension/durée (hypothèse : le volume de cyclage ne dépend pas du type TURPE,
    contrairement au revenu). Même méthode d'extraction que pour l'ORO (voir
    `docs/specs/aur_cases.md`), fetchée via `flexplorer_get_scenario`/`get_download_url`.
  - Recalcul de contrôle sur le BP réel : rendement recalculé ≈ 85,0 % (82 300,69 MWh pertes /
    547 923,89 MWh chargés), proche mais pas identique aux 86 % donnés par l'utilisateur — la
    valeur donnée est retenue (pas le recalcul cas-par-cas, voir "Questions ouvertes").
- **Remplace, n'ajoute pas, les lignes Aurora "Grid charges"/"Accise"** (`aur_cases.
  _opex_with_grid_charges`) — ces 2 libellés étaient déjà sommés dans `OPEX_LINE_ITEMS` comme
  repli générique Aurora pour les postes qu'ICP ne couvre pas (voir `docs/specs/copex_icp.md`) ;
  les additionner par-dessus aurait compté ces postes deux fois. Même principe que
  `_opex_with_land_lease_override`.
- **S'applique uniquement à `capex_and_opex_keur` (source ICP, le chemin par défaut), PAS à
  `capex_and_opex_keur_aurora_only`** (option "Use Aurora's own CAPEX/OPEX assumptions") :
  ce 2ᵉ chemin sert spécifiquement à comparer "coûts 100 % Aurora" vs "nos coûts réels" — y
  injecter notre calcul précis le rendrait hybride et casserait sa valeur de comparaison pure. Il
  garde donc la ligne Aurora générique "Grid charges"/"Accise" inchangée, y compris pour
  l'abattement TURPE 50 % (`_opex_with_turpe_50pct_reduction_aurora_only`, qui réduit la ligne
  Aurora brute plutôt que notre calcul précis).
- **Escalade : table ICP "Forecast price factor" réutilisée comme proxy de l'IPC du BP**, pas la
  vraie série IPC du BP source. Le BP indexe ces 3 postes sur l'IPC (`I-Fixed`/`C-SPV`,
  "Indexation factor - Operating taxes" = IPC), une série annuelle propre non fournie comme table
  plate exploitable (contrairement à la "Forecast price factor" de la COPEX Library, déjà utilisée
  pour tout le reste). Reconnu explicitement comme une approximation (voir "Questions ouvertes").
  Référence : ligne "OPEX - O&M (annual cost)" de la COPEX Library (générique, pas liée à une
  techno spécifique, contrairement à "Batteries and PCS" qui décline avec la courbe d'apprentissage
  technologique).
- **`copex_icp.icp_escalation_factor` rendue publique** (ex-`_icp_escalation_factor`) pour être
  réutilisée ici sans dupliquer la logique de plafonnement NTP.

## Fichiers

- `config/aur_opex_grid_charges.yaml` — tables TURPE Power/CTA/Accise/Auxiliaires (constantes du
  BP réel, pas mises à jour mensuellement comme ICP — à revoir si le BP change ces tarifs).
- `config/aur_charge_volume.yaml` — 8 courbes de volume chargé (MWh/MW/an, par année civile),
  source Aurora Flexplorer.

## Questions ouvertes

- **Escalade IPC approximée par la table ICP**, pas la vraie série du BP — voir ci-dessus. Écart
  non quantifié (pas de série IPC isolée disponible pour comparer).
- **Rendement aller-retour 86 % (donné) vs ~85,0 % (recalculé sur un cas réel du BP)** — écart
  faible mais pas nul, pas d'explication trouvée (arrondis, ou une définition légèrement
  différente du rendement selon la source).
- **`core/copex_comparison.py` ("Aurora COPEX Comparison" du Configurateur) ne reflète toujours pas
  ce calcul précis pour Grid charges/Accise** : son tableau les affiche comme postes "Info only"
  sourcés d'Aurora pur des 2 côtés, pas le calcul précis `opex_grid_charges` — cohérent avec le fait
  que ce tableau compare justement "Aurora pur" vs "nos coûts", mais la colonne "nos coûts" de ces 2
  lignes spécifiques n'a pas été mise à jour pour inclure le nouveau calcul. Le total OPEX réellement
  utilisé par le moteur (`aur_cases.capex_and_opex_keur`) est correct ; seul cet écran de
  comparaison détaillé poste-par-poste est en retard sur ces 2 postes précis. Par contraste,
  Insurance (operation)/Other/Asset Management (construction et operation) — les 3 autres postes
  qui ne venaient plus d'Aurora depuis le 2026-10-08, voir `docs/specs/copex_icp.md` "V2 bis" —
  ont bien chacun leur propre ligne ICP dans ce tableau (plus "toujours = Aurora").
- **Coût d'achat de l'énergie consommée par les auxiliaires** (`C-SPV!E358`, au prix moyen
  Day-Ahead de l'année) n'est pas modélisé — hors périmètre de la demande du 2026-10-08, qui ne
  portait que sur la taxe Accise, pas sur ce coût d'achat séparé.
- **OPEX reste plat par année** (convention déjà en place pour tout le reste du moteur, voir
  `aur_cases.opex_series_keur`) : TURPE Power/CTA/Accise sont calculés à l'année de COD puis
  appliqués identiquement chaque année, alors que le volume chargé réel varie dans le temps
  (dégradation, cyclage) - même simplification que partout ailleurs dans l'engine, pas une
  nouvelle limite propre à ce poste.
