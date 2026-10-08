"""Test UI headless (streamlit.testing.v1.AppTest) pour le mode Configurateur
Aurora - pas de navigateur necessaire, execute le script app.py et simule les
interactions. Volontairement minimal (pas un test par widget) : l'objectif est
d'attraper les erreurs d'integration (imports, signatures, cache_resource) que
les tests unitaires de core/ ne peuvent pas voir, pas de retester la logique
metier deja couverte par tests/test_portfolio.py.

Assertions sur les libelles UI en anglais depuis le 2026-09-24 (voir
ui/configurateur_tab.py)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core import portfolio_import

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


def test_configurateur_turpe_50pct_checkbox_only_shown_for_htb_tensions():
    """Demande de l'utilisateur, 2026-10-01 : abattement TURPE 50% reserve
    aux raccordements >=50kV (HTB1/HTB2/HTB3) - la case ne doit pas meme
    etre proposee en HTA (voir docs/specs/turpe_50pct_reduction.md)."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    tension_selectbox = next(sb for sb in at.selectbox if sb.label == "Voltage (Tension)")
    assert tension_selectbox.value == "HTA"
    assert not any(cb.label == "TURPE 50% reduction" for cb in at.checkbox)

    tension_selectbox.set_value("HTB2")
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    turpe_checkbox = next(cb for cb in at.checkbox if cb.label == "TURPE 50% reduction")
    assert turpe_checkbox.value is False

    turpe_checkbox.set_value(True)
    at.run(timeout=_TIMEOUT)
    add_button = next(b for b in at.button if b.label == "Add the project")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "TURPE 50%" in "".join(w.value for w in at.markdown)


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
    voir docs/specs/portfolio.md). Teste a 15 ans (pas le defaut 20) : depuis
    le 2026-10-01, desactiver le repowering au-dela de la fenetre SoH sure
    (18 ans pour un 2h, voir core/soh_degradation.py) leve une erreur
    explicite plutot que de calculer un resultat - voir
    test_configurateur_repowering_disabled_beyond_soh_window_shows_error
    ci-dessous pour CE cas-la."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    next(ni for ni in at.number_input if ni.label == "Operating life (years)").set_value(15)
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


def test_configurateur_repowering_disabled_beyond_soh_window_shows_error():
    """Retour utilisateur, 2026-10-01 : desactiver le repowering sur un projet
    HTA par defaut (20 ans, 2h - au-dela de la fenetre SoH sure de 18 ans,
    voir core/soh_degradation.py) doit afficher une erreur explicite (`st.error`,
    deja le mecanisme existant pour les autres `AuroraConfigError`, voir
    ui/configurateur_tab.py ligne ~922), pas planter ni produire un tableau de
    resultats trompeur."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    next(cb for cb in at.checkbox if cb.label == "Enable repowering").set_value(False)
    at.run(timeout=_TIMEOUT)

    add_button = next(b for b in at.button if b.label == "Add the project")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert any("SoH" in e.value for e in at.error)
    assert not at.dataframe


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


def test_configurateur_bulk_import_replaces_project_list():
    """Demande de l'utilisateur, 2026-09-28 : l'app n'a pas de memoire entre
    sessions - upload du template rempli, verifie que la liste (2 projets du
    template) remplace bien la saisie manuelle, et que les resultats/export
    s'affichent normalement dessus."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    at.file_uploader[0].set_value(
        (
            "projects.xlsx",
            portfolio_import.template_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    )
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Portfolio projects (2)" in "".join(h.value for h in at.subheader)
    assert "Portfolio results" in "".join(h.value for h in at.subheader)
    assert any(b.label.startswith("Download Hold & Operate results") for b in at.download_button)


