from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-long-window-learning.yml")


def test_long_window_workflow_is_fixed_public_mainnet_and_paper_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "https://api.hyperliquid.xyz" in source
    assert "testnet" not in source.lower()
    assert "COCOMELON_LIVE_ACK" not in source
    assert "schedule:" not in source
    assert "workflow_dispatch:" in source
    assert "pull_request:" in source

    assert 'WINDOW_START_ISO: "2026-07-01T00:00:00+00:00"' in source
    assert 'WINDOW_END_ISO: "2026-09-20T00:00:00+00:00"' in source
    assert "--min-train-anchors 8000" in source
    assert "--validation-anchors 2000" in source
    assert "--test-anchors 2000" in source
    assert "--step-anchors 2000" in source
    assert "--embargo-anchors 48" in source


def test_long_window_workflow_preserves_models_stability_and_economics() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for market in ("BTC", "ETH", "SOL", "HYPE"):
        assert f"--market {market}" in source
    for horizon in ("900000", "3600000", "14400000"):
        assert f"--horizon-ms {horizon}" in source

    assert "--round-trip-fee-fraction 0.0007" in source
    assert "--round-trip-slippage-fraction 0.0005" in source
    assert "--funding-reserve-fraction-per-hour 0.0001" in source
    assert "--baseline-min-state-samples 50" in source
    assert "--baseline-min-coin-samples 100" in source
    assert "--ridge-min-market-samples 100" in source
    assert "--min-sample-count 50" in source
    assert "--min-validation-trades 20" in source
    assert "--stability-blocks 4" in source
    assert "--min-validation-block-trades 5" in source

    assert "cocomelon-historical-backfill" in source
    assert "cocomelon-historical-model-comparison" in source
    assert "baseline_folds" in source
    assert "ridge_folds" in source
    assert "horizon_ridge_folds" in source
    assert "stable_horizon_ridge_folds" in source
    assert "actions/upload-artifact@v7" in source
    assert "if-no-files-found: error" in source
    assert "historical-mainnet-learning-2026-07-01-to-2026-09-20" in source
