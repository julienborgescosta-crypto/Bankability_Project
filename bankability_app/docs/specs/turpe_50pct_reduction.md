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
(c'est-a-dire le TURPE lui-meme, par opposition au cout de l'energie ou aux taxes) - les sources
consultees ne precisent pas explicitement si la part fixe (capacite) et la part variable
(energie) du TURPE sont toutes deux concernees, ou seulement la part variable. Vu que le critere
d'eligibilite porte specifiquement sur le PROFIL de soutirage (heures creuses), et que c'est la
partie variable qui depend de ce profil, cette spec applique l'abattement uniquement au TURPE
variable cote revenu - voir "Limite connue" ci-dessous.

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

UI (`ui/configurateur_tab.py::_render_add_project_form`) : case a cocher "TURPE 50% reduction",
visible **uniquement** si la tension choisie est HTB1/HTB2/HTB3 (jamais proposee en HTA - evite de
laisser l'utilisateur cocher une combinaison qui leverait une erreur a l'ajout). Import en masse
(`core/portfolio_import.py`) : colonne "TURPE 50% reduction" (Yes/No, defaut No) - meme garde-fou
tension applique au moment du calcul, pas du parsing (coherent avec les autres validations
croisees du fichier, ex. gabarit+Classique).

## Limite connue

**Seul le TURPE variable cote revenu est reduit, pas la composante fixe "Grid charges" cote
OPEX.** Le TURPE apparait a 2 endroits dans l'app (voir docs/specs/copex_comparison.md, "Mise en
garde TURPE") :
- Cote revenu, `ProjectInputs.turpe_keur` (serie annuelle AU_Store, "Storage volume-related
  network charges") - **reduit par cette fonctionnalite**.
- Cote OPEX, le poste "Grid charges" (part fixe du TURPE + CTA, agrege dans `copex_icp.
  icp_opex_year1_keur` avec Insurance/Land lease/Accise/Other, pas de valeur isolable sans
  refactoring) - **pas reduit**.

Refactorer `icp_opex_year1_keur` pour isoler "Grid charges" et lui appliquer le meme abattement
est possible mais plus invasif (touche une fonction partagee par tout le moteur, pas seulement ce
levier) - pas fait dans cette 1ere implementation, le poste etant de toute facon petit comparativement
au TURPE variable (ex. HTB2 2h : ~3.8 k€/MW/an de Grid charges fixe contre ~10 k€/MW/an de TURPE
variable). A faire si l'utilisateur confirme que la precision supplementaire est necessaire.

## Questions ouvertes

- **Eligibilite non verifiee par l'app** : la case est une bascule de scenario ("et si ce projet
  etait eligible ?"), pas une verification automatique des 3 criteres reels (consommation annuelle
  soutiree > 10 GWh, taux heures creuses >= 0.44, dispatch reel simule) - l'app n'a pas de modele
  de dispatch horaire, seulement des revenus annuels agreges par `AU_Store`.
- **Part fixe TURPE (OPEX) non reduite** - voir "Limite connue" ci-dessus.
- **Hypothese "part variable uniquement"** non confirmee aupres de l'utilisateur ni d'une source
  juridique primaire (texte CRE/Legifrance lu uniquement via resume web, pas le texte integral de
  l'annexe D.341-9) - a verifier si une precision plus fine est necessaire.
