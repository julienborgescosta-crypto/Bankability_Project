# `core/aur_cases.py` — moteur de revenu Aurora (`AU_Store`)

## Objectif

Charger les 18 configurations Aurora standalone de `AU_Store` (courbes RAW/TURPE calendaires,
dégradation par op-year, métadonnées de config) et construire un `ProjectInputs` pour une
config/COD/puissance donnée — même forme que `dev_case.build_project_inputs`, utilisable tel
quel par `financial_engine.compute_results()`. Voir `docs/specs/aur_v2_methodology.md` pour la
méthodologie complète et `CONTEXT.md` pour le vocabulaire (AU_Store, AUStoreKey, DropKey).

## Décisions

- **Parsing par recherche de libellé**, pas par adresse de colonne fixe (même discipline que
  `bp_parser.py`) : les 4 blocs d'`AU_Store` (RAW, TURPE, métadonnées de config, dégradation par
  op-year) sont repérés par leur en-tête (`Year`, `DropKey`, `OpYear`) puis lus comme des runs de
  colonnes contiguës, plutôt que des indices codés en dur — résiste à un réordonnancement de
  colonnes tant que les libellés restent stables.
- **Indépendant de `dev_case.py`/`CF Aurora`** par choix explicite (bibliothèque Aurora distincte,
  granularité différente — voir `CONTEXT.md`) : seules les fonctions **publiques**
  `capex_total_keur`/`opex_year1_keur` de `dev_case.py` sont réutilisées pour `COPEX_library`
  (même table pour les deux chemins de donnée), via un `DevCaseParams` construit comme simple
  vecteur de calcul (`voltage_class_override` court-circuite le besoin de `connection_type`).
- **TURPE non dégradé** : seule la courbe RAW est multipliée par le facteur de dégradation par
  op-year — hypothèse non extraite du fichier (AU_Store ne précise pas si TURPE doit l'être),
  raisonnée par analogie avec le reste de l'app (TURPE = charge réseau, pas liée à la dégradation
  de la batterie). Voir "Questions ouvertes" ci-dessous.
- **Frais d'agrégateur en mécanisme complet** (paliers avant/après seuil + bascule net-du-TURPE),
  pas un taux plat — voir `docs/adr/0001`. Le toggle `net_of_energy_costs` est extrait mais n'a
  pas d'effet distinct implémenté : la courbe RAW est déjà nette des coûts d'énergie par
  construction (voir `CONTEXT.md` "AU_Store"), donc ce toggle ne change rien de plus sur le seul
  exemple disponible.
- **Puissance en `power_mw=1.0` = unité par kW** : les courbes AU_Store et `COPEX_library` sont
  en €/kW ; multiplier par `power_mw` (en MW) donne directement un total en k€ (1 MW × X €/kW =
  X k€/MW = X k€ pour 1 MW) — même convention que `dev_case.py`.
- **Garde-fou explicite si `COPEX_library` n'a pas la tension demandée** (trouvé en implémentant
  la Phase 5, `docs/specs/global_sensitivity.md`) : `AU_Store` modélise HTB3 (`2h`/`4h HTB3
  Classique g0`) mais `COPEX_library` ne couvre que HTA/HTB1/HTB2 — `dev_case.capex_total_keur`/
  `opex_year1_keur` retournent silencieusement 0 pour une clé absente (`dict.get(key, {})`), sans
  conséquence pour `dev_case.py` lui-même (`VOLTAGE_CLASSES` n'expose que HTA/HTB1/HTB2, qui
  existent tous). `capex_and_opex_keur()` vérifie donc la présence de la clé **avant** d'appeler
  `dev_case.*` et lève `AuroraConfigError` sinon — un projet HTB3 aurait sinon silencieusement un
  CAPEX/OPEX à 0 (brief section 7, "zéro zéro silencieux").
