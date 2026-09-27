from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.entry_mid_markout_shadow import (
    ENTRY_MID_MARKOUT_MAX_LAG_MS,
    EntryMidMarkoutShadow,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _position(
    *,
    suffix: str,
    side: PositionSide,
    opened_at_ms: int,
) -> PaperPosition:
    return PaperPosition(
        market=MARKET,
        side=side,
        quantity=Decimal("2"),
        average_entry_price=Decimal("100"),
        stop_price=(
            Decimal("95")
            if side is PositionSide.LONG
            else Decimal("105")
        ),
        opening_plan_id=f"plan-{suffix}",
        opened_at_ms=opened_at_ms,
        updated_at_ms=opened_at_ms,
        initial_risk_decision_id=f"risk-{suffix}",
        planned_risk=Decimal("10"),
    )


def _record(
    timestamp_ms: int,
    mid_px: str,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=timestamp_ms,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=None,
        event_key=f"allMids:{timestamp_ms}:{mid_px}",
        payload_json=f'{{"mid_px":"{mid_px}"}}',
        event_kind="all_mids",
    )


def _trade(
    position: PaperPosition,
    *,
    suffix: str,
    closed_at_ms: int,
) -> TradeJournalEntry:
    direction = (
        Direction.LONG
        if position.side is PositionSide.LONG
        else Direction.SHORT
    )
    return TradeJournalEntry(
        market=position.market,
        direction=direction,
        opened_at_ms=position.opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=position.initial_risk_decision_id,
        opening_plan_id=position.opening_plan_id,
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"open-fill-{suffix}", f"exit-fill-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=position.stop_price,
        initial_risk_amount=position.planned_risk,
        entry_price=position.average_entry_price,
        exit_price=position.average_entry_price,
        filled_quantity=position.quantity,
        gross_realized_pnl=Decimal("0"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("0"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - position.opened_at_ms,
        mfe=None,
        mae=None,
        net_r=Decimal("0"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000"),
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _fact(
    trade: TradeJournalEntry,
    *,
    lead_strategy: str,
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=RUN_ID,
        market=trade.market,
        direction=trade.direction,
        timestamp_ms=trade.opened_at_ms - 1,
        score=Decimal("80"),
        lead_strategy=lead_strategy,
        signal_ids=(f"signal-{trade.trade_id}",),
        reason_codes=("decision_threshold_met",),
        trend_regime=(
            TrendRegime.UP
            if trade.direction is Direction.LONG
            else TrendRegime.DOWN
        ),
        volatility_regime=VolatilityRegime.NORMAL,
    )


def test_allmids_shadow_records_fresh_long_and_short_markouts(
    tmp_path: Path,
) -> None:
    shadow = EntryMidMarkoutShadow(started_at_ms=1_000_000)
    long = _position(
        suffix="long",
        side=PositionSide.LONG,
        opened_at_ms=1_100_000,
    )
    short = _position(
        suffix="short",
        side=PositionSide.SHORT,
        opened_at_ms=2_100_000,
    )

    shadow.observe(
        _record(1_160_000, "101"),
        (long,),
        now_ms=1_160_000,
    )
    shadow.observe(
        _record(1_400_000, "102"),
        (long,),
        now_ms=1_400_000,
    )
    long_trade = _trade(
        long,
        suffix="long",
        closed_at_ms=1_500_000,
    )
    shadow.record_closed_trade(long_trade)

    shadow.observe(
        _record(2_160_000, "99"),
        (short,),
        now_ms=2_160_000,
    )
    shadow.observe(
        _record(2_400_000, "98"),
        (short,),
        now_ms=2_400_000,
    )
    short_trade = _trade(
        short,
        suffix="short",
        closed_at_ms=2_500_000,
    )
    shadow.record_closed_trade(short_trade)

    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        facts.record_decision_fact(
            _fact(long_trade, lead_strategy="trend")
        )
        facts.record_decision_fact(
            _fact(short_trade, lead_strategy="breakout")
        )
        payload = shadow.summary_payload(facts)
    finally:
        facts.close()

    one = payload["by_horizon_ms"]["60000"]
    assert one["fresh"] == 2
    assert one["stale"] == 0
    assert one["censored"] == 0
    assert one["missing_at_close"] == 0
    assert one["positive"] == 2
    assert one["mean_signed_return_bps"] == "100.00"
    assert one["mean_gross_r"] == "0.2"
    assert one["by_side"]["long"]["mean_gross_r"] == "0.2"
    assert one["by_side"]["short"]["mean_gross_r"] == "0.2"
    assert one["by_lead_strategy"]["trend"]["observations"] == 1
    assert one["by_lead_strategy"]["breakout"]["observations"] == 1

    five = payload["by_horizon_ms"]["300000"]
    assert five["fresh"] == 2
    assert five["positive"] == 2
    assert five["mean_signed_return_bps"] == "200.00"
    assert five["mean_gross_r"] == "0.4"

    fifteen = payload["by_horizon_ms"]["900000"]
    assert fifteen["fresh"] == 0
    assert fifteen["censored"] == 2


def test_allmids_shadow_distinguishes_stale_and_missing_close(
    tmp_path: Path,
) -> None:
    shadow = EntryMidMarkoutShadow(started_at_ms=1_000_000)
    position = _position(
        suffix="stale",
        side=PositionSide.LONG,
        opened_at_ms=1_100_000,
    )
    late = (
        position.opened_at_ms
        + 60_000
        + ENTRY_MID_MARKOUT_MAX_LAG_MS
        + 1
    )
    shadow.observe(
        _record(late, "101"),
        (position,),
        now_ms=late,
    )
    trade = _trade(
        position,
        suffix="stale",
        closed_at_ms=position.opened_at_ms + 400_000,
    )
    shadow.record_closed_trade(trade)

    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        facts.record_decision_fact(
            _fact(trade, lead_strategy="trend")
        )
        payload = shadow.summary_payload(facts)
    finally:
        facts.close()

    one = payload["by_horizon_ms"]["60000"]
    assert one["fresh"] == 0
    assert one["stale"] == 1
    assert one["missing_at_close"] == 0

    five = payload["by_horizon_ms"]["300000"]
    assert five["fresh"] == 0
    assert five["stale"] == 0
    assert five["missing_at_close"] == 1

    fifteen = payload["by_horizon_ms"]["900000"]
    assert fifteen["censored"] == 1


def test_allmids_shadow_excludes_pre_observer_positions(
    tmp_path: Path,
) -> None:
    shadow = EntryMidMarkoutShadow(started_at_ms=2_000_000)
    position = _position(
        suffix="old",
        side=PositionSide.LONG,
        opened_at_ms=1_900_000,
    )
    shadow.observe(
        _record(2_000_000, "101"),
        (position,),
        now_ms=2_000_000,
    )
    shadow.record_closed_trade(
        _trade(
            position,
            suffix="old",
            closed_at_ms=2_300_000,
        )
    )

    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        payload = shadow.summary_payload(facts)
    finally:
        facts.close()

    assert payload["excluded_closed_trades"] == 1
    assert payload["closed_trade_count"] == 0


def test_allmids_shadow_state_round_trip_preserves_open_observation(
    tmp_path: Path,
) -> None:
    shadow = EntryMidMarkoutShadow(started_at_ms=1_000_000)
    position = _position(
        suffix="restore",
        side=PositionSide.LONG,
        opened_at_ms=1_100_000,
    )
    shadow.observe(
        _record(1_160_000, "101"),
        (position,),
        now_ms=1_160_000,
    )

    restored = EntryMidMarkoutShadow(started_at_ms=9_999_999)
    restored.restore_state(shadow.state_payload())
    restored.observe(
        _record(1_400_000, "102"),
        (position,),
        now_ms=1_400_000,
    )
    trade = _trade(
        position,
        suffix="restore",
        closed_at_ms=1_500_000,
    )
    restored.record_closed_trade(trade)

    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        facts.record_decision_fact(
            _fact(trade, lead_strategy="trend")
        )
        payload = restored.summary_payload(facts)
    finally:
        facts.close()

    assert payload["state_restored"] is True
    assert payload["started_at_ms"] == 1_000_000
    assert payload["by_horizon_ms"]["60000"]["fresh"] == 1
    assert payload["by_horizon_ms"]["300000"]["fresh"] == 1


def test_allmids_shadow_rebases_r_on_closed_trade_initial_risk(
    tmp_path: Path,
) -> None:
    shadow = EntryMidMarkoutShadow(started_at_ms=1_000_000)
    tracked = _position(
        suffix="risk-rebase",
        side=PositionSide.LONG,
        opened_at_ms=1_100_000,
    )
    shadow.observe(
        _record(1_160_000, "101"),
        (tracked,),
        now_ms=1_160_000,
    )
    trade = _trade(
        tracked,
        suffix="risk-rebase",
        closed_at_ms=1_500_000,
    )
    trade = replace(
        trade,
        initial_risk_amount=Decimal("20"),
    )
    shadow.record_closed_trade(trade)

    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        facts.record_decision_fact(
            _fact(trade, lead_strategy="trend")
        )
        payload = shadow.summary_payload(facts)
    finally:
        facts.close()

    assert payload["closed_trade_count"] == 1
    assert payload["lineage_mismatch_closed_trades"] == 0
    assert payload["risk_basis"] == "closed_trade_initial_risk_amount"
    assert payload["quantity_basis"] == "closed_trade_filled_quantity"
    assert payload["by_horizon_ms"]["60000"]["mean_gross_r"] == "0.1"


def test_allmids_shadow_still_rejects_true_identity_drift(
    tmp_path: Path,
) -> None:
    shadow = EntryMidMarkoutShadow(started_at_ms=1_000_000)
    tracked = _position(
        suffix="identity-mismatch",
        side=PositionSide.LONG,
        opened_at_ms=1_100_000,
    )
    shadow.observe(
        _record(1_160_000, "101"),
        (tracked,),
        now_ms=1_160_000,
    )
    mismatched = PaperPosition(
        market=tracked.market,
        side=tracked.side,
        quantity=tracked.quantity,
        average_entry_price=Decimal("101"),
        stop_price=tracked.stop_price,
        opening_plan_id=tracked.opening_plan_id,
        opened_at_ms=tracked.opened_at_ms,
        updated_at_ms=tracked.updated_at_ms,
        initial_risk_decision_id=tracked.initial_risk_decision_id,
        planned_risk=tracked.planned_risk,
    )
    shadow.record_closed_trade(
        _trade(
            mismatched,
            suffix="identity-mismatch",
            closed_at_ms=1_500_000,
        )
    )

    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        payload = shadow.summary_payload(facts)
    finally:
        facts.close()

    assert payload["closed_trade_count"] == 0
    assert payload["lineage_mismatch_closed_trades"] == 1


def test_allmids_shadow_reconciles_orphaned_restored_position(
    tmp_path: Path,
) -> None:
    shadow = EntryMidMarkoutShadow(started_at_ms=1_000_000)
    position = _position(
        suffix="orphan",
        side=PositionSide.LONG,
        opened_at_ms=1_100_000,
    )
    shadow.observe(
        _record(1_160_000, "101"),
        (position,),
        now_ms=1_160_000,
    )

    restored = EntryMidMarkoutShadow(started_at_ms=9_999_999)
    restored.restore_state(shadow.state_payload())
    restored.reconcile_open_positions(())

    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        payload = restored.summary_payload(facts)
    finally:
        facts.close()
    assert payload["eligible_open_positions"] == 0
    assert payload["orphaned_restored_positions"] == 1
