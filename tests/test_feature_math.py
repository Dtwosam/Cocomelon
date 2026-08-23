import importlib
from decimal import Decimal

import pytest

feature_math = importlib.import_module("cocomelon.features.math")
percentile_rank = feature_math.percentile_rank
quantile = feature_math.quantile


def test_percentile_rank_is_order_invariant_and_uses_midpoint_for_ties() -> None:
    values = (Decimal("4"), Decimal("2"), Decimal("1"), Decimal("2"))

    assert percentile_rank(values, Decimal("1")) == Decimal("0")
    assert percentile_rank(values, Decimal("2")) == Decimal("0.5")
    assert percentile_rank(tuple(reversed(values)), Decimal("2")) == Decimal("0.5")
    assert percentile_rank(values, Decimal("4")) == Decimal("1")


def test_percentile_rank_singleton_is_neutral_midpoint() -> None:
    assert percentile_rank((Decimal("7"),), Decimal("7")) == Decimal("0.5")


def test_percentile_rank_rejects_empty_or_absent_value() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        percentile_rank((), Decimal("1"))
    with pytest.raises(ValueError, match="value must be present"):
        percentile_rank((Decimal("1"), Decimal("2")), Decimal("3"))


def test_quantile_is_deterministic_with_linear_interpolation() -> None:
    values = (Decimal("8"), Decimal("1"), Decimal("4"), Decimal("2"))

    assert quantile(values, Decimal("0")) == Decimal("1")
    assert quantile(values, Decimal("0.5")) == Decimal("3")
    assert quantile(values, Decimal("1")) == Decimal("8")
    assert quantile(tuple(reversed(values)), Decimal("0.5")) == Decimal("3")


def test_quantile_rejects_empty_input_and_out_of_range_q() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        quantile((), Decimal("0.5"))
    with pytest.raises(ValueError, match="between 0 and 1"):
        quantile((Decimal("1"),), Decimal("1.01"))