def test_configurateur_copex_comparison_checkbox_shows_download_only():
    """Demande de l'utilisateur, 2026-09-30 : voir si notre CAPEX/OPEX est en
    dessous ou au-dessus des hypotheses Aurora, sur le modele d'une macro VBA
    equivalente (voir core/copex_comparison.py). Depuis le 2026-10-01, export
    Excel uniquement, aucun tableau affiche a l'ecran (demande de
    l'utilisateur - "juste le fichier excel d'extract me suffit")."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    add_button = next(b for b in at.button if b.label == "Add the project")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    dataframes_before = len(at.dataframe)
    next(cb for cb in at.checkbox if cb.label == "Aurora COPEX Comparison").set_value(True)
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert len(at.dataframe) == dataframes_before  # aucun tableau supplementaire a l'ecran
    assert any(b.label.startswith("Download Aurora COPEX Comparison") for b in at.download_button)


def test_configurateur_aurora_costs_checkbox_shows_second_table():
    """Demande de l'utilisateur, 2026-10-01 : voir le TRI avec les hypotheses
    CAPEX/OPEX d'Aurora plutot que les notres, en 2e tableau sous le tableau
    Hold & Operate habituel. Utilise toujours le databook Aurora Q2 2026
    (plus de choix de millesime depuis le meme jour : la reference
    COPEX_library/fixture a ete jugee caduque par l'utilisateur et retiree,
    voir core.dev_case.load_copex_library_q2_2026 / docs/specs/
    copex_comparison.md)."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    add_button = next(b for b in at.button if b.label == "Add the project")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    dataframes_before = len(at.dataframe)
    next(
        cb
        for cb in at.checkbox
        if cb.label == "Also show results with Aurora's own CAPEX/OPEX assumptions"
    ).set_value(True)
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert len(at.dataframe) == dataframes_before + 1
    assert not any(r.label == "Which Aurora cost assumptions?" for r in at.radio)
    assert any(
        b.label.startswith("Download Hold & Operate (Aurora CAPEX-OPEX)")
        for b in at.download_button
    )


def test_configurateur_renaming_project_after_setting_overrides_keeps_them():
    """Bug signale par l'utilisateur, 2026-10-01 : un raccordement manuel a
    250 k€ saisi dans le formulaire ressortait a l'estimation bibliotheque
    (ex. 2081 k€) dans l'export "Aurora COPEX Comparison" - preuve que le mode
    "manual"/la valeur n'avaient pas ete appliques au projet ajoute. Cause :
    les widgets "Advanced overrides" (mode raccordement, ORO, repowering,
    overrides financiers) etaient cles sur `key=f"..._{name}"`, `name` etant
    le texte du champ "Project name" - retape a chaque frappe. Chaque
    changement de `name` (y compris renommer le projet APRES avoir configure
    les overrides, un ordre de saisie parfaitement normal) change la cle de
    CES widgets, que Streamlit traite alors comme neufs et reinitialise a
    leur defaut - perdant silencieusement le mode "manual"/250 k€ deja
    saisis. Corrige en clefant sur `form_id` (compteur de projets deja
    ajoutes, stable pendant toute la saisie d'UN formulaire) plutot que sur
    `name`."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    next(sb for sb in at.selectbox if sb.label == "Grid connection CAPEX mode").set_value("manual")
    at.run(timeout=_TIMEOUT)
    next(ni for ni in at.number_input if ni.label == "Manual grid connection CAPEX (k€)").set_value(
        250.0
    )
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    # Renommer le projet APRES avoir configure l'override - exactement le
    # scenario signale (l'utilisateur finit de nommer son projet en dernier).
    next(ti for ti in at.text_input if ti.label == "Project name").set_value("Mansle")
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    # Le mode "manual" et la valeur doivent avoir survecu au renommage.
    mode_after_rename = next(sb for sb in at.selectbox if sb.label == "Grid connection CAPEX mode")
    assert mode_after_rename.value == "manual"
    value_after_rename = next(
        ni for ni in at.number_input if ni.label == "Manual grid connection CAPEX (k€)"
    )
    assert value_after_rename.value == 250.0

    add_button = next(b for b in at.button if b.label == "Add the project")
    add_button.click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    markdown_text = "".join(w.value for w in at.markdown)
    assert "Mansle" in markdown_text
    assert "manual connection 250 k€" in markdown_text


def test_configurateur_land_lease_indexation_option():
    """Demande de l'utilisateur, 2026-10-07 : option d'indexation du loyer au
    taux choisi - champ du taux visible seulement une fois la case cochee,
    puis repris dans la liste des projets et pre-rempli en edition."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    assert not any(ni.label == "Land lease indexation (%/yr)" for ni in at.number_input)
    next(ni for ni in at.number_input if ni.label == "Land lease OPEX (k€/yr)").set_value(200.0)
    at.run(timeout=_TIMEOUT)
    next(cb for cb in at.checkbox if cb.label == "Index land lease").set_value(True)
    at.run(timeout=_TIMEOUT)
    next(ni for ni in at.number_input if ni.label == "Land lease indexation (%/yr)").set_value(2.5)
    at.run(timeout=_TIMEOUT)
    assert not at.exception

    next(b for b in at.button if b.label == "Add the project").click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "land lease indexed 2.5%/yr" in "".join(w.value for w in at.markdown)

    next(b for b in at.button if b.label == "Edit").click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert next(cb for cb in at.checkbox if cb.label == "Index land lease").value is True
    assert next(
        ni for ni in at.number_input if ni.label == "Land lease indexation (%/yr)"
    ).value == pytest.approx(2.5)


