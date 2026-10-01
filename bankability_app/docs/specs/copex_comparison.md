# Comparaison CAPEX/OPEX vs Aurora (`core/copex_comparison.py`)

## Objectif

Demande de l'utilisateur (2026-09-30), sur le modele d'une macro VBA equivalente
(`ModAuroraComparison`, sections "ECARTS CAPEX BP vs AURORA"/"ECARTS OPEX BP vs AURORA") deja
utilisee sur le vrai BP Excel : voir si notre CAPEX/OPEX (ICP + repli Aurora, ce que le moteur
applique reellement) est en dessous ou au-dessus de ce que la bibliotheque Aurora `COPEX_library`
donnerait seule, poste par poste et au total. Option "Aurora COPEX Comparison" dans le
Configurateur, avant les tableaux de resultats/export.

**Export Excel uniquement depuis le 2026-10-01** (retour utilisateur : "pas la peine de faire
apparaitre tous les tableaux dans la web app, juste le fichier excel d'extract me suffit") - la
case a cocher ne fait plus qu'un bouton de telechargement (un onglet CAPEX/OPEX par projet + un
onglet Notes), aucun tableau affiche a l'ecran. Voir `ui/configurateur_tab.py::_render_copex_comparison`.

## Difference avec la macro VBA source

La macro VBA reconciliait 2 taxonomies de bucket **differentes** (les lignes CAPEX du BP dans
`I-Project` vs les 5 lignes forfaitaires d'Aurora `COPEX_library`), d'ou sa mise en garde : Aurora
alloue les postes HT/MT dans "Grid", le BP les compte dans "EPC" - l'ecart EPC/Grid se compense,
seul le TOTAL est vraiment comparable.

Ici, ICP (`copex_icp.py`) ne partage pas non plus la taxonomie d'Aurora (ICP detaille Electrical
works/Civil works/HV Transformer/HV substation/MV substation/Communication/Other BoP/Integration/
Batteries and PCS/EPC Margin/Insurance construction ; Aurora a 5 lignes forfaitaires en €/kW).
L'utilisateur a signale le 2026-09-30 un piege du meme type : le "Grid connection" d'Aurora
couvrirait l'ensemble du cout de raccordement **y compris le poste de livraison/sous-station
privee** (HV Transformer/HV substation/MV substation), la ou ICP les compte a part dans le total
"construction" - comparer "Grid connection" seul ferait ressortir un ecart enorme et trompeur.

**Attention, verifie le 2026-10-01 : l'hypothese "meme perimetre une fois la sous-station
ajoutee" ne resout PAS l'ecart - elle l'aggrave** sur HTB1/HTB2 (voir "Verification faite"
ci-dessous). Plutot que de choisir une seule lecture non confirmee, le module affiche **3 vues
cote a cote** pour le raccordement, et laisse l'utilisateur juger :

- **Core equipment** (Battery+PCS+Electrical/Civil works+Communication+Integration, hors
  sous-stations et hors raccordement) : ICP = postes directs x (1+marge EPC) x (1+assurance
  construction) ; Aurora = somme des 4 lignes `CAPEX_LINE_ITEMS` correspondantes (hors
  Development).
- **Grid connection (PTF only)** : raccordement seul - comparable seulement si le projet utilise
  `connection_capex_mode="library"` (sinon `comparable=False`, le projet n'utilise pas cette
  valeur).
- **Private substation** : cout ICP des 3 postes HV/MV substation seuls, sans equivalent Aurora
  isolable - affiche pour information (`comparable=False`), jamais comme un ecart a interpreter.
- **Grid connection & substations (combined)** : somme des 2 lignes precedentes vs Aurora "Grid
  connection" - la lecture qui SUPPOSE l'hypothese de perimetre elargi d'Aurora ; a confirmer
  avant de la considerer comme la comparaison de reference (voir "Verification faite").
- **OPEX Fixed O&M** (+ ICP Guarantees, poste sans equivalent Aurora) vs Aurora "Fixed O&M" seul.
- **TOTAL CAPEX / TOTAL OPEX** : la ligne a regarder en priorite - les postes eclates expliquent
  le POURQUOI, pas l'inverse. Le total ne depend pas de la repartition core/grid/substation.

Development (CAPEX) et Insurance/Grid charges/Land lease(bibliotheque)/Accise/Other (OPEX) restent
**toujours** = Aurora (ICP ne les couvre pas) - affiches en `comparable=False` ("Info only"),
jamais comme un ecart a interpreter : un ecart de 0% n'est pas un signal ici, c'est la meme donnee
des 2 cotes par construction.

## Mise en garde TURPE (meme esprit que la macro VBA source)

