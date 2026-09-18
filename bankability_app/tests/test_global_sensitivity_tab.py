"""Test UI headless (streamlit.testing.v1.AppTest) pour le mode Analyse
globale Aurora - voir tests/test_configurateur_tab.py pour le rationnel."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
_TIMEOUT = 120  # 1er chargement du fixture Aurora (4.7 Mo) non mis en cache entre process


def test_global_sensitivity_mode_loads_without_exception():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Analyse globale Aurora")
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Table complète" in "".join(h.value for h in at.subheader)
    assert "Coupe 2 variables" in "".join(h.value for h in at.subheader)
    assert len(at.dataframe) == 1
