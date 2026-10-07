from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.evidence.baseline import RecordedStateBook
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import DecisionEpoch, EpochMarketEvaluation
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_paired_portfolio_shadow import (
    LossContextPairedPortfolioShadow,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)

MARKET = MarketId("", "TEST")
FROZEN_AT_MS = 1_000
PROSPECTIVE_MS = FROZEN_AT_MS + MIN_PROSPECTIVE_EMBARGO_MS
EVALUATED_AT_MS = PROSPECTIVE_MS + 60_000
OPEN_BOOK_MS = EVALUATED_AT_MS + 250
STOP_MARK_MS = EVALUATED_AT_MS + 500
CLOSE_BOOK_MS = EVALUATED_AT_MS + 800


def _freeze() -> LossContextPortfolioShadowFreeze:
    return LossContextPortfolioShadowFreeze(
        loss_context_candidate_id="a" * 64,
        source_composition_digest="b" * 64,
        source_max_timestamp_ms=900,
        source_paper_run_id=123,
        source_paper_run_attempt=1,
        source_paper_head_sha="c" * 40,
        dimensions=("lead_strategy", "trend_regime"),
        values=("mean_reversion", "down"),
        horizons_ms=(300_000, 900_000),
        frozen_at_ms=FROZEN_AT_MS,
        prospective_not_before_ms=PROSPECTIVE_MS,
    )


def _config() -> BaselineReplayConfig:
    return BaselineReplayConfig(
        execution=PaperExecutionConfig(),
    )


def _record(
    *,
    kind: str,
    available_at_ms: int,
    payload: dict[str, object],
    exchange_time_ms: int | None = None,
    event_key: str | None = None,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=available_at_ms,
        source="paired-shadow-fixture",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=exchange_time_ms,
        event_key=event_key or f"{kind}:{available_at_ms}",
        payload_json=json.dumps(payload, sort_keys=True),
        event_kind=kind,
    )


def _snapshot_record() -> ReplayRecord:
    return _record(
        kind="market_snapshot",
        available_at_ms=EVALUATED_AT_MS - 1_000,
        payload={
            "meta": {
                "wire_name": MARKET.wire_name,
                "sz_decimals": 4,
                "max_leverage": 20,
                "margin_table_id": 1,
                "only_isolated": False,
                "is_delisted": False,
                "margin_mode": None,
            },
            "context": {
                "mark_px": "100",
                "mid_px": "100",
                "oracle_px": "100",
                "funding": "0",
                "open_interest": "1000000",
                "day_ntl_vlm": "500000000",
                "premium": "0",
                "prev_day_px": "101",
            },
        },
    )


def _trigger_record() -> ReplayRecord:
    return _record(
        kind="candle",
        available_at_ms=EVALUATED_AT_MS,
        exchange_time_ms=EVALUATED_AT_MS - 1,
        event_key="epoch-trigger",
        payload={
            "interval": "15m",
            "start_ms": EVALUATED_AT_MS - 900_000,
            "end_ms": EVALUATED_AT_MS - 1,
            "open_px": "101",
            "high_px": "101",
            "low_px": "99",
            "close_px": "100",
            "volume": "1000",
            "trade_count": 100,
        },
    )


def _book(receive_ms: int, *, bid: str, ask: str) -> ReplayRecord:
    return _record(
        kind="l2_book",
        available_at_ms=receive_ms,
        exchange_time_ms=receive_ms,
        payload={
            "bids": [{"px": bid, "sz": "1000", "n": 1}],
            "asks": [{"px": ask, "sz": "1000", "n": 1}],
        },
    )


def _mark(receive_ms: int, *, mark: str) -> ReplayRecord:
    return _record(
        kind="active_asset_ctx",
        available_at_ms=receive_ms,
        payload={
            "mark_px": mark,
            "mid_px": mark,
            "oracle_px": mark,
            "funding": "0",
            "open_interest": "1000000",
        },
    )


def _feature() -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MARKET,
        as_of_ms=EVALUATED_AT_MS,
        source_received_at_ms=EVALUATED_AT_MS - 1_000,
        schema_version=1,
        day_return=Decimal("-0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("500000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=Decimal("-0.002"),
        return_15m=Decimal("-0.01"),
        return_1h=Decimal("-0.02"),
        return_4h=None,
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("-0.1"),
        book_age_ms=10,
        trend_regime=TrendRegime.DOWN,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("paired-shadow-fixture",),
    )


