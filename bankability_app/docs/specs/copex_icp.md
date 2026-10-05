# `core/copex_icp.py` — CAPEX/OPEX depuis l'ICP (couts unitaires QEF reels)

Spec retrospective.

## Objectif

Depuis le 2026-09-24, le CAPEX/OPEX BESS de l'app (Configurateur/Portfolio/Sensibilite globale)
vient en priorite de `config/copex_icp.xlsx` ("ICP" — Internal Cost Pricing, couts unitaires reels
maintenus par l'utilisateur, mis a jour mensuellement en remplacant ce fichier), plutot que de la
bibliotheque Aurora `COPEX_library` (qui reste une estimation generique, moins a jour). Aurora
`COPEX_library` reste utilisee comme **repli** pour les postes qu'ICP ne couvre pas : `Development`
cote CAPEX, `Insurance`/`Grid charges`/`Land lease`(ligne bibliotheque)/`Accise`/`Other` cote OPEX,
et **HTB3 entierement** (ICP n'a jamais eu de colonne pour cette tension). Voir `core/aur_cases.py`
`capex_and_opex_keur()`/`repowering_capex_keur()` pour le point d'integration.

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
