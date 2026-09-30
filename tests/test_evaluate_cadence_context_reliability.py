from __future__ import annotations

from decimal import Decimal

from cocomelon.research.cadence_context_reliability import (
    CadenceContextReliabilityConfig,
)


def test_default_reliability_contract_is_small_and_positive() -> None:
    config = CadenceContextReliabilityConfig()

    assert config.min_exact_context_rows == 8
    assert config.admission_margin == Decimal("0.0001")
