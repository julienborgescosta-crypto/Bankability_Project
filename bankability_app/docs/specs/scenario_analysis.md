# Scenario Analysis (Bear / Base / Bull)

Spec retrospective.

## Objectif

Reproduire l'ecran "Scenario Analysis" de la reference visuelle (P10/P50/P90) : appliquer des
facteurs d'ajustement (Revenue/CAPEX/OPEX multiplicateurs + delta de taux) au cas de base et
recalculer IRR/DSCR/NPV pour chaque scenario, avec les facteurs eux-memes editables dans l'UI.

## Fichiers impactes

- `core/scenarios.py` — `ScenarioFactors`, `DEFAULT_SCENARIOS`, `run_scenarios`
- `ui/scenario_tab.py` — table de facteurs editable (`st.data_editor`) + table "Scenario Inputs
  (After Adjustments)" + cartes de resultats par scenario

## Logique metier

`run_scenarios` ne fait qu'appeler `financial_engine.compute_results` une fois par scenario
avec les multiplicateurs correspondants — aucune logique financiere dupliquee. Les valeurs par
defaut (`DEFAULT_SCENARIOS`) reprennent exactement les facteurs de la maquette de reference :

| Scenario | Revenue x | CAPEX x | OPEX x | Interest Rate |
|---|---|---|---|---|
| Bear (P10) | 0.85 | 1.10 | 1.05 | +0.3% |
| Base (P50) | 1.00 | 1.00 | 1.00 | 0% |
| Bull (P90) | 1.25 | 0.90 | 0.95 | -0.5% |

L'UI permet de modifier ces facteurs via un `st.data_editor` ; les scenarios recalcules
utilisent alors les valeurs editees, pas les valeurs par defaut.

## Tests

`tests/test_scenarios.py` :
- ordre attendu `Bear < Base < Bull` sur l'IRR projet
- le scenario "Base (P50)" (facteurs neutres) doit produire un resultat **identique** a
  `financial_engine.compute_results` sans aucun multiplicateur — garantit qu'aucun facteur
  neutre n'introduit de biais
- un jeu de scenarios personnalise remplace bien le defaut

## Questions ouvertes

- Les facteurs par defaut sont ceux de la maquette de reference fournie par l'utilisateur, pas
  calibres sur des donnees P10/P50/P90 reelles du secteur BESS. A ajuster si l'utilisateur a des
  hypotheses propres.
