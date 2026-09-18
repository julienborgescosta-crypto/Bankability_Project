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

## Ajustement global CAPEX/OPEX (%)

Demandé par l'utilisateur (2026-09-18) : `ProjectConfig.capex_adjustment_pct`/`opex_adjustment_pct`
(défaut `0.0`) multiplient directement la série `ProjectInputs.capex_keur`/`opex_keur` **et** les
scalaires "info" correspondants (`capex_initial_keur`, `capex_repowering_keur`, `opex_year1_keur`)
dans `build_project_inputs` — pas seulement passés en kwargs à `financial_engine.compute_results`.
Raison : `strategy.compute_cod_resale_value_keur` (stratégie 3) lit `inputs.opex_keur` directement,
hors `compute_results` — un ajustement passé uniquement via `capex_multiplier`/`opex_multiplier`
(paramètres déjà supportés par `compute_results`, utilisés par `sensitivity.py`) n'aurait affecté
que les stratégies 1/2, pas la valeur de revente au COD. Ajuster la série une fois, en amont,
garantit une lecture cohérente partout. Multiplication directe (`x * (1 + pct)`) valide quel que
soit le signe de la série (CAPEX/OPEX déjà négatifs) : `pct > 0` accentue le coût, `pct < 0`
l'atténue, sans distinction de cas.
