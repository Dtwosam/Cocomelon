from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, localcontext

RISK_DECIMAL_PRECISION = 28


@contextmanager
def risk_decimal_context() -> Iterator[None]:
    """Run authoritative risk arithmetic in a fixed deterministic Decimal context."""
    with localcontext() as context:
        context.prec = RISK_DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        yield


def divide_down(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Divide positive Decimals without ever rounding the quotient upward."""
    with localcontext() as context:
        context.prec = RISK_DECIMAL_PRECISION
        context.rounding = ROUND_DOWN
        return numerator / denominator
