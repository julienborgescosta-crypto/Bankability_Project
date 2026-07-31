# Sensitivity Analysis (tornado one-way)

Spec retrospective.

## Objectif

Reproduire l'ecran "Sensitivity Analysis" de la reference visuelle : pour chaque variable
(Revenue, CAPEX, OPEX, Interest Rate, Debt Ratio), appliquer des chocs -20%/-10%/0/+10%/+20%
et mesurer l'impact sur Equity IRR et DSCR min, avec un graphique tornado.

## Fichiers impactes

- `core/sensitivity.py` — `CORE_VARIABLES`, `SHOCKS`, `run_sensitivity`
- `ui/sensitivity_tab.py` — tables Base Case Values / Impact IRR / Impact DSCR + tornado Plotly

## Logique metier

Chaque variable a un `kind` qui determine comment le choc est applique a
`financial_engine.compute_results` :

- `revenue_multiplier` / `capex_multiplier` / `opex_multiplier` : `1 + shock` directement
- `interest_rate_relative` : `interest_rate_base * (1 + shock)` (choc relatif, pas additif)
- `gearing_relative` : `gearing_base * (1 + shock)`, borne a `[0, 0.95]`

Le choc `0.0` doit toujours reproduire exactement le cas de base — verifie explicitement en
test (`test_zero_shock_matches_base_case`) car c'est la garantie que le "tornado" est bien
centre sur le vrai cas de base et non sur un decalage accidentel.

## Limitation connue (volontaire)

`DETAILED_VARIABLES = ["DAM Spread", "ID Spread", "Cycles", "Capacity Price"]` sont listees
mais **non implementees** : elles necessiteraient le detail de revenus par flux de marche
(voir `bp_parsing.md`, section "Questions ouvertes"), qui n'est pas encore extrait de maniere
fiable du classeur complet. L'UI l'affiche explicitement comme "disponible avec le detail du
BP" plutot que de simuler ces sensibilites a partir de valeurs inventees.

## Tests

`tests/test_sensitivity.py` :
- toutes les `CORE_VARIABLES` sont couvertes, dans l'ordre
- choc nul == cas de base (IRR et DSCR)
- monotonicite : Revenue croissant -> Equity IRR croissant ; CAPEX croissant -> Equity IRR
  decroissant

## Questions ouvertes

- Meme question ouverte que `bp_parsing.md` : comment determiner la cle `configuration` de
  l'onglet `Annual cashflows 1 MW` pour un projet donne (Type TURPE x duree x segment) — a
  clarifier avant d'activer `DETAILED_VARIABLES`.
