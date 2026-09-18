# Cas de développement (construire un BP depuis les hypothèses dev)

Spec retrospective.

## Objectif

Point d'entrée en amont de l'outil : au lieu de lire un BP déjà chiffré (O-Financials déjà
calculé), l'utilisateur saisit des hypothèses de développement (année de COD, puissance, durée
BESS, segment réseau, type TURPE, gabarit, mode de CAPEX de raccordement) et l'outil construit un
`ProjectInputs` synthétique en allant chercher les revenus dans `CF Aurora` et le CAPEX/OPEX dans
`COPEX_library` — puis réutilise `financial_engine.compute_results()` et tous les onglets
existants sans aucune modification. Reproduit l'esprit de l'onglet `Advise Dev` du BP source
(section 4 "Leviers", section 5 "Analyses de sensibilité").

## Fichiers impactés

- `core/dev_case.py` — `DevCaseParams`, `CopexLibrary`, `AuroraLibrary`, `aurora_combo_key`,
  `connection_capex_keur`, `capex_total_keur`, `opex_year1_keur`, `_escalated_unit_cost`,
  `build_project_inputs`, `run_distance_sensitivity`/`run_duration_sensitivity`/
  `run_config_sensitivity`/`run_cod_year_sensitivity`
- `core/dev_case_parser.py` — `has_dev_case_sheets`, `load_dev_case_grids`,
  `parse_copex_library` (+ `_parse_escalation_table`), `parse_cf_aurora`, `parse_inputs_dev`
- `ui/dev_case_tab.py` — formulaire + cas de base + leviers + case "Analyse bancabilité complète"
- `app.py` — détecte les 3 onglets sources sur le fichier déjà uploadé, insère l'onglet en 1ère
  position, bascule `inputs`/`base_result` sur le cas de base si la case bancabilité est cochée

## Logique métier

**Trois onglets sources, lus depuis le même fichier uploadé** (pas de 2e uploader) :
`Inputs Dev` (formulaire, pré-remplit les valeurs par défaut), `COPEX_library` (coûts
unitaires), `CF Aurora` (revenus par configuration). Contrairement à `bp_parser.py`
(qui lit un BP déjà résolu), ici on reconstruit les flux depuis des tables sources.

