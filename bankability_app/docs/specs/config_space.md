# `core/config_space.py` — énumération de l'espace des configs Aurora

## Objectif

Couche fine au-dessus de `core.aur_cases.AuStoreLibrary` pour les besoins du Configurateur
(Phase 4) : listes en cascade (durée → tension → type TURPE → gabarit) et garde-fou COD2030,
sans dupliquer la logique de chargement/validation déjà dans `aur_cases.py`.

## Décisions

- **Pas de table de correspondance tension→segment** : `AuStoreConfig.tension` (HTA/HTB1/HTB2/
  HTB3) est déjà le même libellé que `ProjectInputs.segment` utilisé partout ailleurs dans l'app
  — le "mapping" mentionné dans le brief est l'identité, pas une vraie table à maintenir.
- **Validation COD2030 exposée en 2 formes** : `is_cod_valid` (booléen, pour une UI qui veut
  griser une option) et `valid_cod_years` (filtre une liste de candidats, pour une UI qui
  construit une liste déroulante d'années). Les deux délèguent à la même règle que
  `aur_cases.validate_cod` (qui lève, pour l'usage moteur) — pas de dérive possible entre les
  deux code paths.
- **`has_cost_data` exclut par disponibilité réelle, pas par une liste de tensions bannies** —
  ajouté après que l'utilisateur a demandé de ne plus proposer HTB3 (2026-09-18), suite à la
  découverte que `COPEX_library` ne couvre pas cette tension (voir `docs/specs/aur_cases.md`,
  `docs/specs/global_sensitivity.md`). Dériver l'exclusion de la donnée réelle plutôt que coder en
  dur `"HTB3"` évite que le filtre devienne obsolète si `COPEX_library` est un jour complété.
  `tensions()` accepte `copex_library` en optionnel : fourni, il filtre ; absent, comportement
  inchangé (tests existants non affectés).
- **Exclusion HTB3 repassée en dur le 2026-10-01** — ce que la décision ci-dessus anticipait
  ("si `COPEX_library` est un jour complété") s'est produit, mais par un autre chemin que prévu :
  le remplacement du `copex_library` par défaut (fixture → databook Aurora Q2 2026, voir
  `docs/specs/copex_comparison.md`) a fait apparaître des données HTB3 là où il n'y en avait
  jamais eu — ce qui aurait réactivé HTB3 silencieusement partout (dropdown Configurateur, Aurora
  Global Analysis), un changement de comportement visible non demandé. Garde-fou explicite remis
  en place en attendant une décision de l'utilisateur (voir "Questions ouvertes").

## Questions ouvertes

- **HTB3 a maintenant des données CAPEX/OPEX réelles (Aurora Q2 2026)** — l'exclusion reste pour
  l'instant forcée en dur dans `has_cost_data`, contrairement à l'intention de conception
  originale (exclusion purement pilotée par la donnée). À trancher avec l'utilisateur : réactiver
  HTB3 partout maintenant que la donnée existe, ou garder l'exclusion explicite.
