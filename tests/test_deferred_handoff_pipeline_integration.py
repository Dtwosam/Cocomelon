from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.journal import ExcursionMetric, TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathMark,
    ContinuousPaperTradePathStore,
    continuous_paper_trade_path,
)
from cocomelon.research.deferred_all_trade_chart_audit import (
    AllPaperTradeChartAuditError,
    write_deferred_trade_charts,
)
from cocomelon.research.deferred_long_entry_loss_attribution import (
    LongEntryLossAttributionError,
    write_long_entry_loss_attribution,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore

RUN_ID = "continuous-paper-mainnet-v1"
D = Decimal


def _feature(opened: int, market: MarketId) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=opened - 1000,
        source_received_at_ms=opened - 1000,
        schema_version=1,
        day_return=D("-0.03"),
        funding=D("0.0001"),
        open_interest=D("1000000"),
        day_notional_volume=D("5000000"),
        oi_change_fraction=D("0.01"),
        funding_change=D("0"),
        mark_oracle_dislocation_bps=D("1"),
        return_5m=D("-0.005"),
        return_15m=D("-0.01"),
        return_1h=D("-0.02"),
        return_4h=D("-0.04"),
        realized_vol_15m=D("0.03"),
        range_expansion_15m=D("1.2"),
        relative_volume_15m=D("1.1"),
        spread_bps=D("2"),
        bid_depth_25bps=D("100000"),
        ask_depth_25bps=D("110000"),
        book_imbalance=D("-0.2"),
        book_age_ms=100,
        trend_regime=TrendRegime.DOWN,
        volatility_regime=VolatilityRegime.HIGH,
        provenance=("mainnet-paper-fixture",),
    )


def _excursion(kind: str, opened: int, r: str) -> ExcursionMetric:
    return ExcursionMetric(
        kind=kind,
        price=D("101") if kind == "mfe" else D("96"),
        per_unit=D("1"),
        fraction=D("0.01"),
        currency=D("1"),
        r_multiple=D(r),
        timestamp_ms=opened + 30_000,
        source_event_key=f"observed-{opened}-{kind}",
        complete=True,
    )