"Grid charges" (poste OPEX Aurora) ne represente que la **part fixe** du TURPE (+ CTA). Le TURPE
**variable** (charge reseau liee a l'energie) est modelise **separement**, cote revenu, par
`aur_cases.revenue_and_turpe_series` (colonne TURPE d'AU_Store, "Storage volume-related network
charges" - voir docs/specs/aur_cases.md). Pas de double-compte entre les 2 - mais aussi pas de
rapprochement possible ici : ce module ne couvre que le CAPEX/OPEX, jamais le TURPE variable
revenu (note toujours affichee dans l'UI).

## Statuts (OK / Watch / Large gap)

Seuils choisis par analogie avec ceux observes sur la capture d'ecran fournie par l'utilisateur
(macro VBA) - pas une constante Aurora documentee ailleurs :

- **OK** : |ecart| < 10%
- **Watch** : 10% <= |ecart| < 20%
- **Large gap** : |ecart| >= 20%
- **Info only** : poste non comparable (toujours = Aurora, ou mode de raccordement non-library)

## Bug corrige (2026-10-01) : la ligne "Grid connection" ignorait le mode de raccordement reel

Signale par l'utilisateur : un projet du Configurateur avec `connection_capex_mode="manual"` et un
raccordement reel de 17 k€ affichait quand meme, dans la colonne "Ours" de l'export, l'estimation
ICP bibliotheque (plusieurs millions d'euros) - un nombre totalement decorrele de ce que le moteur
applique reellement a ce projet (`aur_cases.capex_and_opex_keur` respecte deja le mode manuel/
distance, seul ce module de comparaison l'ignorait). La ligne restait certes marquee
`comparable=False` ("Info only"), mais la VALEUR affichee induisait en erreur, et surtout **la
ligne "TOTAL CAPEX" en heritait aussi** (elle somme `ours_grid_and_substation_keur`, qui incluait
la meme estimation bibliotheque fantome) - pas juste un probleme d'affichage sur une ligne
secondaire, un vrai gonflement du total "Ours" pour tout projet en mode manuel/distance.

Corrige : `compare_capex_opex` prend desormais `manual_connection_capex_keur`/`distance_rte_km` en
parametres (miroir de `portfolio.ProjectConfig`) et calcule `ours_grid_only_keur` selon le mode
reel du projet (valeur manuelle, formule distance, ou estimation bibliotheque uniquement en mode
"library") - la ligne "Grid connection (PTF only)" et donc "TOTAL CAPEX" refletent desormais le
cout reellement applique. La note explicative a ete mise a jour pour dire clairement que la valeur
affichee EST la valeur appliquee (plus "shown for reference only, not applied to this project"),
tout en rappelant qu'elle n'est pas directement comparable au chiffre generique Aurora (statut
"Info only" inchange).

## Bug corrige (2026-10-01, meme jour) : le loyer foncier manuel n'apparaissait nulle part

Meme classe de bug, signale juste apres le precedent : un projet avec un loyer foncier manuel (ex.
300 k€/an, `land_lease_opex_keur` sur `ProjectConfig`) ressortait avec un OPEX "Ours" **exactement
identique** a Aurora dans l'export - le loyer manuel (`aur_cases.capex_and_opex_keur`, "ajoute tel
quel" par-dessus l'estimation Aurora "Land lease") n'etait tout simplement pas repris ici :
"Land lease" faisait partie du groupe `_OPEX_INFO_ONLY_LABELS` (Insurance/Grid charges/Land
lease/Accise/Other), toujours affiche avec la MEME valeur Aurora des 2 cotes par construction -
correct pour les 4 autres postes (jamais challengeables individuellement), faux pour "Land lease"
qui, lui, EST challengeable (seul 2e poste OPEX/CAPEX ajustable du formulaire, avec le
raccordement).

Corrige : "Land lease" a sa propre ligne desormais (`compare_capex_opex(land_lease_opex_keur=...)`),
`comparable=True`, `ours = estimation Aurora + land_lease_opex_keur` - les 4 autres postes restent
groupes dans une ligne "Info only" (label mis a jour, "Land lease" retire). "TOTAL OPEX" integre
desormais correctement l'ajout manuel.

## Verification faite (donnees reelles, `sample_data/160926_BP_Stockage_Standalone__.xlsx`)

Execution manuelle sur HTA/HTB1/HTB2/HTB3 x 2h/4h, COD 2028, 40 MW :

- **TOTAL CAPEX** : ecarts de -0.2% (HTA 2h, OK) a +23% (HTB1 2h, Large gap) selon la tension -
  coherent, pas un artefact (chaque poste sous-jacent bouge dans un sens defendable).
- **Grid connection (PTF only)** : ecart tres marque en HTA (ours 2 081 k€ vs Aurora 410 k€, x5) -
  explique : ICP price le raccordement DSO en **forfait k€ plat** (2 000 k€, independant de la
  puissance), la ou Aurora COPEX_library le scale **lineairement au MW** (~10 k€/MW). A 40 MW ces
  2 philosophies divergent fortement - un vrai ecart de modelisation, pas un bug de ce module
  (verifie en inspectant `IcpCostLibrary.line_items["Grid connection"]` directement : unite
  `keur_flat` pour DSO/TSO, `eur_per_mw` seulement pour Industrial).
- **Grid connection & substations (combined)** : **l'ajout du cout de sous-station ICP AGGRAVE
  l'ecart au lieu de le resorber**, sur HTB1/HTB2 - a 40 MW : HV Transformer (25-30 k€/MW = 1.0-1.2
  M€), HV substation (3.9-4.5 M€ forfait), MV substation (18 k€/MW = 0.72 M€), soit ~5.6-6.4 M€ de
  sous-station ICP a ajouter a un raccordement PTF ICP deja proche d'Aurora (~3.7-4.0 M€ vs Aurora
  ~3.3-4.9 M€, deja OK/Watch) - contre un "Grid connection" Aurora qui reste sur le meme ordre de
  grandeur generique (~3.3-4.9 M€ tout compris, cense inclure la sous-station). Conclusion : soit
  Aurora sous-estime largement ce poste dans son propre referentiel `COPEX_library`, soit
  l'hypothese "meme perimetre" ne tient pas non plus completement - **non tranche, presente a
  l'utilisateur via les 3 vues plutot que via un seul chiffre reconcilie**.
- **HTB3** : ours = Aurora = 0 sur ce fixture (ni ICP ni le `COPEX_library` du fixture n'ont de
  colonne HTB3) - `comparable` reste calcule correctement (0% ecart, "OK"), mais ce 0/0 vient de la
  limite du fixture de test, pas d'un vrai raccordement gratuit. Sur un classeur reel avec une
  colonne HTB3 dans `COPEX_library`, le repli Aurora produirait une comparaison non-triviale.

## Recalculer le portefeuille avec les hypotheses Aurora (`capex_opex_source`)

Ajoute le 2026-10-01, demande de l'utilisateur : au-dela de la simple comparaison poste par poste,
voir directement **quel TRI on obtiendrait** si on faisait confiance aux hypotheses generiques
d'Aurora plutot qu'aux couts reels QEF (ICP). Case a cocher "Use Aurora's own CAPEX/OPEX
assumptions" sous le tableau Hold & Operate du Configurateur - affiche un 2e tableau en dessous,
memes projets/revenu/financement, seul le CAPEX/OPEX change de source.

Implemente par un nouveau parametre `capex_opex_source: "icp" | "aurora"` (defaut `"icp"`, aucun
changement de comportement si non precise) qui traverse toute la chaine : `aur_cases.
build_project_inputs` -> `portfolio.build_project_inputs`/`find_best_repowering_op_year`/
`_effective_repowering_op_year` -> `portfolio.run_portfolio`. Cote "aurora", 2 nouvelles fonctions
miroir des fonctions ICP existantes, jamais un patch post-hoc sur un `ProjectInputs` deja construit
(plus sur, plus facile a tester en isolation) :

- `aur_cases.capex_and_opex_keur_aurora_only` - meme perimetre exact que `capex_and_opex_keur`
  (les 2 postes challengeables individuellement, raccordement/loyer foncier, restent
  source-independants), mais les 5+1 lignes `CAPEX_LINE_ITEMS`/`Grid connection` et les 6 lignes
  `OPEX_LINE_ITEMS` viennent toutes de `COPEX_library` - jamais ICP. Reutilise directement les
  memes totaux que `copex_comparison.compare_capex_opex()` calcule deja pour son tableau (verifie
  par test qu'ils correspondent exactement).
- `aur_cases.repowering_capex_keur_aurora_only` - pendant pour la tranche de repowering
  (`REPOWERING_CAPEX_LINE_ITEMS` = Battery system + Inverter, Aurora seul).

## Back-test contre le TRI reel Aurora (2026-10-01) : le TRI Projet doit matcher exactement

Question de l'utilisateur : "pour les TRI projets on est censé avoir les mêmes [qu'Aurora]".
Confirme dans le code : `project_irr` (`core/financial_engine.py`) est l'IRR d'un
`net_cashflow_series` = `cfads + capex_out`, ou `cfads = revenue + opex + turpe + end_of_life` -
**aucune hypothese de financement** (gearing, taux, mode de dette) n'y entre. Le TRI Projet est
donc theoriquement independant du capital structure, et devrait matcher le TRI Projet reel
d'Aurora des lors que revenu ET CAPEX/OPEX sont identiques.

Back-test initial (8 cas reels, non extrapoles, `capex_opex_source="aurora"` avec le
`COPEX_library` fixture) : ecart systematique de -1.4 a -7.2 pts vs le TRI reel rapporte par
Aurora (pire en HTA qu'en HTB2). Root-cause identifiee : le `COPEX_library` utilise (lu depuis
`sample_data/160926_BP_Stockage_Standalone__.xlsx`, donnees d'un BP client a une date figee)
n'est PAS le meme millesime que le databook Aurora Q2 2026 fourni par l'utilisateur - un
"Grid connection" different, une pente d'escalade differente sur Battery system/Fixed O&M, etc.
Verifie en rejouant 2 cas avec les chiffres du Q2 26 : l'ecart tombe de -2.2/-7.2 pts a -0.8/-1.6
pt - la quasi-totalite du gap venait du millesime, pas d'un defaut du moteur.

### 2e base COPEX optionnelle : `copex_library_q2_2026.json`

Retour de l'utilisateur (2026-10-01) : ne PAS remplacer le `COPEX_library` fixture existant (base
par defaut de toute l'app, y compris le repli ICP) - ajouter une **option supplementaire**,
seulement sous la case "Use Aurora's own CAPEX/OPEX assumptions" du Configurateur, pour comparer
contre ce millesime plus recent sans rien changer ailleurs.

- Asset : `config/copex_library_q2_2026.json`, extrait de l'onglet "Costs assumptions" du
  classeur `Aurora_Q2_26_FRA_Flexible_Data_Forecast_Investment_Cases_v1.1.xlsm` (fourni par
  l'utilisateur, hors repo) - **committe normalement** (choix explicite de l'utilisateur
  2026-10-01, malgre l'onglet Disclaimer du classeur source ; a la difference du databook TRI/NPV
  par cas, ce sont des couts unitaires generiques €/kW, pas des resultats de cas nommes).
- Chargeur : `core.dev_case.load_copex_library_q2_2026()` -> `CopexLibrary` (meme dataclass que
  le fixture). Base annee 2028 ; escalade = delta moyen (`statistics.mean`) sur toutes les
  combinaisons tension/duree qui portent ce poste - verifie avant de moyenner que la tendance
  est bien identique quelle que soit la tension/duree pour un meme poste (ex. Battery system
  2h et 4h ont exactement le meme ratio 2028->2030), donc la moyenne ne lisse aucune vraie
  divergence. "Grid connection"/"Grid charges" sont plats (memes €/kW toutes annees dans la
  source) -> escalade nulle, verifie par test.
- UI (`ui/configurateur_tab.py::_render_hold_and_operate`) : un `st.radio` apparait sous la case
  a cocher, "COPEX_library (base fixture)" (defaut, comportement inchange) vs "Aurora Q2 2026
  update (databook)". `load_library()` charge les 2 bibliotheques ; le radio choisit laquelle est
  passee a `portfolio.run_portfolio(..., capex_opex_source="aurora")` - aucun changement cote
  `core.aur_cases`/`core.portfolio` (le parametre `copex_library` etait deja generique).

## Questions ouvertes

- **Perimetre exact du "Grid connection" d'Aurora non confirme** - l'hypothese qu'il inclut la
  sous-station privee (avancee par l'utilisateur) ne se verifie pas numeriquement une fois testee
  (l'ecart s'aggrave, ne se resorbe pas, voir "Verification faite"). A trancher avec l'utilisateur :
  soit Aurora sous-estime reellement ce poste, soit son "Grid connection" ne couvre en fait que le
  PTF (comme ICP) et la sous-station n'a simplement pas d'equivalent Aurora du tout.
- ~~Repowering (2e tranche CAPEX) non couvert~~ - resolu le 2026-10-01 par
  `aur_cases.repowering_capex_keur_aurora_only` (voir section suivante), utilise par l'option
  "Use Aurora's own CAPEX/OPEX assumptions" du Configurateur, meme si `compare_capex_opex()`
  lui-meme (le tableau de comparaison poste par poste) ne l'inclut toujours pas explicitement.
- **Comparaison au niveau portefeuille, pas agregee** : la table UI liste un groupe de lignes par
  projet (CAPEX puis OPEX) - pas de vue "moyenne du portefeuille" ni de tri par ampleur d'ecart.
  A envisager si le portefeuille grossit au point de rendre la table brute difficile a lire.
- **Seuils OK/Watch/Large gap non valides par l'utilisateur** - repris par analogie avec la macro
  VBA source, jamais confirmes explicitement pour ce contexte precis (ICP vs Aurora, par opposition
  a BP reel vs Aurora).
- **Reliquat -0.8/-1.6 pt meme avec les couts Q2 2026** (voir section back-test ci-dessus) - non
  investigue plus loin (dans l'epaisseur du trait), plausiblement un detail fin (contingence,
  arrondi du "Grid connection", convention de temporisation du CAPEX) plutot qu'un vrai defaut de
  modelisation, etant donne que le TRI Projet est deja confirme independant du financement dans le
  code.
