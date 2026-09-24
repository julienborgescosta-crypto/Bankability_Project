"""Test UI headless (streamlit.testing.v1.AppTest) pour le mode Configurateur
Aurora - pas de navigateur necessaire, execute le script app.py et simule les
interactions. Volontairement minimal (pas un test par widget) : l'objectif est
d'attraper les erreurs d'integration (imports, signatures, cache_resource) que
les tests unitaires de core/ ne peuvent pas voir, pas de retester la logique
metier deja couverte par tests/test_portfolio.py.

Assertions sur les libelles UI en anglais depuis le 2026-09-24 (voir
ui/configurateur_tab.py)."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


_TIMEOUT = 120  # 1er chargement du fixture Aurora (4.7 Mo) non mis en cache entre process


def test_configurateur_mode_loads_without_exception():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Add a project" in "".join(h.value for h in at.subheader)


def test_configurateur_add_default_project_and_see_results():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    add_button = next(b for b in at.button if b.label == "Add the project")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Portfolio projects (1)" in "".join(h.value for h in at.subheader)

    assert "Portfolio results" in "".join(h.value for h in at.subheader)
    # 3 tables: Hold & Operate / Develop & sell at RtB / Buy RtB & sell at COD.
    assert len(at.dataframe) == 3


def test_configurateur_extrapolated_combo_shows_warning_and_adds_project():
    """HTB1 + Injection n'est pas modelise par Aurora (seul Classique existe) -
    depuis le 2026-09-24 c'est extrapole plutot que bloque, et l'UI doit le
    signaler explicitement avant et apres l'ajout (voir
    docs/specs/config_extrapolation.md)."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    next(sb for sb in at.selectbox if sb.label == "Voltage (Tension)").set_value("HTB1")
    at.run(timeout=_TIMEOUT)
    next(sb for sb in at.selectbox if sb.label == "TURPE type").set_value("Injection")
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert any("extrapolated" in i.value for i in at.info)

    add_button = next(b for b in at.button if b.label == "Add the project")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Portfolio results" in "".join(h.value for h in at.subheader)
    assert any("extrapolated" in e.label for e in at.expander)


def test_configurateur_oro_with_custom_curtailment_hours():
    """HTB2 injection ORO existe reellement a 3000h - a 1500h, ce doit etre
    extrapole via le profil de perte % du databook (voir
    docs/specs/config_extrapolation.md)."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    next(sb for sb in at.selectbox if sb.label == "Voltage (Tension)").set_value("HTB2")
    at.run(timeout=_TIMEOUT)
    next(sb for sb in at.selectbox if sb.label == "TURPE type").set_value("Injection")
    at.run(timeout=_TIMEOUT)
    next(cb for cb in at.checkbox if cb.label.startswith("ORO")).set_value(True)
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    # 3000h par defaut = courbe reelle Aurora, pas d'avertissement d'extrapolation.
    assert not any("extrapolated" in i.value for i in at.info)

    next(ni for ni in at.number_input if ni.label.startswith("ORO curtailment hours")).set_value(
        1500
    )
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert any("extrapolated" in i.value for i in at.info)


def test_configurateur_cod_locked_config_disables_add_button():
    """4h HTB2 Injection gabarit ORO est une courbe reelle Aurora deja
    degradee (pre_degraded), verrouillee sur COD=2030 - pas de variante
    "brute" pour l'extrapoler sur un autre COD (voir
    docs/specs/config_extrapolation.md). Avant ce fix (2026-09-24, suite a un
    ajout par erreur signale par l'utilisateur), le bouton "Add the project"
    restait cliquable malgre l'avertissement, et l'erreur explicite
    n'apparaissait qu'au calcul des resultats du portefeuille."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    next(sb for sb in at.selectbox if sb.label == "BESS duration (h)").set_value(4)
    at.run(timeout=_TIMEOUT)
    next(sb for sb in at.selectbox if sb.label == "Voltage (Tension)").set_value("HTB2")
    at.run(timeout=_TIMEOUT)
    next(sb for sb in at.selectbox if sb.label == "TURPE type").set_value("Injection")
    at.run(timeout=_TIMEOUT)
    next(sb for sb in at.selectbox if sb.label == "Gabarit").set_value(True)
    at.run(timeout=_TIMEOUT)
    next(cb for cb in at.checkbox if cb.label.startswith("ORO")).set_value(True)
    at.run(timeout=_TIMEOUT)
    next(ni for ni in at.number_input if ni.label == "COD year").set_value(2029)
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    assert any("only modelled by Aurora for COD=2030" in w.value for w in at.warning)
    add_button = next(b for b in at.button if b.label == "Add the project")
    assert add_button.disabled


def test_configurateur_repowering_disabled_shows_in_project_list_and_results():
    """Demande de l'utilisateur, 2026-09-24 : le repowering doit pouvoir etre
    desactive (avant ce changement il etait force, sans controle possible -
    voir docs/specs/portfolio.md)."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    next(cb for cb in at.checkbox if cb.label == "Enable repowering").set_value(False)
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    add_button = next(b for b in at.button if b.label == "Add the project")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert any("repowering disabled" in w.value for w in at.markdown)
    df = at.dataframe[0].value
    assert "disabled" in df["Repowering"].iloc[0]


def test_configurateur_repowering_manual_year_used_in_results():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    next(r for r in at.radio if r.label == "Repowering year").set_value("manual")
    at.run(timeout=_TIMEOUT)
    next(ni for ni in at.number_input if ni.label.startswith("Repowering year (op-year")).set_value(
        11
    )
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    add_button = next(b for b in at.button if b.label == "Add the project")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    df = at.dataframe[0].value
    assert "year 11" in df["Repowering"].iloc[0]
