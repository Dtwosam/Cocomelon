"""Synthetic protocol receipts; these do not establish real prospective source coverage."""

from copy import deepcopy
from decimal import Decimal

import pytest

from cocomelon.domain.features import EligibilityDecision
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamKind
from cocomelon.research.volatility_budget import EIGHT_HOURS_MS
from cocomelon.research.volatility_source import MARKETS, VolatilitySource

BTC = MarketId("", "BTC")
DAY = 86_400_000
T = 100 * DAY + 30_000


def _candles() -> list[dict[str, object]]:
    return [
        dict(
            s="BTC",
            i="8h",
            t=start,
            T=start + EIGHT_HOURS_MS - 1,
            o="100",
            h="101",
            l="99",
            c="100",
            v="20",
            n=3,
        )
        for start in range(70 * DAY, 100 * DAY, EIGHT_HOURS_MS)
    ]


def _meta() -> list[object]:
    return [
        {"universe": [dict(name=m.coin, szDecimals=3, maxLeverage=20) for m in MARKETS]},
        [
            dict(
                dayNtlVlm="20000000",
                funding="0.00001",
                markPx="100",
                midPx="100",
                openInterest="100000",
                oraclePx="100",
                premium="0",
                prevDayPx="100",
            )
            for _ in MARKETS
        ],
    ]


def _book(t: int = T - 100) -> dict[str, object]:
    return {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "time": t,
            "levels": [
                [{"px": "99.99", "sz": "1000", "n": 1}],
                [{"px": "100.01", "sz": "1000", "n": 1}],
            ],
        },
    }


def test_archive_precedes_mutation_and_preserves_full_response_and_real_receipt() -> None:
    receipts: list[dict[str, object]] = []
    source = VolatilitySource(receipts.append)
    source.ingest_candles(BTC, _candles(), received_at_ms=T - 2, request_started_ms=T - 200)
    windows = source.daily_windows(T, eligibility={})
    assert len(receipts) == 1 and receipts[0]["raw"] == _candles()
    assert receipts[0]["received_at_ms"] == T - 2
    assert receipts[0]["request_started_ms"] == T - 200
    assert windows[0].bars[-1].received_at_ms == T - 2
    assert windows[0].eligibility.deep_ready is False
    assert windows[0].bars[0].open_time_ms == 70 * DAY


def test_archive_failure_cannot_release_unarchived_observations() -> None:
    def fail(_: object) -> None:
        raise OSError("synthetic disk failure")

    source = VolatilitySource(fail)
    with pytest.raises(OSError):
        source.ingest_ws(_book(), received_at_ms=T)
    assert source.books == {}


def test_closed_candles_keep_first_receipt_and_unfinished_rows_are_not_admitted() -> None:
    source = VolatilitySource(lambda _: None)
    values = _candles()
    source.ingest_candles(BTC, values, received_at_ms=T - 100)
    source.ingest_candles(BTC, values, received_at_ms=T - 1)
    unfinished = dict(values[-1], t=100 * DAY, T=100 * DAY + EIGHT_HOURS_MS - 1)
    source.ingest_candles(BTC, [unfinished], received_at_ms=T)
    bars = source.daily_windows(T, eligibility={})[0].bars
    assert len(bars) == 90
    assert bars[-1].received_at_ms == T - 100


def test_late_candle_retrieval_never_becomes_predecision_availability() -> None:
    source = VolatilitySource(lambda _: None)
    source.ingest_candles(BTC, _candles(), received_at_ms=T + 1)
    assert source.daily_windows(T, eligibility={})[0].bars == ()


def test_conflicting_closed_candle_rejects_whole_page_without_overwriting_first() -> None:
    source = VolatilitySource(lambda _: None)
    values = _candles()
    source.ingest_candles(BTC, values, received_at_ms=T - 100)
    changed = deepcopy(values)
    changed[-1]["c"] = "100.5"
    with pytest.raises(ValueError, match="conflicting closed candle"):
        source.ingest_candles(BTC, changed, received_at_ms=T - 1)
    assert source.daily_windows(T, eligibility={})[0].bars[-1].close == Decimal("100")


