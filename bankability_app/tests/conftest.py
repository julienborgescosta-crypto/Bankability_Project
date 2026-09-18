from pathlib import Path

import openpyxl
import pytest

from core import aur_cases
from core.dev_case_parser import load_dev_case_grids, parse_copex_library
from core.models import ProjectInputs

SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture
def simple_inputs() -> ProjectInputs:
    """3 annees, chiffres ronds choisis pour etre verifiables a la main :
    construction (CAPEX -1000) puis 2 annees d'exploitation identiques
    (Revenue 500, OPEX -100, TURPE -20 -> CFADS 380)."""
    return ProjectInputs(
        name="Test Project",
        location="Testville",
        segment="HTB1",
        cod="2026-01-01",
        operating_years=2,
        usable_power_mw=10.0,
        usable_energy_mwh=20.0,
        capex_initial_keur=1000.0,
        capex_repowering_keur=0.0,
        repowering=False,
        opex_year1_keur=100.0,
        opex_adjustment_keur=0.0,
        turpe_fixed_eur_per_kw=0.0,
        years=[2025, 2026, 2027],
        capex_keur=[-1000.0, 0.0, 0.0],
        opex_keur=[0.0, -100.0, -100.0],
        end_of_life_keur=[0.0, 0.0, 0.0],
        revenues_keur=[0.0, 500.0, 500.0],
        turpe_keur=[0.0, -20.0, -20.0],
        net_cashflow_keur=[-1000.0, 380.0, 380.0],
        wacc=0.10,
        gearing_pct=0.5,
        interest_rate=0.05,
        debt_tenor_years=2,
    )


@pytest.fixture
def varying_cfads_inputs() -> ProjectInputs:
    """4 annees : construction (CAPEX -1000) puis 3 annees d'exploitation avec un
    CFADS DIFFERENT chaque annee (200, 400, 300) - contrairement a simple_inputs
    (CFADS constant), sert a prouver que le dimensionnement DSCR sculpte vraiment
    le remboursement (variable par annee) plutot que de plafonner une annuite
    constante par la pire annee."""
    return ProjectInputs(
        name="Varying CFADS Project",
        location="Testville",
        segment="HTB1",
        cod="2026-01-01",
        operating_years=3,
        usable_power_mw=10.0,
        usable_energy_mwh=20.0,
        capex_initial_keur=1000.0,
        capex_repowering_keur=0.0,
        repowering=False,
        opex_year1_keur=80.0,
        opex_adjustment_keur=0.0,
        turpe_fixed_eur_per_kw=0.0,
        years=[2025, 2026, 2027, 2028],
        capex_keur=[-1000.0, 0.0, 0.0, 0.0],
        opex_keur=[0.0, -80.0, -80.0, -80.0],
        end_of_life_keur=[0.0, 0.0, 0.0, 0.0],
        revenues_keur=[0.0, 300.0, 500.0, 400.0],
        turpe_keur=[0.0, -20.0, -20.0, -20.0],
        net_cashflow_keur=[-1000.0, 200.0, 400.0, 300.0],
        wacc=0.10,
        gearing_pct=0.7,
        interest_rate=0.05,
        debt_tenor_years=3,
    )


@pytest.fixture
def ramp_up_inputs() -> ProjectInputs:
    """4 annees : construction, une annee de ramp-up SANS CAPEX ni revenu (COD
    tombe apres le dernier decaissement CAPEX), puis 2 annees d'exploitation.
    Sert a verifier que le service de la dette ne demarre pas pendant le ramp-up."""
    return ProjectInputs(
        name="Ramp-up Project",
        location="Testville",
        segment="HTB1",
        cod="2027-01-01",
        operating_years=2,
        usable_power_mw=10.0,
        usable_energy_mwh=20.0,
        capex_initial_keur=1000.0,
        capex_repowering_keur=0.0,
        repowering=False,
        opex_year1_keur=100.0,
        opex_adjustment_keur=0.0,
        turpe_fixed_eur_per_kw=0.0,
        years=[2025, 2026, 2027, 2028],
        capex_keur=[-1000.0, 0.0, 0.0, 0.0],
        opex_keur=[0.0, -10.0, -100.0, -100.0],
        end_of_life_keur=[0.0, 0.0, 0.0, 0.0],
        revenues_keur=[0.0, 0.0, 500.0, 500.0],
        turpe_keur=[0.0, 0.0, -20.0, -20.0],
        net_cashflow_keur=[-1000.0, -10.0, 380.0, 380.0],
        wacc=0.10,
        gearing_pct=0.5,
        interest_rate=0.05,
        debt_tenor_years=2,
    )


