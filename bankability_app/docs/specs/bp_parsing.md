# Ingestion du Business Plan (parsing Excel)

Spec retrospective — ecrite apres implementation, pour tracer le raisonnement et les
decisions prises (voir `docs/workflow_feature.md` du projet de reference `turpe_optimisation`
pour la convention).

## Objectif

Lire un classeur Excel de Business Plan BESS depose par l'utilisateur et le transformer en
`core.models.ProjectInputs`, independamment de sa structure interne exacte. Deux formats
reels ont ete rencontres, tres differents en richesse :

1. **Format resume** (`parse_summary_bp`) : un seul onglet, cashflows deja agreges par annee
   (CAPEX/OPEX/Revenues/TURPE/Net Cashflow), IRR/WACC/NPV deja calcules. Illustre par le fixture
   `sample_data/260612_BP_Stockage_Standalone__Claude.xlsx`.
2. **Format complet** (`parse_full_bp`) : classeur multi-onglets reel (`O-Financials` = P&L +
   cashflows annuels, `O-Control` = hypotheses + resultats deja calcules avec une vraie dette
   senior sculptee). Beaucoup plus riche, mais aussi plus heterogene dans la position des
   libelles selon la section du classeur.

## Fichiers impactes

- `core/bp_parser.py` — logique de lecture (grille de cellules -> `ProjectInputs`)
- `config/bp_mapping.yaml` — mapping libelle -> emplacement pour le format resume
- `config/bp_mapping_full.yaml` — mapping libelle -> emplacement pour le format complet
- `core/models.py` — `ProjectInputs` (champs `reported_*` pour les metriques deja calculees
  dans le BP, utilisees comme reference de validation croisee)
- `app.py` — appelle `bp_parser.parse_bp()` (dispatch automatique) a l'upload

## Decisions cles

**Recherche de libelle, pas de position de cellule fixe.** Meme dans le format resume, un
libelle comme "Year" n'est pas a la meme colonne que les autres (colonne G au lieu de B). Le
parser recherche chaque libelle dans toute la grille (`_find_label`, match exact puis
`startswith` en repli) plutot que de supposer une adresse de cellule figee. Les valeurs d'une
serie annuelle sont alignees sur la colonne de depart trouvee pour la ligne "Year" — pas sur
une colonne fixe par ligne — car chaque ligne peut avoir un nombre de cellules vides de tete
different.

**Offset configurable pour les scalaires (format complet uniquement).** Certaines lignes du
classeur complet portent plusieurs valeurs apres le meme libelle (ex. `Debt | 19251 k€ | 70%`).
`bp_mapping_full.yaml` permet d'ecrire `{label: "Debt", offset: 2}` pour choisir la 2e valeur
non-vide apres le libelle plutot que la 1ere. Voir `_field_spec` / `_scalar_value`.

**Deux grilles separees pour le format complet.** `parse_full_bp` lit `O-Control` (hypotheses/
resultats) et `O-Financials` (series annuelles) independamment : un libelle identique dans les
deux onglets (ex. "CAPEX (w/o DSRA and financing fees)") ne cree pas d'ambiguite puisque les
recherches ne se melangent jamais entre les deux grilles.

**Convention de signe : les series portent leur propre signe.** `capex_keur`, `opex_keur`,
`turpe_keur` sont deja negatifs dans le BP source (ce sont des sorties de cash) ; seuls
`revenues_keur` et `end_of_life_keur` sont positifs. Le CFADS est donc une simple somme
(`revenue + opex + turpe + end_of_life`), jamais une soustraction — piege rencontre lors de
l'implementation initiale (voir `financial_engine.md`, section "bug corrige").

**WACC absent du format complet.** `O-Control` n'expose pas de cellule "WACC" explicite. En
son absence, `parse_full_bp` approxime un WACC par un blend gearing-pondere entre le cout de la
dette (`All-in rate (fixed part)`) et le "Equity discount factor" trouve dans le classeur —
document explicitement comme une approximation, pas une donnee extraite telle quelle.

## Risques de regression

- Un nouveau format de BP (3e variante) casserait silencieusement si son schema de libelles
  differe des deux mappings existants : `detect_format` ne reconnait que ces deux cas
  (`O-Financials`+`O-Control` presents -> "full", sinon "summary"). Un 3e format tomberait a
  tort dans la branche "summary" et echouerait au parsing avec un message d'erreur explicite
  (ligne "Year" introuvable), pas silencieusement.
- Renommer un libelle source (ex. "Operating Costs" -> "Opex") casse le mapping correspondant
  sans avertissement autre que l'erreur de la ligne concernee.

## Tests

`tests/test_bp_parser.py` — couvre les deux formats via fixtures :
- `sample_summary_bp_path` (fichier commite, donnees fabriquees a partir du BP illustratif fourni)
- `sample_full_bp_path` (classeur synthetique construit a la volee par `conftest.py`, donnees
  entierement fabriquees — jamais les vraies donnees confidentielles de l'utilisateur)

Validation croisee cle : `test_parse_summary_bp_reported_metrics_match_engine_unlevered_irr`
verifie que l'IRR recalcule par `financial_engine` (gearing=0%) retombe a ~0.1% pres sur l'IRR
deja present dans le BP source — c'est ce test qui a permis de detecter puis corriger le bug de
signe OPEX/TURPE initial.

## Questions ouvertes (non resolues)

- **Detail des revenus par flux (DA/ID/aFRR/FCR)** : le classeur complet contient un onglet
  `Annual cashflows 1 MW` avec un detail par flux tres granulaire, mais indexe par une cle
  `configuration` (ex. `HTB22h1MW`) dont la regle de selection pour un projet donne n'est pas
  encore etablie avec certitude — le bloc correspondant a un projet HTB1/Classique observe
  s'est revele etre un jeu de test, pas une donnee de production. Non implemente. Voir
  `sensitivity_analysis.md`, section "Limitation".
- **Ecart NPV sur le format resume** : le NPV recalcule ne correspond pas exactement au NPV
  du BP source (ecart observe ~10%), alors que l'IRR correspond quasi exactement. Hypothese non
  confirmee : convention de taux (reel vs nominal) differente entre le BP source et notre WACC.
