# Stress-Test Matrix

Spec retrospective.

## Objectif

Repondre au "matrix testing bear case revenue, degradation, and combined stresses" decrit dans
la methodologie de reference (article substack sur les templates de bancabilite BESS) : croiser
un stress sur les revenus (Bear) et un stress sur la degradation (courbe additionnelle), pour
observer separement et conjointement leur impact.

## Fichiers impactes

- `core/degradation.py` — `degradation_multipliers`, `DEGRADATION_CASES`
- `core/stress_test.py` — `REVENUE_CASES`, `run_stress_matrix`
- `ui/stress_tab.py` — tableau des 4 combinaisons

## Logique metier

Grille 2x2 : `{Base, Bear} x {Base degradation, Conservative degradation}`. Chaque cellule
rappelle `financial_engine.compute_results` avec `revenue_multiplier` (0.85 pour Bear) et
`degradation_multipliers` (courbe cumulative, voir ci-dessous). `combined = True` uniquement
quand les DEUX stress sont actifs simultanement (ni Bear seul, ni Conservative seul).

**La degradation ici est additionnelle**, independante de celle deja implicite dans la serie de
revenus du BP (qui encode deja la baisse de capacite/prix prevue par le modelisateur d'origine).
C'est une hypothese de stress supplementaire, explicitement documentee comme telle dans l'UI —
pas une donnee extraite du BP.

| Cas | 1ere annee | Annees suivantes |
|---|---|---|
| Base | -2%/an | -0.5%/an |
| Conservative | -3%/an | -1.0%/an |

## Tests

`tests/test_stress_test.py` :
- les 4 combinaisons sont bien presentes
- le flag `combined` correspond exactement a "les deux stress actifs"
- `(Base, Base)` est strictement moins penalisant que `(Bear, Conservative)` sur IRR et DSCR

## Questions ouvertes

- Les taux de degradation additionnelle (2%/0.5% base, 3%/1% conservative) sont des valeurs
  d'ingenierie generiques, non calibrees sur une chimie de batterie ou un contrat O&M
  specifique — a ajuster si l'utilisateur a des courbes de degradation propres.
