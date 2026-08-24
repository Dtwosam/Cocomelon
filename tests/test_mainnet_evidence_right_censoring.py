from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


def test_right_censoring_guard_rejects_closed_samples_with_open_exposure() -> None:
    module = importlib.import_module("cocomelon.evaluation.mainnet_evidence")
    result = SimpleNamespace(
        opened_positions=2,
        closed_positions=1,
        closed_trade_ids=("trade-a",),
    )

    with pytest.raises(module.MainnetEvidenceError, match="finish flat"):
        module._require_no_right_censoring(result)


def test_right_censoring_guard_accepts_flat_closed_samples() -> None:
    module = importlib.import_module("cocomelon.evaluation.mainnet_evidence")
    result = SimpleNamespace(
        opened_positions=2,
        closed_positions=2,
        closed_trade_ids=("trade-a", "trade-b"),
    )

    module._require_no_right_censoring(result)


def test_right_censoring_guard_allows_zero_trade_diagnostics() -> None:
    module = importlib.import_module("cocomelon.evaluation.mainnet_evidence")
    result = SimpleNamespace(
        opened_positions=1,
        closed_positions=0,
        closed_trade_ids=(),
    )

    module._require_no_right_censoring(result)
