from __future__ import annotations


def degradation_multipliers(
    length: int,
    *,
    first_year_decline: float = 0.02,
    annual_decline: float = 0.005,
) -> list[float]:
    """Cumulative multiplier curve applied on top of the BP's own revenue series.

    This models an *additional* stress on capacity fade, independent from whatever
    degradation is already embedded in the BP's revenue forecast - it is a
    user-adjustable assumption for scenario/stress-test purposes, not data
    extracted from the BP.
    """
    multipliers = []
    factor = 1.0
    for i in range(length):
        if i > 0:
            decline = first_year_decline if i == 1 else annual_decline
            factor *= 1 - decline
        multipliers.append(factor)
    return multipliers


DEGRADATION_CASES = {
    "Base": {"first_year_decline": 0.02, "annual_decline": 0.005},
    "Conservative": {"first_year_decline": 0.03, "annual_decline": 0.010},
}
