import pytest

from core import degradation


def test_first_year_multiplier_is_always_one():
    multipliers = degradation.degradation_multipliers(5)
    assert multipliers[0] == 1.0


def test_multipliers_are_cumulative_and_decreasing():
    multipliers = degradation.degradation_multipliers(
        4, first_year_decline=0.02, annual_decline=0.01
    )
    assert multipliers[1] == pytest.approx(0.98)
    assert multipliers[2] == pytest.approx(0.98 * 0.99)
    assert multipliers[3] == pytest.approx(0.98 * 0.99 * 0.99)
    assert multipliers == sorted(multipliers, reverse=True)


def test_conservative_case_degrades_faster_than_base():
    length = 10
    base = degradation.degradation_multipliers(length, **degradation.DEGRADATION_CASES["Base"])
    conservative = degradation.degradation_multipliers(
        length, **degradation.DEGRADATION_CASES["Conservative"]
    )
    assert conservative[-1] < base[-1]
