# `core/config_extrapolation.py` — extrapolation des combinaisons non modélisées par Aurora

## Objectif

`AU_Store` ne modélise que 22 combinaisons (durée × tension × type TURPE × gabarit × ORO) sur
l'espace théorique complet — ex. HTB1/HTB3 n'ont que la variante Classique, la limitation ORO n'a
été chiffrée que pour HTB2 injection/soutirage. Demande de l'utilisateur, 2026-09-24 : pouvoir
explorer les combinaisons manquantes plutôt que de se heurter à une erreur bloquante ou (pire) un
repli silencieux — mais **toujours indiquer clairement quand un chiffre est une estimation**, pas
une donnée Aurora.

`resolve_config()` est le point d'entrée unique : il retourne une `AuStoreConfig` (réelle si
Aurora l'a modélisée, sinon synthétique) directement utilisable par
`aur_cases.build_project_inputs`, sans que le reste du pipeline (`portfolio.py`, `strategy.py`,
les 3 stratégies, l'UI) n'ait besoin de savoir si elle regarde une donnée réelle ou estimée — la
seule différence visible est `AuStoreConfig.extrapolated` (bool) et les `notes` explicatives
retournées à côté.

## Décisions

- **Config synthétique injectée dans une copie de la bibliothèque**, pas un chemin de calcul
  parallèle : `resolve_config()` retourne un `ResolvedConfig(library, config, notes)` où `library`
  est soit l'`AuStoreLibrary` d'origine inchangée (cas réel), soit une copie (`dataclasses.replace`)
  avec une `AuStoreConfig` de plus et ses courbes RAW/TURPE ajoutées aux dicts existants. Tout le
  reste du pipeline (`aur_cases.revenue_and_turpe_series`, `build_project_inputs`,
  `financial_engine.compute_results`) fonctionne sans modification — c'est la même astuce que pour
  n'importe quelle config réelle, juste une entrée de plus dans le dict.
- **Modèle à facteurs indépendants, calibré sur HTB2** (seule tension où Aurora a modélisé
  Classique/Injection/Soutirage × gabarit 0/1 en intégralité) :
  - Effet type TURPE : `RAW_cible = RAW_cible(Classique) × [RAW_HTB2(type) / RAW_HTB2(Classique)]`
    (multiplicatif, par année) ; `TURPE_cible = TURPE_cible(Classique) + [TURPE_HTB2(type) −
    TURPE_HTB2(Classique)]` (additif, par année — un ratio n'a pas de sens sur du TURPE qui peut
    changer de signe entre Classique et Injection).
  - Effet gabarit : même principe, `RAW_HTB2(type, g1) / RAW_HTB2(type, g0)` et
    `TURPE_HTB2(type, g1) − TURPE_HTB2(type, g0)`.
  - Les deux se combinent (multiplication/addition successive) quand type ET gabarit manquent tous
    les deux pour la tension cible.
  - Hypothèse non vérifiée au-delà de HTB2 : que l'effet d'un changement de type TURPE ou de
    gabarit est le même quelle que soit la tension. Chaque extrapolation porte une note explicite
    le rappelant.
- **Effet ORO, même principe**, calibré sur les 4 cas HTB2 ORO réels (injection/soutirage × 2h/4h) :
  `RAW_ORO_cible = RAW_standard_cible × [RAW_HTB2_ORO(type) / RAW_HTB2_standard(type)]`. Appliqué
  par-dessus la courbe standard déjà résolue (réelle ou elle-même extrapolée à l'étape précédente).
- **Combinaisons bloquées, pas extrapolées** : gabarit ou ORO avec le type TURPE Classique lèvent
  `AuroraConfigError`. Ce ne sont pas des données manquantes mais des combinaisons sans sens
  business — le gabarit et l'ORO limitent spécifiquement l'injection ou le soutirage, la
  distinction Classique ne s'applique pas. Extrapoler ici inventerait un chiffre pour un concept
  qui n'existe pas.
- **Heures de curtailment personnalisées (500-4000h)** : la courbe ORO à 3000h (réelle ou déjà
  extrapolée par l'étape précédente) sert d'ancre. Le ratio `(1 − perte%(heures)) / (1 −
  perte%(3000h))`, tiré de `config/aur_oro_curtailment_losses.yaml` (profil de perte % par année,
  interpolé linéairement entre les paliers 500h), rééchelonne la courbe RAW — jamais le TURPE
  (l'onglet source "Curtailment analysis" du databook Aurora ne documente que des pertes de
  revenu, pas un effet sur le TURPE). Hors de la plage 500-4000h analysée par Aurora, erreur
  explicite plutôt qu'une extrapolation sans aucune base.
  - `config/aur_oro_curtailment_losses.yaml` est **calibré sur un seul cas de référence** (2h HTB2
    injection, Central, COD2027, onglet "Curtailment analysis" du databook Aurora Q2 2026) —
    transféré tel quel à toutes les autres combinaisons/durées. C'est la moins bien fondée des
    trois extrapolations de ce module ; c'est pour ça qu'elle n'intervient qu'en dernier ressort,
    en rééchelonnement relatif d'une courbe ORO déjà résolue par ailleurs (jamais comme source
    absolue).
- **`AuStoreConfig.extrapolated: bool`** (défaut `False`) plutôt qu'un type séparé pour les configs
  synthétiques : garde tout le pipeline existant (`config_by_attributes`, `revenue_and_turpe_series`,
  toutes les stratégies) inchangé — une config extrapolée est juste une `AuStoreConfig` comme une
  autre, avec un flag et une clé technique explicite (`"{duree}h {tension} {type} [gabarit] [ORO
  [heures]] (extrapolé)"`).
- **`config_space.turpe_types()`/`gabarit_options()`/`oro_options()` élargis à l'espace théorique
  complet** (2026-09-24) : avant, ces fonctions ne proposaient que ce qu'Aurora avait réellement
  modélisé pour la tension/durée choisie (filtrage sur `AuStoreLibrary.configs`). Elles retournent
  désormais toujours `["Classique", "Injection", "Soutirage"]` / `[False, True]` (sauf gabarit avec
  Classique, toujours `[False]`) — l'UI n'a plus besoin de désactiver une option pour "donnée
  manquante", `resolve_config()` gère la suite. `config_space.has_cost_data()` (CAPEX/OPEX,
  `COPEX_library`) reste un filtre dur inchangé — aucune extrapolation proposée côté coûts, c'est
  une source de données totalement différente.

## Questions ouvertes

- **Pas d'extrapolation vers une 3ᵉ durée BESS** (ex. 6h) : `resolve_config()` requiert
  `duree_h` réel (2h ou 4h, seules durées qu'Aurora a modélisées) — extrapoler sur cet axe
  demanderait une toute autre méthode (interpolation entre 2h et 4h), non demandée et non
  implémentée.
- **Analyse globale (`global_sensitivity.py`) ne balaie pas l'espace extrapolé** : `enumerate_configs`
  continue d'énumérer uniquement les 22 configs réelles d'`AU_Store` (voir
  `docs/specs/global_sensitivity.md`) — étendre au plein espace théorique multiplierait le nombre
  de cas par ~3-4x (tous les types TURPE × gabarit pour HTA/HTB1/HTB3, en plus de l'ORO), au prix
  d'un temps de calcul et d'une lisibilité de la table dégradés pour une confiance moindre sur ces
  lignes. Le Configurateur (projet par projet) couvre le cas d'usage "explorer une config précise
  non modélisée" ; l'Analyse globale reste focalisée sur les données réelles pour l'instant.
