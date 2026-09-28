from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

ZERO = Decimal("0")


class ExactDecimalAggregationError(ValueError):
    pass


def exact_decimal_sum(values: Iterable[Decimal]) -> Decimal:
    resolved = tuple(values)
    if not resolved:
        return ZERO
    if any(not value.is_finite() for value in resolved):
        raise ExactDecimalAggregationError(
            "exact decimal aggregation requires finite values"
        )

    exponents = tuple(
        int(value.as_tuple().exponent)
        for value in resolved
    )
    base_exponent = min(exponents)
    total_coefficient = 0

    for value, exponent in zip(
        resolved,
        exponents,
        strict=True,
    ):
        decimal_tuple = value.as_tuple()
        coefficient = 0
        for digit in decimal_tuple.digits:
            coefficient = coefficient * 10 + digit
        if decimal_tuple.sign:
            coefficient = -coefficient
        total_coefficient += coefficient * (
            10 ** (exponent - base_exponent)
        )

    if total_coefficient == 0:
        return ZERO

    sign = 1 if total_coefficient < 0 else 0
    digits = tuple(
        int(character)
        for character in str(abs(total_coefficient))
    )
    return Decimal((sign, digits, base_exponent))
