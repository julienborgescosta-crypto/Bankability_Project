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


def test_configurateur_extrapolated_combo_shows_warning_and_adds_project():
    """HTB1 + Injection n'est pas modelise par Aurora (seul Classique existe) -
    depuis le 2026-09-24 c'est extrapole plutot que bloque, et l'UI doit le
    signaler explicitement avant et apres l'ajout (voir
    docs/specs/config_extrapolation.md)."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Configurateur Aurora (multi-projets)")
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    next(sb for sb in at.selectbox if sb.label == "Tension").set_value("HTB1")
    at.run(timeout=_TIMEOUT)
    next(sb for sb in at.selectbox if sb.label == "Type TURPE").set_value("Injection")
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert any("extrapolée" in i.value for i in at.info)

    add_button = next(b for b in at.button if b.label == "Ajouter le projet")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Résultats du portefeuille" in "".join(h.value for h in at.subheader)
    assert any("extrapolée" in e.label for e in at.expander)


def test_configurateur_oro_with_custom_curtailment_hours():
    """HTB2 injection ORO existe reellement a 3000h - a 1500h, ce doit etre
    extrapole via le profil de perte % du databook (voir
    docs/specs/config_extrapolation.md)."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Configurateur Aurora (multi-projets)")
    at.run(timeout=_TIMEOUT)

    next(sb for sb in at.selectbox if sb.label == "Tension").set_value("HTB2")
    at.run(timeout=_TIMEOUT)
    next(sb for sb in at.selectbox if sb.label == "Type TURPE").set_value("Injection")
    at.run(timeout=_TIMEOUT)
    next(cb for cb in at.checkbox if cb.label.startswith("ORO")).set_value(True)
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    # 3000h par defaut = courbe reelle Aurora, pas d'avertissement d'extrapolation.
    assert not any("extrapolée" in i.value for i in at.info)

    next(ni for ni in at.number_input if ni.label.startswith("Heures de curtailment")).set_value(
        1500
    )
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert any("extrapolée" in i.value for i in at.info)
