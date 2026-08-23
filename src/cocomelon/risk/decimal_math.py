from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, localcontext


def divide_down(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Divide positive Decimals without ever rounding the quotient upward."""
    with localcontext() as context:
        context.rounding = ROUND_DOWN
        return numerator / denominator
