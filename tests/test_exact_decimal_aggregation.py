from __future__ import annotations

from decimal import Decimal, localcontext

import pytest

from cocomelon.research.exact_decimal_aggregation import (
    ExactDecimalAggregationError,
    exact_decimal_sum,
)


def test_exact_decimal_sum_ignores_ambient_precision() -> None:
    values = (
        Decimal("516473753866167234"),
        Decimal("-585.615689306716257"),
        Decimal("34754448.4863227666"),
    )
    with localcontext() as context:
        context.prec = 8
        resolved = exact_decimal_sum(values)

    assert resolved == Decimal(
        "516473753900921096.8706334596"
    )


def test_exact_decimal_sum_preserves_tiny_and_large_terms() -> None:
    values = (
        Decimal("1000000000000000000000000000"),
        Decimal("0.00000000000000000000000001"),
        Decimal("-999999999999999999999999999"),
    )

    assert exact_decimal_sum(values) == Decimal(
        "1.00000000000000000000000001"
    )


def test_exact_decimal_sum_empty_is_zero() -> None:
    assert exact_decimal_sum(()) == Decimal("0")


def test_exact_decimal_sum_rejects_non_finite_values() -> None:
    with pytest.raises(
        ExactDecimalAggregationError,
        match="finite values",
    ):
        exact_decimal_sum((Decimal("NaN"),))