@pytest.fixture
def repowering_inputs() -> ProjectInputs:
    """11 annees avec 2 sorties de CAPEX (construction 2025 puis repowering 2031),
    chacune avec ses propres termes de financement - sert a verifier la logique
    de dette a 2 tranches independantes de financial_engine.compute_results."""
    years = list(range(2025, 2036))  # 2025..2035
    capex = [-1000.0] + [0.0] * 5 + [-600.0] + [0.0] * 4
    # CFADS annuel = 380 (Revenue 500, OPEX -100, TURPE -20) sur toutes les annees
    # d'exploitation ; l'annee de repowering (2031) est en pause (0 partout).
    revenues = [0.0] + [500.0] * 5 + [0.0] + [500.0] * 4
    opex = [0.0] + [-100.0] * 5 + [0.0] + [-100.0] * 4
    turpe = [0.0] + [-20.0] * 5 + [0.0] + [-20.0] * 4
    return ProjectInputs(
        name="Repowering Project",
        location="Testville",
        segment="HTB1",
        cod="2026-01-01",
        operating_years=10,
        usable_power_mw=10.0,
        usable_energy_mwh=20.0,
        capex_initial_keur=1000.0,
        capex_repowering_keur=600.0,
        repowering=True,
        opex_year1_keur=100.0,
        opex_adjustment_keur=0.0,
        turpe_fixed_eur_per_kw=0.0,
        years=years,
        capex_keur=capex,
        opex_keur=opex,
        end_of_life_keur=[0.0] * len(years),
        revenues_keur=revenues,
        turpe_keur=turpe,
        net_cashflow_keur=[
            c + o + t + r for c, o, t, r in zip(capex, opex, turpe, revenues, strict=True)
        ],
        wacc=0.10,
        gearing_pct=0.5,
        interest_rate=0.05,
        debt_tenor_years=3,
        repowering_gearing_pct=0.6,
        repowering_interest_rate=0.08,
        repowering_debt_tenor_years=2,
    )


@pytest.fixture
def repowering_with_ramp_up_inputs() -> ProjectInputs:
    """Comme repowering_inputs, mais avec une annee de flottement APRES le CAPEX
    de repowering (2032 : pas de CAPEX, mais pas encore de revenu non plus -
    chantier de repowering qui deborde sur l'annee suivante). Sert a verifier
    que la tranche repowering beneficie de la meme protection anti-flottement
    que la tranche initiale (first_op_index_after_repowering), au lieu de
    demarrer son service de dette des repowering_index + 1 sans verification."""
    years = list(range(2025, 2037))  # 2025..2036
    capex = [-1000.0] + [0.0] * 5 + [-600.0] + [0.0] * 5
    # 2032 (index 7) : flottement post-repowering, revenu nul, petit cout de
    # chantier -> CFADS legerement negatif, comme le ramp-up initial.
    revenues = [0.0] + [500.0] * 5 + [0.0, 0.0] + [500.0] * 4
    opex = [0.0] + [-100.0] * 5 + [0.0, -10.0] + [-100.0] * 4
    turpe = [0.0] + [-20.0] * 5 + [0.0, 0.0] + [-20.0] * 4
    return ProjectInputs(
        name="Repowering Ramp-up Project",
        location="Testville",
        segment="HTB1",
        cod="2026-01-01",
        operating_years=10,
        usable_power_mw=10.0,
        usable_energy_mwh=20.0,
        capex_initial_keur=1000.0,
        capex_repowering_keur=600.0,
        repowering=True,
        opex_year1_keur=100.0,
        opex_adjustment_keur=0.0,
        turpe_fixed_eur_per_kw=0.0,
        years=years,
        capex_keur=capex,
        opex_keur=opex,
        end_of_life_keur=[0.0] * len(years),
        revenues_keur=revenues,
        turpe_keur=turpe,
        net_cashflow_keur=[
            c + o + t + r for c, o, t, r in zip(capex, opex, turpe, revenues, strict=True)
        ],
        wacc=0.10,
        gearing_pct=0.7,
        interest_rate=0.05,
        debt_tenor_years=3,
        repowering_gearing_pct=0.6,
        repowering_interest_rate=0.08,
        repowering_debt_tenor_years=3,
    )


