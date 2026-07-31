# Risk Dashboard

Spec retrospective.

## Objectif

Repondre au "Risk Assessment Layer" de la methodologie de reference : generer automatiquement
des alertes (vert/orange/rouge) quand une metrique franchit un seuil bancaire usuel, plutot que
de laisser l'utilisateur relire des tableaux de chiffres pour reperer les problemes.

## Fichiers impactes

- `config/risk_thresholds.yaml` — seuils (source unique, pas de valeur en dur dans le code)
- `core/risk_rules.py` — `RiskFlag`, `evaluate_risks`, `load_thresholds`
- `ui/risk_tab.py` — affichage des flags via `st.error`/`st.warning`/`st.success`

## Logique metier

Trois regles independantes, chacune produisant exactement un `RiskFlag` :

1. **DSCR min** : rouge si `< dscr_min_red` (1.10x), orange si `< dscr_min_amber` (1.30x — seuil
   bancaire usuel pour du financement BESS), vert sinon. Orange (pas rouge) si non calculable
   (pas de dette ou pas d'annee d'exploitation) — l'absence de donnee n'est pas en soi un signal
   de risque rouge.
2. **Equity IRR** : rouge si sous le hurdle rate (`equity_irr_hurdle`, 8% par defaut), vert
   sinon.
3. **Project IRR vs WACC** : rouge si le Project IRR ne couvre pas le WACC + marge minimale
   (`project_irr_vs_wacc_margin`, 0% par defaut), vert sinon avec la marge affichee.

## Tests

`tests/test_risk_rules.py` :
- gearing faible -> DSCR confortable -> flag vert
- gearing tres eleve + taux eleve -> DSCR distresse -> flag rouge
- WACC artificiellement extreme (99%) -> Project IRR < WACC -> flag rouge
- `load_thresholds()` lit bien `config/risk_thresholds.yaml`

## Questions ouvertes

- Les seuils par defaut (DSCR 1.30x/1.10x, hurdle 8%) sont des valeurs usuelles du secteur, pas
  negociees avec un preteur specifique — a ajuster projet par projet si necessaire.
