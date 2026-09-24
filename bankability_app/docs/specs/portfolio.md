# `core/portfolio.py` — portefeuille multi-projets

## Objectif

Exécuter les 3 stratégies (`core/strategy.py`) sur N projets Aurora (`ProjectConfig`) et agréger
les KPI en une table comparable (`PortfolioRow`) — voir `docs/specs/aur_v2_methodology.md`
section 4.

## Décisions

- **`build_project_inputs` compose 3 couches dans un ordre précis** : (1) revenu de base
  (`aur_cases.build_project_inputs`, sans frais d'agrégateur), (2) overlay contractuel
  (`contract_overlay.apply_contract_overlay`), (3) frais d'agrégateur sur la seule part merchant
  du revenu ajusté (`docs/adr/0005`). Inverser (1) et (3) — appliquer le frais avant l'overlay —
  facturerait une commission de trading sur du revenu qui, une fois sécurisé par un floor/tolling,
  n'a jamais transité par un mécanisme de marché.
- **`debt_sizing_mode="dscr"` uniforme**, jamais `"gearing"`, pour tous les projets du
  portefeuille (full merchant compris) : le mode DSCR existant gère déjà les deux régimes de
  dimensionnement (plafond de gearing 70 % qui borde avant le DSCR sur les configs favorables,
  DSCR mordant sur les configs à faible revenu) via son propre plafond de gearing interne
  (`_size_tranche_by_dscr`) — pas besoin de choisir entre les deux modes au niveau du portefeuille,
  contrairement au flux mono-projet (BP réel) qui, lui, expose ce choix à l'utilisateur.
- **`interest_rate` reste un défaut fixe (5 %) ou un override par projet**, pas encore composé
  depuis `senior_debt_margin_pct`/`swap_margin_pct` de `aur_financing_terms.yaml` : ces deux
  bps sont des marges de crédit, pas un taux complet — il manque un taux de base (swap rate) qui
  est une donnée de marché flottante, pas une constante à figer dans un fichier de config (voir
  Questions ouvertes).
- **`ProjectConfig` est un dataclass frozen**, les overrides sont `None` par défaut (pas de
  sentinelle magique) — `None` signifie explicitement "utiliser le défaut de
  `aur_financing_terms.yaml`", jamais une valeur ambiguë comme `0.0`. **Corrigé le 2026-09-18** :
  `dsa_keur` violait ce principe depuis son introduction — sans override, il retombait
  directement sur `0.0` en dur plutôt que sur un défaut de config, contrairement à
  `devex_keur`/`carry_months`/`carry_rate` qui suivaient déjà la règle. Signalé par l'utilisateur
  en voyant un DSA à 0 dans le tableau de résultats sans explication.
- **DSA par défaut = marge de dev cible (par durée BESS) + DEVEX**, pas un taux plat indépendant
  du DEVEX (2ᵉ correction le même jour, `aur_cases.dsa_default_keur`) : la 1ʳᵉ version du fix
  ci-dessus (`dsa_default_keur_per_mw`, 75 k€/MW plat) faisait disparaître 0 mais restait
  déconnectée du DEVEX — `net_margin_keur = TSP - DEVEX` ne retombait donc jamais exactement sur
  une marge cible même quand SPA = 0 (le projet atteint pile le TRI cible de l'acheteur). Construit
  comme `marge_cible(durée) x power_mw + DEVEX`, le DSA seul (SPA = 0) donne déjà
  `net_margin_keur = marge_cible x power_mw` par construction — SPA absorbe ensuite tout écart au
  TRI cible dans les deux sens (voir `docs/specs/strategy.md`). `devex_keur` doit être résolu
  **avant** `dsa_keur` dans `run_portfolio` (déjà le cas) pour qu'un DEVEX overridé par projet se
  répercute sur le DSA par défaut, pas seulement sur `net_margin_keur`. Marges confirmées par
  l'utilisateur (2026-09-18) : 50 k€/MW en 2h, 80 k€/MW en 4h.
- **`run_portfolio` appelle `strategy.compute_build_and_flip` en plus de `compute_dev_and_sell`**
  (au lieu du seul `compute_cod_resale_value_keur` de la 1ère version) — donne le rendement net
  complet de la stratégie 3 (`build_and_flip_net_return_keur`, `build_and_flip_carry_cost_keur`),
  pas seulement la valeur de revente isolée. Recalcule `compute_dev_and_sell` une 2ᵉ fois en
  interne (appel déjà fait pour la stratégie 1) — redondance acceptée, le calcul est bon marché et
  ça évite de dupliquer la logique DSA/SPA dans `portfolio.py`.
- **Durée/taux de portage** (`portage_duration_months`=18 confirmé, `carry_rate_pct`=8%
  provisoire) dans `aur_financing_terms.yaml`, overridables par projet
  (`carry_months_override`/`carry_rate_override`) — même pattern que les autres défauts.
- **Repowering choisi/optimisé, plus subi figé à l'op-year 15** (demande de l'utilisateur,
  2026-09-24, suite au constat qu'un repowering forcé sur un projet de 20 ans ne laissait que 5
  ans pour en profiter — pas de moyen de le désactiver ni de tester une autre année).
  `ProjectConfig` porte 3 champs : `repowering_enabled` (case à cocher), `repowering_year_mode`
  (`"manual"` ou `"auto"`), `repowering_op_year_manual`. En mode `"auto"`,
  `find_best_repowering_op_year()` balaie `repowering_candidate_years(operating_years)` (10 à
  `operating_years - 2`, vide si `operating_years < 15` — pas de repowering sur un projet trop
  court pour en profiter) et retient l'année qui maximise l'**Equity IRR** de la stratégie Garder
  & exploiter (confirmé par l'utilisateur — c'est la stratégie où le choix a le plus d'impact
  direct). Chaque candidat reconstruit un `ProjectInputs` complet (revenu ET CAPEX suivent
  l'année choisie, pas juste un des deux — voir `aur_cases._shifted_degradation`, qui généralise
  le reset de dégradation à n'importe quel op-year plutôt que le figer sur celui d'`AU_Store`).
  **Défaut dataclass volontairement différent du défaut UI** : `ProjectConfig` par défaut est
  `repowering_year_mode="manual"`/année 15 (= comportement identique à avant ce changement), pour
  ne pas ralentir silencieusement `global_sensitivity.py` (~22 configs × ~30 CODs — passer chacun
  en mode "auto" multiplierait son coût par ~9, le nombre de candidats balayés). Le formulaire
  interactif du Configurateur (`ui/configurateur_tab.py`, un projet à la fois) pré-sélectionne
  "auto" explicitement dans son widget — seul ce chemin paie le coût du balayage, là où
  l'utilisateur en profite réellement. `PortfolioRow.repowering_op_year_used`/
  `repowering_auto_optimized` exposent le résultat dans le tableau de résultats.

## Questions ouvertes

- **Composition du taux d'intérêt** : `aur_financing_terms.yaml` porte `senior_debt_margin_pct`
  (150 bps) et `swap_margin_pct` (10 bps), validés sur le fichier réel, mais pas de taux de base
  (swap rate) par défaut - c'est une donnée de marché qui change dans le temps, pas une constante
  du projet. `interest_rate_override` reste donc le seul levier pour l'instant ; il faudra soit
  ajouter un taux de base configurable séparément, soit accepter que l'utilisateur saisisse un
  taux tout-compris par projet.
- **Comparaison coûts Aurora vs coûts QEnergy** (brief section 4) non implémentée : seule la
  source de coûts Aurora (`COPEX_library`, déjà utilisée par `aur_cases.py`) est disponible.
  La table "Hypothèses CAPEX BP" de `COPEX_library` (coûts QEnergy, ~415/~19 €/kW cités par le
  brief) n'est **pas** une bibliothèque réutilisable — `dev_case_parser.parse_copex_library` la
  saute délibérément car ses valeurs sont déjà totalisées pour un projet particulier, pas des taux
  génériques (voir `docs/specs/dev_case.md`). Il n'y a donc pas encore de deuxième source de coûts
  à comparer - le toggle "Aurora vs QEnergy" reste à construire une fois une vraie bibliothèque de
  coûts QEnergy identifiée.
- ~~Pas d'UI Configurateur/Vue portefeuille~~ — fait, voir `ui/configurateur_tab.py`.

## Ajustement global CAPEX/OPEX (%) — retiré, remplacé par 2 leviers ciblés

Une première version (2026-09-18) ajoutait `ProjectConfig.capex_adjustment_pct`/
`opex_adjustment_pct` (défaut `0.0`), multipliant directement toute la série
`ProjectInputs.capex_keur`/`opex_keur` en amont dans `build_project_inputs`. Retour négatif de
l'utilisateur le 2026-09-23 : *"la variation des CAPEX/OPEX en % j'ai eu un feedback négatif …
Il faut pas rechallenger les CAPEX/OPEX qu'on a overall mais certains uniquement comme dans le BP
Stockage Standalone 160926, en pouvant toucher aux CAPEX racco avec 2 options: saisir une valeur
manuelle ou une valeur calculée en fonction de la distance au poste: =4650,7*Distance^0,239, et
côté OPEX seulement les OPEX loyer fonciers"*. Un choc global en % sur tout le CAPEX/OPEX n'a pas
de sens business — le BP réel ne stresse que des postes précis, individuellement identifiables.

Remplacé par 2 leviers repris tels quels de `core/dev_case.py` (déjà utilisés par l'onglet "Cas de
développement", donc alignés sur le BP réel) :

- **CAPEX de raccordement** (`ProjectConfig.connection_capex_mode` : `"library"` par défaut, ou
  `"manual"` avec `manual_connection_capex_keur`, ou `"distance_rte"` avec `distance_rte_km` →
  coût = `4650.7 * distance_km**0.239` k€, formule I-Project du BP Stockage Standalone 160926).
- **OPEX loyer foncier** (`ProjectConfig.land_lease_opex_keur`, additif, non escaladé — ajouté tel
  quel à l'OPEX année 1 comme dans `dev_case.opex_year1_keur`).

Les deux sont passés jusqu'à `aur_cases.build_project_inputs`/`capex_and_opex_keur`, qui les
transmet à la construction interne du `DevCaseParams` (au lieu du `connection_capex_mode="library"`
en dur précédent). Plus de scaling post-hoc de la série : `build_project_inputs` redevient un
simple `replace(base_inputs, revenues_keur=..., net_cashflow_keur=...)`, la CAPEX/OPEX vient
directement de `base_inputs` (déjà correcte pour le poste raccordement/loyer foncier choisi).

## Toggle ORO (limitation non-firm) — extrapolé plutôt qu'un repli silencieux

`ProjectConfig.oro_requested: bool` + `curtailment_hours: int | None` (2026-09-23, étendu
2026-09-24 — voir `docs/specs/aur_cases.md` pour le contexte de la dimension ORO dans `AU_Store` et
`docs/specs/config_extrapolation.md` pour la méthode). Seuls 4 cas Aurora (HTB2 injection/soutirage,
2h/4h) à exactement 3000h ont une courbe ORO réelle — demander ORO (à 3000h ou toute autre valeur
500-4000h) sur une autre combinaison ne renvoie plus un revenu nul silencieux, **ni un repli
silencieux sur la courbe standard** (comportement du 2026-09-23, remplacé le lendemain suite à la
demande explicite de l'utilisateur d'extrapoler plutôt que d'ignorer) : `_resolve_au_config()`
délègue entièrement à `config_extrapolation.resolve_config()`, qui retourne toujours une courbe
utilisable — réelle ou estimée, jamais bloquante sauf combinaison sans sens business (ORO/gabarit +
Classique).

`build_project_inputs()` retourne `(inputs, secured_revenue, resolved: ResolvedConfig)` - le 3ᵉ
élément porte la config Aurora effectivement utilisée (`resolved.config.extrapolated`,
`resolved.notes`). `run_portfolio()` peuple `PortfolioRow.extrapolated`/`extrapolation_notes` (plus
générique que l'ancien `oro_applied` — couvre aussi bien l'extrapolation ORO que celle du type
TURPE/gabarit) sans dupliquer la résolution. L'UI (`ui/configurateur_tab.py`) affiche l'estimation
et ses notes **avant** l'ajout (aperçu dans le formulaire) et **après** (expander sur le tableau de
résultats) — jamais une seule des deux.
