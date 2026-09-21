from __future__ import annotations

from datetime import datetime
from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-mainnet-15m-learning.yml")


def test_15m_historical_workflow_is_bounded_free_and_paper_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "https://api.hyperliquid.xyz" in source
    assert "testnet" not in source.lower()
    assert "COCOMELON_LIVE_ACK" not in source
    assert "workflow_dispatch:" in source
    assert "schedule:" not in source

    assert 'WINDOW_START_ISO: "2026-08-01T00:00:00+00:00"' in source
    assert 'WINDOW_END_ISO: "2026-09-20T00:00:00+00:00"' in source
    assert "--interval 15m" in source
    assert "--interval 5m" not in source
    assert "--max-candles 5000" in source
    assert "--anchor-interval 15m" in source

    start = datetime.fromisoformat("2026-08-01T00:00:00+00:00")
    end = datetime.fromisoformat("2026-09-20T00:00:00+00:00")
    expected_candle_count = int((end - start).total_seconds() // (15 * 60)) + 1
    assert expected_candle_count <= 5000

    for market in ("BTC", "ETH", "SOL", "HYPE"):
        assert f"--market {market}" in source

    assert "--horizon-ms 900000" in source
    assert "--horizon-ms 3600000" in source
    assert "--horizon-ms 14400000" in source
    assert "--embargo-anchors 16" in source
    assert "--stability-blocks 4" in source
    assert "--min-validation-block-trades 5" in source


def test_15m_workflow_keeps_distinct_artifact_and_dataset_identity() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "historical-mainnet-15m-2026-08-01-to-2026-09-20" in source
    assert "anchor_interval" in source
    assert "supervised_numeric_feature_registry" in source
    assert "stable_horizon_ridge_folds" in source
    assert "stable_tree_folds" in source
    assert "actions/upload-artifact@v7" in source
    assert "if-no-files-found: error" in source