def _trade(
    n: int,
    *,
    market: MarketId,
    side: Direction,
    gross: str,
    with_excursions: bool,
) -> TradeJournalEntry:
    opened = 1_000_000 * n
    profit = D(gross)
    fee = D("0.25")
    net = profit - fee - fee
    return TradeJournalEntry(
        market=market,
        direction=side,
        opened_at_ms=opened,
        closed_at_ms=opened + 60_000,
        feature_snapshot_id=f"missing-feature-{n}",
        strategy_decision_id=f"decision-{n}",
        risk_decision_id=f"risk-{n}",
        opening_plan_id=f"opening-{n}",
        opening_attempt_id=f"attempt-{n}",
        exit_plan_ids=(f"exit-plan-{n}",),
        exit_attempt_ids=(f"exit-attempt-{n}",),
        fill_ids=(f"opening-fill-{n}", f"closing-fill-{n}"),
        position_action_ids=(f"action-{n}",),
        funding_event_ids=(),
        initial_stop=D("90") if side is Direction.LONG else D("110"),
        initial_risk_amount=D("10"),
        entry_price=D("100"),
        exit_price=(D("100") + profit if side is Direction.LONG
                    else D("100") - profit),
        filled_quantity=D("1"),
        gross_realized_pnl=profit,
        entry_fees=fee,
        exit_fees=fee,
        funding_cash_pnl=D("0"),
        net_pnl=net,
        entry_slippage_amount=D("0.1"),
        exit_slippage_amount=D("0.1"),
        entry_slippage_fraction=D("0.001"),
        exit_slippage_fraction=D("0.001"),
        holding_duration_ms=60_000,
        mfe=_excursion("mfe", opened, "0.7") if with_excursions else None,
        mae=_excursion("mae", opened, "1") if with_excursions else None,
        net_r=net / D("10"),
        equity_before=D("10000"),
        equity_after=D("10000") + net,
        exit_reason="MARK_STOP_TRIGGERED" if net < D("0") else "EXIT_RULE",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _populate_state(root: Path) -> tuple[TradeJournalEntry, ...]:
    root.mkdir(parents=True, exist_ok=True)
    journal = JournalStore(root / "journal.sqlite3")
    facts = EvaluationFactStore(root / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(root / "learning-features")
    ranks = ContinuousPaperOpeningRankStore(root / "opening-ranks")
    paths = ContinuousPaperTradePathStore(root / "trade-paths")
    trades = (
        _trade(1, market=MarketId("", "HYPE"), side=Direction.LONG,
               gross="-4", with_excursions=True),
        _trade(2, market=MarketId("", "SOL"), side=Direction.LONG,
               gross="-2", with_excursions=False),
        _trade(3, market=MarketId("", "BTC"), side=Direction.SHORT,
               gross="3", with_excursions=False),
    )
    try:
        for trade in trades:
            # The missing third trade stays in every denominator and total.
            if trade is not trades[2]:
                feat = _feature(trade.opened_at_ms, trade.market)
                # A journaled trade may carry the feature ID only if the
                # corresponding immutable snapshot was available at entry.
                trade = replace(trade, feature_snapshot_id=feat.snapshot_id)
                features.record(feat)
                facts.record_decision_fact(DecisionEvaluationFact(
                    strategy_decision_id=trade.strategy_decision_id,
                    feature_snapshot_id=trade.feature_snapshot_id,
                    replay_run_id=RUN_ID,
                    market=trade.market,
                    direction=trade.direction,
                    timestamp_ms=trade.opened_at_ms - 100,
                    score=D("0.8"),
                    lead_strategy="trend",
                    signal_ids=(f"signal-{trade.strategy_decision_id}",),
                    reason_codes=("decision_threshold_met",),
                    trend_regime=TrendRegime.DOWN,
                    volatility_regime=VolatilityRegime.HIGH,
                ))
                age = 100 if trade.opened_at_ms == 1_000_000 else 300_001
                ranks.record(ContinuousPaperOpeningRankEvidence(
                    opening_plan_id=trade.opening_plan_id,
                    market=trade.market.canonical,
                    opened_at_ms=trade.opened_at_ms,
                    rank_observed_at_ms=trade.opened_at_ms - age,
                    rank_age_ms=age,
                    ordinal=15 if age == 100 else 2,
                    score=D("0.9"),
                    rank_pool_size=20,
                    reason_codes=("ranked",),
                ))
            journal.record_trade(trade)
            if trade.opened_at_ms != 3_000_000:
                marks = tuple(
                    ContinuousPaperTradePathMark(
                        available_at_ms=trade.opened_at_ms + offset,
                        exchange_time_ms=None,
                        event_key=f"mark-{trade.opened_at_ms}-{offset}",
                        mark_px=D("100") if offset == 0
                        else D("101") if offset == 30_000
                        else trade.exit_price,
                    )
                    for offset in (0, 30_000, 60_000)
                )
                # The second trade lacks complete excursion evidence despite
                # its marks; do not infer executable exit opportunities.
                paths.record(continuous_paper_trade_path(
                    trade, marks, (),
                ))
        (root / "session-summary.json").write_text(
            json.dumps({"exit_reason": "duration_elapsed"}), encoding="utf-8"
        )
    finally:
        journal.close()
        facts.close()
    return trades


def test_completed_real_store_handoff_builds_exact_full_journal_chart_and_loss_reports(
    tmp_path: Path,
) -> None:
    _populate_state(tmp_path)
    chart_path, html_path, chart = write_deferred_trade_charts(tmp_path)
    assert chart_path.is_file()
    assert html_path.is_file()
    assert "All 3 closed paper trades" in html_path.read_text(encoding="utf-8")
    assert chart["total_journal_trades"] == 3
    assert chart["complete_chart_paths"] == 1
    assert chart["incomplete_or_gapped_chart_paths"] == 1
    assert len(chart["missing_chart_path_trade_ids"]) == 1
    assert chart["verified_entry_exit_context"]["entry_context_verified_trades"] == 2
    by_id = {t["opened_at_ms"]: t for t in chart["trades"]}
    assert by_id[1_000_000]["entry_context"]["rank_band"] == "outside10"
    assert by_id[2_000_000]["entry_context"]["rank_band"] == "stale"
    assert by_id[3_000_000]["entry_context"] is None

    loss_path = write_long_entry_loss_attribution(tmp_path)
    loss = json.loads(loss_path.read_text(encoding="utf-8"))
    assert loss["source_trades"] == 3
    assert loss["verified_entry_context_trades"] == 2
    assert loss["missing_entry_context_trades"] == 1
    assert D(loss["total_realized_closed_net_pnl"]) == D("-4.5")
    assert loss["by_side"]["long"]["trades"] == 2
    assert D(loss["by_side"]["long"]["net_pnl"]) == D("-7")
    assert D(loss["by_side"]["short"]["net_pnl"]) == D("2.5")
    assert loss["loss_reasons_by_side"]["long"][
        "loss_after_0_5r_favorable_move"
    ]["trades"] == 1
    assert loss["loss_reasons_by_side"]["long"][
        "unknown_favorable_path_or_incomplete_chart"
    ]["trades"] == 1
    assert loss["can_select_entry_filter"] is False
    assert loss["execution_authority"] is False


def test_crashed_real_store_handoff_cannot_generate_research_artifacts(
    tmp_path: Path,
) -> None:
    _populate_state(tmp_path)
    (tmp_path / "session-summary.json").write_text(
        json.dumps({"exit_reason": "crashed"}), encoding="utf-8"
    )
    with pytest.raises(AllPaperTradeChartAuditError, match="handoff"):
        write_deferred_trade_charts(tmp_path)
    with pytest.raises(LongEntryLossAttributionError, match="handoff"):
        write_long_entry_loss_attribution(tmp_path)
    assert not (tmp_path / "all-paper-trade-chart-audit.json").exists()
    assert not (tmp_path / "long-entry-loss-attribution.json").exists()