@pytest.fixture
def sample_summary_bp_path() -> Path:
    path = SAMPLE_DATA_DIR / "260612_BP_Stockage_Standalone__Claude.xlsx"
    assert path.exists(), "Fixture manquante - lancer sample_data/build_sample_xlsx.py"
    return path


@pytest.fixture(scope="session")
def sample_aurora_bp_path() -> Path:
    """Format complet + onglets Aurora (AU_Store, Source BP, BP Aurora, cas de
    developpement) - donnees fictives, voir README section "Donnees confidentielles"."""
    path = SAMPLE_DATA_DIR / "160926_BP_Stockage_Standalone__.xlsx"
    assert path.exists(), "Fixture manquante - voir README pour la provenance du fichier"
    return path


@pytest.fixture(scope="session")
def au_store(sample_aurora_bp_path):
    """Session-scope : le classeur fait 4.7 Mo, le reparser par module de test
    (comme le ferait un scope 'module' plus naturel) fait passer la suite de
    quelques secondes a plusieurs minutes - lecture seule, sans risque de fuite
    d'etat entre tests (AuStoreLibrary est un frozen dataclass)."""
    return aur_cases.load_au_store(sample_aurora_bp_path)


@pytest.fixture(scope="session")
def copex_library(sample_aurora_bp_path):
    """Session-scope pour la meme raison que `au_store` ci-dessus."""
    _, copex_grid, _ = load_dev_case_grids(sample_aurora_bp_path)
    return parse_copex_library(copex_grid)


@pytest.fixture
def default_financing_terms() -> dict:
    return aur_cases.load_financing_terms()


@pytest.fixture
def sample_full_bp_path(tmp_path: Path) -> Path:
    """Construit un classeur synthetique minimal au format 'complet'
    (onglets O-Financials / O-Control), avec des donnees fabriquees - jamais
    les vraies donnees BP confidentielles de l'utilisateur, pour que ce test
    reste executable sans le fichier reel (qui n'est jamais commite)."""
    path = tmp_path / "synthetic_full_bp.xlsx"
    wb = openpyxl.Workbook()

    control = wb.active
    control.title = "O-Control"
    control["B3"], control["C3"] = "Name", "Synthetic Project"
    control["B4"], control["C4"] = "Location city", "Testville"
    control["B5"], control["C5"] = "Segment", "HTB1"
    control["B6"], control["C6"] = "BESS commercial operation date (COD)", "2027-01-01"
    control["B7"], control["C7"], control["D7"] = "BESS operating time", 2, "years"
    control["B8"], control["C8"], control["D8"] = "ESS Usable Power @PoC (AC)", 10, "MW"
    control["B9"], control["C9"], control["D9"] = "ESS Usable Energy @PoC BoL (AC)", 20, "MWh"
    control["G4"], control["H4"], control["I4"] = "IRR", 0.08, 0.06
    control["G12"], control["H12"] = "NPV", 150.0
    control["G17"], control["H17"] = "CAPEX (w/o DSRA and financing fees)", 1000.0
    control["G28"], control["H28"], control["I28"] = "Debt", 500.0, 0.5
    control["G42"], control["H42"] = "Maturity", 2
    control["G43"], control["H43"] = "All-in rate (fixed part)", 0.05
    control["G44"], control["H44"] = "Average DSCR", 1.4
    control["G45"], control["H45"] = "Min. DSCR", 1.4
    control["G7"], control["H7"] = "Equity discount factor", 0.12

    financials = wb.create_sheet("O-Financials")
    financials["K8"] = "Year"
    years = [2025, 2026, 2027]
    for offset, year in enumerate(years):
        financials.cell(row=8, column=12 + offset, value=year)

    def series(row: int, label: str, values: list[float]) -> None:
        financials.cell(row=row, column=4, value=label)
        for offset, value in enumerate(values):
            financials.cell(row=row, column=12 + offset, value=value)

    series(11, "Revenues", [0.0, 500.0, 500.0])
    series(16, "Operating Costs", [0.0, -100.0, -100.0])
    series(27, "Operating Taxes", [0.0, -20.0, -20.0])
    series(58, "CAPEX (w/o DSRA and financing fees)", [-1000.0, 0.0, 0.0])

    wb.save(path)
    return path