@pytest.mark.parametrize(
    "change", [dict(i="1d"), dict(n=True), dict(o="NaN"), dict(T=100), dict(v="0")]
)
def test_malformed_closed_candles_fail_without_partial_admission(change: dict[str, object]) -> None:
    source = VolatilitySource(lambda _: None)
    values = _candles()
    values[-1].update(change)
    with pytest.raises(ValueError):
        source.ingest_candles(BTC, values, received_at_ms=T - 1)
    assert source.daily_windows(T, eligibility={})[0].bars == ()


def test_original_ws_book_and_context_keep_distinct_exchange_clock_semantics() -> None:
    receipts: list[dict[str, object]] = []
    source = VolatilitySource(receipts.append)
    (event,) = source.ingest_ws(_book(), received_at_ms=T - 20)
    assert event.source == "hyperliquid-mainnet-ws"
    assert event.exchange_time_ms == T - 100
    ctx = {"channel": "activeAssetCtx", "data": {"coin": "BTC", "ctx": _meta()[1][0]}}
    (mark,) = source.ingest_ws(ctx, received_at_ms=T - 10)
    assert mark.kind is StreamKind.ACTIVE_ASSET_CTX
    assert mark.exchange_time_ms is None
    assert len(receipts) == 2 and receipts[0]["raw"] == _book()


@pytest.mark.parametrize("bad", [dict(time=T + 1), dict(coin="DOGE")])
def test_future_or_unapproved_ws_book_is_not_released(bad: dict[str, object]) -> None:
    source = VolatilitySource(lambda _: None)
    raw = _book()
    raw["data"].update(bad)
    with pytest.raises(ValueError):
        source.ingest_ws(raw, received_at_ms=T)
    assert source.books == {}


def test_meta_provides_native_specs_and_current_funding_without_fabricated_exchange_clock() -> None:
    source = VolatilitySource(lambda _: None)
    marks = source.ingest_meta(_meta(), received_at_ms=T - 10)
    assert len(marks) == 4 and all(m.exchange_time_ms is None for m in marks)
    window = source.daily_windows(T, eligibility={BTC: EligibilityDecision(BTC, True, True, ())})[0]
    assert window.snapshot is not None and window.snapshot.received_at_ms == T - 10
    assert window.funding is not None and window.funding.time_ms == T - 10
    spec = source.instruments()[BTC]
    assert spec.sz_decimals == 3 and spec.minimum_order_notional == 10


def test_settled_funding_is_retained_for_postclose_recovery_and_conflicts_fail() -> None:
    source = VolatilitySource(lambda _: None)
    boundary = 100 * DAY
    raw = [dict(coin="BTC", time=boundary, fundingRate="0.00001", premium="0")]
    (first,) = source.ingest_funding(BTC, raw, received_at_ms=T)
    (second,) = source.ingest_funding(BTC, raw, received_at_ms=T + 1000)
    assert first == second
    assert source.funding_rates[(BTC, boundary)] == first
    raw[0]["fundingRate"] = "0.00002"
    with pytest.raises(ValueError, match="conflicting settled funding"):
        source.ingest_funding(BTC, raw, received_at_ms=T + 2000)


def test_restore_replays_original_receipts_without_rearchiving_or_retiming() -> None:
    receipts: list[dict[str, object]] = []
    original = VolatilitySource(receipts.append)
    original.ingest_candles(BTC, _candles(), received_at_ms=T - 100)
    original.ingest_meta(_meta(), received_at_ms=T - 90)
    original.ingest_ws(_book(), received_at_ms=T - 80)
    original.gap("synthetic reconnect", now_ms=T - 70)
    restored = VolatilitySource(lambda _: pytest.fail("must not rearchive replay"))
    restored.restore(receipts)
    assert restored.daily_windows(T, eligibility={}) == original.daily_windows(T, eligibility={})
    assert restored.gaps == original.gaps


def test_receive_clock_regression_and_unsupported_market_fail_before_updates() -> None:
    source = VolatilitySource(lambda _: None)
    source.ingest_ws(_book(), received_at_ms=T)
    with pytest.raises(ValueError, match="receive clock regression"):
        source.ingest_ws(_book(), received_at_ms=T - 1)
    with pytest.raises(ValueError, match="unsupported market"):
        source.ingest_candles(MarketId("", "DOGE"), [], received_at_ms=T + 1)