def _epoch(*, lead_strategy: str) -> DecisionEpoch:
    feature = _feature()
    decision = StrategyDecision(
        market=MARKET,
        direction=Direction.LONG,
        score=Decimal("80"),
        timestamp_ms=EVALUATED_AT_MS,
        feature_snapshot_id=feature.snapshot_id,
        lead_strategy=lead_strategy,
        invalidation_price=Decimal("95"),
        signal_ids=("paired-shadow-signal",),
        reason_codes=("paired-shadow-directional",),
    )
    return DecisionEpoch(
        boundary_ms=EVALUATED_AT_MS - 30_000,
        evaluated_at_ms=EVALUATED_AT_MS,
        markets=(
            EpochMarketEvaluation(
                feature=feature,
                eligibility=EligibilityDecision(
                    market=MARKET,
                    rankable=True,
                    deep_ready=True,
                    reasons=(),
                ),
                decision=decision,
            ),
        ),
    )


class _ScriptedDecisionEngine:
    def __init__(
        self,
        config: BaselineReplayConfig,
        *,
        lead_strategy: str,
    ) -> None:
        self._state = RecordedStateBook(
            microstructure_window_ms=config.microstructure_window_ms
        )
        self._lead_strategy = lead_strategy
        self._emitted = False

    @property
    def state_book(self) -> RecordedStateBook:
        return self._state

    def seed(self, record: ReplayRecord, now_ms: int) -> None:
        self._state.apply(record, now_ms)

    def observe(
        self,
        record: ReplayRecord,
        now_ms: int,
    ) -> tuple[DecisionEpoch, ...]:
        self._state.apply(record, now_ms)
        if record.event_key == "epoch-trigger" and not self._emitted:
            self._emitted = True
            return (_epoch(lead_strategy=self._lead_strategy),)
        return ()

    def flush(self, _end_ms: int) -> tuple[DecisionEpoch, ...]:
        return ()


def _records() -> tuple[ReplayRecord, ...]:
    return (
        _snapshot_record(),
        _trigger_record(),
        _book(OPEN_BOOK_MS, bid="99.9", ask="100.1"),
        _mark(STOP_MARK_MS, mark="94"),
        _book(CLOSE_BOOK_MS, bid="93.9", ask="94.0"),
    )


def _run(
    tmp_path: Path,
    *,
    lead_strategy: str,
) -> dict[str, object]:
    config = _config()
    shadow = LossContextPairedPortfolioShadow(
        freeze=_freeze(),
        replay_config=config,
        selected_markets=(MARKET,),
        state_root=tmp_path,
        startup_timestamp_ms=EVALUATED_AT_MS - 2_000,
        decision_engine_factory=lambda: _ScriptedDecisionEngine(
            config,
            lead_strategy=lead_strategy,
        ),
    )
    try:
        for record in _records():
            shadow.on_record(record, record.available_at_ms)
        return shadow.summary_payload(end_ms=CLOSE_BOOK_MS)
    finally:
        shadow.close()


def test_paired_shadow_blocks_exact_bad_context_and_keeps_account_effects(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, lead_strategy="mean_reversion")

    baseline = result["baseline"]
    candidate = result["candidate"]
    assert isinstance(baseline, dict)
    assert isinstance(candidate, dict)

    assert baseline["closed_trade_count"] == 1
    assert candidate["closed_trade_count"] == 0
    assert Decimal(str(baseline["total_account_pnl"])) < 0
    assert Decimal(str(candidate["total_account_pnl"])) == 0
    assert Decimal(
        str(result["candidate_minus_baseline_total_account_pnl"])
    ) > 0
    assert Decimal(
        str(result["candidate_minus_baseline_max_drawdown_fraction"])
    ) < 0

    baseline_admission = result["baseline_admission"]
    candidate_admission = result["candidate_admission"]
    assert isinstance(baseline_admission, dict)
    assert isinstance(candidate_admission, dict)
    assert baseline_admission["matching_context_blocked"] == 0
    assert candidate_admission["matching_context_blocked"] == 1
    assert result["candidate_difference_is_opening_admission_only"] is True
    assert result["execution_authority"] is False


def test_paired_shadow_does_not_block_same_direction_outside_context(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, lead_strategy="trend")

    baseline = result["baseline"]
    candidate = result["candidate"]
    assert isinstance(baseline, dict)
    assert isinstance(candidate, dict)
    assert baseline["closed_trade_count"] == 1
    assert candidate["closed_trade_count"] == 1
    assert baseline["total_account_pnl"] == candidate["total_account_pnl"]
    assert baseline["realized_net_pnl"] == candidate["realized_net_pnl"]
    assert Decimal(
        str(result["candidate_minus_baseline_total_account_pnl"])
    ) == 0

    candidate_admission = result["candidate_admission"]
    assert isinstance(candidate_admission, dict)
    assert candidate_admission["matching_context_blocked"] == 0
    assert candidate_admission["admitted_after_boundary"] == 1
