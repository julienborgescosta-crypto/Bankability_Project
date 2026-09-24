# `core/aur_cases.py` — moteur de revenu Aurora (`AU_Store`)

## Objectif

Charger les 22 configurations Aurora standalone de `AU_Store` (18 standard + 4 ORO, courbes RAW/TURPE calendaires,
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

- **CAPEX de raccordement et OPEX loyer foncier challengeables individuellement** (remplace
  l'ajustement global CAPEX/OPEX en %, retiré le 2026-09-23 suite à un retour négatif — voir
  `docs/specs/portfolio.md`, "Ajustement global CAPEX/OPEX (%) — retiré"). `capex_and_opex_keur()`
  et `build_project_inputs()` acceptent désormais `connection_capex_mode` (`"library"` par défaut,
  `"manual"`, `"distance_rte"`), `manual_connection_capex_keur`, `distance_rte_km` et
  `land_lease_opex_keur`, simplement transmis à la construction interne du `DevCaseParams` (avant :
  `connection_capex_mode="library"` en dur). Aucune nouvelle formule : ce sont les modes/formule
  déjà implémentés et validés dans `dev_case.py` pour l'onglet "Cas de développement"
  (`CONNECTION_CAPEX_MODES`, `_connection_cost_from_distance(km) = 4650.7 * km**0.239`,
  `DevCaseParams.land_lease_opex_keur`) — seule nouveauté : les exposer aussi côté Configurateur/
  portefeuille, poste par poste, plutôt qu'un choc global.

- **Dimension ORO (limitation non-firm 3000h/an, Offre de Raccordement Optimisé) ajoutée**
  (demande de l'utilisateur, 2026-09-23, suite au remplacement du fixture BP par une nouvelle
  version). Aurora modélise 4 cas ORO (HTB2 injection/soutirage, 2h/4h) mais leur clé de config
  (`{durée}×{tension}×{TURPE}×{gabarit}`) était identique à celle de leur équivalent sans
  curtailment — les 6 cas ORO du databook Aurora (dont 2 doublons par année de COD) étaient donc
  écartés en silence à l'extraction, `AU_Store` ne contenait aucune courbe ORO. Corrigé par un 5ᵉ
  champ `AuStoreConfig.oro: bool` (dérivé du mot "ORO" dans `AUStoreKey`, pas d'une colonne
  metadata dédiée — aucune n'existe dans `AU_Store`) et un paramètre `oro: bool = False` sur
  `config_by_attributes()`, qui désambiguïse enfin les deux variantes.
  Le fixture fourni par l'utilisateur (nouveau `160926_BP_Stockage_Standalone__.xlsm`) contenait
  déjà les 4 colonnes RAW ORO + les lignes de métadonnées correspondantes dans `AU_Store`, mais
  **pas de bloc TURPE correspondant** (colonnes RAW ajoutées à la place où commençait l'ancien
  bloc TURPE, qui s'est retrouvé écrasé/vide) — `load_au_store` échouait donc immédiatement
  (`RAW ≠ TURPE labels`) sur ce fichier. Reconstruit manuellement depuis le databook Aurora Q2
  2026 (`Undegraded batteries`/`Degraded batteries`), avec la formule validée **exactement** (à 2
  décimales, contre les valeurs `AU_Store` déjà commitées pour "2h HTB2 injection" : 209,11/1,69 à
  2027) : `RAW = "Storage total cashflow" − "Storage volume-related network charges"`,
  `TURPE = "Storage volume-related network charges"`. Les 2 cas 2h ORO (Case 6/7, COD2027, valides
  "toute" COD) viennent directement de l'onglet `Undegraded batteries` (courbe déjà COD-indépendante,
  comme toutes les autres configs "toute"). Les 2 cas 4h ORO (Case 23/24, COD2030 uniquement)
  n'existent que dans `Degraded batteries` (pas de variante "undegraded" pour ce COD) — un nouveau
  champ `AuStoreConfig.pre_degraded: bool` (= `oro and valide_cod is not None`) indique à
  `revenue_and_turpe_series` de **ne pas** réappliquer la table `DegFactor` par-dessus une courbe
  déjà dégradée, sans quoi la dégradation serait comptée deux fois.
  Limite documentée : le repowering (op-year 15) déclenche quand même le CAPEX de remplacement
  (`repowering_capex_keur`) pour ces 2 configs `pre_degraded`, mais son bénéfice (reset de
  dégradation) n'est pas modélisé — la trajectoire Aurora source ne porte aucun mécanisme de reset.
  UI (`ui/configurateur_tab.py`) : toggle "ORO" à côté du gabarit. Depuis le 2026-09-24, une
  demande d'ORO (ou de type TURPE/gabarit) sur une combinaison non modélisée n'est plus bloquée ni
  repliée silencieusement sur la courbe standard : elle est **extrapolée** par
  `core.config_extrapolation.resolve_config()` (`PortfolioRow.extrapolated`/`extrapolation_notes`,
  jamais un revenu nul ni un repli invisible) — voir `docs/specs/config_extrapolation.md` et
  `docs/specs/portfolio.md`.

- **Les courbes RAW/TURPE viennent maintenant d'un asset statique**
  (`config/aurora_curves_22configs.json`, `load_aurora_curves()`), pas d'un `AU_Store` re-parsé à
  chaque upload — décision de l'utilisateur, 2026-09-24, suite à une triangulation à 3 sources
  (fichier `AU_Store` multi-config, databook Aurora Q2 26 brut, connecteur Aurora live) qui a
  confirmé que ces 22 courbes sont universelles (mêmes valeurs pour tout projet, vérifiées à la
  décimale près contre le databook). `ui/configurateur_tab.py` appelle `load_aurora_curves()` au
  lieu de `load_au_store(SAMPLE_AURORA_BP_PATH)` ; `COPEX_library` (CAPEX/OPEX), lui, reste lu
  depuis le fixture Aurora commité (poste indépendant des courbes de revenu).
  Toutes les configs de ce JSON portent `pre_degraded=False` : contrairement au format `AU_Store`
  historique (où les 2 cas ORO verrouillés à COD2030 stockent la valeur déjà dégradée, court-
  circuitant `DegFactor`), ces courbes ont été "un-dégradées" à la source pour ces mêmes cas —
  `RAW/TURPE[année] × DegFactor[op_year]` reproduit exactement le cashflow Aurora Degraded pour
  COD2030 avec la formule uniforme, sans cas particulier. Vérifié : les 2 conventions (JSON
  un-dégradé × DegFactor, vs `AU_Store` historique déjà dégradé × 1.0) retombent sur exactement le
  même revenu/TURPE final, config par config, année par année (240 points de contrôle sur les 4
  configs verrouillées COD2030).
  **Diagnostic de l'écart TURPE/RAW signalé initialement** (session du 2026-09-23/24) : l'écart
  ~2x sur TURPE (et ~2% sur RAW) mesuré en triangulant l'app contre l'API Aurora venait du fixture
  *legacy* `fichier_excel/260612_BP_Stockage_Standalone__.xlsm` (projet Belle Épine, single-config,
  antérieur à l'architecture multi-config) — ce fichier appliquait une seule courbe `Raw2h`/`TURPE_var_2h`
  codée en dur (millésime `2h HTB2`) quelle que soit la tension réelle du projet (HTB1 dans ce cas),
  d'où un TURPE à moitié du vrai HTB1. L'architecture multi-config (`AU_Store` 22 configs,
  `aur_cases.py`) n'a jamais eu ce bug — vérifié en triangulant directement le fichier `160926`
  multi-config contre le databook brut (RAW et TURPE identiques à la décimale pour HTA/HTB1/HTB2).
- **`load_au_store()` localise le bloc TURPE par libellé, pas par décalage fixe** (robustesse
  demandée par l'utilisateur, 2026-09-24) : 2 mises en page rencontrées dans la vraie vie — à côté
  du bloc RAW sur la même ligne d'en-tête (historique, ex. fixture `160926_BP_Stockage_Standalone__.xlsx`
  committé), ou empilé dessous comme son propre bloc `Year` (BP `160926.xlsm` frais fourni le
  2026-09-24, après l'ajout des configs ORO — le bloc TURPE s'est retrouvé décalé sous le bloc RAW
  plutôt qu'à côté). `_find_stacked_turpe_header_row()` cherche un 2e bloc `Year` portant
  exactement les mêmes labels que RAW, où qu'il soit dans la feuille. Si aucune des deux mises en
  page ne matche → `AuroraConfigError` explicite, jamais un TURPE à 0 silencieux (voir README
  "zéro zéro silencieux"). Ce chemin (`load_au_store`, lecture d'un `AU_Store` réel) reste
  disponible comme fallback/robustesse, mais n'est plus le chemin utilisé par le Configurateur.

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
