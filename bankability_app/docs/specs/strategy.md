# `core/strategy.py` — les 3 stratégies

## Objectif

Exprimer les trois façons dont QEnergy gagne de l'argent sur un même projet (développer & vendre
au RtB / garder & exploiter / racheter RtB & vendre au COD) comme trois lectures du même moteur
financier — voir `docs/specs/aur_v2_methodology.md` section 3, `docs/adr/0002` et
`docs/adr/0004`.

## Décisions

- **DSA rejoint le CAPEX de la série d'inputs directement** (`_inputs_with_extra_capex`), plutôt
  que d'étendre `financial_engine.py` avec un nouveau paramètre `dsa_keur`. Le DSA doit être
  financé par emprunt exactement comme le CAPEX (docs/adr/0004) — l'ajouter à la 1ère sortie CAPEX
  de la série fait automatiquement transiter tout le mécanisme de gearing/DSCR déjà existant sans
  toucher `financial_engine.py`. Limite acceptée : si un projet a une repowering CAPEX (2ᵉ sortie),
  le DSA rejoint uniquement la **1ère** sortie (tranche initiale), jamais la tranche repowering —
  cohérent avec le sens de la stratégie 1 (DSA payé à l'acquisition initiale, pas au repowering).
- **SPA réutilise `acquisition.compute_acquisition_valuation` sans modification** — même calcul
  NPV-à-TRI-cible, appliqué à des cashflows equity qui incluent déjà le DSA. Validé de bout en
  bout dans `tests/test_strategy.py` (`test_dev_and_sell_spa_brings_actual_equity_irr_exactly_to_target`) :
  soustraire le SPA calculé du cashflow equity de l'année 0 fait retomber le TRI réellement
  réalisé exactement sur le TRI cible, par construction — pas une approximation.
- **Valeur de revente au COD sans dette re-dimensionnée** (docs/adr/0002, amendé avant
  implémentation) : PV des cashflows non-levérisés post-COD au TRI cible de l'acheteur à la
  revente, plutôt qu'un re-run de `financial_engine` en mode "dscr" (qui plafonne le principal par
  une assiette liée au CAPEX — nulle une fois l'actif construit, ce qui aurait annulé toute dette).
  Sous-estime donc la valeur réelle (pas de surcroît de valeur par effet de levier) — documenté
  comme limite, pas masqué.
- **Coût de portage en intérêts composés simples** sur `prix RtB + CAPEX construction`, capitalisés
  sur `carry_months/12` années au taux `carry_rate` fourni par l'appelant — pas de tirage
  échelonné mois par mois (comme `capitalized_construction_interest` le fait pour la dette de
  construction dans `financial_engine.py`) : simplification acceptée pour cette 1ère version, la
  base de calcul (prix RtB + CAPEX, pas juste le CAPEX) restant le choix le plus défendable en
  l'absence d'un échéancier de tirage détaillé.

- **`devex_keur` optionnel (défaut 0.0)** sur `compute_dev_and_sell`, donne
  `net_margin_keur = TSP - DEVEX` — distinct de TSP (revenu brut), jamais affiché à sa place. Le
  DEVEX est forfaitaire par classe de tension (150 k€ HTA / 300 k€ HTB1-2-3, confirmé
  2026-09-17 — voir `aur_cases.devex_keur_for_tension`), pas un taux par MW : ce sont des coûts
  largement fixes (raccordement, permitting, foncier), pas proportionnels à la puissance.
  `compute_build_and_flip` ne passe **pas** de DEVEX à son appel interne de
  `compute_dev_and_sell` : dans cette stratégie QEF est l'**acheteur** du RtB (paie DSA+SPA), pas
  le développeur — DEVEX ne s'applique qu'à la stratégie 1.

## Questions ouvertes

- Le DSA a un défaut (`aur_cases.dsa_default_keur`, câblé dans `portfolio.py`, pas dans
  `strategy.py` lui-même qui reste agnostique de la source du paramètre) — voir
  `docs/specs/portfolio.md` pour l'historique des deux corrections du 2026-09-18 (d'abord un défaut
  manquant faisait retomber DSA à 0, puis le 1ᵉʳ défaut ajouté ignorait le DEVEX). Défaut final,
  confirmé : `marge de dev cible(durée) x MW + DEVEX` — 50 k€/MW en 2h, 80 k€/MW en 4h.
- `compute_build_and_flip` ne modélise pas de dette pendant la construction (le "coût de portage"
  est un forfait composé, pas un tirage de dette de construction avec intérêts intercalaires
  capitalisés comme le reste du moteur) — cohérent avec la décision ci-dessus, à revisiter si la
  précision devient un point bloquant.