**Deux taxonomies de segment coexistent dans le fichier réel, une seule est utilisée ici.**
`COPEX_library` a une table "Hypothèses CAPEX BP" à 7 segments (`Industrial-New/Existing
trench`, `TSO 63/90/225kV`, `DSO` x2) ; `CF Aurora` n'a que 3 classes de tension
(`HTA`/`HTB1`/`HTB2`). Après inspection des formules (`I-Project!G39`), le mapping confirmé
avec l'utilisateur est : `DSO → HTA`, `TSO 63kV/90kV → HTB1`, `TSO 225kV → HTB2` ;
`Industrial-*` n'a pas de classe de tension fixe (un raccordement industriel privé peut être à
n'importe quel niveau de tension) — le formulaire demande alors une `voltage_class_override`
explicite (`DevCaseParams.voltage_class`, propriété qui lève `ValueError` si l'override manque).

**La table "Hypothèses CAPEX BP" (7 segments) n'est PAS utilisée pour le calcul.** Première
implémentation basée dessus : elle produisait un CAPEX total ~14 millions de k€ pour un projet
40 MW (absurde). Investigation : ses valeurs se sont révélées être déjà les totaux réels du
projet courant sous des choix de segment alternatifs (comparaison faite par `Advise Dev` section
2), pas une bibliothèque de taux réutilisable pour un MW/MWh arbitraire. La bonne source,
confirmée par une correspondance EXACTE avec le fichier réel, est la table "**CAPEX assumptions
- AURORA (base 2028)**" du même onglet — indexée par `{durée}h - {classe de tension}` (même
taxonomie que `CF Aurora`), postes `Battery system`/`Inverter`/`Balance of
system`/`Development`/`Grid connection`/`EPC soft costs`, en **€/kW** (= k€/MW : multiplier
directement par `power_mw` donne un total en k€, les deux facteurs 1000 s'annulant). Validation :
`Total(2h-HTB1) = 538.4 €/kW x 40 MW = 21 536 k€`, qui matche **exactement** la colonne
"Aurora (k€)" de la section 2 "ECARTS CAPEX BP vs AURORA" d'`Advise Dev` pour ce même projet.
`connection_capex_keur()` gère séparément la ligne `Grid connection` (les 3 autres modes -
manuel, distance RTE, distance RTE + poste HTB - la remplacent).

**OPEX** : même mécanique, table "OPEX assumptions - AURORA" du même onglet, même indexation
`{durée}h - {classe de tension}`, postes Fixed O&M/Insurance/Grid charges/Land lease/
Accise/Other, même unité €/kW. `+ land_lease_opex_keur` (saisi par l'utilisateur, cette table
a bien un poste "Land lease" mais l'utilisateur peut vouloir le surcharger).

**Escalade CAPEX/OPEX par année de COD ("Forecast price factor").** Signalé par l'utilisateur
("tu as pris en compte le tableau colonne L à P avec l'évolution des couts ?") - non pris en
compte dans une première version, corrigé. À droite de chacune des 2 tables ci-dessus (après
les 7 colonnes segment + 1 colonne vide), une 2e zone donne, **par poste** (pas par segment -
un même delta s'applique aux 7 colonnes B-H d'une ligne), un delta relatif au coût de base 2028
pour les années 2029-2034 (ex. `Battery system` décline de -0,11% en 2029 à -0,63% en 2034 ;
`Grid connection` a un delta nul toutes années - pas d'escalade pour ce poste). Chaque poste a
sa propre courbe (l'`Inverter` décline ~10x plus vite que la `Battery`) - appliquer un facteur
unique au `Total` plutôt qu'à chaque ligne individuellement donnerait un résultat légèrement
différent (moins précis). `_escalated_unit_cost()` : `valeur(cod_year) = valeur_base_2028 x
(1 + delta(cod_year))` ; au-delà de 2034 (dernière année couverte par la table), le delta est
**plafonné sur la dernière année connue** plutôt que de revenir à 0% - extrapolation prudente,
pas une vraie prévision. Le raccordement en mode `manual`/`distance_rte`/
`distance_rte_and_substation` n'est **pas** escaladé (ce sont des valeurs/formules saisies
directement, pas des coûts de bibliothèque). Pas de figure de référence indépendante pour
valider le niveau exact d'un COD non-2028 (contrairement au CAPEX 2028, validé à l'euro près
contre `Advise Dev`) - seule la cohérence interne du mécanisme (valeurs déclinantes, plafond
au-delà de 2034) a été vérifiée.

**Revenu (CF Aurora) : conversion d'unité différente de CAPEX/OPEX.** Les flux `CF Aurora`
(`wholesale_storage_*`, `intraday_revenue`, `afrr_*`, `fcr_revenue`, `tariff_TURPE
*_revenue`) sont en **€ pur pour un projet 1 MW notionnel** (pas en €/kW comme
`COPEX_library`) - `x power_mw` donne donc un total en €, qu'il faut encore diviser par 1000
pour obtenir des k€. Bug rencontré et corrigé pendant l'implémentation : sans ce `/1000`, le
revenu ressortait à l'échelle du milliard d'euros pour un projet 40 MW. Séparation revenu/TURPE :
tout flux dont le nom commence par `tariff_TURPE` va dans `turpe_keur` (déjà négatif dans la
donnée source), le reste dans `revenues_keur` (déjà positif) - cohérent avec la convention de
signe du reste du projet (voir README "Conventions de signe").

**Lecture par année calendaire, pas par année depuis COD.** `CF Aurora` ne contient qu'une seule
courbe par combinaison (segment/TURPE/gabarit/durée), indexée par année calendaire (2028, 2029,
...) - pas une courbe par année de COD. Reproduit exactement le mécanisme du fichier réel
(`AU_Store`/`BP Aurora` : `VLOOKUP` par année calendaire, où changer le COD revient juste à lire
une autre tranche de la même courbe). `_revenue_and_turpe_series()` construit la fenêtre
`[cod_year, cod_year + operating_years[` et lit cette tranche ; une année calendaire hors de la
plage couverte par `CF Aurora` donne un revenu/TURPE nul plutôt qu'une erreur (permet de tester
un COD proche des bords de la simulation de marché sans crasher).

**Bug corrigé : chaque ligne de `CF Aurora` contient 4 blocs juxtaposés, pas 1.** Sur la même
ligne physique, après le run "Aurora - Forecast..." (colonnes E+), le fichier réel répète 3 fois
de plus le même flux sous un run "Clean Horizon..." **décalé d'1 an à chaque fois** (2029, puis
2030, puis 2031 en 1ère colonne), séparés par 3 colonnes vides puis 3 colonnes de labels
(`configuration`/`price`/`stream`) redéclarées - sert à la comparaison Aurora vs Clean Horizon
d'`Advise Dev`. La première implémentation filtrait tous les nombres de la ligne d'en-tête sans
s'arrêter au 1er blanc, produisant une liste d'années 4x trop longue ; zippée avec la ligne de
valeurs (qui, elle, garde ses blancs), les années et les valeurs déraillaient après la 1ère
frontière de bloc - ex. sur le fichier réel, l'année 2030 récupérait la valeur réelle de l'année
2053 du 2e bloc (-8 953,7 - vérifié cellule par cellule). Revenu total 2030 obtenu : 37 862 €
(1MW) au lieu des 98 093 € réels - un facteur ~2,6x, expliquant un TRI bien trop bas
(observé : -15,6 %) sur un premier test. Corrigé par `_leading_numeric_run()` : ne garder que la
1ère série de cellules numériques consécutives à partir de la colonne E, en s'arrêtant au 1er
blanc - le même correctif s'applique naturellement aux lignes de données (`values =
row[4:4+len(year_columns)]`, déjà borné par la longueur - correcte - de `year_columns`). Après
correction, le revenu 2030 recalculé (3 923,7 k€ pour 40 MW) matche exactement la somme à la
main des cellules réelles du 1er bloc. Régression couverte par
`test_parse_cf_aurora_ignores_trailing_clean_horizon_blocks`.

**Bug corrigé : extraction de la durée par regex trop gourmand.** `_extract_duration_h()`
cherchait `(\d+)h` (un ou plusieurs chiffres) dans le libellé de configuration. Ça fonctionne
pour les libellés `C2h1MW`/`CTest4h1MW` (sections HTA/HTB1 de base), mais certaines sections
préfixent le libellé par `STHTB1`/`STHTB2` **sans séparateur** (ex. `STHTB12h1MW`,
`STHTB24h1MW`) : le `1` final de `HTB1` (ou le `2` final de `HTB2`) se collait au chiffre de
durée qui suit, donnant des durées fantômes 12/14/22/24 au lieu de 2/4 - `HTA soutirage
gabarit` en particulier n'avait alors **aucune** entrée valide pour durée 2 ou 4 (seulement
12/14), rendant cette combo inutilisable dès qu'on demandait `duration_h=2`. Corrigé en
cherchant `(\d)h` (un **seul** chiffre immédiatement avant "h", pas un groupe gourmand) - la
durée est toujours un chiffre unique dans ce fichier (1, 2 ou 4). Revalidé sur le fichier réel :
les 15 combos x 2 durées (30 entrées) ont désormais toutes une durée dans {2, 4} (`HTB1
soutirage gabarit` n'a par contre bien qu'une durée disponible, 2h - absence réelle dans le
fichier source, pas un bug de parsing). Régression couverte par
`test_extract_duration_h_ignores_digit_from_prefix`.

**Bornage de l'année de COD sur la couverture réelle des données.** Signalé par l'utilisateur
("on peut décaler la date de COD que sur les années pour lesquelles on dispose des revenus et
des prix CAPEX ?") - non fait dans une première version (aucune borne sur le `st.number_input`).
`AuroraLibrary.year_range()` donne la plage couverte par `CF Aurora` (2028-2057 sur le fichier
réel, identique pour les 30 combos x durée) ; `ui/dev_case_tab.py` l'utilise pour borner le
sélecteur de COD (`min_value`/`max_value`) et pour clamper le levier "TRI vs année de COD" aux
valeurs réellement couvertes. Un avertissement séparé signale si `cod_year + operating_years - 1`
dépasse la dernière année couverte (les années au-delà auraient un revenu nul, silencieusement,
sans ce garde-fou). La couverture CAPEX/OPEX (escalade "Forecast price factor", 2028-2034) est
plus courte que celle du revenu (2028-2057) - au-delà de 2034 le CAPEX/OPEX est **plafonné** sur
le dernier delta connu (pas mis à zéro comme le revenu hors plage), donc les deux limites ne
sont pas symétriques ; la caption du formulaire précise les deux plages séparément.

**Dégradation additionnelle** : réutilise `core/degradation.py` tel quel (`Base`/`Conservative`),
appliquée uniquement sur le revenu (pas sur le TURPE) - même limitation déjà documentée pour le
reste de l'app : ce n'est pas la courbe `DegFactor` propriétaire du fichier réel (un cache
généré par VBA, valeurs collées, pas de formule lisible), juste l'hypothèse additionnelle
existante de l'outil.

**Combo Aurora manquante ou durée manquante → `ValueError` explicite**, pas un résultat silencieux
à zéro - une combinaison segment/TURPE/gabarit/durée qui n'existe pas dans `CF Aurora` (ex. faute
de frappe, ou classeur qui ne couvre pas toutes les combinaisons) doit être signalée, contrairement
à une année calendaire hors plage (qui, elle, retombe sur zéro - voir ci-dessus, cas normal en
bord de simulation).

**Leviers structurels vs sensibilité continue.** `sensitivity.py` (existant) choque des
multiplicateurs continus (±10/20%) sur un `ProjectInputs` déjà figé. Les fonctions
`run_*_sensitivity` de `dev_case.py` sont différentes par nature : chacune **reconstruit un
`ProjectInputs` complet** pour chaque valeur du levier (distance, durée, config
segment/TURPE/gabarit/repowering, année de COD), car ces leviers changent la donnée source
elle-même (quel bloc Aurora lire, quel poste CAPEX), pas juste un facteur multiplicatif dessus.

**Intégration UI : nouvel onglet en 1ère position, sur le même fichier uploadé.** Détecté via
`dev_case_parser.has_dev_case_sheets()` (présence des 3 onglets), sans 2e uploader — le fichier
réel contient déjà tout. La case "Analyse bancabilité complète" renvoie `(inputs, result)` du cas
de base à `app.py`, qui les substitue à `inputs`/`base_result` pour tous les autres onglets
(Cashflow/Scenario/Sensitivity/Stress-Test/Risk/Acquisition) — ceux-ci restent inchangés, agnostiques
de la provenance des données. Garde-fou : un cas de développement synthétique n'a pas de
`target_dscr` (pas de covenant DSCR propre à un projet qui n'existe pas encore) - si le mode
"Dimensionné par DSCR" du sidebar était actif (hérité d'un BP principal déjà chiffré), il est
désactivé au profit du gearing fixe dès que le cas de base prend le relais, pour éviter un
`ValueError` de `compute_results()`.

## Tests

`tests/test_dev_case.py` (logique pure, bibliothèques `CopexLibrary`/`AuroraLibrary` synthétiques
en fixture, chiffres ronds vérifiables à la main) : `aurora_combo_key` sur les 15 combinaisons,
mapping segment→classe de tension (+ cas Industrial sans override), `connection_capex_keur` sur
les 4 modes, `capex_total_keur`/`opex_year1_keur` (avec et sans escalade par année de COD),
`_escalated_unit_cost` (année de base, année connue, extrapolation au-delà de la dernière année
couverte, absence de données), `build_project_inputs` (forme des séries, année calendaire
manquante = zéro, combo/durée manquante = erreur), sanity check bout-en-bout avec
`financial_engine.compute_results`, et les 4 fonctions de sensibilité structurelle.

`tests/test_dev_case_parser.py` (classeur synthétique `sample_dev_case_workbook_path` dans
`conftest.py`, 2 segments/2 durées/3 années, chiffres fabriqués - jamais les vraies données
Aurora/Clean Horizon du fichier réel) : détection des 3 onglets, lecture des 2 tables
`COPEX_library` (+ lecture des facteurs d'escalade), lecture de `CF Aurora` (2 durées dans la
même section), pipeline complet parse → build, et
`test_parse_cf_aurora_ignores_trailing_clean_horizon_blocks` (régression du bug des 4 blocs
juxtaposés par ligne, voir ci-dessus).

## Questions ouvertes

- **OPEX "Land lease" présent 2 fois** (dans la table OPEX-AURORA ET dans le champ utilisateur
  `land_lease_opex_keur` d'`Inputs Dev`) - actuellement additionnés, à valider : le champ
  utilisateur est peut-être censé **remplacer** la ligne de la bibliothèque, pas s'y ajouter.
- **Revenu maintenant validé à l'euro près** (voir le bug des 4 blocs ci-dessus, corrigé) : le
  revenu 2030 recalculé matche exactement la somme à la main des cellules réelles.
- **Sur 20 ans d'exploitation, le cashflow devient durablement négatif en fin de période et l'IRR
  n'est plus calculable (`npf.irr` renvoie `NaN`).** Testé sur le fichier réel (COD 2028,
  TSO 90kV/HTB1, Classique, sans repowering, gearing 70%/taux 5%/tenor 15 ans, sans dégradation
  additionnelle) : le revenu Aurora (courbe calendaire central case) décline régulièrement d'une
  année sur l'autre (5 411 k€ en 2028 -> 2 562 k€ en 2037 pour 40 MW) pendant que l'OPEX reste
  **plat** (`opex_year1_keur` répété identique chaque année, pas d'escalade) - le cashflow net
  devient négatif à partir de l'année ~12 et se dégrade ensuite, ce qui rend le polynôme de l'IRR
  sans racine réelle exploitable. Deux pistes non tranchées : (a) c'est le résultat réel et
  attendu d'un scénario de marché central où les revenus batterie s'érodent structurellement sur
  20 ans sans qu'un OPEX indexé ne soit modélisé (dans ce cas le résultat est correct, juste
  décevant) ; (b) il manque une composante (OPEX qui devrait s'indexer, valeur résiduelle/terminal
  value en fin de vie, ou une durée d'exploitation économique plus courte que 20 ans pour ce type
  de configuration) - à trancher avec l'utilisateur, qui connaît l'économie réelle de l'actif.
  Le CAPEX et le revenu, eux, sont désormais solides.
- **Détection de la table "CAPEX/OPEX assumptions - AURORA"** repose sur un titre de section
  (`_find_row_index` + recherche de la 1ère ligne suivante dont la colonne A est un nombre) -
  robuste au décalage de lignes vides, mais suppose que le titre contient toujours "CAPEX
  assumptions"/"OPEX assumptions" et que la ligne d'en-tête a bien une année nue en colonne A.
- **Un seul "cas" `Inputs Dev`/`I-Project`** est lu (`Current_case` dans le fichier réel permet en
  fait plusieurs scénarios sauvegardés côte à côte, via une indirection `INDEX/MATCH` non
  reproduite ici) - le formulaire part des valeurs actuellement actives, pas d'une liste de cas
  sauvegardés.