@pytest.fixture
def sample_full_bp_with_revenue_mix_path(tmp_path: Path) -> Path:
    """Meme classeur synthetique que sample_full_bp_path, avec en plus les
    sous-lignes PPA Revenues / Capacity market / Merchant revenues de O-Financials
    (contracted = PPA + Capacity = 150/an, merchant = 350/an, soit 30%/70% du
    total 500/an) - sert a tester le seuil DSCR pondere par mix de revenu."""
    path = tmp_path / "synthetic_full_bp_with_revenue_mix.xlsx"
    wb = openpyxl.Workbook()

    control = wb.active
    control.title = "O-Control"
    control["B3"], control["C3"] = "Name", "Synthetic Project"
    control["B4"], control["C4"] = "Location city", "Testville"
    control["B5"], control["C5"] = "Segment", "HTB1"
    control["B6"], control["C6"] = "BESS commercial operation date (COD)", "2027-01-01"
    control["B7"], control["C7"], control["D7"] = "BESS operating time", 2, "years"
    control["B8"], control["C8"], control["D8"] = "ESS Usable Power @PoC (AC)", 10, "MW"
    control["B9"], control["C9"], control["D9"] = "ESS Usable Energy @PoC BoL (AC)", 20, "MWh"
    control["G4"], control["H4"], control["I4"] = "IRR", 0.08, 0.06
    control["G12"], control["H12"] = "NPV", 150.0
    control["G17"], control["H17"] = "CAPEX (w/o DSRA and financing fees)", 1000.0
    control["G28"], control["H28"], control["I28"] = "Debt", 500.0, 0.5
    control["G42"], control["H42"] = "Maturity", 2
    control["G43"], control["H43"] = "All-in rate (fixed part)", 0.05
    control["G44"], control["H44"] = "Average DSCR", 1.4
    control["G45"], control["H45"] = "Min. DSCR", 1.4
    control["G7"], control["H7"] = "Equity discount factor", 0.12

    financials = wb.create_sheet("O-Financials")
    financials["K8"] = "Year"
    years = [2025, 2026, 2027]
    for offset, year in enumerate(years):
        financials.cell(row=8, column=12 + offset, value=year)

    def series(row: int, label: str, values: list[float]) -> None:
        financials.cell(row=row, column=4, value=label)
        for offset, value in enumerate(values):
            financials.cell(row=row, column=12 + offset, value=value)

    series(11, "Revenues", [0.0, 500.0, 500.0])
    series(12, "PPA Revenues", [0.0, 100.0, 100.0])
    series(13, "Merchant revenues (net of energy costs)", [0.0, 350.0, 350.0])
    series(14, "Capacity market", [0.0, 50.0, 50.0])
    series(16, "Operating Costs", [0.0, -100.0, -100.0])
    series(27, "Operating Taxes", [0.0, -20.0, -20.0])
    series(58, "CAPEX (w/o DSRA and financing fees)", [-1000.0, 0.0, 0.0])

    wb.save(path)
    return path


