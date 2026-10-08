# `core/copex_icp.py` — CAPEX/OPEX depuis l'ICP (couts unitaires QEF reels)

Spec retrospective.

## Objectif

Depuis le 2026-09-24, le CAPEX/OPEX BESS de l'app (Configurateur/Portfolio/Sensibilite globale)
vient en priorite de `config/copex_icp.xlsx` ("ICP" — Internal Cost Pricing, couts unitaires reels
maintenus par l'utilisateur, mis a jour mensuellement en remplacant ce fichier), plutot que de la
bibliotheque Aurora `COPEX_library` (qui reste une estimation generique, moins a jour). Aurora
`COPEX_library` reste utilisee comme **repli** pour les postes qu'ICP ne couvre toujours pas :
`Land lease`(ligne bibliotheque, quand non renseigne par l'utilisateur) cote OPEX, et **HTB3
entierement** (ICP n'a jamais eu de colonne pour cette tension). Voir `core/aur_cases.py`
`capex_and_opex_keur()`/`repowering_capex_keur()` pour le point d'integration.

Depuis le 2026-10-08 ("je ne veux plus reprendre aucune hypothese Aurora, tous nos couts viennent
de la COPEX Library maintenant" — demande explicite de l'utilisateur), les derniers postes qui
repliaient encore sur Aurora ont chacun une ligne ICP dediee : `Development`/`Asset Management
(construction)` cote CAPEX, `Insurance (operation)`/`Other (Admin/Accounting/Communication)`/
`Asset Management (operation)` cote OPEX. Seuls `Land lease` (quand non renseigne) et HTB3 restent
un repli Aurora, faute d'alternative ICP. `Grid charges`/`Accise` ne sont plus un repli Aurora non
plus, mais pas davantage une ligne ICP : ils sont calcules precisement par
`core/opex_grid_charges.py` (voir `docs/specs/opex_grid_charges.md`).

## Pourquoi ce changement

Demande de l'utilisateur, 2026-09-24 — pour "eviter un detour" (ne plus re-committer/re-parser un
fixture BP entier pour changer une hypothese CAPEX/OPEX) et parce qu'ICP contient des couts reels
maintenus activement par QEF (source ICP mise a jour mensuellement, cf. cellule `C2` "Update ICP"),
la ou Aurora `COPEX_library` est une estimation generique figee (base 2028, extraite d'un BP
donne). Le fichier reste committe dans `config/` (option choisie par l'utilisateur, cf. session de
cadrage) sous un **nom stable** `copex_icp.xlsx` — remplacer son contenu chaque mois, pas son nom,
pour qu'aucun changement de code ne soit necessaire a chaque mise a jour.

## Structure du fichier source (`config/copex_icp.xlsx`, version V1_20261001)

Depuis le 2026-10-05, `config/copex_icp.xlsx` est la COPEX Library QEF "LIVE" (fichier
`LIVE_v1_20261001_COPEX LIBRARY.xlsx` fourni par l'utilisateur), qui remplace l'export ICP du
22/05/2026. Onglet `COPEX_library` (l'ancien nom `CAPEX_library` reste accepte), table
"Hypotheses CAPEX BP - BESS Standalone". Tout est lu **par libelle** (`load_icp_library`) :

- **ligne d'en-tete "Case"** : les segments (`Industrial-New trench`, `Industrial-Existing trench`,
  `TSO 63kV`, `TSO 90kV`, `TSO 225kV`, `DSO`, `DSO`) puis les annees du "Forecast price factor
  (selon annee de NTP)" (2027-2032). Les 2 colonnes `DSO` (2h/4h dans la table de correspondance
  R8:S15) sont identiques : fusionnees, et le chargement echoue si elles divergent un jour. La
  colonne `Hybrid PV` de l'ancienne version a disparu.
- **lignes reperees par leur libelle en colonne A** (la 1re occurrence : les blocs "CAPEX/OPEX
  assumptions - AURORA (base 2028)" qui suivent dans le meme onglet reutilisent certains libelles ;
  ils sont identiques au `COPEX_library` du fixture, verifie le 2026-10-05, et ne sont pas lus) :
  `Batteries and PCS - 2h`/`- 4h` (valeurs €/MWh par segment : 123 200 en TSO "75MWh+", 125 600 en
  DSO "[0-75MWh]" pour le 2h ; 106 100/108 200 en 4h), les 8 postes directs, `Grid connection`,
  `OPEX - Guarantees & preventive maint - 2h (annual)`/`- 4h (annual)`, `OPEX - O&M (annual cost)`,
  `Insurances during construction`, `EPC Margin`, `EPC Contingency` (nouveau, 7 %).
- **unite lue dans le format de chaque cellule** (`_unit_from_number_format`, inchange).

Le bloc "OPEX legacy - Source OPEX Library (Jan 2024) - A METTRE A JOUR" (Telecom 2,4 k€/an,
Asset Management 40 k€/an) n'est pas utilise.

## Decisions (confirmees par l'utilisateur, session de cadrage 2026-09-24)

- **L'unite varie par cellule, pas par ligne** — une meme ligne (ex. `Grid connection`,
  `HV substation`) melange `€/MWh`, `€/MW` et `k€` forfait selon la colonne. **Jamais deduite de la
  valeur brute** : toujours lue depuis `cell.number_format` (suffixe entre guillemets), via
  `_unit_from_number_format()`. Garantit que l'unite suit automatiquement une mise a jour mensuelle
  du fichier, meme si une ligne change d'unite entre-temps.
- **V1_20261001 (2026-10-05)** :
  - **Batteries + PCS en valeurs par segment** (€/MWh), plus en loi de puissance : la V1 fixe 2 prix
    selon la taille (TSO = projets de 75 MWh et plus, DSO = moins de 75 MWh).
  - **Garanties : la loi de puissance est relue dans la formule** du fichier
    (`=794.13*'[2]I-Project'!$G$28^(-0.61)*1000`, liee a la taille du BP 160926, 80 MWh en cache)
    et re-evaluee a la taille de chaque projet (`IcpPowerLaw`, `_POWER_LAW_FORMULA`). La valeur est
    un **total sur 15 ans** malgre le libelle "(annual)" (decision de l'utilisateur, 2026-10-05) :
    lue comme annuelle, elle donnerait ~110 k€/MW/an, 10 fois Aurora et Greensolver. Etalee sur
    15 ans et payee chaque annee de la vie du projet (decision du 2026-10-02).
  - **O&M en "k€/y"** : lu en k€/MWh/an, comme la version precedente (meme valeur, 2) - 2 k€/an pour
    tout un projet n'a pas de sens. A confirmer par l'equipe OPEX.
  - **Communication** passe de €/MW a €/MWh dans le format de la cellule : suivi tel quel.
  - **Raccordement DSO** : le fichier indique 0,3 k€, erreur de saisie - **300 k€** (confirme par
    l'utilisateur, 2026-10-05), corrige a l'installation (`--dso-grid-connection-keur 300`, voir
    ci-dessous). Le test `test_hta_grid_connection_is_300_keur` rattrapera la meme erreur dans une
    prochaine version.
  - **Aleas EPC (`EPC Contingency`, 7 %)** appliques comme la marge EPC : construction x (1 + marge)
    x (1 + aleas) x (1 + assurance construction) (`construction_markup_factor`), jamais au
    raccordement ni au developpement (decision de l'utilisateur, 2026-10-05).
  - **Indexation sur l'annee de NTP = COD - 1** (`NTP_YEARS_BEFORE_COD`, decision du 2026-10-05),
    meme convention que le paiement du CAPEX ; vaut pour toutes les lignes de la COPEX Library
    (CAPEX, O&M, garanties, repowering valorise a son annee de NTP). Avant la 1re annee de la table
    (2027), multiplicateur 1,0 ; au-dela de 2032, plafonne sur 2032.
  - Le fichier source embarque des **liens externes** vers 3 classeurs du OneDrive de l'utilisateur
    (BP Kerlo, BP 160926, Estimation_Projets_bess) avec quelques cellules en cache - l'ancienne
    version commitee en avait deja. **Retires a l'installation** (decision de l'utilisateur,
    2026-10-05) : `config/copex_icp.xlsx` est committe, jamais un BP reel.
- **V2 - JFE - 08/10/2026 (installee le 2026-10-08)** :
  - Raccordement DSO deja correct a 300 k€ dans le fichier source - pas besoin de
    `--dso-grid-connection-keur` cette fois (verifie a l'installation).
  - Mapping segment -> tension redevenu coherent avec notre table figee
    (`TENSION_TO_ICP_SEGMENT`) : `TSO 225kV -> HTB2` (une version intermediaire du meme jour
    l'avait brievement libelle `HTB3`, traite comme une erreur de saisie, voir plus bas - le
    fichier final confirme `HTB2`).
  - Libelle "Insurances during construction..." devenu "Insurances construction..." (mot
    "during" retire) - `_pct()` cherche desormais 2 morceaux ("Insurances", "construction")
    au lieu d'une chaine complete, pour matcher les deux sans ambiguite avec la nouvelle ligne
    "Insurances operation (% Capex + 1y incomes)" (non utilisee).
  - 4 nouvelles lignes ICP, toutes activees le meme jour (voir bullet "V2 bis" ci-dessous) :
    "Asset Management construction (incl. Cout fixe ISA)", "Asset Management operation (annual
    cost)" (valeur en formule texte, "400€/MWh + 18k€"), "Insurances operation (% Capex + 1y
    incomes)" (idem, "0,45% + 1y income"), "Other (Admin/Accounting/Communication)". La ligne
    "Telecom (annual)" du bloc legacy a ete retiree du fichier source par l'utilisateur le
    2026-10-08 (jamais lue par le code, deja incluse dans "Asset Management operation" selon
    l'utilisateur - aucun impact).
- **V2 bis - "plus aucune hypothese Aurora" (2026-10-08, meme jour)** : l'utilisateur a demande que
  les 4 nouvelles lignes ci-dessus remplacent les derniers replis Aurora generiques, plutot que de
  rester inutilisees :
  - **"Asset Management construction"** (70 k€, format Excel `k€` plat comme "Other BoP cost" -
    jamais scale par MW) : ajoute au CAPEX **apres** la marge EPC/assurance construction, comme
    `Development` (`icp_capex_total_keur`) - "Cost Owner : ASSET", pas "Cost Owner : EPC", donc hors
    perimetre de ce markup. Decision de l'utilisateur (option recommandee).
  - **"Other (Admin/Accounting/Communication)"** (8 k€ plat, pas d'escalade dans le fichier) :
    remplace la ligne de repli Aurora "Other" dans `icp_opex_year1_keur`.
  - **"Insurances operation (% Capex + 1y incomes)"** : remplace la ligne de repli Aurora
    "Insurance". Formule confirmee par l'utilisateur apres relecture du libelle (qui dit "+", pas
    "x") : `0,45% x (CAPEX total + revenu annee 1)`, PAS `0,45% x CAPEX x revenu` (ordre de
    grandeur incoherent - une prime d'assurance a plusieurs dizaines de M€ n'a pas de sens). "CAPEX
    total" = le CAPEX complet du projet (construction + Development + Asset Management + Grid
    connection, le meme total que `capex_initial_keur`) ; "revenu annee 1" = le revenu de la 1re
    annee d'exploitation du projet, sur la base des scenarios Aurora ("tu prends les revenus sur 1
    annee sur la base des scenarios Aurora"). Pas d'escalade (la ligne n'a pas de "Forecast price
    factor" dans le fichier, et CAPEX/revenu sont deja des montants de l'annee consideree).
    Nouveau parametre `revenue_year1_keur` sur `icp_opex_year1_keur`/`aur_cases.capex_and_opex_keur`
    (0.0 par defaut si l'appelant ne le fournit pas - sous-estime ce seul poste, jamais une erreur
    silencieuse ailleurs). Consequence notable : l'OPEX d'un projet n'est plus totalement
    independant de son CAPEX (ex. changer `connection_capex_mode` change aussi legerement l'OPEX
    via ce poste) - voir `tests/test_portfolio.py
    test_build_project_inputs_connection_capex_manual_overrides_library`.
  - **"Asset Management operation (annual cost)"** = "400€/MWh + 18k€" (energie utile du projet,
    `power_mw x duree_h`) : nouveau poste purement additif, aucun equivalent Aurora a remplacer.
    Escalade sur l'annee de NTP comme le reste de l'OPEX (`icp_asset_management_operation_keur`).
  - **Portee du changement, confirmee par l'utilisateur** : uniquement le chemin ICP
    (`aur_cases.capex_and_opex_keur`) - `capex_and_opex_keur_aurora_only` (option "Use Aurora's own
    CAPEX/OPEX assumptions" du Configurateur) garde les lignes Aurora brutes pour rester une base de
    comparaison "100% Aurora" pure ("sauf quand on coche l'option de reprendre TOUTES les
    hypotheses AURORA pour comparer"). `core/dev_case.py` (onglet "Cas de developpement", lecture
    BP single-project, utilise la section Aurora "base 2028" du propre onglet `COPEX_library` du
    BP) est un chemin independant, non concerne par ce changement.
  - **`core/copex_comparison.py` mis a jour en consequence** : "Asset Management (construction)"
    compte desormais dans `TOTAL CAPEX`, "Insurance (operation)"/"Other"/"Asset Management
    (operation)" ont chacun leur propre ligne OPEX (ours = ICP, aurora = l'estimation Aurora
    generique pour comparaison) au lieu d'etre noyes dans le groupe "Info only". Seuls `Grid
    charges`/`Accise` restent "Info only" = Aurora des 2 cotes (le calcul precis
    `opex_grid_charges` n'est pas encore reflete dans cet ecran de comparaison poste par poste -
    limite documentee, voir `docs/specs/opex_grid_charges.md`).
- **V2 ter - formule de "OPEX - Guarantees & prev maint" restauree en texte (2026-10-08, 3e revision
  du meme jour)** : l'utilisateur a "remis les formules" sur cette ligne (perdue lors de
  l'aplatissement en valeurs fixes des revisions precedentes - 54 828,54/28 375,89 €/MWh pour
  2h/4h). Contrairement a l'ancienne formule Excel (`=794.13*'[2]I-Project'!$G$28^(-0.61)*1000`,
  avec une reference externe retiree a chaque installation), la loi de puissance est maintenant du
  **texte descriptif**, pas une formule Excel executable : `"794,13 × MWh^(-0,61) k€/MWh"` (2h),
  `"1 408 × MWh^(-0,891) k€/MWh"` (4h) - memes libelles de ligne suffixes d'un "(15 y)" explicite,
  pour clarifier que la valeur est un total sur 15 ans (confirme par l'utilisateur, deja la
  convention du moteur depuis le 2026-10-02, voir plus bas). Meme coefficient/exposant que l'ancienne
  formule (verifie : 794.13/-0.61 reproduit l'ordre de grandeur historiquement valide, "170-300 k€/an
  pour 40 MW 2h") → meme interpretation du coefficient (`eur_per_kwh`, voir "Bugs corriges"),
  malgre le suffixe de texte "k€/MWh" qui suggererait une autre unite - meme precedent que le
  mislabeling Excel deja rencontre, pas une raison de changer la convention deja validee. Nouveau
  parseur `_TEXT_POWER_LAW_FORMULA` (sur `cell.value`, pas `ws_formulas` puisque ce n'est plus une
  formule) en complement de `_POWER_LAW_FORMULA` (garde la compatibilite si une future version
  revient a une vraie formule Excel).
  - **Confirmation explicite de l'utilisateur sur le prorata au-dela de 15 ans** : "si projet 20 ans
    faire pro-rata pour l'instant et si 30 ans x 2". Deja le comportement du moteur PAR CONSTRUCTION,
    sans changement de code necessaire : le taux annualise (`total_15y / GUARANTEES_DURATION_YEARS`)
    est applique identiquement **chaque annee de la vie du projet** quelle que soit sa duree
    (`aur_cases.opex_series_keur`, convention OPEX plat) - le total paye sur N annees vaut donc
    automatiquement `total_15y x N/15` : 20/15 = 1,33x (prorata d'une periode partielle), 30/15 = 2x
    (2 periodes completes). Verrouille par
    `tests/test_copex_icp.py::test_icp_opex_guarantees_prorates_over_longer_project_life`. Limite
    assumee (deja documentee) : pas de vrai "saut" a l'annee 15/30 (rachat explicite d'un 2e
    contrat) - juste un lissage continu, different d'un vrai echeancier d'achat mais
    mathematiquement equivalent au total.
- **Installer une nouvelle version** : `.venv\Scripts\python.exe sample_data/install_copex_library.py
  "<COPEX LIBRARY.xlsx>" [--dso-grid-connection-keur 300]`. Le script copie le classeur dans
  `config/copex_icp.xlsx` en travaillant sur son XML (openpyxl effacerait les valeurs en cache des
  formules) : il retire les liens externes et les noms definis qui en dependent, remplace chaque
  reference externe d'une formule par sa valeur en cache (`=794.13*'[2]I-Project'!$G$28^(-0.61)*1000`
  devient `=794.13*80^(-0.61)*1000`, que l'app relit comme loi de puissance), applique l'eventuelle
  correction du raccordement DSO, puis affiche les valeurs cles relues par `core.copex_icp` (avec
  une alerte si un raccordement est inferieur a 1 k€). Les metadonnees SharePoint du document
  lui-meme (identifiant documentaire) restent, comme dans la version precedente.
- **Base du power-law (`OPEX Guarantees`) = MWh nominal du projet en cours**
  (`power_mw x duree_h`, nameplate — pas l'energie utile apres pertes/DoD). Formule auto-referente :
  une loi de puissance `base x MWh^exposant` n'a de sens que si `MWh` est la taille du projet qu'on
  modelise (c'est ce qui produit l'economie d'echelle) — si `MWh` etait une constante de reference,
  le fichier aurait fige directement le `€/MWh` resultant plutot que de garder une formule.
  `cout_total_keur = (base x MWh^exposant) x MWh` — **`base` est en EUR/kWh, pas EUR/MWh malgre le
  libelle Excel** de la cellule (`"156,37*MWh^(-0,051) €/MWh"`) : voir "Bugs corriges" ci-dessous.
- **`OPEX - Guarantees & preventive maint` est un cout total pour 15 ans**, pas un taux annuel —
  etale lineairement (`/15`) et paye **chaque annee de la vie du projet** (`opex_year1_keur`
  constant) : decision de l'utilisateur du 2026-10-02, apres essai d'une version limitee aux 15
  premieres annees de chaque batterie (annulee).
- **Agregation CAPEX = (somme des postes directs) x (1 + EPC Margin) x (1 + EPC Contingency depuis
  la V1_20261001) x (1 + Insurance)**, dans cet
  ordre conceptuellement (meme si commutatif numeriquement, ecart <0.05% du CAPEX entre les 2
  ordres) : l'assurance "Insurances during construction (% of **Total Capex**)" porte sur le total
  incluant la marge EPC (convention assurance Construction All Risks classique — on assure la
  valeur totale de construction, marge contractant incluse), tandis que la marge EPC elle-meme ne
  porte que sur les travaux (elle est hors perimetre du poste "assurance construction", qui est un
  cout proprietaire/developpeur, pas un cout de l'entreprise EPC).
- **`Development` (CAPEX) reste additif, hors marquage EPC/assurance** : c'est un cout de
  developpement/origination (etudes, permitting, foncier), pas un cout de construction — la marge
  EPC et l'assurance chantier ne s'y appliquent pas. Absent d'ICP, source Aurora `COPEX_library`.
  **Depuis le 2026-10-02, le moteur Aurora v2 lui substitue le DSA du projet** (marge de dev cible
  50 k€/MW en 2h / 80 k€/MW en 4h + DEVEX 150 k€ HTA / 300 k€ HTB, ou l'override du projet) via
  `icp_capex_total_keur(development_keur=...)` - decision de l'utilisateur, voir
  `docs/specs/strategy.md`. La ligne Aurora ne sert plus que si l'appelant ne fournit rien.
- **Mapping tension -> segment ICP**, reprenant le mapping deja etabli ailleurs dans l'app (voir
  `docs/specs/dev_case.md` "Deux taxonomies de segment coexistent") : `DSO -> HTA`,
  `TSO 63kV/90kV -> HTB1`, `TSO 225kV -> HTB2`. **`TSO 90kV` retenu comme representant HTB1**
  (63kV et 90kV ne different que sur `HV Transformer`/`HV substation`, ecart <12% — le reste des
  postes est identique entre les 2 colonnes sur le fichier reel) — choix documente ici, revisable
  si le fichier ICP diverge davantage a l'avenir. **HTB3 n'a pas de colonne ICP** (n'en a jamais
  eu) — reste entierement source par Aurora `COPEX_library`, comme avant ce changement (meme limite
  pre-existante : HTB3 est aussi absent d'Aurora `COPEX_library`, garde-fou explicite dans
  `aur_cases.capex_and_opex_keur()`, inchange).
- **Repowering suit desormais ICP** (`icp_repowering_capex_keur`, formule `Batteries and PCS`
  valuee a l'annee civile du repowering) plutot que de rester fige sur Aurora `Battery system +
  Inverter` — coherence : le meme composant remplace doit suivre le meme modele de cout que sa
  premiere pose, pas un cout Aurora fige pendant que le CAPEX initial suit ICP.
- **`Grid connection` reste gere separement** du reste du CAPEX generique (comme avant ce
  changement — `connection_capex_mode`), simplement source depuis ICP en mode `"library"` quand la
  tension est couverte (sinon Aurora). Les 3 autres modes (`manual`/`distance_rte`/
  `distance_rte_and_substation`) sont inchanges (valeurs/formules saisies directement, pas des
  couts de bibliotheque).
- **Pas de threading d'`IcpCostLibrary` a travers tout l'appel (`portfolio.py`,
  `global_sensitivity.py`, `config_space.py`, UI)** — `capex_and_opex_keur()`/
  `repowering_capex_keur()` chargent l'ICP en interne via `load_icp_library_cached()`
  (`functools.lru_cache`, le fichier n'est relu qu'une fois par process malgre potentiellement des
  milliers d'appels pendant une sensibilite globale). Choix delibere pour minimiser la surface de
  changement : `copex_library` (Aurora) reste le seul parametre requis par l'ensemble des fonctions
  existantes, inchange, maintenant utilise uniquement comme repli.
- **`capex_opex_source_notes(tension)`** : note statique (pas un calcul precis par projet) pour
  l'UI, affichee dans un expander pres des controles CAPEX raccordement/OPEX loyer foncier
  (`ui/configurateur_tab.py`) — liste quels postes viennent d'ICP vs d'Aurora pour la tension
  choisie, jamais un repli silencieux (discipline "zero zero silencieux" du repo).

## Bugs corriges

- **`_power_law_cost_keur` divisait par 1000 en trop (2026-09-24)** — decouvert lors d'un test de
  coherence globale demande par l'utilisateur ("si on reprend CAPEX/OPEX Aurora sur la meme config,
  arrive-t-on au meme TRI Projet ?"). En comparant, config par config (HTA/HTB1/HTB2 x 2h/4h), le
  CAPEX ICP au CAPEX Aurora equivalent (memes revenu/financement, seul le CAPEX/OPEX source varie),
  l'ecart observe etait enorme et incoherent : -55% a -57% sur HTA (+22 points de TRI Projet), la ou
  un simple changement de source de cout ne devrait pas a lui seul faire ~tripler le TRI. Cause :
  `formula.base` (ex. `156.37` pour `Batteries and PCS` 2h) est en **EUR/kWh**, pas EUR/MWh comme le
  suggere le libelle Excel de la cellule (`"156,37*MWh^(-0,051) €/MWh"` — mislabeling du fichier
  source, pas du code) ; le code divisait quand meme le total par 1000 en plus, donnant un cout
  Batteries+PCS d'environ 0.1 €/kWh installe pour un BESS 40 MW/2h — physiquement impossible (plage
  reelle : 100-300+ €/kWh). Corrige en retirant cette division (`core/copex_icp.py`
  `_power_law_cost_keur`). Verification post-correction : le CAPEX HTA recalcule (18 711 k€) tombe a
  moins de 0.5% du CAPEX Aurora HTA validee independamment a l'euro pres (18 670 k€, voir
  `docs/specs/dev_case.md`) — un point de recoupement qui n'existait pas cote ICP avant cette
  correction (voir "Questions ouvertes" ci-dessous, 1er point). L'ecart residuel post-correction
  (+19 a +23% sur HTB1/HTB2) est attribuable a des postes qu'ICP detaille (`HV Transformer`/
  `HV substation`, plusieurs milliers de k€ forfait) et qu'Aurora ne modelisait que dans une ligne
  generique `Balance of system` — coherent avec la logique du changement (ICP = couts reels
  detailles), pas un signe de bug supplementaire. Meme correction appliquee a `OPEX - Guarantees`
  (le seul autre poste en power-law) : l'OPEX de garantie annualise passe de ~0.2-0.3 k€/an
  (negligeable, donc jamais remarque) a 170-300 k€/an pour un projet 40 MW.
  Garde-fous de non-regression sur l'ordre de grandeur (pas une valeur exacte, qui bougera a chaque
  mise a jour mensuelle du fichier ICP) : `tests/test_copex_icp.py`
  `test_icp_battery_pcs_keur_order_of_magnitude_is_realistic` /
  `test_icp_opex_guarantees_order_of_magnitude_is_realistic`.

- **`_header()` dependait du libelle exact de la cellule de tete de la ligne d'en-tete
  ("Case" en V1_20261001) - casse des la V2 du 2026-10-08, qui renomme cette cellule
  "Cost Owner : EPC" (meme ligne, meme structure, juste un changement cosmetique de
  libelle). Plutot que d'ajouter un 2e libelle en dur (fragile a la prochaine
  renomination), `_header()` reconnait desormais la ligne d'en-tete **structurellement** :
  elle cherche un run d'au moins 3 annees consecutives 2000-2100 (le bloc "Forecast price
  factor"), puis remonte en arriere pour collecter les libelles de segment contigus juste
  avant (en sautant un eventuel trou) - independant de ce qu'il y a dans la toute premiere
  cellule de la ligne. `_find_row()` (recherche des lignes de postes par libelle) reste
  inchangee, elle n'a jamais depende de cette cellule de tete.

- **`_header()` incluait la colonne de libelle de ligne ("Cost Owner : EPC") comme un faux
  "segment" supplementaire** - decouvert le 2026-10-08 en ajoutant `_read_formula_row` (lecture des
  2 nouvelles lignes texte "Asset Management operation"/"Insurances operation") : le balayage
  arriere depuis le bloc d'annees collecte toute cellule texte contigue, y compris la colonne de
  libelle elle-meme (adjacente aux vrais segments, sans trou pour la distinguer). Invisible
  jusqu'ici : les lecteurs numeriques (`_read_line_item_row`) ignorent silencieusement cette
  pseudo-colonne (son contenu - le libelle de CHAQUE ligne - n'est jamais un nombre), mais
  `_read_formula_row` (qui accepte tout texte) la traitait comme une vraie valeur a parser et
  levait une erreur. Corrige en filtrant les colonnes candidates sur un critere structurel plutot
  qu'une position : une colonne n'est retenue comme segment que si elle contient AU MOINS une
  valeur numerique sur les lignes de donnees suivantes (`_column_has_numeric_value_below`) - la
  colonne de libelle ne contient jamais que du texte, sur aucune ligne.

## Questions ouvertes

- **A confirmer avec l'equipe OPEX (2026-10-05)** : unite de l'O&M ("k€/y" lu en k€/MWh/an),
  lecture "total 15 ans" de la ligne garanties malgre son libelle "(annual)", perimetre de cette
  ligne (recoupement avec l'O&M - chez Greensolver, l'O&M inclut deja la garantie de performance du
  fabricant), multiplicateur 2032 = 1,0 de la ligne Batteries 2h (rupture par rapport a 1,007 en
  2031), raccordement DSO a corriger a 300 k€ dans le fichier source. Avec la courbe des garanties,
  notre O&M fixe sort 1,25 a 3,4 fois celui d'Aurora, surtout sur les petits projets.
- **Pas de ligne "Total" dans le fichier ICP pour verifier l'agregation EPC Margin/Insurance a
  l'euro pres** (contrairement au CAPEX ligne "Battery system"/etc. d'Aurora, valide exactement
  contre `Advise Dev` du BP reel) — la formule d'agregation est confirmee par l'utilisateur
  (raisonnement metier : convention assurance CAR/TRC), pas verifiee contre un total source. Le
  recoupement HTA post-correction (voir "Bugs corriges", <0.5% d'ecart avec Aurora) est rassurant
  mais reste un proxy indirect, pas une ligne "Total" ICP native — a refaire si un total source
  devient disponible.
- **Mapping TSO 90kV pour HTB1** perd la distinction 63kV/90kV que le fichier ICP fournit
  desormais (contrairement a Aurora `COPEX_library`, qui n'a jamais distingue les deux) — ecart
  mineur (<12% sur 2 postes seulement) mais une vraie perte de precision par rapport a ce que le
  fichier source permettrait. Non resolu : ferait basculer toute la modelisation HTB1 vers une
  distinction 63kV/90kV a travers l'app (AU_Store/CF Aurora n'ont eux non plus qu'une seule courbe
  HTB1), hors perimetre de ce changement.
- **`Insurances during construction`/`EPC Margin` ne varient pas par segment dans le fichier
  actuel** (0.9%/5% partout) — le code lit neanmoins ces valeurs par segment (`insurance_
  construction_pct: dict[str, float]`, pas un scalaire), au cas ou une future version du fichier
  les differencie.
