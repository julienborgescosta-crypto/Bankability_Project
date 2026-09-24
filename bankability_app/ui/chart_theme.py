"""Palette de graphiques Plotly partagee par toute l'app - source unique pour
ne jamais choisir une couleur "a l'oeil" dans un fichier ui/*.py (skill
dataviz, 2026-09-24 : demande explicite de l'utilisateur). Voir
docs/specs/chart_theme.md pour le detail des choix et leur justification.

Palette categorielle = la palette de reference du skill (8 teintes, ordre
fixe deja valide CVD-safe - Delta E adjacent 9.1 clair/8.4 sombre, plancher
vision normale 19.6/19.3, voir palette.md du skill). Reprise telle quelle
(aucun hex invente), seul le clair est cable dans l'app (theme Streamlit fige
sur clair, voir .streamlit/config.toml) - le sombre est documente pour une
extension future mais pas branche (pas de detection fiable cote Plotly sans
tester st.context.theme.type a chaque re-render).

Le validateur JS du skill (scripts/validate_palette.js) necessite Node, non
installe dans cet environnement - la palette de reference est deja validee
dans le skill lui-meme (palette.md), reprise sans modification (regle
"documented palette only"), donc pas re-validee ici."""

from __future__ import annotations

# --- Palette categorielle (ordre fixe = mecanisme de securite CVD, jamais
# reordonne - voir color-formula.md du skill "Fixed hue anchors").
BLUE = "#2a78d6"  # slot 1
ORANGE = "#eb6834"  # slot 2
AQUA = "#1baf7a"  # slot 3
YELLOW = "#eda100"  # slot 4
MAGENTA = "#e87ba4"  # slot 5
GREEN = "#008300"  # slot 6
VIOLET = "#4a3aa7"  # slot 7
RED = "#e34948"  # slot 8

CATEGORICAL = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED]

# --- Couleur d'entite : une grandeur financiere garde la meme couleur dans
# tous les graphiques ou elle apparait (skill dataviz, non-negociable "color
# follows the entity, never its rank"). Un graphique a une seule serie utilise
# BLUE par defaut (le titre nomme la serie, pas besoin de legende - voir
# color-formula.md "one series ... each bar takes the same slot-1 hue").
ENTITY = {
    "revenue": GREEN,
    "capex": VIOLET,
    "opex": RED,
    "turpe": ORANGE,
    "net_cashflow": BLUE,
    "cfads": BLUE,
    "debt_service": AQUA,
    "single_series": BLUE,
}

# --- Rampe sequentielle (une seule teinte, magnitude claire->foncee) - pour
# les metriques toujours positives type IRR% (heatmap Analyse globale). 13
# paliers 100->700 de palette.md, espaces uniformement sur [0,1].
_SEQUENTIAL_BLUE_STEPS = [
    "#cde2fb",
    "#b7d3f6",
    "#9ec5f4",
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
    "#104281",
    "#0d366b",
]
SEQUENTIAL_BLUE = [
    [i / (len(_SEQUENTIAL_BLUE_STEPS) - 1), hexv] for i, hexv in enumerate(_SEQUENTIAL_BLUE_STEPS)
]

# --- Rampe divergente (bleu <-> rouge + gris neutre au milieu, poles a poids
# egal - palette.md "Diverging pair") - pour les metriques qui peuvent etre
# negatives (NPV, marge nette RtB, rendement build-and-flip). Remplace
# l'ancien colorscale "RdYlGn" (rouge/vert = exactement la confusion
# daltonienne la plus courante, l'anti-pattern que le skill cible en
# premier). 5 paliers a la main (le validateur ne couvre que les palettes
# categorielles, pas les rampes sequentielles/divergentes - color-formula.md
# "Scope" - seule la monotonie de luminosite compte ici, verifiee a l'oeil :
# rouge fonce -> rouge -> gris -> bleu -> bleu fonce, symetrique).
DIVERGING = [
    [0.0, "#7a1f1f"],
    [0.25, RED],
    [0.5, "#f0efec"],
    [0.75, BLUE],
    [1.0, "#0d366b"],
]

# --- Chrome (fond, grille, encre) - clair uniquement, voir palette.md
# "Chart chrome & ink". Applique a chaque figure via apply_layout().
CHART_SURFACE = "#fcfcfb"
PRIMARY_INK = "#0b0b0b"
SECONDARY_INK = "#52514e"
MUTED_INK = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"


def apply_layout(fig, *, legend_horizontal: bool = True):
    """Applique le chrome commun (fond, grille, police) a une `go.Figure` -
    a appeler en dernier, apres les `update_layout` propres au graphique
    (titre, axes) pour ne pas les ecraser."""
    layout: dict = {
        "paper_bgcolor": CHART_SURFACE,
        "plot_bgcolor": CHART_SURFACE,
        "font": {"family": FONT_FAMILY, "color": PRIMARY_INK},
        "xaxis": {"gridcolor": GRIDLINE, "linecolor": BASELINE, "zerolinecolor": BASELINE},
        "yaxis": {"gridcolor": GRIDLINE, "linecolor": BASELINE, "zerolinecolor": BASELINE},
    }
    if legend_horizontal:
        layout["legend"] = {"orientation": "h"}
    fig.update_layout(**layout)
    return fig
