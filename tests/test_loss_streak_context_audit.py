from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.loss_streak_context_audit import (
    LossStreakContextAuditError,
    loss_streak_context_audit,
)

RUN_ID = "continuous-paper-mainnet-v1"
MARKET = MarketId("", "HYPE")


def _feature(
    *,
    as_of_ms: int,
    market: MarketId = MARKET,
    trend: TrendRegime = TrendRegime.DOWN,
    volatility: VolatilityRegime = VolatilityRegime.HIGH,
    return_15m: str = "-0.01",
    return_1h: str = "-0.02",
    funding: str = "0.0001",
    imbalance: str = "-0.2",
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=Decimal("-0.03"),
        funding=Decimal(funding),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("5000000"),
        oi_change_fraction=Decimal("0.01"),
        funding_change=Decimal("0"),
        mark_oracle_dislocation_bps=Decimal("1"),
        return_5m=Decimal("-0.005"),
        return_15m=Decimal(return_15m),
        return_1h=Decimal(return_1h),
        return_4h=Decimal("-0.04"),
        realized_vol_15m=Decimal("0.03"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.1"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("110000"),
        book_imbalance=Decimal(imbalance),
        book_age_ms=100,
        trend_regime=trend,
        volatility_regime=volatility,
        provenance=("test",),
    )


def _trade(
    *,
    suffix: str,
    feature: FeatureSnapshot,
    opened_at_ms: int,
    pnl: str,
    direction: Direction = Direction.SHORT,
    exit_reason: str = "MARK_STOP_TRIGGERED",
) -> TradeJournalEntry:
    value = Decimal(pnl)
    return TradeJournalEntry(
        market=feature.market,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
        feature_snapshot_id=feature.snapshot_id,
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"fill-open-{suffix}", f"fill-exit-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=Decimal("105"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100") - value,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=value,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=value,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=value / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + value,
        exit_reason=exit_reason,
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _fact(
    trade: TradeJournalEntry,
    *,
    strategy: str = "mean_reversion",
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=RUN_ID,
        market=trade.market,
        direction=trade.direction,
        timestamp_ms=trade.opened_at_ms - 1,
        score=Decimal("0.8"),
        lead_strategy=strategy,
        signal_ids=(f"signal-{trade.strategy_decision_id}",),
        reason_codes=("decision_threshold_met",),
        trend_regime=TrendRegime.DOWN,
        volatility_regime=VolatilityRegime.HIGH,
    )


def _rank(
    trade: TradeJournalEntry,
    *,
    ordinal: int = 2,
) -> ContinuousPaperOpeningRankEvidence:
    return ContinuousPaperOpeningRankEvidence(
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        opened_at_ms=trade.opened_at_ms,
        rank_observed_at_ms=trade.opened_at_ms - 100,
        rank_age_ms=100,
        ordinal=ordinal,
        score=Decimal("0.9"),
        rank_pool_size=20,
        reason_codes=("ranked",),
    )


def _record(
    trade: TradeJournalEntry,
    feature: FeatureSnapshot,
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
    *,
    strategy: str = "mean_reversion",
    ordinal: int = 2,
) -> None:
    features.record(feature)
    facts.record_decision_fact(_fact(trade, strategy=strategy))
    ranks.record(_rank(trade, ordinal=ordinal))


def test_loss_streak_audit_finds_recurring_context_across_streaks(
    tmp_path: Path,
) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    trades: list[TradeJournalEntry] = []

    try:
        timestamp = 1_000_000
        for streak_index, length in enumerate((3, 4), start=1):
            for index in range(length):
                feature = _feature(as_of_ms=timestamp - 1_000)
                trade = _trade(
                    suffix=f"s{streak_index}-{index}",
                    feature=feature,
                    opened_at_ms=timestamp,
                    pnl="-5",
                )
                _record(trade, feature, facts, features, ranks)
                trades.append(trade)
                timestamp += 120_000
            if streak_index == 1:
                feature = _feature(as_of_ms=timestamp - 1_000)
                winner = _trade(
                    suffix="winner",
                    feature=feature,
                    opened_at_ms=timestamp,
                    pnl="6",
                    exit_reason="OPPOSITE_FRESH_THESIS",
                )
                _record(
                    winner,
                    feature,
                    facts,
                    features,
                    ranks,
                    strategy="trend",
                    ordinal=6,
                )
                trades.append(winner)
                timestamp += 120_000

        result = loss_streak_context_audit(
            tuple(trades),
            facts,
            features,
            ranks,
        )
    finally:
        facts.close()

    assert result["trade_count"] == 8
    assert result["loss_streak_count"] == 2
    assert result["qualifying_loss_streak_count"] == 2
    assert result["current_consecutive_losses"] == 4
    assert result["execution_authority"] is False
    assert result["changes_strategy"] is False
    assert result["changes_risk_limits"] is False
    assert result["baseline_resolved_trade_count"] == 8
    assert result["baseline_unresolved_trade_count"] == 0
    assert result["baseline_normalization_complete"] is True
    assert result["non_loss_control_trade_count"] == 1
    assert result["qualifying_loss_trade_count"] == 7
    assert result["recurring_patterns_baseline_normalized"] is True
    assert result["normalization_strategy_authority"] is False

    latest = result["latest_qualifying_streak"]
    assert isinstance(latest, dict)
    assert latest["length"] == 4
    assert latest["net_pnl"] == "-20"
    assert latest["net_r"] == "-2.0"
    assert latest["stop_triggered_losses"] == 4

    recurring = result["recurring_dominant_patterns"]
    assert isinstance(recurring, tuple)
    patterns = {
        (item["field"], item["value"]): item
        for item in recurring
    }
    assert patterns[("direction", "short")]["qualifying_streaks"] == 2
    assert patterns[("direction", "short")]["qualifying_loss_trade_share"] == "1"
    assert patterns[("direction", "short")]["baseline_trade_share"] == "1"
    assert patterns[("direction", "short")]["loss_share_lift_vs_baseline"] == "0"
    assert patterns[("direction", "short")]["non_loss_trade_share"] == "1"
    assert patterns[("direction", "short")]["loss_share_delta_vs_non_loss"] == "0"
    assert patterns[("direction", "short")]["entry_time_context"] is True
    assert patterns[("direction", "short")]["strategy_authority"] is False
    assert patterns[("exit_reason", "MARK_STOP_TRIGGERED")][
        "qualifying_streaks"
    ] == 2
    assert patterns[("lead_strategy", "mean_reversion")][
        "qualifying_streaks"
    ] == 2
    assert patterns[("volatility_regime", "high")][
        "qualifying_streaks"
    ] == 2
    assert patterns[("rank_band", "top3")]["qualifying_streaks"] == 2


def test_single_streak_does_not_claim_recurring_pattern(tmp_path: Path) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    trades: list[TradeJournalEntry] = []
    try:
        for index in range(3):
            opened = 1_000_000 + index * 120_000
            feature = _feature(as_of_ms=opened - 1_000)
            trade = _trade(
                suffix=str(index),
                feature=feature,
                opened_at_ms=opened,
                pnl="-4",
            )
            _record(trade, feature, facts, features, ranks)
            trades.append(trade)
        result = loss_streak_context_audit(
            tuple(trades),
            facts,
            features,
            ranks,
        )
    finally:
        facts.close()

    assert result["qualifying_loss_streak_count"] == 1
    assert result["current_consecutive_losses"] == 3
    assert result["recurring_dominant_patterns"] == ()


def test_current_short_streak_is_visible_below_qualifying_floor(
    tmp_path: Path,
) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    trades: list[TradeJournalEntry] = []
    try:
        for index in range(2):
            opened = 1_000_000 + index * 120_000
            feature = _feature(as_of_ms=opened - 1_000)
            trade = _trade(
                suffix=str(index),
                feature=feature,
                opened_at_ms=opened,
                pnl="-4",
            )
            _record(trade, feature, facts, features, ranks)
            trades.append(trade)
        result = loss_streak_context_audit(
            tuple(trades),
            facts,
            features,
            ranks,
        )
    finally:
        facts.close()

    assert result["qualifying_loss_streak_count"] == 0
    assert result["current_consecutive_losses"] == 2
    assert result["latest_qualifying_streak"] is None


def test_loss_streak_audit_fails_closed_on_missing_feature(
    tmp_path: Path,
) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    feature = _feature(as_of_ms=999_000)
    trades = tuple(
        _trade(
            suffix=str(index),
            feature=feature,
            opened_at_ms=1_000_000 + index * 120_000,
            pnl="-4",
        )
        for index in range(3)
    )
    try:
        for trade in trades:
            facts.record_decision_fact(_fact(trade))
            ranks.record(_rank(trade))

        with pytest.raises(
            LossStreakContextAuditError,
            match="missing feature snapshot",
        ):
            loss_streak_context_audit(
                trades,
                facts,
                features,
                ranks,
            )
    finally:
        facts.close()



def test_loss_streak_audit_highlights_context_overrepresented_vs_winners(
    tmp_path: Path,
) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    trades: list[TradeJournalEntry] = []
    try:
        timestamp = 2_000_000
        for streak_index in range(2):
            for index in range(3):
                feature = _feature(as_of_ms=timestamp - 1_000)
                trade = _trade(
                    suffix=f"loss-{streak_index}-{index}",
                    feature=feature,
                    opened_at_ms=timestamp,
                    pnl="-5",
                    direction=Direction.SHORT,
                )
                _record(
                    trade,
                    feature,
                    facts,
                    features,
                    ranks,
                    strategy="mean_reversion",
                    ordinal=2,
                )
                trades.append(trade)
                timestamp += 120_000

            feature = _feature(
                as_of_ms=timestamp - 1_000,
                trend=TrendRegime.UP,
                volatility=VolatilityRegime.NORMAL,
                return_15m="0.01",
                return_1h="0.02",
                imbalance="0.2",
            )
            winner = _trade(
                suffix=f"separator-{streak_index}",
                feature=feature,
                opened_at_ms=timestamp,
                pnl="6",
                direction=Direction.LONG,
                exit_reason="OPPOSITE_FRESH_THESIS",
            )
            _record(
                winner,
                feature,
                facts,
                features,
                ranks,
                strategy="trend",
                ordinal=8,
            )
            trades.append(winner)
            timestamp += 120_000

        for index in range(4):
            feature = _feature(
                as_of_ms=timestamp - 1_000,
                trend=TrendRegime.UP,
                volatility=VolatilityRegime.NORMAL,
                return_15m="0.01",
                return_1h="0.02",
                imbalance="0.2",
            )
            winner = _trade(
                suffix=f"control-{index}",
                feature=feature,
                opened_at_ms=timestamp,
                pnl="6",
                direction=Direction.LONG,
                exit_reason="OPPOSITE_FRESH_THESIS",
            )
            _record(
                winner,
                feature,
                facts,
                features,
                ranks,
                strategy="trend",
                ordinal=8,
            )
            trades.append(winner)
            timestamp += 120_000

        result = loss_streak_context_audit(
            tuple(trades),
            facts,
            features,
            ranks,
        )
    finally:
        facts.close()

    assert result["baseline_resolved_trade_count"] == 12
    assert result["non_loss_control_trade_count"] == 6
    assert result["qualifying_loss_trade_count"] == 6

    recurring = result["recurring_dominant_patterns"]
    assert isinstance(recurring, tuple)
    patterns = {
        (item["field"], item["value"]): item
        for item in recurring
    }
    short = patterns[("direction", "short")]
    assert short["qualifying_loss_trade_share"] == "1"
    assert short["baseline_trade_share"] == "0.5"
    assert short["loss_share_lift_vs_baseline"] == "0.5"
    assert short["non_loss_trade_share"] == "0"
    assert short["loss_share_delta_vs_non_loss"] == "1"

    high_vol = patterns[("volatility_regime", "high")]
    assert high_vol["qualifying_loss_trade_share"] == "1"
    assert high_vol["baseline_trade_share"] == "0.5"
    assert high_vol["loss_share_lift_vs_baseline"] == "0.5"
    assert high_vol["non_loss_trade_share"] == "0"
    assert high_vol["loss_share_delta_vs_non_loss"] == "1"


def test_loss_streak_baseline_tracks_unresolved_legacy_control_rows(
    tmp_path: Path,
) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    trades: list[TradeJournalEntry] = []
    try:
        timestamp = 3_000_000
        for streak_index in range(2):
            for index in range(3):
                feature = _feature(as_of_ms=timestamp - 1_000)
                trade = _trade(
                    suffix=f"resolved-{streak_index}-{index}",
                    feature=feature,
                    opened_at_ms=timestamp,
                    pnl="-4",
                )
                _record(trade, feature, facts, features, ranks)
                trades.append(trade)
                timestamp += 120_000
            if streak_index == 0:
                feature = _feature(as_of_ms=timestamp - 1_000)
                winner = _trade(
                    suffix="resolved-winner",
                    feature=feature,
                    opened_at_ms=timestamp,
                    pnl="5",
                )
                _record(winner, feature, facts, features, ranks)
                trades.append(winner)
                timestamp += 120_000

        legacy_feature = _feature(as_of_ms=timestamp - 1_000)
        legacy = _trade(
            suffix="legacy-control",
            feature=legacy_feature,
            opened_at_ms=timestamp,
            pnl="5",
        )
        legacy = replace(legacy, replay_run_id=None)
        trades.append(legacy)

        result = loss_streak_context_audit(
            tuple(trades),
            facts,
            features,
            ranks,
        )
    finally:
        facts.close()

    assert result["baseline_resolved_trade_count"] == 7
    assert result["baseline_unresolved_trade_count"] == 1
    assert result["baseline_unresolved_reason_counts"] == {
        "missing replay_run_id": 1
    }
    assert result["baseline_normalization_complete"] is False

    recurring = result["recurring_dominant_patterns"]
    assert isinstance(recurring, tuple)
    assert all(item["baseline_complete"] is False for item in recurring)



def test_loss_context_filter_requires_context_not_direction_only(
    tmp_path: Path,
) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    trades: list[TradeJournalEntry] = []
    markets = (
        MarketId("", "AAA"),
        MarketId("", "BBB"),
        MarketId("", "CCC"),
    )
    try:
        timestamp = 4_000_000

        def add_trade(
            *,
            suffix: str,
            market: MarketId,
            pnl: str,
            strategy: str,
            trend: TrendRegime,
            volatility: VolatilityRegime,
        ) -> None:
            nonlocal timestamp
            feature = _feature(
                as_of_ms=timestamp - 1_000,
                market=market,
                trend=trend,
                volatility=volatility,
                return_15m=(
                    "-0.01"
                    if trend is TrendRegime.DOWN
                    else "0.01"
                ),
                return_1h=(
                    "-0.02"
                    if trend is TrendRegime.DOWN
                    else "0.02"
                ),
                imbalance=(
                    "-0.2"
                    if trend is TrendRegime.DOWN
                    else "0.2"
                ),
            )
            trade = _trade(
                suffix=suffix,
                feature=feature,
                opened_at_ms=timestamp,
                pnl=pnl,
                direction=Direction.SHORT,
                exit_reason=(
                    "MARK_STOP_TRIGGERED"
                    if Decimal(pnl) < 0
                    else "OPPOSITE_FRESH_THESIS"
                ),
            )
            _record(
                trade,
                feature,
                facts,
                features,
                ranks,
                strategy=strategy,
                ordinal=2,
            )
            trades.append(trade)
            timestamp += 120_000

        # First 60%: repeated losing mean-reversion/down/high context,
        # separated by unrelated trend winners so the context recurs across
        # multiple qualifying loss streaks.
        for streak in range(3):
            for index in range(3):
                add_trade(
                    suffix=f"discovery-loss-{streak}-{index}",
                    market=markets[index % len(markets)],
                    pnl="-5",
                    strategy="mean_reversion",
                    trend=TrendRegime.DOWN,
                    volatility=VolatilityRegime.HIGH,
                )
            add_trade(
                suffix=f"discovery-separator-{streak}",
                market=markets[streak % len(markets)],
                pnl="4",
                strategy="trend",
                trend=TrendRegime.UP,
                volatility=VolatilityRegime.NORMAL,
            )
        add_trade(
            suffix="discovery-context-win",
            market=markets[0],
            pnl="2",
            strategy="mean_reversion",
            trend=TrendRegime.DOWN,
            volatility=VolatilityRegime.HIGH,
        )
        add_trade(
            suffix="discovery-tail-loss",
            market=markets[1],
            pnl="-5",
            strategy="mean_reversion",
            trend=TrendRegime.DOWN,
            volatility=VolatilityRegime.HIGH,
        )

        # Later holdout: the same exact context remains harmful in two
        # chronological blocks and across three markets.
        for block in range(2):
            for index in range(3):
                add_trade(
                    suffix=f"validation-loss-{block}-{index}",
                    market=markets[index],
                    pnl="-5",
                    strategy="mean_reversion",
                    trend=TrendRegime.DOWN,
                    volatility=VolatilityRegime.HIGH,
                )
            add_trade(
                suffix=f"validation-context-win-{block}",
                market=markets[block],
                pnl="2",
                strategy="mean_reversion",
                trend=TrendRegime.DOWN,
                volatility=VolatilityRegime.HIGH,
            )
            add_trade(
                suffix=f"validation-separator-{block}",
                market=markets[block],
                pnl="4",
                strategy="trend",
                trend=TrendRegime.UP,
                volatility=VolatilityRegime.NORMAL,
            )

        result = loss_streak_context_audit(
            tuple(trades),
            facts,
            features,
            ranks,
        )
    finally:
        facts.close()

    stability = result["context_filter_stability"]
    assert isinstance(stability, dict)
    assert stability["direction_only_candidates_allowed"] is False
    assert stability["lead_strategy_context_required"] is True
    assert ("direction",) not in stability["candidate_dimension_sets"]
    assert stability["stable_candidate_count"] > 0

    candidates = stability["candidates"]
    assert isinstance(candidates, tuple)
    candidate = next(
        item
        for item in candidates
        if item["dimensions"] == ("lead_strategy", "trend_regime")
        and item["values"] == ("mean_reversion", "down")
    )
    assert candidate["recurring_loss_streaks"] >= 2
    assert candidate["validation_rows"] >= 6
    assert candidate["validation_markets"] == 3
    assert Decimal(candidate["validation_filter_delta_pnl"]) > 0
    assert Decimal(
        candidate["validation_leave_one_trade_min_delta_pnl"]
    ) > 0
    assert Decimal(
        candidate["validation_leave_one_market_min_delta_pnl"]
    ) > 0
    assert candidate["validation_blocks_consistent"] == 2
    assert candidate["stable_on_validation"] is True
    assert candidate["strategy_authority"] is False
    assert candidate["execution_authority"] is False


def test_loss_context_filter_rejects_one_market_carry(
    tmp_path: Path,
) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    trades: list[TradeJournalEntry] = []
    try:
        timestamp = 6_000_000
        for streak in range(4):
            for index in range(3):
                feature = _feature(as_of_ms=timestamp - 1_000)
                trade = _trade(
                    suffix=f"loss-{streak}-{index}",
                    feature=feature,
                    opened_at_ms=timestamp,
                    pnl="-5",
                )
                _record(
                    trade,
                    feature,
                    facts,
                    features,
                    ranks,
                    strategy="mean_reversion",
                    ordinal=2,
                )
                trades.append(trade)
                timestamp += 120_000
            feature = _feature(
                as_of_ms=timestamp - 1_000,
                trend=TrendRegime.UP,
                volatility=VolatilityRegime.NORMAL,
                return_15m="0.01",
                return_1h="0.02",
                imbalance="0.2",
            )
            winner = _trade(
                suffix=f"separator-{streak}",
                feature=feature,
                opened_at_ms=timestamp,
                pnl="2",
            )
            _record(
                winner,
                feature,
                facts,
                features,
                ranks,
                strategy="trend",
                ordinal=8,
            )
            trades.append(winner)
            timestamp += 120_000

        result = loss_streak_context_audit(
            tuple(trades),
            facts,
            features,
            ranks,
        )
    finally:
        facts.close()

    stability = result["context_filter_stability"]
    assert isinstance(stability, dict)
    candidates = stability["candidates"]
    assert isinstance(candidates, tuple)
    candidate = next(
        item
        for item in candidates
        if item["dimensions"] == ("lead_strategy", "trend_regime")
        and item["values"] == ("mean_reversion", "down")
    )
    assert candidate["validation_markets"] == 1
    assert candidate["stable_on_validation"] is False
