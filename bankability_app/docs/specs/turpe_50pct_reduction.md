# Abattement TURPE 50% pour sites de stockage (`ProjectConfig.turpe_50pct_reduction`)

## Objectif

Demande de l'utilisateur (2026-10-01), suite a un echange d'emails avec Aurora (Guilhem, QEF, et
la reponse d'Aurora Energy Research) : Aurora confirme qu'un abattement de 50% du TURPE existe
pour les sites de stockage, et que certaines strategies de dispatch de BESS permettent d'y etre
eligibles "sans trop de difficulte" pour un site raccorde RTE a partir d'une certaine taille.
Aurora avait fait une etude interne (environ 1 an avant l'email, donc ~2025) montrant que les
couts TURPE etaient a peu pres divises par 2 dans ce cas, avec un impact tres positif sur les
performances economiques - sans qu'ils aient besoin de forcer la batterie a respecter la
contrainte d'eligibilite dans les cas etudies.

## Base reglementaire (recherche web, 2026-10-01)

Code de l'energie, annexe de l'article D.341-9 - delibere par la CRE (voir TURPE 7 HTB/HTA-BT).
Conditions d'eligibilite pour un site de stockage (stockage en vue d'une restitution ulterieure
au reseau) :

- **Raccordement direct a RTE, ou a un ouvrage de tension >= 50 kV.**
- **Electricite soutiree > 10 GWh/an.**
- **Taux d'utilisation du reseau en heures creuses >= 0.44** (au moins 44% du volume soutire doit
  avoir lieu en heures creuses - le critere determinant pour le stockage est l'usage anticyclique
  du reseau, pour favoriser la flexibilite du systeme electrique).
- Contrairement aux autres categories de sites eligibles a un abattement TURPE, les sites de
  stockage ne sont PAS soumis a l'obligation de Plan de Performance Energetique (PPE) ni de
  certification ISO 50001.

Taux de reduction : **50% exactement**, applique a la "part acheminement" de la facture
(c'est-a-dire le TURPE lui-meme, par opposition au cout de l'energie ou aux taxes). **Extension du
2026-10-01 (meme jour, retour utilisateur)** : la 1ere implementation ne reduisait que le TURPE
variable cote revenu (le critere d'eligibilite - profil de soutirage en heures creuses - porte sur
cette composante) ; l'utilisateur a demande d'inclure aussi la part fixe, "quitte a la retirer
d'Aurora" si besoin, en pointant l'onglet `I-Fixed` (ligne 72, "TURPE (Power)") du BP Stockage
Standalone comme reference du calcul reel. "Part acheminement" dans les textes consultes designe
le TURPE dans son ensemble (fixe + variable), sans distinction - rien ne justifie de n'en reduire
qu'une partie. Voir "Implementation" pour comment la part fixe est isolee et reduite.