@pytest.fixture
def sample_full_bp_with_i_project_path(tmp_path: Path) -> Path:
    """Meme classeur synthetique que sample_full_bp_path, avec en plus un onglet
    I-Project reproduisant le piege du fichier reel : certains libelles ("Maturity",
    "All-in rate (fixed part)") sont repetes une fois pour la dette senior et une
    fois pour la dette de repowering - sert a tester le parametre `occurrence`."""
    path = tmp_path / "synthetic_full_bp_with_i_project.xlsx"
    wb = openpyxl.Workbook()

    control = wb.active
    control.title = "O-Control"
    control["B3"], control["C3"] = "Name", "Synthetic Project"
    control["B4"], control["C4"] = "Location city", "Testville"
    control["B5"], control["C5"] = "Segment", "HTB1"
    control["B6"], control["C6"] = "BESS commercial operation date (COD)", "2027-01-01"
    control["B7"], control["C7"], control["D7"] = "BESS operating time", 2, "years"
    control["B8"], control["C8"], control["D8"] = "ESS Usable Power @PoC (AC)", 10, "MW"
    control["B9"], control["C9"], control["D9"] = "ESS Usable Energy @PoC BoL (AC)", 20, "MWh"
    control["G4"], control["H4"], control["I4"] = "IRR", 0.08, 0.06
    control["G12"], control["H12"] = "NPV", 150.0
    control["G17"], control["H17"] = "CAPEX (w/o DSRA and financing fees)", 1000.0
    control["G28"], control["H28"], control["I28"] = "Debt", 500.0, 0.5
    control["G42"], control["H42"] = "Maturity", 2
    control["G43"], control["H43"] = "All-in rate (fixed part)", 0.05
    control["G44"], control["H44"] = "Average DSCR", 1.4
    control["G45"], control["H45"] = "Min. DSCR", 1.4
    control["G7"], control["H7"] = "Equity discount factor", 0.12

    financials = wb.create_sheet("O-Financials")
    financials["K8"] = "Year"
    years = [2025, 2026, 2027]
    for offset, year in enumerate(years):
        financials.cell(row=8, column=12 + offset, value=year)

    def series(row: int, label: str, values: list[float]) -> None:
        financials.cell(row=row, column=4, value=label)
        for offset, value in enumerate(values):
            financials.cell(row=row, column=12 + offset, value=value)

    series(11, "Revenues", [0.0, 500.0, 500.0])
    series(16, "Operating Costs", [0.0, -100.0, -100.0])
    series(27, "Operating Taxes", [0.0, -20.0, -20.0])
    series(58, "CAPEX (w/o DSRA and financing fees)", [-1000.0, 0.0, 0.0])

    # I-Project a un ordre de colonnes different de O-Control : libelle | unite |
    # valeur (ex. "Maturity | years | 10"), pas libelle | valeur | unite - piege
    # rencontre sur le fichier reel, reproduit ici intentionnellement.
    i_project = wb.create_sheet("I-Project")
    i_project["B10"], i_project["C10"], i_project["D10"] = (
        "CAPEX (w/o DSRA and financing fees)",
        "k€",
        -1050.0,
    )
    i_project["B20"], i_project["C20"], i_project["D20"] = "Target DSCR - Period 1", "x", 1.5
    i_project["B30"], i_project["C30"], i_project["D30"] = (
        "Maturity",
        "years",
        10,
    )  # senior debt (1ere occurrence)
    i_project["B31"], i_project["C31"], i_project["D31"] = (
        "All-in rate (fixed part)",
        "%",
        0.07,
    )  # senior debt
    i_project["B40"], i_project["C40"], i_project["D40"] = (
        "Gearing",
        "%",
        0.6,
    )  # repowering debt (libelle unique)
    i_project["B41"], i_project["C41"], i_project["D41"] = (
        "Maturity",
        "years",
        8,
    )  # repowering debt (2e occurrence)
    i_project["B42"], i_project["C42"], i_project["D42"] = (
        "All-in rate (fixed part)",
        "%",
        0.09,
    )  # repowering debt

    wb.save(path)
    return path


