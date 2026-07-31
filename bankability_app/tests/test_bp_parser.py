import pytest

from core import bp_parser, financial_engine


def test_detect_format_summary(sample_summary_bp_path):
    assert bp_parser.detect_format(sample_summary_bp_path) == "summary"


def test_detect_format_full(sample_full_bp_path):
    assert bp_parser.detect_format(sample_full_bp_path) == "full"


def test_parse_summary_bp_extracts_project_header(sample_summary_bp_path):
    inputs = bp_parser.parse_summary_bp(sample_summary_bp_path)

    assert inputs.name == "Fougeres"
    assert inputs.segment == "HTB2"
    assert inputs.usable_power_mw == pytest.approx(20.0)
    assert inputs.usable_energy_mwh == pytest.approx(40.0)
    assert inputs.operating_years == 20
    assert inputs.capex_initial_keur == pytest.approx(14707.0)
    assert inputs.repowering is False


def test_parse_summary_bp_extracts_year_aligned_series(sample_summary_bp_path):
    inputs = bp_parser.parse_summary_bp(sample_summary_bp_path)

    assert inputs.years[0] == 2027
    assert len(inputs.years) == 33
    # Annee de construction : CAPEX seul, pas de revenu/OPEX/TURPE.
    assert inputs.capex_keur[0] == pytest.approx(-14707.0)
    assert inputs.opex_keur[0] == 0.0
    # 1ere annee d'exploitation (2028) : valeurs connues du BP source, deja
    # negatives pour OPEX/TURPE (convention BP), positives pour Revenues.
    assert inputs.opex_keur[1] == pytest.approx(-469.0)
    assert inputs.revenues_keur[1] == pytest.approx(3087.0)
    assert inputs.turpe_keur[1] == pytest.approx(-272.0)


def test_parse_summary_bp_reported_metrics_match_engine_unlevered_irr(sample_summary_bp_path):
    """Le fixture encode l'IRR projet (non lévère) déjà calculé dans le BP source (6.66%).
    Avec gearing=0%, notre moteur doit retomber quasiment exactement sur ce chiffre -
    c'est la validation croisée qui a confirme les conventions de signe du parser."""
    inputs = bp_parser.parse_summary_bp(sample_summary_bp_path)
    assert inputs.reported_irr == pytest.approx(0.0666)

    result = financial_engine.compute_results(inputs, gearing_pct=0.0)
    assert result.project_irr == pytest.approx(inputs.reported_irr, abs=0.001)


def test_parse_full_bp_extracts_project_header(sample_full_bp_path):
    inputs = bp_parser.parse_full_bp(sample_full_bp_path)

    assert inputs.name == "Synthetic Project"
    assert inputs.location == "Testville"
    assert inputs.segment == "HTB1"
    assert inputs.usable_power_mw == pytest.approx(10.0)
    assert inputs.usable_energy_mwh == pytest.approx(20.0)


def test_parse_full_bp_extracts_series_with_bp_sign_convention(sample_full_bp_path):
    inputs = bp_parser.parse_full_bp(sample_full_bp_path)

    assert inputs.years == [2025, 2026, 2027]
    assert inputs.capex_keur == pytest.approx([-1000.0, 0.0, 0.0])
    assert inputs.opex_keur == pytest.approx([0.0, -100.0, -100.0])
    assert inputs.turpe_keur == pytest.approx([0.0, -20.0, -20.0])
    assert inputs.revenues_keur == pytest.approx([0.0, 500.0, 500.0])


def test_parse_full_bp_extracts_financing_terms_and_offset_fields(sample_full_bp_path):
    inputs = bp_parser.parse_full_bp(sample_full_bp_path)

    assert inputs.gearing_pct == pytest.approx(0.5)  # 2e valeur apres le label "Debt"
    assert inputs.interest_rate == pytest.approx(0.05)
    assert inputs.debt_tenor_years == 2
    assert inputs.reported_irr == pytest.approx(0.08)  # 1ere valeur apres "IRR"
    assert inputs.reported_equity_irr == pytest.approx(0.06)  # 2e valeur apres "IRR"
    assert inputs.reported_dscr_avg == pytest.approx(1.4)
    assert inputs.reported_dscr_min == pytest.approx(1.4)
    # WACC non present tel quel dans le BP -> approxime par un blend gearing/cout de la dette/equity.
    assert inputs.wacc == pytest.approx(0.5 * 0.05 + 0.5 * 0.12)


def test_parse_bp_dispatches_on_detected_format(sample_summary_bp_path, sample_full_bp_path):
    summary_inputs = bp_parser.parse_bp(sample_summary_bp_path)
    full_inputs = bp_parser.parse_bp(sample_full_bp_path)

    assert summary_inputs.name == "Fougeres"
    assert full_inputs.name == "Synthetic Project"


def test_parse_summary_bp_raises_on_missing_year_row(tmp_path):
    import openpyxl

    path = tmp_path / "broken.xlsx"
    wb = openpyxl.Workbook()
    wb.active["B2"] = "Name"
    wb.active["C2"] = "No Year Row Here"
    wb.save(path)

    with pytest.raises(ValueError, match="Year"):
        bp_parser.parse_summary_bp(path)