- **`dsa_default_keur` = marge de dev cible (par durée BESS) + `devex_keur` déjà résolu**
  (confirmé par l'utilisateur, 2026-09-18) — prend `devex_keur` en paramètre plutôt que de
  recalculer `devex_keur_for_tension` en interne, pour qu'un DEVEX overridé par l'appelant
  (`portfolio.py`) se répercute correctement sur le DSA par défaut. Construit ainsi,
  `DSA - DEVEX = marge cible` exactement quand `strategy.compute_dev_and_sell` résout `SPA = 0`
  (le projet atteint pile le TRI cible de l'acheteur) — voir `docs/specs/strategy.md`.

## Décisions (suite)

- **Coût de repowering = Battery system + Inverter (PCS) de `COPEX_library`, à l'année civile du
  repowering** (méthodologie donnée par l'utilisateur, 2026-09-18, suite au signalement du même
  jour que seul le bénéfice — reset de dégradation — était modélisé, jamais le coût).
  `repowering_capex_keur()` réutilise `dev_case.escalated_unit_cost` (rendue publique à cette
  occasion, ex-`_escalated_unit_cost`) — même plafonnement sur le dernier delta d'escalade connu
  si l'année de repowering dépasse la couverture de la table (2028-2034 sur le fichier réel), même
  logique que pour le CAPEX initial. Seuls Battery+Inverter sont remplacés, pas les autres postes
  (Balance of system/Development/EPC/raccordement) : ce sont les seuls composants qui dégradent
  physiquement. `build_project_inputs` insère cette sortie à l'index de l'op-year de repowering
  (`library.repowering_op_year`, 15 sur le fichier réel) si `with_repowering=True` **et**
  `operating_years >= repowering_op_year` — sinon le comportement reste inchangé (pas de 2ᵉ sortie
  CAPEX). Cette 2ᵉ sortie CAPEX déclenche automatiquement la tranche de dette de repowering déjà
  gérée par `financial_engine.py` (détection générique "2ᵉ sortie CAPEX de la série") — **aucune
  modification du moteur financier n'a été nécessaire**, juste lui donner la donnée qu'il attendait
  déjà.
  Piste écartée : le coût réel observé dans `I-Project!183` (-5 723 k€ pour un projet à 16 626 k€
  de CAPEX initial, ≈34 %) — un seul point de données projet-spécifique, moins fiable que
  recomposer depuis `COPEX_library` (déjà validée, réutilisable par n'importe quelle config).

## Questions ouvertes

- **Valeur résiduelle de fin de vie non modélisée** (signalé par l'utilisateur, 2026-09-18) :
  `AU_Store!EoL_perkW` (118,44 €/kW) est chargé dans `AuStoreLibrary.eol_per_kw` mais **jamais
  utilisé** dans `build_project_inputs` — `end_of_life_keur` reste une série de zéros. Sous-estime
  légèrement le rendement des projets longs (l'effet inverse du gap repowering ci-dessus, de
  moindre ampleur). Donnée directement disponible et simple à câbler (contrairement au coût de
  repowering) si une future session veut fermer ce point.
- **Validation contre la Aurora Summary Table non reproduite exactement — écart attendu,
  confirmé par l'utilisateur.** Le brief cite "2h HTA COD 2027 = TRI 9,9 %" comme cible de
  non-régression. `COPEX_library` (466,76/35,06 €/kW, base 2028) n'est **pas** la même hypothèse
  CAPEX/OPEX que celle utilisée dans la Summary Table Aurora externe (~463/34,82 €/kW) — écart
  confirmé normal par l'utilisateur (2026-09-17), cohérent avec le constat de réconciliation déjà
  documenté au brief section 1 (l'écart BP Aurora vs Summary Table est décomposable en
  COD + CAPEX + OPEX, la courbe de revenu étant identique des deux côtés).
  En rejouant Case 33 avec les vraies valeurs Aurora (463/34,82) plutôt que `COPEX_library`, le
  NPV se rapproche nettement de la cible (-22,5 €/kW calculé vs -23,9 €/kW cible, contre un
  écart de -28 à -3 selon les hypothèses testées avec 466,76/35,06). Un écart résiduel subsiste
  sur IRR (~9,0-9,6 % calculé vs 9,9 % cible) et PV des revenus (843-927 vs 989,2 €/kW cible),
  probablement du a des conventions Aurora non documentees dans le classeur (date exacte de
  paiement du CAPEX - annee de COD ou annee precedente -, taux d'actualisation exact, assiette
  precise des frais de trading) plutot qu'a une erreur de methode - `capex_and_opex_keur()`
  utilise `COPEX_library` par design (Round 1 Q5 de la session de cadrage : reutiliser
  l'escalade deja validee plutot que de chasser un chiffre approximatif), donc ce residu est
  **accepte comme limite connue**, pas a corriger avant la Phase 3.
- **TURPE dégradé ou non** : non tranché faute de point de validation exact (voir ci-dessus) —
  actuellement non dégradé.
- **Toggle `net_of_energy_costs`** : extrait du fichier mais sans effet distinct implémenté (voir
  Décisions) — à revisiter si un projet réel l'active en désaccord avec la définition de RAW.
