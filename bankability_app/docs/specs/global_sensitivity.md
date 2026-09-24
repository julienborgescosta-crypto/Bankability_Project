# `core/global_sensitivity.py` — analyse globale (Phase 5)

## Objectif

Énumérer et calculer les KPI de **tout** l'espace des configs Aurora disponibles (22 configs
`AU_Store`, dont 4 ORO, x années de COD valides x structure contractuelle), indépendamment des
projets saisis par l'utilisateur dans le Configurateur — voir `docs/adr/0003` et
`docs/specs/aur_v2_methodology.md` section 5.

## Décisions

- **Énumération complète, pas un balayage variable-par-variable** (`docs/adr/0003`) : l'espace est
  fini et petit (22 configs x ~15 années de COD valides x 3 structures ≈ 850-950 cas), calculé en
  quelques secondes (mesuré). Pas besoin d'optimisation ni de cache applicatif côté `core/` — un
  simple `st.cache_data` côté UI suffit.
- **`ProjectConfig.oro_requested = au_config.oro` dans `enumerate_configs`** (2026-09-23, ajout de
  la dimension ORO) : sans ça, un `au_config` ORO et son équivalent standard partagent le même
  `(duree_h, tension, turpe_type, gabarit)` et `config_extrapolation.resolve_config` résoudrait la
  même courbe standard pour les deux (le `oro_requested` par défaut à `False` masquerait la
  dimension ORO de l'`au_config` réel qu'on est pourtant en train d'énumérer) — 2 lignes
  identiques plutôt qu'une ligne ORO distincte.
  `GlobalSensitivityRow.oro` expose la dimension pour filtrage/heatmap (jamais moyenné avec les
  configs standard sans distinction — même discipline que gabarit/turpe_type, voir
  `docs/specs/aur_cases.md`).
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
- **`run_global_sensitivity` ne mentionne plus HTB3 du tout, même dans `skipped`** (demande de
  l'utilisateur, 2026-09-24) : HTB3 est une limite **permanente** (aucune tension n'aura jamais de
  données CAPEX/OPEX pour elle, ni Aurora ni ICP), pas une donnée manquante ponctuelle qui
  mériterait d'être signalée à chaque utilisation — filtré explicitement hors du résumé
  `excluded_configs` par `c.tension != "HTB3"`. Le mécanisme `skipped` générique reste actif pour
  toute *autre* tension qui manquerait de données à l'avenir.

## UI (`ui/global_sensitivity_tab.py`)

- **La heatmap doit moyenner sur les dimensions non choisies — mais respecter les filtres de la
  table.** Signalé par l'utilisateur (2026-09-23) : la heatmap ignorait les filtres de la table
  (bug réel, pas juste une confusion — `render()` appelait `_render_heatmap(df)` sur le
  dataframe **brut**, pas sur `filtered`, donc une case "COD × Tension" moyennait TOUJOURS tous
  les types TURPE/gabarits/structures ensemble, même en filtrant la table sur `TURPE=Injection`).
  Corrigé : `render()` passe désormais le dataframe filtré à `_render_heatmap`. Filtres Gabarit et
  Durée BESS ajoutés à la table (seuls Tension/TURPE/Structure existaient) pour pouvoir isoler
  n'importe quelle dimension.
- **Petits multiples ("Séparer par")** : un sélecteur optionnel qui, au lieu de moyenner une
  dimension dans la heatmap, la fait éclater en plusieurs heatmaps côte à côte (une par valeur) —
  répond au besoin explicite de comparer "Injection vs Soutirage vs Classique" ou "Gabarit Oui vs
  Non" sans les mélanger dans une même moyenne. `COD` volontairement exclu des choix de séparation
  (jusqu'à ~15 valeurs, generait trop de panneaux) — reste utilisable comme axe X/Y ou filtre.
  Chaque case affiche aussi le nombre de cas moyennés au survol (`hovertemplate`), pour qu'une
  moyenne sur plusieurs cas ne soit jamais confondue avec une valeur unique.
- **`key` explicite sur chaque `st.plotly_chart` des petits multiples** : sans `key`, Streamlit
  1.60 identifie un élément par type + paramètres d'appel (pas le contenu de la figure) — deux
  `st.plotly_chart(fig, use_container_width=True)` consécutifs peuvent lever
  `StreamlitDuplicateElementId` selon comment l'ID auto-généré est calculé. Trouvé en écrivant le
  test headless (`streamlit.testing.v1.AppTest`) avant de le voir en usage réel — corrigé avec
  `key=f"heatmap_{facet_col}_{value}"`.

## Questions ouvertes

- Prix/durée floor-tolling par défaut (80 k€/MW/an, 10 ans, partage 40 %) non confirmés par
  l'utilisateur — mêmes valeurs que les exemples déjà utilisés ailleurs dans le code, pas une
  hypothèse business validée.
- **N'énumère pas l'espace extrapolé** (2026-09-24, voir `docs/specs/config_extrapolation.md`) :
  `enumerate_configs` continue de ne balayer que les 22 configs réelles d'`AU_Store`, pas les
  combinaisons type TURPE/gabarit/ORO manquantes que le Configurateur sait désormais extrapoler
  projet par projet. Étendre au plein espace théorique multiplierait le nombre de cas par ~3-4x
  pour une confiance moindre sur ces lignes — scope non demandé pour l'instant.
