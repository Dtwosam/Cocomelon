from __future__ import annotations

from collections.abc import Callable

from cocomelon.domain.market import Candle, FundingRate, PerpMarketSnapshot
from cocomelon.evidence.contracts import EvidenceRecordingConfig, EvidenceRecordingSession
from cocomelon.evidence.recording import (
    EvidenceInfoReader,
    RecordingBootstrap,
    _recent_funding,
    _warmup_candles,
)
from cocomelon.hyperliquid.registry import MarketRegistry
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager


def build_recording_resume_bootstrap(
    reader: EvidenceInfoReader,
    config: EvidenceRecordingConfig,
    session: EvidenceRecordingSession,
    *,
    now_ms: Callable[[], int],
) -> RecordingBootstrap:
    if session.recording_config_digest != config.config_digest:
        raise ValueError("recording session config does not match requested config")
    if session.api_url != config.api_url or session.ws_url != config.ws_url:
        raise ValueError("recording session endpoints do not match requested config")
    if session.selection_policy_id != config.selection_policy_id:
        raise ValueError("recording session selection policy does not match requested config")
    if len(session.selected) > config.deep_limit:
        raise ValueError("recording session cohort exceeds requested deep limit")

    registry = MarketRegistry(reader, now_ms=now_ms).refresh()
    selected_markets = tuple(item.market for item in session.selected)
    snapshots: list[PerpMarketSnapshot] = []
    for market in selected_markets:
        snapshot = registry.markets.get(market.canonical)
        if snapshot is None:
            raise ValueError(
                f"selected recording market is no longer discoverable: {market.canonical}"
            )
        if snapshot.meta.is_delisted:
            raise ValueError(f"selected recording market is now delisted: {market.canonical}")
        snapshots.append(snapshot)

    end_ms = now_ms()
    candles: list[Candle] = []
    funding_rates: list[FundingRate] = []
    for market in selected_markets:
        candles.extend(
            _warmup_candles(
                reader,
                market,
                config,
                end_ms=end_ms,
                now_ms=now_ms,
            )
        )
        funding_rates.extend(
            _recent_funding(
                reader,
                market,
                end_ms=end_ms,
                now_ms=now_ms,
            )
        )

    plan = DeepWatchlistManager(candle_intervals=config.candle_intervals).reconcile(
        selected_markets
    )
    return RecordingBootstrap(
        session=session,
        snapshots=tuple(snapshots),
        candles=tuple(candles),
        funding_rates=tuple(funding_rates),
        subscriptions=plan.subscribe,
    )
