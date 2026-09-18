# `core/contract_overlay.py` — overlays contractuels (floor / tolling)

## Objectif

Ajuster la série de revenu merchant selon la structure contractuelle du projet (full merchant /
floor / tolling) et dériver la cible DSCR + la maturité de dette qui en découlent (tiering
sécurisé/merchant, maturité PPA+3) — voir `docs/specs/aur_v2_methodology.md` section 2.2 et
`CONTEXT.md`.

## Décisions

- **Le tolling remplace le revenu, le floor le plafonne en bas.** Pendant la durée du contrat, la
  tolling paie un prix fixe indépendant du merchant (revenu = prix × puissance, intégralement
  sécurisé) ; le floor garantit un minimum (revenu = floor si le merchant est en dessous) et
  partage l'excédent au-dessus du floor avec l'agrégateur (`revenue_sharing_above_floor_pct`,
  I-Project!54) — l'excédent partagé reste au risque merchant, seul le floor lui-même est
  sécurisé. Au-delà de la durée du contrat, retour au merchant brut dans les deux cas.
- **Indépendant de `financial_engine.py`** : ce module ne modifie pas `compute_results` — il
  calcule `target_dscr`/`debt_tenor_years` à **passer tels quels** en paramètres (déjà acceptés
  génériquement par `compute_results(..., debt_sizing_mode="dscr")`). Pas de nouvelle abstraction
  dans le moteur pour une logique qui se réduit à "quelles valeurs lui donner en entrée".
- **Tiering DSCR par blend pondéré**, pas par sculpt séparé secured/merchant : `blended_target_dscr`
  calcule une moyenne pondérée par la part de revenu sécurisé sur toute la fenêtre considérée,
  puis ce chiffre unique est passé à `sculpt_debt_service` — même principe que
  `risk_rules.revenue_weighted_dscr_threshold` (qui pondère un seuil affiché), généralisé à une
  série annuelle plutôt qu'au `RevenueBreakdown` du BP réel. Un sculpt véritablement séparé par
  flux (dette secured + dette merchant comme deux tranches) serait plus rigoureux mais change
  l'architecture de `financial_engine.py` pour un gain non demandé par le brief — non fait.
- **Même blend réutilisé pour le TRI cible de l'acheteur au RtB** (`blended_buyer_target_equity_irr`,
  factorisé via `_secured_revenue_share` partagé avec `blended_target_dscr`) : un revenu sécurisé
  justifie un TRI cible plus bas (9 % provisoire vs 11 % confirmé merchant, voir
  `docs/specs/aur_v2_methodology.md` section 3.4) selon exactement la même logique que le
  tiering DSCR — pas une deuxième règle de pondération distincte à maintenir.

## Questions ouvertes

- Le partage de revenu au-dessus du floor (`revenue_sharing_above_floor_pct`) n'a été validé que
  sur l'unique exemple du fichier (40 %) — pas de deuxième point de données pour confirmer la
  formule `floor + (1 - part) x excédent` au-delà du raisonnement direct sur le libellé I-Project.
