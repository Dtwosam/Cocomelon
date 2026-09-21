from __future__ import annotations

from datetime import datetime
from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-mainnet-1h-spread.yml")


def test_1h_spread_workflow_is_free_bounded_and_paper_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "https://api.hyperliquid.xyz" in source
    assert "testnet" not in source.lower()
    assert "requester-pays" not in source.lower()
    assert "COCOMELON_LIVE_ACK" not in source
    assert "workflow_dispatch:" in source
    assert "pull_request:" in source
    assert "schedule:" not in source

    start = datetime.fromisoformat("2026-03-01T00:00:00+00:00")
    end = datetime.fromisoformat("2026-09-20T00:00:00+00:00")
    hourly_intervals = int((end - start).total_seconds() // 3600)
    assert hourly_intervals == 4872
    assert hourly_intervals + 1 <= 5000

    assert "--interval 1h" in source
    assert "--max-candles 5000" in source
    assert ".complete_requested_grid == true" in source
    assert ".record_count == 4873" in source
    for market in ("BTC", "ETH", "SOL", "HYPE"):
        assert f"--market {market}" in source


def test_1h_spread_workflow_uses_two_leg_cost_and_stability_contract() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-historical-cross-sectional-spread" in source
    assert "--anchor-interval 1h" in source
    assert "--horizon-ms 3600000" in source
    assert "--horizon-ms 14400000" in source
    assert "--round-trip-fee-fraction 0.0007" in source
    assert "--round-trip-slippage-fraction 0.0005" in source
    assert "--funding-reserve-fraction-per-hour 0.0001" in source
    assert "--stability-blocks 4" in source
    assert "--min-markets-per-anchor 4" in source
    assert "--min-block-observations 50" in source
    assert "--min-block-mean-net-return 0" in source


def test_1h_spread_workflow_is_diagnostic_only_and_persists_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "spread.json" in source
    assert "entries" in source
    assert "actions/upload-artifact@v7" in source
    assert "if-no-files-found: error" in source
    assert "cocomelon-historical-model-comparison" not in source
    assert "live" not in source.lower()
