from __future__ import annotations

from collections.abc import Callable

import pytest

from cocomelon.cli import DEFAULT_SMOKE_MARKETS, build_parser, stream_smoke_payload
from cocomelon.config import LIVE_ACK, ExecutionMode, Settings

SmokeResult = dict[str, object]
SmokeRunner = Callable[[Settings, float, tuple[str, ...]], SmokeResult]


def test_stream_smoke_parser_defaults_are_bounded_and_market_is_optional() -> None:
    args = build_parser().parse_args(["stream-smoke"])

    assert args.command == "stream-smoke"
    assert args.seconds == 5.0
    assert args.market is None
    assert DEFAULT_SMOKE_MARKETS == ("BTC",)


def test_stream_smoke_parser_has_no_wallet_order_or_live_flags() -> None:
    parser = build_parser()
    forbidden = (
        ["stream-smoke", "--wallet", "0xabc"],
        ["stream-smoke", "--private-key", "secret"],
        ["stream-smoke", "--order", "buy"],
        ["stream-smoke", "--live"],
    )

    for argv in forbidden:
        with pytest.raises(SystemExit):
            parser.parse_args(argv)


def test_stream_smoke_payload_uses_injected_read_only_runner() -> None:
    calls: list[tuple[float, tuple[str, ...]]] = []

    def runner(settings: Settings, seconds: float, markets: tuple[str, ...]) -> SmokeResult:
        assert settings.execution_mode is ExecutionMode.PAPER
        calls.append((seconds, markets))
        return {
            "event_count": 7,
            "gap_count": 0,
            "observed_server_message": True,
        }

    payload = stream_smoke_payload(
        Settings(),
        seconds=2.5,
        markets=("BTC", "xyz:NVDA"),
        runner=runner,
    )

    assert calls == [(2.5, ("BTC", "xyz:NVDA"))]
    assert payload["execution_mode"] == "paper"
    assert payload["ws_url"] == "wss://api.hyperliquid.xyz/ws"
    assert payload["markets"] == ["BTC", "xyz:NVDA"]
    assert payload["event_count"] == 7


def test_stream_smoke_rejects_live_mode_even_though_it_is_read_only() -> None:
    settings = Settings(execution_mode=ExecutionMode.LIVE, live_ack=LIVE_ACK)

    with pytest.raises(ValueError, match="paper mode"):
        stream_smoke_payload(settings, runner=lambda *_: {})


@pytest.mark.parametrize("seconds", [0.0, -1.0, 30.01])
def test_stream_smoke_rejects_unbounded_or_invalid_duration(seconds: float) -> None:
    with pytest.raises(ValueError, match="seconds"):
        stream_smoke_payload(Settings(), seconds=seconds, runner=lambda *_: {})


def test_stream_smoke_rejects_too_many_or_empty_markets() -> None:
    with pytest.raises(ValueError, match="20 markets"):
        stream_smoke_payload(
            Settings(),
            markets=tuple(f"COIN{i}" for i in range(21)),
            runner=lambda *_: {},
        )

    with pytest.raises(ValueError, match="market"):
        stream_smoke_payload(Settings(), markets=("",), runner=lambda *_: {})
