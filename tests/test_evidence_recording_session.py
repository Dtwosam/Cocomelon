from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.evidence.contracts import EvidenceRecordingConfig
from cocomelon.evidence.recording import build_recording_bootstrap
from cocomelon.evidence.resume import build_recording_resume_bootstrap
from cocomelon.hyperliquid.ws_protocol import subscription_id

BASE_MS = 1_787_573_000_000


def _ctx(
    mark: str,
    *,
    volume: str,
    oi: str,
    funding: str = "0.00001",
) -> dict[str, object]:
    return {
        "markPx": mark,
        "midPx": mark,
        "oraclePx": mark,
        "funding": funding,
        "openInterest": oi,
        "dayNtlVlm": volume,
        "premium": "0",
        "prevDayPx": str(Decimal(mark) * Decimal("0.99")),
    }


def _meta(name: str, *, delisted: bool = False) -> dict[str, object]:
    return {
        "name": name,
        "szDecimals": 3,
        "maxLeverage": 20,
        "isDelisted": delisted,
    }


NATIVE = (
    (_meta("BTC"), _ctx("64000", volume="1000000000", oi="500000")),
    (_meta("ETH"), _ctx("3200", volume="800000000", oi="400000")),
    (_meta("SOL"), _ctx("180", volume="700000000", oi="350000")),
    (_meta("DOGE"), _ctx("0.20", volume="600000000", oi="300000")),
    (_meta("AVAX"), _ctx("40", volume="500000000", oi="250000")),
    (_meta("XRP"), _ctx("1.20", volume="2000000000", oi="1000000")),
    (_meta("LOW"), _ctx("10", volume="1", oi="1")),
    (_meta("OLD", delisted=True), _ctx("5", volume="300000000", oi="150000")),
)
HIP3 = (
    (_meta("hip3:ABC"), _ctx("25", volume="900000000", oi="450000")),
)


@dataclass
class FakeReader:
    reverse: bool = False

    def __post_init__(self) -> None:
        self.candle_calls: list[tuple[str, str, int, int]] = []
        self.funding_calls: list[tuple[str, int, int | None]] = []

    def perp_dexs(self) -> object:
        return [
            None,
            {
                "name": "hip3",
                "fullName": "HIP3",
                "deployer": "0xabc",
                "oracleUpdater": None,
                "feeRecipient": None,
            },
        ]

    def meta_and_asset_ctxs(self, dex: str = "") -> object:
        rows = HIP3 if dex == "hip3" else NATIVE
        ordered = tuple(reversed(rows)) if self.reverse else rows
        return [
            {"universe": [meta for meta, _ in ordered]},
            [ctx for _, ctx in ordered],
        ]

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        self.candle_calls.append((market.canonical, interval, start_ms, end_ms))
        interval_ms = 300_000 if interval == "5m" else 900_000
        count = 27
        first = end_ms - count * interval_ms
        return [
            {
                "s": market.wire_name,
                "i": interval,
                "t": first + index * interval_ms,
                "T": first + (index + 1) * interval_ms,
                "o": "100",
                "h": "102",
                "l": "99",
                "c": str(Decimal("100") + Decimal(index) / Decimal("100")),
                "v": "1000",
                "n": 100,
            }
            for index in range(count)
        ]

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        self.funding_calls.append((market.canonical, start_ms, end_ms))
        return [
            {
                "coin": market.wire_name,
                "time": BASE_MS - 3_600_000,
                "fundingRate": "0.00001",
                "premium": "0",
            }
        ]


def _clock() -> tuple[callable, list[int]]:
    values = [BASE_MS + index * 1_000 for index in range(200)]
    iterator: Iterator[int] = iter(values)
    observed: list[int] = []

    def now_ms() -> int:
        value = next(iterator)
        observed.append(value)
        return value

    return now_ms, observed


def _bootstrap(reader: FakeReader, *, deep_limit: int = 4):
    now_ms, observed = _clock()
    result = build_recording_bootstrap(
        reader,
        EvidenceRecordingConfig(duration_seconds=3_600, deep_limit=deep_limit),
        now_ms=now_ms,
        code_revision="a" * 40,
    )
    return result, observed


