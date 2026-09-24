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

## Structure du fichier source (`config/copex_icp.xlsx`, onglet `CAPEX_library`)

Table "Hypothesys CAPEX BP from ICP" — 1 ligne par poste, colonnes C-I (7 segments) :
`Industrial-New trench`, `Industrial-Existing trench`, `TSO 63kV`, `TSO 90kV`, `TSO 225kV`, `DSO`,
`Hybrid PV`. Colonnes K-P : multiplicateur d'escalade par annee (K = annee de base ~2026 = 1.0,
L-P = 2027-2031), **le meme multiplicateur pour les 7 colonnes d'une ligne** (verifie sur le
fichier reel — pas de dimension segment sur l'escalade).

Postes CAPEX (lignes "a valeur plate", `_DIRECT_CAPEX_LABELS`) : `Electrical works and studies`,
`Civil Works and miscellaneous`, `HV Transformer`, `HV substation`, `MV substation`,
`Communication`, `Other BoP cost`, `Integration`. Poste OPEX plat : `OPEX - O&M (annual cost)`.
Poste raccordement (gere separement, voir plus bas) : `Grid connection`.

Postes en power-law (base × MWh^exposant, `IcpPowerLawCost`) : `Batteries and PCS` (2 lignes 2h/4h,
**pas de dimension segment** — une seule formule nationale, colonnes C:G fusionnees en texte
d'affichage) et `OPEX - Guarantees & preventive maint (15 years)` (idem, 2 lignes 2h/4h).

Postes en % : `Insurances during construction (% of Total Capex)`, `EPC Margin`.

## Decisions (confirmees par l'utilisateur, session de cadrage 2026-09-24)

- **L'unite varie par cellule, pas par ligne** — une meme ligne (ex. `Grid connection`,
  `HV substation`) melange `€/MWh`, `€/MW` et `k€` forfait selon la colonne. **Jamais deduite de la
  valeur brute** : toujours lue depuis `cell.number_format` (suffixe entre guillemets), via
  `_unit_from_number_format()`. Garantit que l'unite suit automatiquement une mise a jour mensuelle
  du fichier, meme si une ligne change d'unite entre-temps.
- **Base du power-law (`Batteries and PCS`/`OPEX Guarantees`) = MWh nominal du projet en cours**
  (`power_mw x duree_h`, nameplate — pas l'energie utile apres pertes/DoD). Formule auto-referente :
  une loi de puissance `base x MWh^exposant` n'a de sens que si `MWh` est la taille du projet qu'on
  modelise (c'est ce qui produit l'economie d'echelle) — si `MWh` etait une constante de reference,
  le fichier aurait fige directement le `€/MWh` resultant plutot que de garder une formule.
  `cout_total_keur = (base x MWh^exposant) x MWh` — **`base` est en EUR/kWh, pas EUR/MWh malgre le
  libelle Excel** de la cellule (`"156,37*MWh^(-0,051) €/MWh"`) : voir "Bugs corriges" ci-dessous.
- **`OPEX - Guarantees & preventive maint (15 years)` est un cout total pour 15 ans**, pas un taux
  annuel — etale lineairement (`/15`) et ajoute comme une **addition constante** a l'OPEX annuel
  (`opex_year1_keur`), pas une charge limitee aux 15 premieres annees. Simplification : le moteur
  financier n'a pas de notion d'OPEX variable dans le temps aujourd'hui (`opex_keur` repete
  `opex_year1_keur` identique chaque annee) — voir "Questions ouvertes".
- **Agregation CAPEX = (somme des postes directs) x (1 + EPC Margin) x (1 + Insurance)**, dans cet
  ordre conceptuellement (meme si commutatif numeriquement, ecart <0.05% du CAPEX entre les 2
  ordres) : l'assurance "Insurances during construction (% of **Total Capex**)" porte sur le total
  incluant la marge EPC (convention assurance Construction All Risks classique — on assure la
  valeur totale de construction, marge contractant incluse), tandis que la marge EPC elle-meme ne
  porte que sur les travaux (elle est hors perimetre du poste "assurance construction", qui est un
  cout proprietaire/developpeur, pas un cout de l'entreprise EPC).
- **`Development` (CAPEX) reste additif, hors marquage EPC/assurance** : c'est un cout de
  developpement/origination (etudes, permitting, foncier), pas un cout de construction — la marge
  EPC et l'assurance chantier ne s'y appliquent pas. Absent d'ICP, source Aurora `COPEX_library`.
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

- **`OPEX - Guarantees & preventive maint` etale comme addition constante, pas limitee a 15 ans** —
  simplification liee a l'absence de notion d'OPEX variable dans le temps dans `financial_engine.py`
  aujourd'hui. Sur un projet de 20 ans d'exploitation, ca ajoute ~5 ans d'OPEX de garantie qui ne
  devraient pas etre la (le cout reel s'arrete a l'annee 15). Ecart limite (le poste est petit
  relativement au CAPEX total) mais pas nul — a corriger si le moteur financier gagne un jour une
  notion d'OPEX variable par annee.
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
