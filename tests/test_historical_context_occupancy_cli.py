from __future__ import annotations

from cocomelon.historical_context_occupancy_cli import build_parser
from cocomelon.research.historical_baselines import DecisionAction

DISCOVERY_REPORT_ID = "f3b38a6625ad2ea2d1b2df7e736f5dbded6f2b415c53c80db35514e4f3589481"
DISCOVERY_DATASET_ID = "268aa965584316f35a9db520b13848fd030123eadc99482a89cd7bc68ffc091f"


def _required_args() -> list[str]:
    return [
        "--source-root",
        "sources",
        "--output-root",
        "out",
        "--market",
        "BTC",
        "--market",
        "ETH",
        "--market",
        "SOL",
        "--market",
        "HYPE",
        "--horizon-ms",
        "14400000",
        "--discovery-report-id",
        DISCOVERY_REPORT_ID,
        "--discovery-dataset-id",
        DISCOVERY_DATASET_ID,
        "--candidate-market",
        "HYPE",
        "--context-state",
        "down/bearish/near_basket",
        "--direction",
        "long",
        "--candidate-horizon-ms",
        "14400000",
        "--round-trip-fee-fraction",
        "0.0007",
        "--round-trip-slippage-fraction",
        "0.0005",
        "--funding-reserve-fraction-per-hour",
        "0.0001",
    ]


def test_context_occupancy_parser_defaults_to_strict_contract() -> None:
    args = build_parser().parse_args(_required_args())

    assert args.anchor_interval == "1h"
    assert args.stability_blocks == 4
    assert args.min_block_trades == 20
    assert str(args.min_block_mean_net_return) == "0"
    assert args.direction is DecisionAction.LONG
    assert args.candidate_market.canonical == "HYPE"


def test_context_occupancy_parser_accepts_short_direction() -> None:
    argv = _required_args()
    direction_index = argv.index("--direction") + 1
    argv[direction_index] = "short"
    args = build_parser().parse_args(argv)

    assert args.direction is DecisionAction.SHORT
