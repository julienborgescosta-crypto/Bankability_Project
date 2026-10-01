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
  l'utilisateur, 2026-09-24) : HTB3 était jusqu'ici une limite **permanente** (aucune tension
  n'avait de données CAPEX/OPEX pour elle, ni Aurora ni ICP) — filtré explicitement hors du résumé
  `excluded_configs` par `c.tension != "HTB3"`. **"Permanente" ne tient plus depuis le 2026-10-01**
  (le databook Aurora Q2 2026, nouvelle source par défaut de `copex_library`, couvre HTB3) —
  `config_space.has_cost_data` exclut maintenant HTB3 explicitement (en dur) plutôt que par absence
  de donnée, pour ne pas la réactiver silencieusement ; décision de la réactiver ou non en
  attente de l'utilisateur, voir `docs/specs/config_space.md` "Questions ouvertes". Le mécanisme
  `skipped` générique reste actif pour toute *autre* tension qui manquerait de données à l'avenir.
- **Une puissance de référence PAR TENSION, pas une seule pour tout l'espace**
  (`power_mw_by_tension`, corrigé 2026-10-01 suite à un retour utilisateur) : appliquer une seule
  puissance (ex. 50 MW, réaliste pour HTB2) à toutes les tensions produit des cas incohérents — une
  config "50 MW HTA" ne correspond à aucun raccordement réel (HTA = raccordement distribution
  Enedis, plafonné bien en-dessous de ce que supporte un raccordement RTE HTB1/HTB2). Le problème
  compte plus qu'il n'y paraît : le CAPEX ICP (source par défaut) a des composantes forfaitaires
  (raccordement DSO, génie civil) qui font varier le TRI très fortement à puissance non réaliste —
  vérifié 2026-10-01, HTA 2h Classique COD2030 : TRI de -11.5 % à 10 MW à +3.3 % à 100 MW, seule la
  puissance changeant — donc pas seulement un problème de "cohérence terrain", un vrai artefact de
  modèle si on compare 2 tensions à une puissance qui n'a de sens réel que pour l'une des deux.
  `enumerate_configs(power_mw_by_tension=...)` remplace le paramètre unique `power_mw` ; défaut
  `DEFAULT_POWER_MW_BY_TENSION` (HTA 10 MW, HTB1 30 MW, HTB2 50 MW) — des gabarits de raccordement
  **indicatifs**, pas confirmés par l'utilisateur (même statut que les prix floor/tolling
  ci-dessus), éditables librement dans l'UI (un champ par tension). Lève une erreur explicite si
  une tension d'`AU_Store` n'a pas d'entrée dans le mapping (jamais un repli silencieux sur une
  valeur arbitraire).
- **`optimize_repowering` (2026-10-01, retour utilisateur)** : `enumerate_configs`/
  `run_global_sensitivity` construisaient chaque `ProjectConfig` sans jamais passer
  `repowering_year_mode`/`repowering_op_year_manual` — retombant donc sur le défaut dataclass
  (`"manual"`, année 15 fixe, voir `core/portfolio.py`), alors que le formulaire interactif du
  Configurateur (`ui/configurateur_tab.py`) pré-sélectionne le mode `"auto"`
  (`find_best_repowering_op_year`, balaie les années candidates et garde celle qui maximise
  l'Equity IRR). Même config, 2 écrans, 2 résultats très différents : signalé par l'utilisateur sur
  un cas HTA 2h gabarit Injection COD2028 — +5.5 % TRI Projet dans le Configurateur contre -0.9 %
  dans Global Analysis, le repowering forcé à l'année 15 tombant mal sur un projet où le revenu
  Aurora décline fortement avec le temps (voir README, limite connue "Moteur Aurora v2 ... valeur
  résiduelle de fin de vie non modélisée"). Paramètre booléen ajouté (défaut `False`, comportement
  inchangé) : `True` force `repowering_year_mode="auto"` sur chaque `ProjectConfig` généré, pour
  rendre les 2 écrans comparables. **Volontairement pas le défaut** : balaie
  `portfolio.repowering_candidate_years(operating_years)` (~9 candidats à 20 ans, ~19 à 30 ans) PAR
  CAS, donc multiplie le coût de calcul du balayage complet d'autant — case à cocher dédiée dans
  l'UI (`st.checkbox key="optimize_repowering"`, décochée par défaut), avec `st.spinner` explicite
  quand activée. `GlobalSensitivityRow`/le dataframe UI exposent désormais aussi
  `repowering_op_year`/`repowering_auto_optimized` (déjà présents sur `PortfolioRow`, juste pas
  remontés jusque-là) pour que l'année retenue soit visible dans la table, pas seulement son effet
  sur le TRI.

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
- **`DEFAULT_POWER_MW_BY_TENSION` (HTA 10 MW, HTB1 30 MW, HTB2 50 MW) non confirmés** — des
  gabarits de raccordement indicatifs, pas des plafonds réglementaires Enedis/RTE vérifiés avec
  l'utilisateur. Éditables dans l'UI, donc pas bloquant, mais à ajuster si l'utilisateur a des
  chiffres de raccordement plus précis.
- **La sensibilité forte du TRI à la puissance (composantes CAPEX ICP forfaitaires) n'est pas
  elle-même questionnée ici** — elle peut refléter une vraie économie d'échelle (réaliste : un
  raccordement DSO forfaitaire coûte proportionnellement moins cher dilué sur un plus gros projet)
  ou un artefact du modèle ICP (voir `docs/specs/copex_icp.md`) : non tranché, ce fix choisit des
  puissances de référence réalistes par tension plutôt que de statuer sur la validité de l'économie
  d'échelle elle-même.
- ~~N'énumère pas l'espace extrapolé~~ — implémenté le 2026-10-01, demande explicite de
  l'utilisateur ("je le veux en option on coche et ça sort toutes les extrapolations"). Nouveau
  paramètre `enumerate_configs(include_extrapolated=True)` (défaut `False`, comportement inchangé)
  : balaie en plus tout l'espace théorique (durée x tension x type TURPE x gabarit x ORO, HTB3
  exclu) via `core.config_extrapolation.resolve_config`, en excluant les combinaisons déjà
  couvertes par une config réelle (`covered`, jamais générées 2x). Vérifié empiriquement : 20
  combos réels -> 54 combos au total (~2.7x, dans l'ordre de grandeur "~3-4x" déjà estimé ici).
  Chaque ligne reste identifiable via `PortfolioRow.extrapolated`/`.extrapolation_notes` (déjà
  posés par `portfolio.build_project_inputs`, pas de nouveau champ nécessaire sur
  `GlobalSensitivityRow`) — colonne "Extrapolated" + filtre dédié dans la table UI, jamais mélangée
  sans distinction aux lignes réelles.
- **`run_global_sensitivity(capex_opex_source=...)` (2026-10-01, même demande utilisateur)** :
  "comme dans Aurora Configurator je veux une option pour repasser avec le CAPEX Aurora" - même
  bascule `"icp"`/`"aurora"` que le Configurateur (`aur_cases.build_project_inputs`), appliquée ici
  à TOUT le balayage d'un coup (case à cocher UI) plutôt qu'à un 2e tableau côte à côte comme le
  Configurateur — un 2e sweep complet de 150+ cas aurait été coûteux et peu lisible côte à côte.
