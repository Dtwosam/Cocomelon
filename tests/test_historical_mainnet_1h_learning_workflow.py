from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-mainnet-1h-learning.yml")


def test_historical_mainnet_1h_workflow_is_free_bounded_and_paper_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "https://api.hyperliquid.xyz" in source
    assert "testnet" not in source.lower()
    assert "COCOMELON_LIVE_ACK" not in source
    assert "workflow_dispatch:" in source
    assert "schedule:" not in source

    assert 'WINDOW_START_ISO: "2026-04-01T00:00:00+00:00"' in source
    assert 'WINDOW_END_ISO: "2026-09-20T00:00:00+00:00"' in source
    assert "--interval 1h" in source
    assert "--max-candles 5000" in source
    assert "historical-archive" not in source
    assert "requester" not in source.lower()

    for market in ("BTC", "ETH", "SOL", "HYPE"):
        assert f"--market {market}" in source


def test_historical_mainnet_1h_workflow_locks_chronology_and_costs() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "--anchor-interval 1h" in source
    assert "--horizon-ms 3600000" in source
    assert "--horizon-ms 14400000" in source
    assert "--min-train-anchors 1200" in source
    assert "--validation-anchors 480" in source
    assert "--test-anchors 480" in source
    assert "--step-anchors 480" in source
    assert "--embargo-anchors 4" in source

    assert "--round-trip-fee-fraction 0.0007" in source
    assert "--round-trip-slippage-fraction 0.0005" in source
    assert "--funding-reserve-fraction-per-hour 0.0001" in source
    assert "--stability-blocks 4" in source
    assert "--min-validation-block-trades 5" in source
    assert "--portfolio-max-concurrent-positions 2" in source


def test_historical_mainnet_1h_workflow_preserves_full_comparison_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-historical-backfill" in source
    assert "cocomelon-historical-model-comparison" in source
    assert "supervised_numeric_feature_registry" in source
    assert "stable_horizon_ridge_folds" in source
    assert "occupancy_stable_ridge_folds" in source
    assert "portfolio_capacity_stable_ridge_folds" in source
    assert "stable_tree_folds" in source
    assert "actions/upload-artifact@v7" in source
    assert "if-no-files-found: error" in source
