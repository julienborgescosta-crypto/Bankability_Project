"""Test UI headless (streamlit.testing.v1.AppTest) pour le mode Analyse
globale Aurora - voir tests/test_configurateur_tab.py pour le rationnel."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
_TIMEOUT = 120  # 1er chargement du fixture Aurora (4.7 Mo) non mis en cache entre process


def test_global_sensitivity_mode_loads_without_exception():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Global Analysis")
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Full table" in "".join(h.value for h in at.subheader)
    assert "2-variable cut" in "".join(h.value for h in at.subheader)
    assert len(at.dataframe) == 1
    # Par defaut ("Split by" = "None"), une seule heatmap.
    assert len(at.get("plotly_chart")) == 1


def test_global_sensitivity_heatmap_facet_renders_one_chart_per_value():
    """ "Split by" doit produire plusieurs petits multiples (une heatmap par
    valeur de la dimension choisie), pas une seule heatmap moyennee - c'est le
    point signale par l'utilisateur (comparer Injection/Soutirage/Classique
    sans les melanger dans une meme moyenne)."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Global Analysis")
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    facet_selectbox = at.selectbox(key="heatmap_facet")
    facet_selectbox.set_value(facet_selectbox.options[1])  # 1ere vraie dimension (pas "None")
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    # Plus d'une heatmap : les valeurs de la dimension choisie ne sont plus
    # melangees dans une seule moyenne (le bug signale par l'utilisateur).
    assert len(at.get("plotly_chart")) > 1
