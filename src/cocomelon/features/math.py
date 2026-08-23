from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def _validated(values: Sequence[Decimal]) -> tuple[Decimal, ...]:
    if not values:
        raise ValueError("values must not be empty")
    normalized = tuple(values)
    if any(not value.is_finite() for value in normalized):
        raise ValueError("values must be finite")
    return normalized


def percentile_rank(values: Sequence[Decimal], value: Decimal) -> Decimal:
    normalized = _validated(values)
    if not value.is_finite():
        raise ValueError("value must be finite")
    ordered = tuple(sorted(normalized))
    positions = tuple(index for index, item in enumerate(ordered) if item == value)
    if not positions:
        raise ValueError("value must be present in values")
    if len(ordered) == 1:
        return Decimal("0.5")
    midpoint = (Decimal(positions[0]) + Decimal(positions[-1])) / Decimal("2")
    return midpoint / Decimal(len(ordered) - 1)


def quantile(values: Sequence[Decimal], q: Decimal) -> Decimal:
    normalized = _validated(values)
    if not q.is_finite() or q < 0 or q > 1:
        raise ValueError("q must be finite and between 0 and 1")
    ordered = tuple(sorted(normalized))
    if len(ordered) == 1:
        return ordered[0]
    position = q * Decimal(len(ordered) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    return lower + (upper - lower) * fraction