@pytest.fixture
def sample_dev_case_workbook_path(tmp_path: Path) -> Path:
    """Classeur synthetique minimal avec les 3 onglets consommes par
    core/dev_case_parser.py (Inputs Dev / COPEX_library / CF Aurora) - chiffres
    ronds fabriques, pas les vraies donnees Aurora/Clean Horizon confidentielles
    du fichier reel (jamais commite)."""
    path = tmp_path / "synthetic_dev_case.xlsx"
    wb = openpyxl.Workbook()

    inputs_dev = wb.active
    inputs_dev.title = "Inputs Dev"
    rows = [
        ("Entry year (COD)", 2028),
        ("Puissance Nominale", 10),
        ("Capacité énergétique", 20),
        ("Network (Segment)", "TSO 90kV"),
        ("Type TURPE", "Classique"),
        ("Gabarit", 0),
        ("Repowering", 0),
        ("Option 1 - Valeur manuelle", 0),
        ("Option 2 - Distance racco RTE", 0),
        ("Option 3 - Distance HV Substation - BESS", 0),
        ("OPEX Loyer foncier", 5),
    ]
    for i, (label, value) in enumerate(rows, start=1):
        inputs_dev.cell(row=i, column=3, value=label)
        inputs_dev.cell(row=i, column=4, value=value)

    copex = wb.create_sheet("COPEX_library")
    copex["A6"] = "CAPEX assumptions - AURORA (base 2028)"
    copex["A8"] = 2028
    copex["B8"] = "2h - HTB1"
    copex["C8"] = "2h - HTA"
    # Colonnes J+ (index 9+, apres les 7 colonnes segment + 1 separateur) :
    # "Forecast price factor (selon annee de COD)" - delta relatif au cout de
    # base 2028, uniquement renseigne pour "Battery system" dans ce fixture.
    copex.cell(row=8, column=10, value=2030)
    capex_rows = [
        ("Battery system", 100.0, 90.0, -0.10),
        ("Inverter", 20.0, 18.0, None),
        ("Balance of system", 15.0, 14.0, None),
        ("Development", 10.0, 9.0, None),
        ("Grid connection", 20.0, 15.0, None),
        ("EPC soft costs", 15.0, 14.0, None),
    ]
    for offset, (label, v1, v2, escalation) in enumerate(capex_rows, start=9):
        copex.cell(row=offset, column=1, value=label)
        copex.cell(row=offset, column=2, value=v1)
        copex.cell(row=offset, column=3, value=v2)
        if escalation is not None:
            copex.cell(row=offset, column=10, value=escalation)

    copex["A20"] = "OPEX assumptions -  AURORA (base 2028)"
    copex["A21"] = 2028
    copex["B21"] = "2h - HTB1"
    copex["C21"] = "2h - HTA"
    opex_rows = [
        ("Fixed O&M", 2.0, 1.5),
        ("Insurance", 1.0, 0.8),
        ("Grid charges", 0.5, 0.4),
        ("Land lease", 0.0, 0.0),
        ("Accise", 0.0, 0.0),
        ("Other", 0.5, 0.3),
    ]
    for offset, (label, v1, v2) in enumerate(opex_rows, start=22):
        copex.cell(row=offset, column=1, value=label)
        copex.cell(row=offset, column=2, value=v1)
        copex.cell(row=offset, column=3, value=v2)

    aurora = wb.create_sheet("CF Aurora")
    aurora["A1"] = "HTB1"
    aurora["B2"] = "configuration"
    aurora["C2"] = "price"
    aurora["D2"] = "stream"
    for offset, year in enumerate([2028, 2029, 2030], start=5):
        aurora.cell(row=2, column=offset, value=year)
    aurora_2h_rows = [
        ("wholesale_storage_sell_revenue", [50_000.0, 50_000.0, 50_000.0]),
        ("tariff_TURPE 7 revenue", [-5_000.0, -5_000.0, -5_000.0]),
    ]
    for r, (stream, values) in enumerate(aurora_2h_rows, start=3):
        aurora.cell(row=r, column=2, value="C2h1MW")
        aurora.cell(row=r, column=3, value="Aurora - Forecast test")
        aurora.cell(row=r, column=4, value=stream)
        for offset, value in enumerate(values, start=5):
            aurora.cell(row=r, column=offset, value=value)

    aurora["B7"] = "configuration"
    aurora["C7"] = "price"
    aurora["D7"] = "stream"
    for offset, year in enumerate([2028, 2029, 2030], start=5):
        aurora.cell(row=7, column=offset, value=year)
    aurora_4h_rows = [
        ("wholesale_storage_sell_revenue", [90_000.0, 90_000.0, 90_000.0]),
        ("tariff_TURPE 7 revenue", [-8_000.0, -8_000.0, -8_000.0]),
    ]
    for r, (stream, values) in enumerate(aurora_4h_rows, start=8):
        aurora.cell(row=r, column=2, value="CTest4h1MW")
        aurora.cell(row=r, column=3, value="Aurora - Forecast test")
        aurora.cell(row=r, column=4, value=stream)
        for offset, value in enumerate(values, start=5):
            aurora.cell(row=r, column=offset, value=value)

    wb.save(path)
    return path
