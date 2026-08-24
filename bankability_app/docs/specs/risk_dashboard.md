# Risk Dashboard

Spec retrospective.

## Objectif

Repondre au "Risk Assessment Layer" de la methodologie de reference : generer automatiquement
des alertes (vert/orange/rouge) quand une metrique franchit un seuil bancaire usuel, plutot que
de laisser l'utilisateur relire des tableaux de chiffres pour reperer les problemes.

## Fichiers impactes

- `config/risk_thresholds.yaml` — seuils (source unique, pas de valeur en dur dans le code)
- `core/risk_rules.py` — `RiskFlag`, `evaluate_risks`, `load_thresholds`,
  `revenue_weighted_dscr_threshold`
- `core/models.py` — `RevenueBreakdown.contracted_keur`/`merchant_keur`
- `core/bp_parser.py` — `parse_full_bp` construit `ProjectInputs.revenue_detail` a partir des
  sous-lignes `PPA Revenues`/`Capacity market`/`Merchant revenues (net of energy costs)` de
  `O-Financials` (contracted = PPA + Capacity market, merchant = Merchant revenues)
- `ui/risk_tab.py` — affichage des flags via `st.error`/`st.warning`/`st.success`, plus le mix
  de revenu quand disponible

## Logique metier

Trois regles independantes, chacune produisant exactement un `RiskFlag` :

1. **DSCR min** : rouge si `< dscr_min_red` (1.10x, seuil generique — le BP n'expose pas de
   covenant de defaut distinct). Orange si `< seuil comfortable`, vert sinon — ce seuil
   "confortable" (orange/vert) est choisi par ordre de priorite decroissant :
   1. `ProjectInputs.target_dscr` — le vrai covenant negocie (`I-Project`, "Target DSCR -
      Period 1"), quand disponible.
   2. **Seuil pondere par mix de revenu** (`revenue_weighted_dscr_threshold`) — a defaut du
      vrai covenant : *"a euro of contracted revenue and a euro of merchant revenue are not
      necessarily worth the same euro to a lender"* (le principe qui a motive cette regle). Le
      seuil est un blend `part contractee x dscr_min_amber_contracted (1.30x) + part merchant x
      dscr_min_amber_merchant (1.50x)`, calcule a partir de `ProjectInputs.revenue_detail`. Un
      projet 100% merchant est tenu a un plancher DSCR plus strict qu'un projet 100% contracte.
   3. Seuil generique de la config (`dscr_min_amber`, 1.30x) — si ni l'un ni l'autre n'est
      disponible (format resume, ou sous-lignes de revenu absentes/nulles du format complet).

   Le message du flag (vert **et** orange) precise toujours la source du seuil applique
   ("cible du projet (I-Project)" / "pondere par mix de revenu contracte/merchant" / "bancaire
   usuel"), pour que la source ne soit jamais implicite. Orange (pas rouge) si le DSCR n'est pas
   calculable (pas de dette ou pas d'annee d'exploitation) — l'absence de donnee n'est pas en soi
   un signal de risque rouge.
2. **Equity IRR** : rouge si sous le hurdle rate (`equity_irr_hurdle`, 8% par defaut), vert
   sinon.
3. **Project IRR vs WACC** : rouge si le Project IRR ne couvre pas le WACC + marge minimale
   (`project_irr_vs_wacc_margin`, 0% par defaut), vert sinon avec la marge affichee.

## Tests

`tests/test_risk_rules.py` :
- gearing faible -> DSCR confortable -> flag vert
- gearing tres eleve + taux eleve -> DSCR distresse -> flag rouge
- WACC artificiellement extreme (99%) -> Project IRR < WACC -> flag rouge
- `load_thresholds()` lit bien `config/risk_thresholds.yaml` (y compris les 2 nouveaux seuils)
- `target_dscr` du projet, quand plus strict que le seuil generique, fait passer un DSCR
  autrement vert a orange (`test_target_dscr_overrides_generic_amber_threshold`)
- `revenue_weighted_dscr_threshold` blend correctement par mix (30%/70% -> 1.44x), retourne
  `None` sans `revenue_detail`
- priorite des 3 sources : `target_dscr` l'emporte sur le seuil pondere quand les deux sont
  disponibles (`test_target_dscr_takes_priority_over_revenue_weighted`)

Validation croisee sur le fichier reel Belle Epine (`fichier_excel/`, non commite) : mix
~3% contracte / ~97% merchant -> seuil pondere ≈1.49x, tres proche du `target_dscr` reel
(1.5x) — coherence attendue puisque le projet est "Full merchant" (PPA Structure).

## Questions ouvertes

- Les seuils par defaut (DSCR 1.30x/1.10x, hurdle 8%, et desormais 1.30x contracte/1.50x
  merchant) sont des valeurs usuelles du secteur, pas negociees avec un preteur specifique — a
  ajuster projet par projet si necessaire.
- Le blend contracte/merchant est calcule sur le **total** des revenus sur toute la duree du
  projet, pas annee par annee — un projet dont le mix change fortement dans le temps (ex. PPA
  qui expire en cours de vie) aurait un seuil unique moyen sur la periode, pas un seuil qui
  suit le mix reel annee par annee.
