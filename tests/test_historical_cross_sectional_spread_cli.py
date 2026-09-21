from __future__ import annotations

from cocomelon.historical_cross_sectional_spread_cli import build_parser


def _required_args() -> list[str]:
    return [
        "--source-root",
        "sources",
        "--output-root",
        "spread",
        "--market",
        "BTC",
        "--market",
        "ETH",
        "--horizon-ms",
        "3600000",
        "--round-trip-fee-fraction",
        "0.0007",
        "--round-trip-slippage-fraction",
        "0.0005",
        "--funding-reserve-fraction-per-hour",
        "0.0001",
    ]


def test_cross_sectional_spread_parser_defaults_to_fixed_1h_contract() -> None:
    args = build_parser().parse_args(_required_args())

    assert args.anchor_interval == "1h"
    assert args.stability_blocks == 4
    assert args.min_markets_per_anchor == 4
    assert args.min_block_observations == 50
    assert str(args.min_block_mean_net_return) == "0"


def test_cross_sectional_spread_parser_accepts_explicit_15m_anchor() -> None:
    args = build_parser().parse_args(
        [*_required_args(), "--anchor-interval", "15m"]
    )

    assert args.anchor_interval == "15m"