Sources (recherche web, non exhaustives) :
- [Abattement du TURPE : PPE, ISO 50001, éligibilité et procédure](https://nepsen.fr/abattement-turpe-2026/)
- [Demander l'abattement du TURPE : le guide Stratégie et contrats d'énergie](https://capitole-energie.com/2026/04/03/abattement-turpe/)
- [Réduction de tarif d'utilisation du réseau public de transport d'électricité](https://www.ecologie.gouv.fr/politiques-publiques/reduction-tarif-dutilisation-du-reseau-public-transport-delectricite)
- [Délibération CRE 2026-33 (TURPE 7 HTB/HTA-BT)](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000053653688)

## Implementation

`ProjectConfig.turpe_50pct_reduction: bool = False` (`core/portfolio.py`) - option "scenario",
jamais appliquee par defaut. Transmis tel quel a `aur_cases.build_project_inputs`, qui porte la
validation ET l'application (pas `portfolio.build_project_inputs`, qui se contente de passer le
flag - meme principe que `connection_capex_mode`/`land_lease_opex_keur`, voir docs/specs/
portfolio.md "Ajustement global CAPEX/OPEX - retiré" : plus de scaling post-hoc d'un `ProjectInputs`
deja construit, le parametre est pousse jusqu'a la construction elle-meme) :

1. **Garde-fou tension** : leve `aur_cases.AuroraConfigError` si coche pour une tension autre que
   HTB1/HTB2/HTB3 (raccordement < 50 kV en HTA, jamais eligible) - jamais un chiffre invente ou un
   repli silencieux (brief section 7).
2. **Application** : juste apres `revenue_and_turpe_series` (qui calcule `turpe_series`), avant
   tout usage downstream de cette serie dans la meme fonction (le bloc frais d'agregateur
   `net_of_turpe`, s'il s'applique) - garantit que l'abattement se propage de facon coherente
   partout ou le TURPE intervient, pas seulement dans le total final.
3. La reduction est appliquee en MAGNITUDE (`valeur * 0.5`), quel que soit le signe de l'annee -
   le TURPE AU_Store peut etre negatif (cout net, type Classique) ou positif (credit net, type
   Injection - voir docs/specs/config_extrapolation.md) ; diviser par 2 la magnitude dans les 2 cas
   reproduit la description d'Aurora ("coûts liés au TURPE à peu près divisés par 2"), une
   simplification deliberee faute d'acces au detail soutirage/injection separe par poste tarifaire
   (seul le net annuel est disponible dans `AU_Store`).
4. **Part fixe (OPEX)** : `aur_cases._opex_with_turpe_50pct_reduction` isole la ligne "Grid
   charges" (part fixe du TURPE + CTA, voir docs/specs/copex_comparison.md "Mise en garde TURPE")
   au sein de l'OPEX generique (toujours sommee via `OPEX_LINE_ITEMS`, meme source Aurora que le
   mode ICP comme le mode "aurora only" - ICP n'a jamais de donnee TURPE propre) et la divise par
   2, sans toucher aux 4 autres postes (O&M/Insurance/Land lease/Accise/Other). Meme mecanisme que
   `_opex_with_land_lease_override` (meme fichier) - applique dans `capex_and_opex_keur` ET
   `capex_and_opex_keur_aurora_only`, donc identique que l'app tourne avec les couts ICP ou les
   couts Aurora seuls.
5. **Pas de double-compte** : le TURPE variable (revenu, courbe AU_Store) et "Grid charges" (OPEX,
   `COPEX_library`) sont 2 composantes **distinctes et deja non chevauchantes** dans l'app (voir
   docs/specs/copex_comparison.md, "Mise en garde TURPE" - une separation deja en place avant cette
   fonctionnalite, pas introduite pour l'occasion) - les reduire toutes les 2 par 50% reduit donc le
   TURPE total une seule fois, pas deux.

UI (`ui/configurateur_tab.py::_render_add_project_form`) : case a cocher "TURPE 50% reduction",
visible **uniquement** si la tension choisie est HTB1/HTB2/HTB3 (jamais proposee en HTA - evite de
laisser l'utilisateur cocher une combinaison qui leverait une erreur a l'ajout). Import en masse
(`core/portfolio_import.py`) : colonne "TURPE 50% reduction" (Yes/No, defaut No) - meme garde-fou
tension applique au moment du calcul, pas du parsing (coherent avec les autres validations
croisees du fichier, ex. gabarit+Classique).

## Verification faite : onglet `I-Fixed` du BP Standalone, et API Aurora

L'utilisateur a demande de verifier "comment fait Aurora" via l'API Aurora (outil cite :
`flexplorer_build_battery_investment_case`). **Cet outil n'existe pas** dans les outils MCP Aurora
disponibles cote session (produit "Flexplorer" : `flexplorer_list_datasets`/`get_scenario`/
`get_investment_case_options`/`get_download_url`/`get_leaderboard_options`, tous pour des donnees
de **revenu** batterie - previsions, backcasts, performance observee - aucun ne porte sur la
structure CAPEX/OPEX/TURPE d'un cas). Pas de decomposition TURPE accessible par ce biais.

A la place, verifie l'onglet `I-Fixed` du fixture `sample_data/081026_BP_Stockage_Standalone__.xlsx`
(ligne 72, "TURPE (Power)", comme demande) - confirme la structure reelle du TURPE "part fixe" :

- **Charges - Variable (par MW)** : -14.51 (HTA) / -11.76 (HTB1) / -3.48 (HTB2) / 0 (HTB3) k€/MW -
  la composante liee a la puissance souscrite (proportionnelle au MW, mais fixe dans l'annee, pas a
  l'energie dispatchee - a ne pas confondre avec le TURPE "variable" cote revenu d'AU_Store, qui
  lui depend de l'energie/du dispatch).
- **Charges - Fixed (forfait, independant du MW)** : -0.88 (HTA) / -12.35 (HTB1/HTB2/HTB3) k€ -
  frais de gestion/comptage (CAG/CAC).
- **CTA** : 10.11% du TURPE Fixe en raccordement GRT (RTE - le cas des projets HTB1/2/3 eligibles
  a cet abattement), 21.93% en raccordement GRD.

**Cette structure confirme que "Grid charges" (COPEX_library, deja utilise par l'app) EST bien la
bonne ligne a reduire** - memes composantes (part fixe TURPE + CTA), memes tensions, meme defaut
"pas de TURPE variable energie melange dedans". Les valeurs numeriques elles-memes du fixture
`I-Fixed` ne sont **pas utilisees** ici : le fixture est explicitement "donnees fictives" (voir
README, "Donnees confidentielles") - seule sa structure/formule a servi a confirmer que `COPEX_library!
Grid charges` est deja isole correctement, sans qu'il faille batir une bibliotheque tarifaire
parallele a partir de chiffres non officiels.

## Questions ouvertes

- **Eligibilite non verifiee par l'app** : la case est une bascule de scenario ("et si ce projet
  etait eligible ?"), pas une verification automatique des 3 criteres reels (consommation annuelle
  soutiree > 10 GWh, taux heures creuses >= 0.44, dispatch reel simule) - l'app n'a pas de modele
  de dispatch horaire, seulement des revenus annuels agreges par `AU_Store`.
- ~~Taux de reduction de "Grid charges" suppose identique a celui du TURPE variable~~ - tranche le
  2026-10-01 (demande explicite de l'utilisateur : recalculer la CTA sur la base du nouveau TURPE
  reduit, pas la laisser inchangee). D'apres `I-Fixed` (ligne 86-87), la CTA est definie comme un
  **pourcentage du TURPE fixe** (`CTA = taux x TURPE_fixe`, donc `Grid_charges = TURPE_fixe x
  (1 + taux)`) - recalculer la CTA sur le TURPE fixe reduit de 50% donne algebriquement
  `Grid_charges x 0.5` (demonstration dans la conversation du 2026-10-01), **exactement** ce que
  `_opex_with_turpe_50pct_reduction` fait deja en divisant directement la ligne bundlee - aucun
  changement de code necessaire, la mise en oeuvre du 2026-10-01 est deja la bonne methode.
- **Grille tarifaire TURPE officielle non chargee dans l'app** : `COPEX_library!Grid charges` reste
  une estimation generique Aurora (€/kW/an, pas la grille CRE reelle par tension/puissance
  souscrite) - suffisant pour ce scenario (l'app ne pretend jamais reproduire le TURPE exact d'un
  projet, voir couche 1 du README), mais a garder en tete si une precision reglementaire plus fine
  est un jour necessaire.