def test_replay_retains_bad_original_response_without_preventing_fresh_protective_source() -> None:
    receipts: list[dict[str, object]] = []
    original = VolatilitySource(receipts.append)
    bad = _book()
    bad["data"]["levels"] = "malformed authentic wire shape"
    with pytest.raises(ValueError):
        original.ingest_ws(bad, received_at_ms=T - 10)
    original.gap("malformed source receipt", now_ms=T - 9)
    original.ingest_ws(_book(), received_at_ms=T)
    restored = VolatilitySource(lambda _: None)
    restored.restore(receipts)
    assert len(restored.rejections) == 1
    assert restored.rejections[0]["received_at_ms"] == T - 10
    assert restored.books[BTC] == original.books[BTC]
    assert len(restored.gaps) == 1


def test_restore_rejects_clock_reordering_and_forged_schema_even_on_invalid_source() -> None:
    receipts: list[dict[str, object]] = []
    original = VolatilitySource(receipts.append)
    original.ingest_ws(_book(), received_at_ms=T)
    record = dict(receipts[0], schema_version=True)
    with pytest.raises(ValueError, match="schema"):
        VolatilitySource(lambda _: None).restore([record])
    with pytest.raises(ValueError, match="receive clock regression"):
        VolatilitySource(lambda _: None).restore(
            [receipts[0], dict(receipts[0], received_at_ms=T - 1)]
        )


def test_one_funding_page_cannot_hide_conflicting_records_inside_timestamp_jitter() -> None:
    source = VolatilitySource(lambda _: None)
    raw = [
        dict(coin="BTC", time=100 * DAY, fundingRate="0.00001", premium="0"),
        dict(coin="BTC", time=100 * DAY + 1, fundingRate="0.00002", premium="0"),
    ]
    with pytest.raises(ValueError, match="duplicate settled funding boundary"):
        source.ingest_funding(BTC, raw, received_at_ms=T)
    assert source.funding_rates == {}


def test_zero_volume_unfinished_native_candle_is_raw_evidence_but_not_a_closed_input() -> None:
    source = VolatilitySource(lambda _: None)
    unfinished = dict(_candles()[-1], t=100 * DAY, T=100 * DAY + EIGHT_HOURS_MS - 1, v="0", n=0)
    source.ingest_candles(BTC, _candles() + [unfinished], received_at_ms=T - 1)
    assert len(source.daily_windows(T, eligibility={})[0].bars) == 90


def test_actual_backward_receive_clock_remains_in_original_archive_before_rejection() -> None:
    records: list[dict[str, object]] = []
    source = VolatilitySource(records.append)
    source.ingest_ws(_book(), received_at_ms=T)
    with pytest.raises(ValueError, match="receive clock regression"):
        source.ingest_ws(_book(), received_at_ms=T - 1)
    assert len(records) == 2
    assert records[-1]["received_at_ms"] == T - 1
    assert records[-1]["raw"] == _book()


@pytest.mark.parametrize("change", [{}, {"c": "100.5"}])
def test_same_page_duplicate_native_candles_fail_before_any_input_is_admitted(
    change: dict[str, object],
) -> None:
    source = VolatilitySource(lambda _: None)
    original = _candles()
    duplicate = dict(original[-1], **change)
    with pytest.raises(ValueError, match="strictly increasing"):
        source.ingest_candles(BTC, original + [duplicate], received_at_ms=T - 1)
    assert source.daily_windows(T, eligibility={})[0].bars == ()


def test_authenticated_adverse_clock_replay_retains_rejection_and_allows_later_protection() -> None:
    records: list[dict[str, object]] = []
    source = VolatilitySource(records.append)
    source.ingest_ws(_book(), received_at_ms=T)
    with pytest.raises(ValueError):
        source.ingest_ws(_book(), received_at_ms=T - 1)
    source.ingest_ws(_book(T + 10), received_at_ms=T + 10)
    restored = VolatilitySource(lambda _: pytest.fail("no raw replay rewrite"))
    restored.restore(records, allow_adverse_clocks=True)
    assert restored.books[BTC].exchange_time_ms == T + 10
    assert len(restored.rejections) == 1
    assert restored.rejections[0]["received_at_ms"] == T - 1
    assert records[1]["received_at_ms"] == T - 1
