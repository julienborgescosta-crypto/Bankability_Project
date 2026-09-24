---
name: streamlit-theme
description: Apply artifact-design principles (hierarchy, typography, spacing, color) to bankability_app's Streamlit theme and custom CSS - use when editing .streamlit/config.toml or the app's visual design
---

# Theme visuel de bankability_app

Demande explicite de l'utilisateur (2026-09-24) : appliquer les principes du skill
`artifact-design` (hierarchie, typographie, espacement, couleurs) au theme Streamlit
(`.streamlit/config.toml`) et au CSS personnalise de l'app.

## Limite importante

`artifact-design` n'est **pas invocable directement** comme skill autonome dans cet
environnement (il est charge automatiquement par l'outil Artifact avant de publier une page
HTML, pas expose en tant que skill listable). Impossible donc de recuperer son contenu textuel
tel quel pour bankability_app. Ce qui suit applique ses principes generaux (connus, pas copies
depuis le skill) au cas Streamlit, en restant coherent avec `ui/chart_theme.py` (voir
`dataviz-charts` skill projet) plutot que de partir d'une feuille blanche.

## Ce qui est deja fige

- `.streamlit/config.toml` : theme clair aligne sur la palette de reference du skill `dataviz`
  (`primaryColor` = bleu slot 1 `#2a78d6`, `backgroundColor`/`secondaryBackgroundColor` = les
  memes surfaces que les graphiques Plotly `#fcfcfb`/`#f9f9f7`, `textColor` = encre primaire
  `#0b0b0b`, police systeme). Voir `docs/specs/chart_theme.md`.
- Pas de CSS personnalise injecte pour l'instant (pas de `st.markdown("<style>...", unsafe_allow_html=True)`
  dans le repo) - le theme Streamlit natif (couleurs, police) est juge suffisant tant qu'aucun
  besoin de mise en page fine (espacement, hierarchie typographique au-dela de ce que
  `st.title`/`st.subheader`/`st.caption` offrent deja) ne se presente.

## Principes a appliquer si le CSS personnalise ou le theme evoluent

- **Hierarchie** : un seul niveau de titre par page/onglet (`st.title` ou `st.header`), les
  sous-sections en `st.subheader`, jamais deux tailles de titre pour la meme importance
  d'information. Les `st.caption` restent reserves aux precisions secondaires (deja la
  convention de l'app).
- **Couleur** : ne jamais introduire une couleur hors de `ui/chart_theme.py` (voir skill
  `dataviz-charts`) - le chrome Streamlit et les graphiques doivent rester visuellement
  coherents, pas deux palettes qui se cotoient.
- **Espacement** : `st.divider()` entre sections majeures (deja la convention de l'app dans
  `ui/overview.py`, `ui/configurateur_tab.py`) plutot que des marges CSS ad hoc.
- **Typographie** : police systeme (`sans serif`, deja dans `config.toml`) - pas de police
  d'affichage/serif, coherent avec la regle du skill `dataviz` ("Everything ... stays in the
  system sans").
- **Mode sombre** : non cable (voir `docs/specs/chart_theme.md`, "Questions ouvertes") - si un
  jour demande, le faire en meme temps pour le theme ET pour `chart_theme.py` (jamais l'un sans
  l'autre, sous peine de fond clair + graphiques sombres ou l'inverse).
