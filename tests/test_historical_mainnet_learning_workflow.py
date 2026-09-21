from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-mainnet-learning.yml")


def test_historical_mainnet_learning_workflow_is_bounded_and_paper_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "https://api.hyperliquid.xyz" in source
    assert "testnet" not in source.lower()
    assert "COCOMELON_LIVE_ACK" not in source
    assert "workflow_dispatch:" in source
    assert "pull_request:" in source
    assert "schedule:" not in source

    assert 'WINDOW_START_ISO: "2026-09-07T00:00:00+00:00"' in source
    assert 'WINDOW_END_ISO: "2026-09-20T00:00:00+00:00"' in source
    for market in ("BTC", "ETH", "SOL", "HYPE"):
        assert f"--market {market}" in source

    assert "--interval 5m" in source
    assert "--interval 15m" in source
    assert "--horizon-ms 900000" in source
    assert "--horizon-ms 3600000" in source
    assert "--horizon-ms 14400000" in source
    assert "--min-train-anchors 1400" in source
    assert "--validation-anchors 500" in source
    assert "--test-anchors 500" in source
    assert "--step-anchors 500" in source
    assert "--embargo-anchors 48" in source
    assert "--min-validation-trades 20" in source
    assert "historical-mainnet-learning-2026-08" in source


def test_historical_mainnet_learning_workflow_preserves_touched_evidence_artifacts() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-historical-backfill" in source
    assert "cocomelon-historical-experiment" in source
    assert "experiment.json" in source
    assert "evidence_class" in source
    assert "source_manifest_ids" in source
    assert 'jq '.' "$SOURCE_ROOT/coverage.json"' in source
    assert "if: ${{ always() }}" in source
    assert "actions/upload-artifact@v7" in source
    assert "if-no-files-found: error" in source
