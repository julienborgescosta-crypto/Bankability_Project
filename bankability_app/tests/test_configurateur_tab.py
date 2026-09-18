"""Test UI headless (streamlit.testing.v1.AppTest) pour le mode Configurateur
Aurora - pas de navigateur necessaire, execute le script app.py et simule les
interactions. Volontairement minimal (pas un test par widget) : l'objectif est
d'attraper les erreurs d'integration (imports, signatures, cache_resource) que
les tests unitaires de core/ ne peuvent pas voir, pas de retester la logique
metier deja couverte par tests/test_portfolio.py."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


_TIMEOUT = 120  # 1er chargement du fixture Aurora (4.7 Mo) non mis en cache entre process


def test_configurateur_mode_loads_without_exception():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    at.sidebar.radio[0].set_value("Configurateur Aurora (multi-projets)")
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Ajouter un projet" in "".join(h.value for h in at.subheader)


def test_configurateur_add_default_project_and_see_results():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Configurateur Aurora (multi-projets)")
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    add_button = next(b for b in at.button if b.label == "Ajouter le projet")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Projets du portefeuille (1)" in "".join(h.value for h in at.subheader)

    assert "Résultats du portefeuille" in "".join(h.value for h in at.subheader)
    # 3 tableaux : Garder & exploiter / Développer & vendre RtB / Racheter & vendre au COD.
    assert len(at.dataframe) == 3
