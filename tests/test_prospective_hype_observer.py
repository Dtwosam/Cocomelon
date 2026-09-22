from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.market import (
    Candle,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveEvidenceStore,
)
from cocomelon.research.prospective_hype_observer import (
    ProspectiveMarketData,
    ProspectiveObserverError,
    observe_current_anchor,
    settle_due_observations,
)

HOUR = 3_600_000
FIFTEEN = 900_000
CUTOVER = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.validation_not_before_ms
BASKET_CLOSES = {
    "BTC": Decimal("95"),
    "ETH": Decimal("96"),
    "HYPE": Decimal("96"),
    "SOL": Decimal("97"),
}


def _snapshot(canonical: str, *, received_at_ms: int) -> PerpMarketSnapshot:
    market = MarketId("", canonical)
    price = BASKET_CLOSES[canonical]
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name=market.wire_name,
            sz_decimals=4,
            max_leverage=20,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=market,
            mark_px=price,
            mid_px=price,
            oracle_px=price,
            funding=Decimal("0.0001"),
            open_interest=Decimal("10000"),
            day_ntl_vlm=Decimal("1000000"),
            premium=Decimal("0"),
            prev_day_px=price + Decimal("1"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _fifteen_minute_candles(
    canonical: str,
    *,
    anchor_end_ms: int,
    received_at_ms: int,
    latest_end_ms: int | None = None,
) -> tuple[Candle, ...]:
    market = MarketId("", canonical)
    resolved_latest_end = anchor_end_ms if latest_end_ms is None else latest_end_ms
    target = BASKET_CLOSES[canonical]
    closes = (
        Decimal("100"),
        Decimal("99"),
        Decimal("98"),
        Decimal("97"),
        target,
    )
    values: list[Candle] = []
    first_end = resolved_latest_end - 4 * FIFTEEN
    for index, close in enumerate(closes):
        end_ms = first_end + index * FIFTEEN
        values.append(
            Candle(
                market=market,
                interval="15m",
                start_ms=end_ms - FIFTEEN + 1,
                end_ms=end_ms,
                open_px=close,
                high_px=close + Decimal("0.1"),
                low_px=close - Decimal("0.1"),
                close_px=close,
                volume=Decimal("1000"),
                trade_count=100,
                source="hyperliquid-mainnet-info",
                received_at_ms=received_at_ms,
                schema_version=1,
            )
        )
    return tuple(values)


def _hype_1h(
    *,
    end_ms: int,
    close: Decimal = Decimal("96"),
    received_at_ms: int,
) -> Candle:
    return Candle(
        market=MarketId("", "HYPE"),
        interval="1h",
        start_ms=end_ms - HOUR + 1,
        end_ms=end_ms,
        open_px=close,
        high_px=close + Decimal("0.2"),
        low_px=close - Decimal("0.2"),
        close_px=close,
        volume=Decimal("5000"),
        trade_count=500,
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _data(
    *,
    anchor_end_ms: int,
    as_of_ms: int | None = None,
    mismatched_market: str | None = None,
) -> ProspectiveMarketData:
    resolved_as_of = anchor_end_ms + 5 * 60_000 if as_of_ms is None else as_of_ms
    received = min(resolved_as_of, anchor_end_ms + 60_000)
    markets = {
        canonical: _snapshot(canonical, received_at_ms=received)
        for canonical in ("BTC", "ETH", "HYPE", "SOL")
    }
    candles: dict[str, tuple[Candle, ...]] = {}
    for canonical in ("BTC", "ETH", "HYPE", "SOL"):
        latest_end = (
            anchor_end_ms - FIFTEEN
            if canonical == mismatched_market
            else anchor_end_ms
        )
        candles[canonical] = _fifteen_minute_candles(
            canonical,
            anchor_end_ms=anchor_end_ms,
            received_at_ms=received,
            latest_end_ms=latest_end,
        )
    return ProspectiveMarketData(
        as_of_ms=resolved_as_of,
        markets=markets,
        candles_15m=candles,
        hype_candles_1h=(
            _hype_1h(
                end_ms=anchor_end_ms,
                received_at_ms=received,
            ),
        ),
    )


def test_matching_context_records_effective_long_and_same_anchor_is_idempotent(
    tmp_path,
) -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    store = ProspectiveEvidenceStore(tmp_path, spec=spec)
    anchor = CUTOVER + HOUR
    data = _data(anchor_end_ms=anchor)

    first = observe_current_anchor(data, store=store, spec=spec)
    second = observe_current_anchor(data, store=store, spec=spec)

    assert first.status == "recorded"
    assert first.raw_direction is Direction.LONG
    assert first.effective_direction is Direction.LONG
    assert first.context_state_1h == "down/bearish/near_basket"
    assert first.created is True
    assert second.status == "already_recorded"
    assert second.observation_id == first.observation_id
    assert second.created is False
    assert len(store.iter_observations()) == 1


def test_next_hour_matching_context_is_suppressed_by_frozen_occupancy(tmp_path) -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    store = ProspectiveEvidenceStore(tmp_path, spec=spec)
    first_anchor = CUTOVER + HOUR

    first = observe_current_anchor(
        _data(anchor_end_ms=first_anchor),
        store=store,
        spec=spec,
    )
    second = observe_current_anchor(
        _data(anchor_end_ms=first_anchor + HOUR),
        store=store,
        spec=spec,
    )

    assert first.effective_direction is Direction.LONG
    assert second.raw_direction is Direction.LONG
    assert second.effective_direction is Direction.NO_TRADE
    stored = store.observation_for_anchor(first_anchor + HOUR)
    assert stored is not None
    assert stored.occupancy_blocked_by_observation_id == first.observation_id
    assert "one_position_per_market_occupied" in stored.reason_codes


def test_observer_waits_for_first_post_cutover_anchor(tmp_path) -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    store = ProspectiveEvidenceStore(tmp_path, spec=spec)
    data = _data(
        anchor_end_ms=CUTOVER - 1,
        as_of_ms=CUTOVER + 5 * 60_000,
    )

    result = observe_current_anchor(data, store=store, spec=spec)

    assert result.status == "waiting_for_post_cutover_anchor"
    assert result.created is False
    assert store.iter_observations() == ()


def test_observer_rejects_cross_market_anchor_mismatch(tmp_path) -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    store = ProspectiveEvidenceStore(tmp_path, spec=spec)
    anchor = CUTOVER + HOUR

    with pytest.raises(ProspectiveObserverError, match="anchor mismatch for SOL"):
        observe_current_anchor(
            _data(anchor_end_ms=anchor, mismatched_market="SOL"),
            store=store,
            spec=spec,
        )


def test_observer_rejects_hype_15m_1h_close_disagreement(tmp_path) -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    store = ProspectiveEvidenceStore(tmp_path, spec=spec)
    anchor = CUTOVER + HOUR
    data = _data(anchor_end_ms=anchor)
    wrong_hour = _hype_1h(
        end_ms=anchor,
        close=Decimal("95"),
        received_at_ms=anchor + 60_000,
    )
    changed = ProspectiveMarketData(
        as_of_ms=data.as_of_ms,
        markets=data.markets,
        candles_15m=data.candles_15m,
        hype_candles_1h=(wrong_hour,),
    )

    with pytest.raises(ProspectiveObserverError, match="closes disagree"):
        observe_current_anchor(changed, store=store, spec=spec)


def test_due_outcome_uses_exact_target_close_and_missing_target_stays_pending(
    tmp_path,
) -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    store = ProspectiveEvidenceStore(tmp_path, spec=spec)
    anchor = CUTOVER + HOUR
    observed = observe_current_anchor(
        _data(anchor_end_ms=anchor),
        store=store,
        spec=spec,
    )
    observation = store.load_observation(str(observed.observation_id))
    assert observation is not None

    missing = settle_due_observations(
        store=store,
        candles_1h=(
            _hype_1h(
                end_ms=observation.target_end_ms - HOUR,
                close=Decimal("100"),
                received_at_ms=observation.target_end_ms + 60_000,
            ),
        ),
        as_of_ms=observation.target_end_ms + 60_000,
        spec=spec,
    )
    assert missing.settled == ()
    assert missing.missing_target_observation_ids == (observation.observation_id,)

    exact = settle_due_observations(
        store=store,
        candles_1h=(
            _hype_1h(
                end_ms=observation.target_end_ms,
                close=Decimal("100"),
                received_at_ms=observation.target_end_ms + 60_000,
            ),
        ),
        as_of_ms=observation.target_end_ms + 60_000,
        spec=spec,
    )

    assert len(exact.settled) == 1
    assert exact.missing_target_observation_ids == ()
    assert exact.settled[0].net_return > 0
    assert store.due_unsettled_observations(
        as_of_ms=observation.target_end_ms + 60_000
    ) == ()