def test_selection_is_permutation_stable_dynamic_and_native_only() -> None:
    first, _ = _bootstrap(FakeReader(reverse=False))
    second, _ = _bootstrap(FakeReader(reverse=True))

    first_selected = tuple(
        (item.market.canonical, item.rank, item.score)
        for item in first.session.selected
    )
    second_selected = tuple(
        (item.market.canonical, item.rank, item.score)
        for item in second.session.selected
    )
    selected_markets = {market for market, _, _ in first_selected}

    assert first_selected == second_selected
    assert len(first_selected) == 4
    assert all(":" not in market for market, _, _ in first_selected)
    assert "LOW" not in selected_markets
    assert "OLD" not in selected_markets
    assert "XRP" in selected_markets
    assert "DOGE" not in selected_markets


def test_resume_bootstrap_preserves_frozen_session_and_refreshes_only_its_cohort() -> None:
    config = EvidenceRecordingConfig(duration_seconds=3_600, deep_limit=3)
    initial_clock, _ = _clock()
    initial = build_recording_bootstrap(
        FakeReader(),
        config,
        now_ms=initial_clock,
        code_revision="a" * 40,
    )
    resumed_reader = FakeReader(reverse=True)
    resumed_clock, observed = _clock()

    resumed = build_recording_resume_bootstrap(
        resumed_reader,
        config,
        initial.session,
        now_ms=resumed_clock,
    )

    assert resumed.session == initial.session
    assert resumed.session.session_id == initial.session.session_id
    assert tuple(item.market for item in resumed.session.selected) == tuple(
        item.market for item in initial.session.selected
    )
    selected = {item.market.canonical for item in initial.session.selected}
    assert {item.meta.market.canonical for item in resumed.snapshots} == selected
    assert {call[0] for call in resumed_reader.candle_calls} == selected
    assert {call[0] for call in resumed_reader.funding_calls} == selected
    assert all(item.received_at_ms in observed for item in resumed.candles)
    assert all(item.received_at_ms in observed for item in resumed.funding_rates)


def test_warmup_uses_response_receive_time_and_requests_required_history() -> None:
    reader = FakeReader()
    bootstrap, observed = _bootstrap(reader, deep_limit=2)
    selected = {item.market.canonical for item in bootstrap.session.selected}

    assert len(reader.candle_calls) == 4
    assert len(reader.funding_calls) == 2
    for market, interval, start_ms, end_ms in reader.candle_calls:
        assert market in selected
        bars = 25
        interval_ms = 300_000 if interval == "5m" else 900_000
        assert end_ms - start_ms >= bars * interval_ms

    selected_candles = [item for item in bootstrap.candles if item.market.canonical in selected]
    assert selected_candles
    assert all(item.received_at_ms > bootstrap.session.started_at_ms for item in selected_candles)
    assert all(item.received_at_ms in observed for item in selected_candles)
    assert all(item.received_at_ms > item.end_ms for item in selected_candles)
    assert all(item.received_at_ms in observed for item in bootstrap.funding_rates)
    assert all(item.received_at_ms > item.time_ms for item in bootstrap.funding_rates)


def test_subscription_plan_is_public_validated_and_under_safety_ceiling() -> None:
    bootstrap, _ = _bootstrap(FakeReader(), deep_limit=5)
    selected = {item.market.wire_name for item in bootstrap.session.selected}
    ids = tuple(subscription_id(item) for item in bootstrap.subscriptions)

    assert len(ids) == len(set(ids))
    assert len(ids) == 1 + len(selected) * 6
    assert len(ids) < 800
    assert "allMids" in ids
    for coin in selected:
        assert f"activeAssetCtx:{coin}" in ids
        assert f"l2Book:{coin}" in ids
        assert f"trades:{coin}" in ids
        assert f"candle:{coin}:1m" in ids
        assert f"candle:{coin}:5m" in ids
        assert f"candle:{coin}:15m" in ids
