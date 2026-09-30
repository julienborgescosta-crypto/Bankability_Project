# Import/export en masse du portefeuille (`core/portfolio_import.py`)

## Objectif

Demande de l'utilisateur (2026-09-28) : l'app n'a pas de memoire entre sessions
(`st.session_state["portfolio_projects"]` est reinitialise a chaque rechargement Streamlit) -
ressaisir chaque projet a la main dans `_render_add_project_form` a chaque ouverture n'est pas
tenable des que le portefeuille depasse quelques projets. Solution : l'utilisateur maintient sa
propre liste de configs dans un fichier Excel (son propre "stockage"), qu'il reupload en debut de
session pour repeupler `portfolio_projects` d'un coup.

## Decisions

- **Remplace, n'ajoute pas** : uploader un fichier ecrase entierement `portfolio_projects` (choix
  de l'utilisateur, confirme explicitement) - pas d'ambiguite sur d'eventuels doublons avec des
  projets deja ajoutes a la main dans la session.
- **Un seul onglet `Projects`, lecture par recherche de libelle de colonne** (pas de position
  fixe) - meme convention que `bp_parser.py` (`docs/specs/bp_parsing.md`), mais ici sans recherche
  de la ligne d'en-tete elle-meme : le format est entierement controle par ce module (pas un
  export Aurora tiers dont la mise en page varie), donc toujours la 1ere ligne du seul onglet lu.
- **7 colonnes requises, ~20 optionnelles** (voir `_COLUMN_SPECS`) : les colonnes optionnelles
  absentes du fichier, ou vides sur une ligne, retombent sur le defaut du dataclass
  `ProjectConfig` - permet un fichier minimal (juste les 7 colonnes requises) aussi bien qu'un
  fichier exhaustif avec tous les overrides. Une colonne requise manquante (a l'en-tete) ou vide
  (sur une ligne) leve un `ValueError` explicite plutot que d'inventer une valeur (brief section 7,
  "zero zero silencieux") - le message de colonne manquante liste tout ce qui manque d'un coup, le
  message de ligne incomplete precise le numero de ligne et le nom du projet pour un debug rapide.
- **Colonnes `"... (%)"` saisies en points** (70 = 70%, pas 0.70) - coherent avec les widgets
  Streamlit du formulaire manuel (`st.number_input(..., value=70.0)` pour le gearing par exemple),
  converties en fraction par `_to_pct` a la lecture.
- **Lignes vides ignorees** (toutes les cellules vides) plutot que de lever une erreur - tolere les
  lignes tampons qu'Excel laisse parfois en bas d'un tableau.
- **Template telechargeable** (`build_template_workbook`/`template_bytes`, bouton "Download
  template" dans le Configurateur) : onglet `Projects` (en-tetes + 2 lignes d'exemple, l'une simple
  Full merchant, l'autre avec Floor + repowering + overrides + ORO/gabarit) + onglet `Legend` (1
  ligne par colonne : description, valeurs attendues) - genere directement depuis `_COLUMN_SPECS`,
  jamais desynchronise du parser.
- **Export des resultats en Excel** (`ui/configurateur_tab.py::_download_results_button`), un
  bouton par table (Hold & Operate / Develop & sell / Buy & flip) - meme `pd.DataFrame` que
  l'affichage a l'ecran, converti en `.xlsx` via `pd.ExcelWriter(engine="openpyxl")` (deja une
  dependance du projet).
- **Garde-fou anti-boucle sur `st.file_uploader`** : Streamlit garde la valeur d'un
  `file_uploader` en memoire tant que l'utilisateur n'uploade pas un nouveau fichier - sans
  suivre `uploaded.file_id` deja traite (`st.session_state["_bulk_import_last_file_id"]`), le
  `st.rerun()` apres import re-declencherait le parsing et l'ecrasement de la liste en boucle a
  chaque interaction ulterieure de la page.

## Verification faite

- `tests/test_portfolio_import.py` : round-trip template -> parse (les 2 lignes d'exemple
  produisent des `ProjectConfig` corrects), fichier minimal (colonnes requises seulement) utilise
  bien les defauts, colonne requise manquante / valeur de ligne manquante levent une erreur claire,
  lignes vides ignorees.
- `tests/test_configurateur_tab.py::test_configurateur_bulk_import_replaces_project_list` :
  round-trip complet via l'UI (AppTest simule l'upload du template genere), verifie que la liste
  de projets et les resultats/export s'affichent correctement.
- Round-trip manuel (`build_template_workbook` -> `parse_portfolio_excel` -> `portfolio.run_
  portfolio`) execute directement contre les donnees reelles (`aur_cases.load_aurora_curves` +
  fixture ICP/COPEX) pour confirmer que les `ProjectConfig` generes sont bien utilisables de bout
  en bout, pas juste structurellement valides.

## Questions ouvertes

- Pas de validation amont des valeurs de colonnes "libres" texte (tension/type TURPE inconnus,
  etc.) au moment du parsing - les erreurs de ce type remontent seulement au calcul du portefeuille
  (`aur_cases.AuroraConfigError`)/l'extrapolation (`config_extrapolation.resolve_config`), comme
  pour la saisie manuelle. Acceptable pour l'instant (memes messages d'erreur qu'ailleurs dans
  l'app, et `resolve_config` ne bloque plus que les combinaisons sans sens business), a revisiter
  si les retours utilisateur montrent que situer l'erreur a la ligne Excel plutot qu'au calcul
  aiderait.
- **`connection_capex_mode`/`repowering_year_mode` valides explicitement, eux** (corrige le
  2026-09-29, suite a un plantage en production) : contrairement aux colonnes ci-dessus, ce sont
  des enums fermes (pas un espace de configs Aurora) - une valeur hors de
  `_VALID_CONNECTION_CAPEX_MODES`/`_VALID_REPOWERING_YEAR_MODES` levait auparavant une simple
  `_normalize()` sans verification, laissant passer n'importe quelle chaine jusqu'a
  `dev_case.connection_capex_keur()`, qui plante avec un `ValueError` generique tres loin de la
  ligne Excel fautive - illisible sur Streamlit Cloud (message d'erreur redacte "pour eviter les
  fuites de donnees"). Cas reel observe : un utilisateur avait tape `"distance"` au lieu de
  `"distance_rte"` sur 3 lignes de son fichier. Desormais rejete des l'import avec le numero de
  ligne et les valeurs valides attendues.
