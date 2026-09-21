from __future__ import annotations

from datetime import datetime
from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-mainnet-1h-broad-learning.yml")
MARKETS = ("BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "LINK", "AVAX")


def test_broad_1h_workflow_is_bounded_free_and_paper_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "https://api.hyperliquid.xyz" in source
    assert "testnet" not in source.lower()
    assert "COCOMELON_LIVE_ACK" not in source
    assert "requester-pays" not in source.lower()
    assert "schedule:" not in source

    start = datetime.fromisoformat("2026-03-01T00:00:00+00:00")
    end = datetime.fromisoformat("2026-09-20T00:00:00+00:00")
    hourly_intervals = int((end - start).total_seconds() // 3600)
    assert hourly_intervals == 4872
    assert hourly_intervals + 1 <= 5000

    for market in MARKETS:
        assert source.count(f"--market {market}") >= 2

    assert "--interval 1h" in source
    assert "--max-candles 5000" in source
    assert "Require complete six-month 1h broad candle grids" in source
    assert "length) == 8" in source
    assert ".complete_requested_grid == true" in source
    assert ".record_count == 4873" in source


def test_broad_1h_workflow_keeps_same_economic_gate() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "--anchor-interval 1h" in source
    assert "--horizon-ms 3600000" in source
    assert "--horizon-ms 14400000" in source
    assert "--min-train-anchors 1800" in source
    assert "--validation-anchors 600" in source
    assert "--test-anchors 600" in source
    assert "--step-anchors 600" in source
    assert "--embargo-anchors 4" in source
    assert "--min-validation-mean-net-return 0" in source
    assert "--stability-blocks 4" in source
    assert "--min-validation-block-trades 5" in source
    assert "--portfolio-max-concurrent-positions 2" in source


def test_broad_1h_workflow_preserves_comparison_and_artifacts() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for token in (
        "baseline_folds",
        "ridge_folds",
        "horizon_ridge_folds",
        "stable_horizon_ridge_folds",
        "occupancy_stable_ridge_folds",
        "portfolio_capacity_stable_ridge_folds",
        "stable_tree_folds",
        "supervised_numeric_feature_registry",
    ):
        assert token in source

    assert "comparison.json" in source
    assert "if: ${{ always() }}" in source
    assert "actions/upload-artifact@v7" in source
    assert "if-no-files-found: error" in source
