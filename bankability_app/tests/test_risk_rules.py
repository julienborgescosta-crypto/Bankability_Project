import pytest

from core import financial_engine, risk_rules

THRESHOLDS = {
    "dscr_min_red": 1.10,
    "dscr_min_amber": 1.30,
    "equity_irr_hurdle": 0.08,
    "project_irr_vs_wacc_margin": 0.0,
}


def _flag(flags, label):
    return next(f for f in flags if f.label == label)


def test_healthy_project_gets_green_flags(simple_inputs):
    # gearing_pct=0 -> DSCR non calculable (pas de dette), mais IRR/WACC restent verifiables.
    result = financial_engine.compute_results(simple_inputs, gearing_pct=0.30)
    flags = risk_rules.evaluate_risks(simple_inputs, result, THRESHOLDS)

    dscr_flag = _flag(flags, "DSCR min")
    assert dscr_flag.level == "green"


def test_distressed_project_gets_red_dscr_flag(simple_inputs):
    # Gearing tres eleve -> service de la dette ecrase le CFADS -> DSCR faible.
    result = financial_engine.compute_results(simple_inputs, gearing_pct=0.95, interest_rate=0.15)
    flags = risk_rules.evaluate_risks(simple_inputs, result, THRESHOLDS)

    dscr_flag = _flag(flags, "DSCR min")
    assert dscr_flag.level == "red"


def test_project_irr_below_wacc_is_red(simple_inputs):
    simple_inputs.wacc = 0.99  # aucun projet ne bat un WACC a 99%
    result = financial_engine.compute_results(simple_inputs, gearing_pct=0.5)
    flags = risk_rules.evaluate_risks(simple_inputs, result, THRESHOLDS)

    wacc_flag = _flag(flags, "Project IRR vs WACC")
    assert wacc_flag.level == "red"


def test_target_dscr_overrides_generic_amber_threshold(simple_inputs):
    """DSCR ~1.41 (gearing 50%, defaut de simple_inputs) est vert sous le seuil
    generique (1.30x) mais doit devenir orange si le covenant du projet
    (I-Project "Target DSCR") est plus strict (1.5x)."""
    result = financial_engine.compute_results(simple_inputs)
    assert result.dscr_min == pytest.approx(1.4132, abs=0.001)

    flags_generic = risk_rules.evaluate_risks(simple_inputs, result, THRESHOLDS)
    assert _flag(flags_generic, "DSCR min").level == "green"

    simple_inputs.target_dscr = 1.5
    flags_with_target = risk_rules.evaluate_risks(simple_inputs, result, THRESHOLDS)
    dscr_flag = _flag(flags_with_target, "DSCR min")
    assert dscr_flag.level == "amber"
    assert "cible du projet" in dscr_flag.message


def test_load_thresholds_reads_the_config_file():
    thresholds = risk_rules.load_thresholds()
    assert thresholds["dscr_min_amber"] == pytest.approx(1.30)
    assert thresholds["dscr_min_red"] == pytest.approx(1.10)
