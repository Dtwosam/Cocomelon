from __future__ import annotations

from datetime import datetime
from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-mainnet-1h-learning.yml")


def test_1h_long_window_workflow_is_free_bounded_and_paper_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "https://api.hyperliquid.xyz" in source
    assert "testnet" not in source.lower()
    assert "COCOMELON_LIVE_ACK" not in source
    assert "requester-pays" not in source.lower()
    assert "workflow_dispatch:" in source
    assert "pull_request:" in source
    assert "schedule:" not in source

    start = datetime.fromisoformat("2026-03-01T00:00:00+00:00")
    end = datetime.fromisoformat("2026-09-20T00:00:00+00:00")
    hourly_intervals = int((end - start).total_seconds() // 3600)
    assert hourly_intervals == 4872
    assert hourly_intervals + 1 <= 5000

    assert 'WINDOW_START_ISO: "2026-03-01T00:00:00+00:00"' in source
    assert 'WINDOW_END_ISO: "2026-09-20T00:00:00+00:00"' in source
    assert "--interval 1h" in source
    assert "--max-candles 5000" in source
    assert "Require complete six-month 1h candle grids" in source
    assert ".complete_requested_grid == true" in source
    assert ".record_count == 4873" in source
    for market in ("BTC", "ETH", "SOL", "HYPE"):
        assert f"--market {market}" in source


def test_1h_long_window_workflow_uses_honest_chronological_evaluation() -> None:
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


def test_1h_long_window_workflow_preserves_same_model_comparison_contract() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-historical-backfill" in source
    assert "cocomelon-historical-model-comparison" in source
    assert "comparison.json" in source
    assert "supervised_numeric_feature_registry" in source
    assert "baseline_folds" in source
    assert "ridge_folds" in source
    assert "horizon_ridge_folds" in source
    assert "stable_horizon_ridge_folds" in source
    assert "occupancy_stable_ridge_folds" in source
    assert "portfolio_capacity_stable_ridge_folds" in source
    assert "stable_tree_folds" in source
    assert "if: ${{ always() }}" in source
    assert "actions/upload-artifact@v7" in source
    assert "if-no-files-found: error" in source


def test_1h_long_window_workflow_reruns_on_core_feature_changes() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for path in (
        "src/cocomelon/research/historical_cross_market.py",
        "src/cocomelon/research/historical_dataset.py",
        "src/cocomelon/research/historical_features.py",
        "src/cocomelon/research/historical_model_comparison.py",
        "src/cocomelon/historical_model_comparison_cli.py",
    ):
        assert f'- "{path}"' in source
