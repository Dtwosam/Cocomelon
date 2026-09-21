from __future__ import annotations

from cocomelon.historical_model_comparison_cli import build_parser


def _required_args() -> list[str]:
    return [
        "--source-root",
        "sources",
        "--output-root",
        "comparison",
        "--market",
        "BTC",
        "--horizon-ms",
        "3600000",
        "--round-trip-fee-fraction",
        "0.0007",
        "--round-trip-slippage-fraction",
        "0.0005",
        "--funding-reserve-fraction-per-hour",
        "0.0001",
        "--candidate-threshold",
        "0",
        "--candidate-ridge-alpha",
        "0.1",
        "--min-train-anchors",
        "10",
        "--validation-anchors",
        "4",
        "--test-anchors",
        "4",
        "--step-anchors",
        "4",
        "--embargo-anchors",
        "1",
        "--baseline-min-state-samples",
        "2",
        "--baseline-min-coin-samples",
        "2",
        "--ridge-min-market-samples",
        "2",
        "--min-sample-count",
        "2",
        "--min-validation-trades",
        "1",
    ]


def test_model_comparison_parser_accepts_1h_anchor_interval() -> None:
    args = build_parser().parse_args(
        [*_required_args(), "--anchor-interval", "1h"]
    )

    assert args.anchor_interval == "1h"


def test_model_comparison_parser_keeps_5m_default() -> None:
    args = build_parser().parse_args(_required_args())

    assert args.anchor_interval == "5m"
