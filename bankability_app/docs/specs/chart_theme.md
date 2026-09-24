# Theme de graphiques (`ui/chart_theme.py`)

## Objectif

Palette Plotly partagee par toute l'app, issue du skill `dataviz` (demande explicite de
l'utilisateur, 2026-09-24 : "Skill dataviz ... s'applique directement a Plotly et Streamlit").
Avant ce module, chaque fichier `ui/*.py` choisissait ses couleurs a l'oeil (`"#1f77b4"`,
`"#2f6f4f"`, `"RdYlGn"`...), sans coherence entre graphiques ni verification d'accessibilite
daltonienne.

## Decisions

- **Palette categorielle** : reprise telle quelle de la palette de reference du skill (8 teintes,
  ordre fixe deja valide CVD-safe - Delta E adjacent 9.1 clair/8.4 sombre, plancher vision
  normale 19.6/19.3 - voir `references/palette.md` du skill). Le skill l'exige : "documented
  palette only", jamais un hex invente. Le validateur JS du skill (`scripts/validate_palette.js`)
  necessite Node, non installe dans cet environnement de dev - la palette de reference est deja
  validee dans le skill lui-meme, reprise sans modification, donc pas re-validee ici (aucune
  substitution de hex qui exigerait une re-validation).
- **Clair uniquement pour l'instant** : `.streamlit/config.toml` fige le theme sur `base = "light"`
  avec les couleurs de chrome de la palette de reference (surface `#fcfcfb`, encre primaire
  `#0b0b0b`). Le sombre est documente dans `chart_theme.py` (pas de constantes dediees) mais pas
  cable : Streamlit expose `st.context.theme.type` pour detecter le mode actif, mais pas de hook
  fiable pour re-render les figures Plotly deja construites a chaque bascule sans re-executer tout
  le script - a revisiter si la demande se precise.
- **Couleur = entite, jamais recalculee** (regle non-negociable du skill "color follows the
  entity, never its rank") : Revenue est toujours vert, CAPEX toujours violet, OPEX toujours
  rouge, TURPE toujours orange, dans tous les graphiques ou ces grandeurs apparaissent
  (`ui/cashflow.py`, `ui/overview.py`, `ui/dev_case_tab.py`). Voir `ENTITY` dans `chart_theme.py`.
- **Graphique a une seule serie -> bleu (slot 1), jamais de legende** : le titre du graphique
  nomme deja la grandeur (skill : "one series ... each bar takes the same slot-1 hue"). S'applique
  aux graphiques DSCR, IRR vs distance, IRR vs COD, et aux bar charts du Configurateur (Project
  IRR, Equity IRR, marge nette, rendement build-and-flip).
- **Divergent bleu<->rouge au lieu de `RdYlGn`** : les 2 heatmaps de sensibilite (NPV dans
  `ui/sensitivity_tab.py`, Analyse globale dans `ui/global_sensitivity_tab.py`) utilisaient
  `colorscale="RdYlGn"` - rouge/vert est precisement la confusion daltonienne la plus frequente,
  l'anti-pattern que le skill cible en premier. Remplace par un divergent bleu<->rouge + gris
  neutre au milieu (`DIVERGING`), conforme a la paire divergente documentee par le skill
  (`palette.md` : "blue <-> red - warm/cool poles that read as opposite... blue<->aqua was
  rejected - both cool, the midpoint doesn't read as nothing"). 5 paliers definis a la main
  (rouge fonce -> rouge -> gris -> bleu -> bleu fonce) : le validateur du skill ne couvre que les
  palettes categorielles, pas les rampes sequentielles/divergentes (`color-formula.md`, "Scope" -
  seule la monotonie de luminosite compte, verifiee a l'oeil ici, pas de check automatise).
- **Sequentiel bleu (13 paliers 100->700) pour les metriques % de l'Analyse globale** (Project
  IRR, Equity IRR - toujours positives en pratique) - `SEQUENTIAL_BLUE`, repris tel quel de
  `palette.md`. Le divergent s'applique aux metriques k€ qui peuvent etre negatives (NPV, marge
  nette RtB, rendement build-and-flip) - meme fonction `_single_heatmap`, colorscale choisi selon
  `is_pct` (voir `ui/global_sensitivity_tab.py::_METRICS`).
- **Tornado (sensibilite -20%/+20%)** : reutilise directement les slots categoriels rouge/bleu
  (baisse = rouge, hausse = bleu) plutot qu'une rampe divergente continue - coherent avec la paire
  divergente du skill, plus simple pour 2 categories discretes.

## Verification faite

- `pytest tests/ -q` : 284/284 passent apres le changement (aucune regression de rendu Python -
  AppTest execute les fonctions de rendu sans navigateur, donc attrape les exceptions Python d'un
  appel Plotly malforme, mais pas un probleme de rendu visuel).
- App lancee localement (`streamlit run app.py`) : demarrage sans erreur. Pas de verification
  visuelle en navigateur dans cette session (pas d'outil de screenshot/navigateur disponible dans
  cet environnement) - a faire manuellement au prochain lancement local.
- Validateur JS du skill non execute (Node non installe) - voir "Decisions" ci-dessus.

## Questions ouvertes

- Mode sombre non cable (voir "Decisions").
- Le validateur JS du skill n'a jamais tourne sur cette instance de palette dans cet
  environnement - elle est reprise sans modification d'une palette deja validee par le skill,
  mais une verification locale (avec Node installe) confirmerait definitivement le fait.
- Verification visuelle en navigateur non faite (limite d'outillage de cette session) - a faire
  au prochain lancement local (`streamlit run app.py`), notamment pour les heatmaps (lisibilite
  du gris neutre au milieu du divergent) et le tornado (largeur des barres, alignement des
  labels).
