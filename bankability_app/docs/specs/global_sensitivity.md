# `core/global_sensitivity.py` — analyse globale (Phase 5)

## Objectif

Énumérer et calculer les KPI de **tout** l'espace des configs Aurora disponibles (18 configs
`AU_Store` x années de COD valides x structure contractuelle), indépendamment des projets saisis
par l'utilisateur dans le Configurateur — voir `docs/adr/0003` et
`docs/specs/aur_v2_methodology.md` section 5.

## Décisions

- **Énumération complète, pas un balayage variable-par-variable** (`docs/adr/0003`) : l'espace est
  fini et petit (18 configs x ~15 années de COD valides x 3 structures ≈ 700-800 cas), calculé en
  ~1-2 secondes (mesuré). Pas besoin d'optimisation ni de cache applicatif côté `core/` — un
  simple `st.cache_data` côté UI suffit.
- **`GlobalSensitivityRow` fait la jointure config↔résultat** que `portfolio.PortfolioRow` seul
  n'expose pas (`config_label` est une chaîne formatée, pas des champs structurés) — nécessaire
  pour filtrer/pivoter par dimension (tension, COD, structure...) dans l'UI sans re-parser une
  chaîne.
- **Prix/durée floor-tolling représentatifs, pas swept eux-mêmes** (défauts 80 k€/MW/an, 10 ans,
  partage 40 % — mêmes ordres de grandeur que les tests de `portfolio.py`) : ce sont des termes
  commerciaux, pas une donnée Aurora modélisée par config — les swiper indépendamment
  multiplierait l'espace sans qu'aucune valeur ne soit plus "vraie" qu'une autre. Overridables en
  paramètres de `enumerate_configs`/`run_global_sensitivity` si besoin d'une analyse à un autre
  niveau de prix.
- **`run_global_sensitivity` retourne `(rows, skipped)`, jamais une liste tronquée en silence** :
  les configs Aurora sans donnée CAPEX/OPEX (HTB3 — voir `docs/specs/aur_cases.md`) sont exclues
  **en amont** de `enumerate_configs` (`config_space.has_cost_data`, ajouté suite à la demande de
  l'utilisateur du 2026-09-18 de ne plus proposer HTB3 du tout) plutôt que générées puis
  rejetées une par une — `skipped` porte alors **une seule** entrée résumant les configs exclues
  et leur motif, pas une entrée par cas COD/structure généré pour rien (90 entrées quasi
  identiques dans la 1ère version de ce module). Un cas qui échouerait malgré tout au calcul (motif
  différent, non encore rencontré) resterait ajouté individuellement — jamais silencieusement
  absent du résultat sans trace (brief section 7, "zéro zéro silencieux"). Boucle un
  `ProjectConfig` à la fois plutôt qu'un seul appel batch à `portfolio.run_portfolio` : nécessaire
  pour isoler une éventuelle erreur résiduelle sans faire échouer tout le balayage.
- **Ce module a mis au jour un vrai bug** dans `aur_cases.capex_and_opex_keur` (CAPEX/OPEX à 0
  silencieux pour HTB3) qui existait depuis la Phase 2 mais n'avait jamais été exercé par les
  tests unitaires (tous sur HTA/HTB1/HTB2) ni par l'usage manuel du Configurateur — corrigé dans
  `aur_cases.py` en même temps que ce module. L'utilisateur a ensuite explicitement demandé de ne
  plus proposer HTB3 du tout (2026-09-18) plutôt que de simplement lever une erreur si choisi —
  `config_space.has_cost_data` exclut la tension en amont, dans le Configurateur (`tensions()`)
  comme dans l'analyse globale (`enumerate_configs`), voir `docs/specs/config_space.md`.

## Questions ouvertes

- Prix/durée floor-tolling par défaut (80 k€/MW/an, 10 ans, partage 40 %) non confirmés par
  l'utilisateur — mêmes valeurs que les exemples déjà utilisés ailleurs dans le code, pas une
  hypothèse business validée.
- Pas encore d'UI (table triable/filtrable + heatmaps + coupes 1-2 variables) — ce module reste
  une couche `core/` pure au moment de l'écriture de cette spec.
