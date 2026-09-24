---
name: dataviz-charts
description: Apply the dataviz skill's method to Plotly charts in bankability_app - use whenever adding or editing a chart in ui/*.py
---

# Graphiques Plotly de bankability_app

Ce skill projet est un pointeur, pas un doublon : la methode complete (choix du type de
graphique, les six checks CVD, marks/anatomy, interaction) vit dans le skill `dataviz` -
invoque-le pour tout nouveau type de graphique. Ce fichier documente uniquement ce que ce depot
a deja fige, pour ne pas le re-deriver a chaque session.

## Regle numero un

**Ne jamais choisir une couleur a l'oeil dans un fichier `ui/*.py`.** Toute couleur de graphique
vient de `bankability_app/ui/chart_theme.py` (import `from ui import chart_theme`). Si la
grandeur que tu affiches n'y est pas encore, ajoute-la a `chart_theme.ENTITY` plutot que
d'ecrire un hex en dur dans le fichier du graphique.

## Ce qui est deja fige (voir `docs/specs/chart_theme.md` pour le detail/justification)

- Palette categorielle = la palette de reference du skill `dataviz` (8 teintes, ordre fixe,
  deja validee CVD-safe), clair uniquement pour l'instant.
- Couleur d'entite fixe et coherente dans toute l'app : Revenue = vert, CAPEX = violet,
  OPEX = rouge, TURPE = orange, un graphique a une seule serie = bleu (`chart_theme.ENTITY`).
- Divergent bleu<->rouge (`chart_theme.DIVERGING`) pour les heatmaps de sensibilite (NPV,
  Analyse globale) - remplace un ancien `colorscale="RdYlGn"` (anti-pattern : rouge/vert est la
  confusion daltonienne la plus frequente).
- Sequentiel bleu (`chart_theme.SEQUENTIAL_BLUE`) pour les metriques % toujours positives
  (Project IRR, Equity IRR dans l'Analyse globale).
- Chrome commun (fond, grille, police) applique via `chart_theme.apply_layout(fig)` - a appeler
  en dernier sur chaque `go.Figure`, apres les `update_layout` propres au graphique.
- `.streamlit/config.toml` (repertoire `bankability_app/`) est aligne sur la meme palette
  (surface, encre) - ne pas le desynchroniser de `chart_theme.py`.

## Limite connue de cet environnement

Le validateur JS du skill (`scripts/validate_palette.js`) necessite Node, non installe ici. La
palette utilisee est deja validee dans le skill lui-meme (reprise sans modification de hex), donc
c'est admissible par la regle "documented palette only" - mais si tu modifies un hex ou ajoutes
une teinte hors de la palette de reference, **installe Node et fais tourner le validateur** avant
de merger (ne jamais eyeballer un delta E).

## Quand ne pas s'arreter a ce fichier

Nouveau type de graphique (scatter/bubble avec >3 series, carte, petits multiples, etc.),
question de choix de forme ("est-ce que ca doit meme etre un graphique ?"), ou ajustement fin des
marks (epaisseur de trait, labels directs, tooltips) : invoque le skill `dataviz` complet, ne
te contente pas de ce pointeur.
