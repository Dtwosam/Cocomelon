from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest

from cocomelon.research.block_l2_grpc_probe import (
    BlockL2Probe,
    _proto_messages,
    parse_block_l2,
    validate_endpoint,
)


@dataclass
class FakeLevel:
    px: str
    sz: str = "2"
    n: int = 1


@dataclass
class FakeUpdate:
    coin: str = "BLUR"
    time: int = 1000
    block_number: int = 10
    bids: tuple[FakeLevel, ...] = ()
    asks: tuple[FakeLevel, ...] = ()


def book(
    *, time: int = 1000, block: int = 10, depth: int = 20,
    coin: str = "BLUR",
) -> FakeUpdate:
    return FakeUpdate(
        coin=coin, time=time, block_number=block,
        bids=tuple(FakeLevel(str(100 - n)) for n in range(depth)),
        asks=tuple(FakeLevel(str(101 + n)) for n in range(depth)),
    )


def market(probe: BlockL2Probe, end_ns: int) -> dict[str, object]:
    summary = probe.summary(end_ns=end_ns)
    markets = summary["markets"]
    assert isinstance(markets, dict)
    values = markets["BLUR"]
    assert isinstance(values, dict)
    assert summary["trading_authority"] is False
    assert summary["venue_completeness_certified"] is False
    return values


def test_per_block_receipts_integrate_strict_depth_and_source_age() -> None:
    start = 10_000_000_000
    probe = BlockL2Probe(("BLUR",), start_ns=start)
    first = probe.observe(
        book(time=800, block=10), b"first",
        utc_ms=1_000, monotonic_ns=start + 1_000_000_000,
    )
    second = probe.observe(
        book(time=5_900, block=11), b"second",
        utc_ms=6_000, monotonic_ns=start + 6_000_000_000,
    )
    assert first is not None and second is not None
    assert first["has_at_least_20x20_levels"] is True
    assert first["wire_sha256"] == hashlib.sha256(b"first").hexdigest()
    assert second["interval_ms"] == 5_000.0
    values = market(probe, start + 10_000_000_000)
    assert values["unique_blocks"] == 2
    assert values["interval_samples"] == 1
    assert values["interval_ge_3s"] == 1
    assert values["interval_ge_5s"] == 1
    assert values["full_depth_fresh3_time_fraction"] == 0.57
    assert values["full_depth_fresh5_time_fraction"] == 0.88
    assert values == market(probe, start + 10_000_000_000)


def test_duplicate_block_is_not_fake_freshness() -> None:
    start = 500_000_000
    probe = BlockL2Probe(("BLUR",), start_ns=start)
    assert probe.observe(
        book(), b"same", utc_ms=1_100, monotonic_ns=start,
    ) is not None
    duplicate = probe.observe(
        book(), b"same", utc_ms=5_000, monotonic_ns=start + 4_000_000_000,
    )
    assert duplicate is not None and duplicate["result"] == "duplicate_block"
    values = market(probe, start + 8_000_000_000)
    assert values["duplicate_blocks"] == 1
    assert values["unique_blocks"] == 1
    assert values["interval_samples"] == 0
    assert values["full_depth_fresh3_time_fraction"] == 0.3625


def test_conflicting_height_and_regression_revoke_freshness() -> None:
    start = 100
    probe = BlockL2Probe(("BLUR",), start_ns=start)
    assert probe.observe(book(block=10), b"a", utc_ms=1000, monotonic_ns=start)
    conflicting = probe.observe(
        book(block=10), b"b", utc_ms=2000, monotonic_ns=start + 1_000_000_000,
    )
    rollback = probe.observe(
        book(block=9), b"c", utc_ms=3000, monotonic_ns=start + 2_000_000_000,
    )
    assert conflicting is not None and conflicting["result"] == "conflicting_block"
    assert rollback is not None and rollback["result"] == "height_regression"
    values = market(probe, start + 9_000_000_000)
    assert values["conflicting_blocks"] == 1
    assert values["height_regressions"] == 1
    assert values["unique_blocks"] == 1
    assert values["full_depth_fresh3_time_fraction"] == pytest.approx(1 / 9)


