from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.continuous_paper import _ContinuousTradePathSink
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.evidence.lifecycle import OpenLifecycleMarkPath
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathError,
    ContinuousPaperTradePathMark,
    ContinuousPaperTradePathStore,
    continuous_paper_trade_path,
)

MARKET = MarketId("", "SOL")


def _trade() -> TradeJournalEntry:
    return TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        feature_snapshot_id="feature-1",
        strategy_decision_id="strategy-1",
        risk_decision_id="risk-1",
        opening_plan_id="plan-open",
        opening_attempt_id="attempt-open",
        exit_plan_ids=("plan-close",),
        exit_attempt_ids=("attempt-close",),
        fill_ids=("fill-open", "fill-close"),
        position_action_ids=("action-close",),
        funding_event_ids=(),
        initial_stop=Decimal("95"),
        initial_risk_amount=Decimal("25"),
        entry_price=Decimal("100"),
        exit_price=Decimal("102"),
        filled_quantity=Decimal("10"),
        gross_realized_pnl=Decimal("20"),
        entry_fees=Decimal("0.45"),
        exit_fees=Decimal("0.459"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("19.091"),
        entry_slippage_amount=Decimal("1"),
        exit_slippage_amount=Decimal("2"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.002"),
        holding_duration_ms=1_000,
        mfe=None,
        mae=None,
        net_r=Decimal("0.76364"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10019.091"),
        exit_reason="exit_thesis",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _record(
    available_at_ms: int,
    mark_px: str,
    event_key: str,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=available_at_ms,
        source="hyperliquid-mainnet",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=available_at_ms - 1,
        event_key=event_key,
        payload_json=f'{{"mark_px":"{mark_px}"}}',
        event_kind="activeAssetCtx",
    )


def _mark(
    available_at_ms: int,
    mark_px: str,
    event_key: str,
) -> ContinuousPaperTradePathMark:
    return ContinuousPaperTradePathMark(
        available_at_ms=available_at_ms,
        exchange_time_ms=available_at_ms - 1,
        event_key=event_key,
        mark_px=Decimal(mark_px),
    )


def test_trade_path_preserves_ordered_mark_sequence() -> None:
    path = continuous_paper_trade_path(
        _trade(),
        (
            _mark(1_500, "103", "mark-2"),
            _mark(1_200, "101", "mark-1"),
        ),
        ((1_700, 1_750),),
    )

    assert path.trade_id == _trade().trade_id
    assert tuple(mark.event_key for mark in path.marks) == (
        "mark-1",
        "mark-2",
    )
    assert tuple(mark.mark_px for mark in path.marks) == (
        Decimal("101"),
        Decimal("103"),
    )
    assert path.known_gap_intervals == ((1_700, 1_750),)
    assert path.excursion_complete is False
    assert path.path_complete is False


def test_trade_path_store_is_idempotent_and_conflict_detecting(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    path = continuous_paper_trade_path(
        _trade(),
        (_mark(1_200, "101", "mark-1"),),
        (),
    )

    assert store.record(path) is True
    assert store.record(path) is False
    assert store.record_count == 1
    assert len(store.state_digest) == 64

    conflict = replace(
        path,
        marks=(
            replace(
                path.marks[0],
                mark_px=Decimal("101.5"),
            ),
        ),
    )
    with pytest.raises(
        ContinuousPaperTradePathError,
        match="CONTINUOUS_PAPER_TRADE_PATH_CONFLICT",
    ):
        store.record(conflict)


def test_open_path_checkpoint_reuses_validated_in_memory_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    assert store.checkpoint_open_path(
        opening_plan_id="plan-open",
        market=MARKET,
        opened_at_ms=1_000,
        venue_max_leverage=Decimal("20"),
        mark_observations=(_record(1_200, "101", "mark-1"),),
    ) == 1

    open_path = store._open_path("plan-open")
    original_read_text = Path.read_text

    def fail_open_path_read(
        path: Path,
        *args: object,
        **kwargs: object,
    ) -> str:
        if path == open_path:
            raise AssertionError(
                "validated open trade path must not be reparsed"
            )
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_open_path_read)

    assert store.checkpoint_open_path(
        opening_plan_id="plan-open",
        market=MARKET,
        opened_at_ms=1_000,
        venue_max_leverage=Decimal("20"),
        mark_observations=(
            _record(1_200, "101", "mark-1"),
            _record(1_500, "103", "mark-2"),
        ),
    ) == 1
    assert store.finalize_trade(
        _trade(),
        (_record(1_900, "102", "mark-3"),),
        (),
    ) is True
    assert store.open_path_count == 0


def test_open_path_checkpoint_survives_store_restart_and_finalizes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "trade-paths"
    first = ContinuousPaperTradePathStore(root)

    assert first.checkpoint_open_path(
        opening_plan_id="plan-open",
        market=MARKET,
        opened_at_ms=1_000,
        venue_max_leverage=Decimal("20"),
        mark_observations=(
            _record(1_200, "101", "mark-1"),
            _record(1_500, "103", "mark-2"),
        ),
    ) == 2
    assert first.open_path_count == 1

    restored = ContinuousPaperTradePathStore(root)
    assert restored.checkpoint_open_path(
        opening_plan_id="plan-open",
        market=MARKET,
        opened_at_ms=1_000,
        venue_max_leverage=Decimal("20"),
        mark_observations=(
            _record(1_500, "103", "mark-2"),
            _record(1_800, "102.5", "mark-3"),
        ),
    ) == 1

    assert restored.finalize_trade(
        _trade(),
        (_record(1_900, "102", "mark-4"),),
        (),
    ) is True

    assert restored.open_path_count == 0
    assert restored.record_count == 1
    payload = restored.iter_payloads()[0]
    assert payload["schema_version"] == 2
    assert payload["venue_max_leverage"] == "20"
    marks = payload["marks"]
    assert isinstance(marks, list)
    assert [mark["event_key"] for mark in marks] == [
        "mark-1",
        "mark-2",
        "mark-3",
        "mark-4",
    ]


def test_open_path_checkpoint_upgrades_legacy_header_with_leverage(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    assert store.checkpoint_open_path(
        opening_plan_id="plan-open",
        market=MARKET,
        opened_at_ms=1_000,
        mark_observations=(_record(1_200, "101", "mark-1"),),
    ) == 1

    assert store.checkpoint_open_path(
        opening_plan_id="plan-open",
        market=MARKET,
        opened_at_ms=1_000,
        venue_max_leverage=Decimal("20"),
        mark_observations=(_record(1_500, "103", "mark-2"),),
    ) == 1

    assert store.finalize_trade(
        _trade(),
        (_record(1_900, "102", "mark-3"),),
        (),
    ) is True
    payload = store.iter_payloads()[0]
    assert payload["schema_version"] == 2
    assert payload["venue_max_leverage"] == "20"


def test_open_path_checkpoint_rejects_identity_drift(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    store.checkpoint_open_path(
        opening_plan_id="plan-open",
        market=MARKET,
        opened_at_ms=1_000,
        mark_observations=(_record(1_200, "101", "mark-1"),),
    )

    with pytest.raises(
        ContinuousPaperTradePathError,
        match="OPEN_IDENTITY_MISMATCH",
    ):
        store.checkpoint_open_path(
            opening_plan_id="plan-open",
            market=MARKET,
            opened_at_ms=999,
            mark_observations=(),
        )


def test_trade_path_rejects_mark_outside_lifecycle() -> None:
    with pytest.raises(ValueError, match="outside lifecycle"):
        continuous_paper_trade_path(
            _trade(),
            (_mark(2_001, "101", "mark-late"),),
            (),
        )


def _open_lifecycle_path(
    *records: ReplayRecord,
    plan_id: str = "plan-open",
) -> OpenLifecycleMarkPath:
    return OpenLifecycleMarkPath(
        market=MARKET,
        opening_plan_id=plan_id,
        opened_at_ms=1_000,
        venue_max_leverage=Decimal("20"),
        mark_observations=records,
    )


def test_sink_incremental_checkpoint_is_exactly_same_durable_path(
    tmp_path: Path,
) -> None:
    class TrackingStore(ContinuousPaperTradePathStore):
        def __init__(self, root: Path) -> None:
            super().__init__(root)
            self.forwarded: list[tuple[str | None, ...]] = []

        def checkpoint_open_path(
            self,
            *,
            opening_plan_id: str,
            market: MarketId,
            opened_at_ms: int,
            mark_observations: tuple[ReplayRecord, ...],
            venue_max_leverage: Decimal | None = None,
        ) -> int:
            self.forwarded.append(
                tuple(row.event_key for row in mark_observations)
            )
            return super().checkpoint_open_path(
                opening_plan_id=opening_plan_id,
                market=market,
                opened_at_ms=opened_at_ms,
                mark_observations=mark_observations,
                venue_max_leverage=venue_max_leverage,
            )

    actual = TrackingStore(tmp_path / "optimized")
    baseline = ContinuousPaperTradePathStore(tmp_path / "baseline")
    sink = _ContinuousTradePathSink(actual)
    r1 = _record(1_200, "101", "one")
    r2 = _record(1_500, "103", "two")
    r3 = _record(1_800, "102", "three")

    sequences = (
        (r1, r2),
        (r1, r2),
        (r1, r2, r3),
        # Identical data reordered is NOT an append-only prefix; it must
        # be reconciled via the full validated durable-store path.
        (r2, r1, r3),
        (r2, r1, r3),
    )
    for records in sequences:
        sink.checkpoint((_open_lifecycle_path(*records),))
        baseline.checkpoint_open_path(
            opening_plan_id="plan-open",
            market=MARKET,
            opened_at_ms=1_000,
            mark_observations=records,
            venue_max_leverage=Decimal("20"),
        )
        assert actual._open_path("plan-open").read_bytes() == (
            baseline._open_path("plan-open").read_bytes()
        )
    assert actual.forwarded == [
        ("one", "two"),
        (),
        ("three",),
        ("two", "one", "three"),
        (),
    ]
    assert sink.error is None

    close = (_record(1_900, "102", "close"),)
    assert sink.record(_trade(), close, ((1_700, 1_710),)) is True
    assert baseline.finalize_trade(_trade(), close, ((1_700, 1_710),))
    assert actual.iter_payloads() == baseline.iter_payloads()
    assert actual.open_path_count == baseline.open_path_count == 0
    assert sink._checkpointed_path_records == {}


def test_append_only_cache_never_suppresses_rewritten_source_conflicts(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperTradePathStore(tmp_path / "store")
    sink = _ContinuousTradePathSink(store)
    first = _record(1_200, "101", "mark-one")
    second = _record(1_500, "102", "mark-two")
    sink.checkpoint((_open_lifecycle_path(first),))
    original_bytes = store._open_path("plan-open").read_bytes()
    # Same identity but different observed value: no allowed prefix
    # shortcut. The existing authoritative conflict check must still fire.
    rewritten = _record(1_200, "110", "mark-one")
    sink.checkpoint((_open_lifecycle_path(rewritten),))
    assert "conflicting trade path mark event" in str(sink.error)
    assert store._open_path("plan-open").read_bytes() == original_bytes
    assert sink._checkpointed_path_records["plan-open"] == (first,)

    # An error cannot mutate the saved prefix or suppress later received
    # marks. The following clean tail must still persist exactly.
    sink.checkpoint((_open_lifecycle_path(first, second),))
    assert sink._checkpointed_path_records["plan-open"] == (
        first, second,
    )
    assert [m.event_key for m in store._load_open("plan-open")[1]] == [
        "mark-one", "mark-two",
    ]


def test_zero_new_marks_still_validate_trade_path_identity(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperTradePathStore(tmp_path / "store")
    assert store.checkpoint_open_path(
        opening_plan_id="plan-open",
        market=MARKET,
        opened_at_ms=1_000,
        mark_observations=(),
        venue_max_leverage=Decimal("20"),
    ) == 0
    original_bytes = store._open_path("plan-open").read_bytes()
    assert store.checkpoint_open_path(
        opening_plan_id="plan-open",
        market=MARKET,
        opened_at_ms=1_000,
        mark_observations=(),
        venue_max_leverage=Decimal("20"),
    ) == 0
    assert store._open_path("plan-open").read_bytes() == original_bytes
    with pytest.raises(
        ContinuousPaperTradePathError, match="OPEN_IDENTITY_MISMATCH"
    ):
        store.checkpoint_open_path(
            opening_plan_id="plan-open",
            market=MARKET,
            opened_at_ms=999,
            mark_observations=(),
            venue_max_leverage=Decimal("20"),
        )
