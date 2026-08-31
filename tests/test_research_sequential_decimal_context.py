from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP, Context, Decimal, localcontext

from cocomelon.research.sequential import posterior_probability_positive


def _posterior(context: Context) -> Decimal:
    values = tuple(
        Decimal(value)
        for value in (
            "0.123456789",
            "-0.031415926",
            "0.271828182",
            "0.090909091",
            "-0.0625",
        )
        * 4
    )
    with localcontext(context):
        return posterior_probability_positive(values)


def test_posterior_probability_ignores_ambient_decimal_context() -> None:
    low_precision = Context(prec=4, rounding=ROUND_DOWN)
    high_precision = Context(prec=50, rounding=ROUND_UP)

    assert _posterior(low_precision) == _posterior(high_precision)