def test_shallow_and_future_dated_books_never_count_as_fresh() -> None:
    start = 1000
    probe = BlockL2Probe(("BLUR",), start_ns=start)
    shallow = probe.observe(
        book(depth=5), b"shallow", utc_ms=1000, monotonic_ns=start
    )
    future = probe.observe(
        book(block=11, time=5000), b"future",
        utc_ms=4000, monotonic_ns=start + 2_000_000_000,
    )
    assert shallow is not None and not shallow["has_at_least_20x20_levels"]
    assert future is not None and future["has_at_least_20x20_levels"]
    values = market(probe, start + 8_000_000_000)
    assert values["books_under_20_levels_per_side"] == 1
    assert values["future_dated_books"] == 1
    assert values["full_depth_fresh3_time_fraction"] == 0.0
    assert values["full_depth_fresh5_time_fraction"] == 0.0


def test_parse_fails_closed_for_crossed_ordered_invalid_or_empty_book() -> None:
    crossed = book()
    crossed.asks = (FakeLevel("99"),)
    with pytest.raises(ValueError, match="crossed"):
        parse_block_l2(crossed, b"a")
    wrong = book()
    wrong.bids = (FakeLevel("98"), FakeLevel("99"))
    with pytest.raises(ValueError, match="descend"):
        parse_block_l2(wrong, b"b")
    bad = book()
    bad.bids = (FakeLevel("NaN"),)
    with pytest.raises(ValueError, match="invalid book levels"):
        parse_block_l2(bad, b"c")
    empty = book()
    empty.asks = ()
    with pytest.raises(ValueError, match="empty"):
        parse_block_l2(empty, b"d")


def test_invalid_and_untracked_source_does_not_extend_cohort() -> None:
    start = 100
    probe = BlockL2Probe(("BLUR",), start_ns=start)
    assert probe.observe(book(coin="BTC"), b"btc", utc_ms=1000, monotonic_ns=101) is None
    assert probe.observe(object(), b"invalid", utc_ms=1000, monotonic_ns=102) is None
    result = probe.summary(end_ns=103)
    assert result["untracked_messages"] == 1
    assert result["parse_errors"] == 1
    with pytest.raises(ValueError):
        probe.observe(book(), b"backward", utc_ms=1000, monotonic_ns=99)
    with pytest.raises(ValueError):
        BlockL2Probe(("BLUR", "BLUR"), start_ns=start)
    with pytest.raises(ValueError):
        BlockL2Probe(("BTC",), start_ns=start)


def test_only_quicknode_tls_mainnet_endpoint_is_allowed() -> None:
    valid = "example.hype-mainnet.quiknode.pro:10000"
    assert validate_endpoint(valid) == valid
    for wrong in (
        "evil.com:10000", "example.hype-testnet.quiknode.pro:10000",
        "http://example.hype-mainnet.quiknode.pro:10000",
        "username@host.hype-mainnet.quiknode.pro:10000",
        "host.hype-mainnet.quiknode.pro:8080",
        "host.hype-mainnet.quiknode.pro:10000/hidden",
        "",
    ):
        with pytest.raises(ValueError):
            validate_endpoint(wrong)


def test_vendor_protobuf_wire_fields_are_compatible_when_installed() -> None:
    pytest.importorskip("google.protobuf")
    request, response = _proto_messages()
    obj = request(coin="BLUR", n_levels=20)
    assert request.FromString(obj.SerializeToString()).coin == "BLUR"
    update = response(coin="BLUR", time=1000, block_number=5)
    bid = update.bids.add()
    bid.px, bid.sz, bid.n = "100", "1", 1
    ask = update.asks.add()
    ask.px, ask.sz, ask.n = "101", "1", 1
    restored = response.FromString(update.SerializeToString())
    parsed = parse_block_l2(restored, update.SerializeToString())
    assert parsed.coin == "BLUR"
    assert parsed.height == 5
    assert parsed.bids[0].px == 100