def test_configurateur_edit_project_updates_it_in_place():
    """Demande de l'utilisateur, 2026-10-01 : "je veux pouvoir editer" un
    projet deja ajoute, plutot que devoir le supprimer et le re-saisir en
    entier. Verifie le cycle complet : le formulaire se pre-remplit avec les
    valeurs du projet choisi, et "Save changes" remplace ce projet EN PLACE
    (pas un 2e projet ajoute a cote)."""
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    next(ti for ti in at.text_input if ti.label == "Project name").set_value("Original")
    at.run(timeout=_TIMEOUT)
    next(ni for ni in at.number_input if ni.label == "Power (MW)").set_value(15.0)
    at.run(timeout=_TIMEOUT)

    next(b for b in at.button if b.label == "Add the project").click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Portfolio projects (1)" in "".join(h.value for h in at.subheader)

    next(b for b in at.button if b.label == "Edit").click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    # Le formulaire doit maintenant se presenter en mode edition, pre-rempli.
    assert "Edit project" in "".join(h.value for h in at.subheader)
    assert next(ti for ti in at.text_input if ti.label == "Project name").value == "Original"
    assert next(ni for ni in at.number_input if ni.label == "Power (MW)").value == 15.0

    next(ti for ti in at.text_input if ti.label == "Project name").set_value("Updated")
    at.run(timeout=_TIMEOUT)
    next(ni for ni in at.number_input if ni.label == "Power (MW)").set_value(25.0)
    at.run(timeout=_TIMEOUT)

    next(b for b in at.button if b.label == "Save changes").click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    # Toujours UN SEUL projet - remplace en place, pas ajoute a cote.
    assert "Portfolio projects (1)" in "".join(h.value for h in at.subheader)
    markdown_text = "".join(w.value for w in at.markdown)
    assert "Updated" in markdown_text
    assert "25.0 MW" in markdown_text
    assert "Original" not in markdown_text
    # Le formulaire doit etre revenu en mode "Add" (edition terminee).
    assert "Add a project" in "".join(h.value for h in at.subheader)


def test_configurateur_cancel_edit_leaves_project_unchanged():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=_TIMEOUT)
    at.sidebar.radio[0].set_value("Aurora Configurator (multi-project)")
    at.run(timeout=_TIMEOUT)

    next(ti for ti in at.text_input if ti.label == "Project name").set_value("KeepMe")
    at.run(timeout=_TIMEOUT)
    next(b for b in at.button if b.label == "Add the project").click()
    at.run(timeout=_TIMEOUT)

    next(b for b in at.button if b.label == "Edit").click()
    at.run(timeout=_TIMEOUT)
    next(ti for ti in at.text_input if ti.label == "Project name").set_value("ShouldNotStick")
    at.run(timeout=_TIMEOUT)

    next(b for b in at.button if b.label == "Cancel edit").click()
    at.run(timeout=_TIMEOUT)
    assert not at.exception
    assert "Add a project" in "".join(h.value for h in at.subheader)
    markdown_text = "".join(w.value for w in at.markdown)
    assert "KeepMe" in markdown_text
    assert "ShouldNotStick" not in markdown_text
