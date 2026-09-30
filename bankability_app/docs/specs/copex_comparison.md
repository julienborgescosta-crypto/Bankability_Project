# Comparaison CAPEX/OPEX vs Aurora (`core/copex_comparison.py`)

## Objectif

Demande de l'utilisateur (2026-09-30), sur le modele d'une macro VBA equivalente
(`ModAuroraComparison`, sections "ECARTS CAPEX BP vs AURORA"/"ECARTS OPEX BP vs AURORA") deja
utilisee sur le vrai BP Excel : voir si notre CAPEX/OPEX (ICP + repli Aurora, ce que le moteur
applique reellement) est en dessous ou au-dessus de ce que la bibliotheque Aurora `COPEX_library`
donnerait seule, poste par poste et au total. Option "Aurora COPEX Comparison" dans le
Configurateur, avant les tableaux de resultats/export.

## Difference avec la macro VBA source

La macro VBA reconciliait 2 taxonomies de bucket **differentes** (les lignes CAPEX du BP dans
`I-Project` vs les 5 lignes forfaitaires d'Aurora `COPEX_library`), d'ou sa mise en garde : Aurora
alloue les postes HT/MT dans "Grid", le BP les compte dans "EPC" - l'ecart EPC/Grid se compense,
seul le TOTAL est vraiment comparable.

Ici, ICP (`copex_icp.py`) ne partage pas non plus la taxonomie d'Aurora (ICP detaille Electrical
works/Civil works/HV Transformer/HV substation/MV substation/Communication/Other BoP/Integration/
Batteries and PCS/EPC Margin/Insurance construction ; Aurora a 5 lignes forfaitaires en €/kW), donc
le meme type de garde-fou s'applique, mais la comparaison se limite aux 2 seuls niveaux ou les 2
sources sont clairement du meme perimetre :

- **Construction CAPEX** (Battery+PCS+BoS+EPC soft costs, hors Development et hors raccordement) :
  ICP = poste direct x (1+marge EPC) x (1+assurance construction) ; Aurora = somme des 4 lignes
  `CAPEX_LINE_ITEMS` correspondantes (hors Development).
- **Grid connection** (raccordement) : ligne dediee des 2 cotes - comparable seulement si le
  projet utilise `connection_capex_mode="library"` (sinon `comparable=False`, le projet n'utilise
  pas cette valeur).
- **OPEX Fixed O&M** (+ ICP Guarantees, poste sans equivalent Aurora) vs Aurora "Fixed O&M" seul.
- **TOTAL CAPEX / TOTAL OPEX** : la ligne a regarder en priorite - les postes eclates expliquent
  le POURQUOI, pas l'inverse.

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

## Verification faite (donnees reelles, `sample_data/160926_BP_Stockage_Standalone__.xlsx`)

Execution manuelle sur HTA/HTB1/HTB2/HTB3 x 2h/4h, COD 2028, 40 MW :

- **TOTAL CAPEX** : ecarts de -0.2% (HTA 2h, OK) a +23% (HTB1 2h, Large gap) selon la tension -
  coherent, pas un artefact (chaque poste sous-jacent bouge dans un sens defendable).
- **Grid connection** : ecart tres marque en HTA (ours 2 081 k€ vs Aurora 410 k€, x5) - explique :
  ICP price le raccordement DSO en **forfait k€ plat** (2 000 k€, independant de la puissance),
  la ou Aurora COPEX_library le scale **lineairement au MW** (~10 k€/MW). A 40 MW ces 2 philosophies
  divergent fortement - un vrai ecart de modelisation a signaler a l'utilisateur, pas un bug de ce
  module (verifie en inspectant `IcpCostLibrary.line_items["Grid connection"]` directement : unite
  `keur_flat` pour DSO/TSO, `eur_per_mw` seulement pour Industrial).
- **HTB3** : ours = Aurora = 0 sur ce fixture (ni ICP ni le `COPEX_library` du fixture n'ont de
  colonne HTB3) - `comparable` reste calcule correctement (0% ecart, "OK"), mais ce 0/0 vient de la
  limite du fixture de test, pas d'un vrai raccordement gratuit. Sur un classeur reel avec une
  colonne HTB3 dans `COPEX_library`, le repli Aurora produirait une comparaison non-triviale.

## Questions ouvertes

- **Repowering (2e tranche CAPEX) non couvert** - seul le CAPEX/OPEX initial (a la COD) l'est.
  `icp_repowering_capex_keur` existe deja (voir `copex_icp.py`) mais n'a pas d'equivalent Aurora
  "pur" facilement isolable dans cette premiere version - a ajouter si le besoin se confirme.
- **Comparaison au niveau portefeuille, pas agregee** : la table UI liste un groupe de lignes par
  projet (CAPEX puis OPEX) - pas de vue "moyenne du portefeuille" ni de tri par ampleur d'ecart.
  A envisager si le portefeuille grossit au point de rendre la table brute difficile a lire.
- **Seuils OK/Watch/Large gap non valides par l'utilisateur** - repris par analogie avec la macro
  VBA source, jamais confirmes explicitement pour ce contexte precis (ICP vs Aurora, par opposition
  a BP reel vs Aurora).
