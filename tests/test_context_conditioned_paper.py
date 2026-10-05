from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.context_conditioned_paper import (
    ContextConditionedPaperError,
    build_context_conditioned_paper_report,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _snapshot(
    market: MarketId,
    *,
    as_of_ms: int,
    return_15m: str = "0.01",
    return_1h: str = "0.02",
    funding: str = "0.0001",
    book_imbalance: str = "0.2",
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=Decimal("0.03"),
        funding=Decimal(funding),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("5000000"),
        oi_change_fraction=Decimal("0.01"),
        funding_change=Decimal("0"),
        mark_oracle_dislocation_bps=Decimal("1"),
        return_5m=Decimal("0.005"),
        return_15m=Decimal(return_15m),
        return_1h=Decimal(return_1h),
        return_4h=Decimal("0.04"),
        realized_vol_15m=Decimal("0.02"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("90000"),
        book_imbalance=Decimal(book_imbalance),
        book_age_ms=100,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )


def _record(
    snapshot: FeatureSnapshot,
    *,
    direction: Direction,
    source_record_id: str,
    net_r: str,
    net_pnl: str,
) -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=source_record_id,
        source_evidence_class="microstructure",
        candidate_id="continuous-paper-ensemble-v1",
        candidate_spec_id="a" * 40,
        campaign_id="worker-1",
        market=snapshot.market,
        direction=direction,
        opened_at_ms=snapshot.as_of_ms + 1_000,
        closed_at_ms=snapshot.as_of_ms + 61_000,
        feature_snapshot_id=snapshot.snapshot_id,
        research_eligible_at_ms=snapshot.as_of_ms + 61_000,
        gross_realized_pnl=Decimal(net_pnl) + Decimal("1"),
        entry_fees=Decimal("0.25"),
        exit_fees=Decimal("0.25"),
        funding_cash_pnl=Decimal("-0.5"),
        entry_slippage_fraction=Decimal("0.0001"),
        exit_slippage_fraction=Decimal("0.0001"),
        net_pnl=Decimal(net_pnl),
        net_r=Decimal(net_r),
    )


def test_report_compares_directions_inside_same_market_context(tmp_path: Path) -> None:
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    market = MarketId("", "HYPE")

    for index, (direction, net_r, net_pnl) in enumerate(
        (
            (Direction.LONG, "1.0", "10"),
            (Direction.LONG, "0.5", "5"),
            (Direction.SHORT, "-0.5", "-5"),
            (Direction.SHORT, "-1.0", "-10"),
        )
    ):
        snapshot = _snapshot(market, as_of_ms=1_000 + index * 100)
        features.record(snapshot)
        ledger.record(
            _record(
                snapshot,
                direction=direction,
                source_record_id=f"trade-{index}",
                net_r=net_r,
                net_pnl=net_pnl,
            )
        )

    report = build_context_conditioned_paper_report(
        ledger,
        features,
        as_of_ms=100_000,
        min_group_rows=2,
    )
    payload = report.to_dict()

    assert payload["side_suppression_authority"] is False
    assert payload["execution_authority"] is False
    direction = payload["direction_summary"]
    assert isinstance(direction, dict)
    assert direction["long"]["trades"] == 2
    assert direction["short"]["trades"] == 2

    contexts = payload["context_summary"]
    assert isinstance(contexts, tuple)
    assert len(contexts) == 1
    context = contexts[0]
    assert context["direction_comparison_ready"] is True
    assert Decimal(str(context["mean_net_r_delta_long_minus_short"])) == Decimal("1.5")
    assert context["strategy_authority"] is False
    marginal = payload["marginal_summary"]
    assert isinstance(marginal, dict)
    volatility = marginal["volatility_regime"]
    assert isinstance(volatility, tuple)
    assert len(volatility) == 1
    assert volatility[0]["value"] == "normal"
    assert volatility[0]["long"]["trades"] == 2
    assert volatility[0]["short"]["trades"] == 2
    assert volatility[0]["direction_comparison_ready"] is True
    assert volatility[0]["strategy_authority"] is False


def test_report_keeps_missing_feature_rows_visible_but_unresolved(
    tmp_path: Path,
) -> None:
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    snapshot = _snapshot(MarketId("", "BTC"), as_of_ms=1_000)
    ledger.record(
        _record(
            snapshot,
            direction=Direction.LONG,
            source_record_id="missing-feature",
            net_r="0.1",
            net_pnl="1",
        )
    )

    report = build_context_conditioned_paper_report(
        ledger,
        features,
        as_of_ms=100_000,
    )

    assert report.research_eligible_records == 1
    assert report.resolved_records == 0
    assert report.missing_feature_snapshot_ids == (snapshot.snapshot_id,)


def test_report_fails_closed_when_feature_is_after_trade_open(
    tmp_path: Path,
) -> None:
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    market = MarketId("", "ETH")
    feature = _snapshot(market, as_of_ms=5_000)
    features.record(feature)
    record = LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id="late-feature",
        source_evidence_class="microstructure",
        candidate_id="continuous-paper-ensemble-v1",
        candidate_spec_id="b" * 40,
        campaign_id="worker-2",
        market=market,
        direction=Direction.SHORT,
        opened_at_ms=4_000,
        closed_at_ms=10_000,
        feature_snapshot_id=feature.snapshot_id,
        research_eligible_at_ms=10_000,
        gross_realized_pnl=Decimal("1"),
        entry_fees=Decimal("0.1"),
        exit_fees=Decimal("0.1"),
        funding_cash_pnl=Decimal("0"),
        entry_slippage_fraction=Decimal("0.0001"),
        exit_slippage_fraction=Decimal("0.0001"),
        net_pnl=Decimal("0.8"),
        net_r=Decimal("0.2"),
    )
    ledger.record(record)

    with pytest.raises(
        ContextConditionedPaperError,
        match="CONTEXT_DIAGNOSTIC_FEATURE_AFTER_OPEN",
    ):
        build_context_conditioned_paper_report(
            ledger,
            features,
            as_of_ms=100_000,
        )
