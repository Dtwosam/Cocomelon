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
    assert "--stability-blocks 4" in source
    assert "--min-validation-block-trades 5" in source
    assert "--candidate-ridge-alpha 0.01" in source
    assert "--candidate-ridge-alpha 0.1" in source
    assert "--candidate-ridge-alpha 1" in source
    assert "--candidate-ridge-alpha 10" in source
    assert "--ridge-min-market-samples 100" in source
    assert "--portfolio-max-concurrent-positions 2" in source
    assert "--tree-min-market-samples 100" in source
    assert "--tree-max-leaf-nodes 7" in source
    assert "--tree-min-samples-leaf 100" in source
    assert "--tree-learning-rate 0.05" in source
    assert "--tree-max-iter 100" in source
    assert "--tree-l2-regularization 1" in source
    assert "historical-mainnet-learning-2026-09-07-to-2026-09-20" in source


def test_historical_mainnet_learning_workflow_preserves_touched_evidence_artifacts() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-historical-backfill" in source
    assert "cocomelon-historical-experiment" in source
    assert "cocomelon-historical-model-comparison" in source
    assert "experiment.json" in source
    assert "comparison.json" in source
    assert "baseline_folds" in source
    assert "ridge_folds" in source
    assert "horizon_ridge_folds" in source
    assert "stable_horizon_ridge_folds" in source
    assert "occupancy_stable_ridge_folds" in source
    assert "portfolio_capacity_stable_ridge_folds" in source
    assert "stable_tree_folds" in source
    assert "evidence_class" in source
    assert "source_manifest_ids" in source
    assert "shared_validation_candidates" in source
    assert "coin_validation_candidates" in source
    assert "shared_test_breakdowns" in source
    assert "coin_test_breakdowns" in source
    assert "jq '.' \"$SOURCE_ROOT/coverage.json\"" in source
    assert "if: ${{ always() }}" in source
    assert "actions/upload-artifact@v7" in source
    assert "if-no-files-found: error" in source


def test_historical_mainnet_workflow_renders_dataset_feature_registry() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Render training feature registry" in source
    assert "$COMPARISON_ROOT/dataset/manifest.json" in source
    assert "converter_version" in source
    assert "columns" in source



def test_historical_mainnet_workflow_reruns_on_core_feature_changes() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for path in (
        "src/cocomelon/research/historical_cross_market.py",
        "src/cocomelon/research/historical_dataset.py",
        "src/cocomelon/research/historical_features.py",
        "src/cocomelon/research/historical_model_comparison.py",
        "src/cocomelon/historical_model_comparison_cli.py",
    ):
        assert f'- "{path}"' in source
