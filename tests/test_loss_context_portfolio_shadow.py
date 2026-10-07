from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.execution.accounting import empty_account
from cocomelon.research.loss_context_portfolio_shadow import (
    LossContextPortfolioShadowPair,
    LossContextPortfolioShadowPairError,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)
from cocomelon.research.loss_context_portfolio_shadow_entry import (
    LossContextPortfolioShadowEntryFilter,
)


def _freeze() -> LossContextPortfolioShadowFreeze:
    return LossContextPortfolioShadowFreeze(
        loss_context_candidate_id="a" * 64,
        source_composition_digest="b" * 64,
        source_max_timestamp_ms=1_000,
        source_paper_run_id=123,
        source_paper_run_attempt=1,
        source_paper_head_sha="c" * 40,
        dimensions=("lead_strategy", "trend_regime"),
        values=("trend", "down"),
        horizons_ms=(300_000, 900_000, 3_600_000),
        frozen_at_ms=2_000,
        prospective_not_before_ms=21_602_000,
    )


class _Execution:
    def __init__(self, *, equity: str, realized: str = "0") -> None:
        base = empty_account(Decimal("10000"), 21_602_000)
        self.account = replace(
            base,
            cash=Decimal(equity),
            equity=Decimal(equity),
            realized_gross_pnl=Decimal(realized),
            updated_at_ms=21_602_000,
        )


class _Pipeline:
    def __init__(self) -> None:
        self.records: list[tuple[ReplayRecord, int, bool]] = []
        self.markets: tuple[MarketId, ...] = ()
        self.raise_on_record = False

    def on_record(
        self,
        record: ReplayRecord,
        now_ms: int,
        *,
        evaluate_decisions: bool = True,
    ) -> tuple[object, ...]:
        if self.raise_on_record:
            raise RuntimeError("shadow boom")
        self.records.append((record, now_ms, evaluate_decisions))
        return ()

    def finalize(self, _end_ms: int) -> tuple[object, ...]:
        return ()

    def reconcile_markets(
        self,
        selected_markets: tuple[MarketId, ...],
    ) -> None:
        self.markets = tuple(selected_markets)


def _record(timestamp_ms: int = 21_602_100) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=timestamp_ms,
        source="test",
        schema_version=1,
        market="BTC",
        exchange_time_ms=timestamp_ms,
        event_key=f"event-{timestamp_ms}",
        payload_json="{}",
        event_kind="active_asset_ctx",
    )


def _pair(
    *,
    baseline_equity: str = "10000",
    candidate_equity: str = "10000",
) -> tuple[LossContextPortfolioShadowPair, _Pipeline, _Pipeline]:
    freeze = _freeze()
    baseline_pipeline = _Pipeline()
    candidate_pipeline = _Pipeline()
    pair = LossContextPortfolioShadowPair(
        freeze=freeze,
        baseline_pipeline=baseline_pipeline,  # type: ignore[arg-type]
        candidate_pipeline=candidate_pipeline,  # type: ignore[arg-type]
        baseline_execution=_Execution(  # type: ignore[arg-type]
            equity=baseline_equity
        ),
        candidate_execution=_Execution(  # type: ignore[arg-type]
            equity=candidate_equity
        ),
        baseline_filter=LossContextPortfolioShadowEntryFilter(
            freeze,
            block_matching_context=False,
        ),
        candidate_filter=LossContextPortfolioShadowEntryFilter(
            freeze,
            block_matching_context=True,
        ),
    )
    return pair, baseline_pipeline, candidate_pipeline


def test_pair_feeds_identical_ordered_record_to_both_lanes() -> None:
    pair, baseline, candidate = _pair()
    record = _record()

    pair.process(record, now_ms=record.available_at_ms)

    assert baseline.records == candidate.records
    assert baseline.records == [
        (record, record.available_at_ms, True)
    ]
    payload = pair.summary_payload()
    assert payload["processed_records"] == 1
    assert payload["integrity_clean"] is True
    assert payload["economic_comparison_valid"] is True
    assert payload["chronological_account_state_replayed"] is True
    assert payload["portfolio_counterfactual_complete"] is False
    assert payload["execution_authority"] is False


def test_pair_reports_account_delta_without_strategy_authority() -> None:
    pair, _baseline, _candidate = _pair(
        baseline_equity="9950",
        candidate_equity="10025",
    )

    payload = pair.summary_payload()

    assert payload["candidate_minus_baseline_total_account_pnl"] == "75"
    assert payload["ready_for_review"] is False
    assert payload["changes_strategy"] is False
    assert payload["changes_risk_limits"] is False
    assert payload["changes_positions"] is False
    assert payload["promotion_authority"] is False
    assert payload["execution_authority"] is False


def test_pair_reconciles_both_market_sets() -> None:
    pair, baseline, candidate = _pair()
    markets = (MarketId("", "BTC"), MarketId("", "ETH"))

    pair.reconcile_markets(markets)

    assert baseline.markets == markets
    assert candidate.markets == markets


def test_pair_fails_closed_after_lane_failure() -> None:
    pair, _baseline, candidate = _pair()
    candidate.raise_on_record = True
    record = _record()

    with pytest.raises(RuntimeError, match="shadow boom"):
        pair.process(record, now_ms=record.available_at_ms)

    payload = pair.summary_payload()
    assert payload["integrity_clean"] is False
    assert payload["economic_comparison_valid"] is False
    assert payload["candidate_minus_baseline_total_account_pnl"] is None
    assert payload["chronological_account_state_replayed"] is False

    with pytest.raises(
        LossContextPortfolioShadowPairError,
        match="failed closed",
    ):
        pair.process(
            _record(record.available_at_ms + 1),
            now_ms=record.available_at_ms + 1,
        )


def test_pair_rejects_candidate_filter_wired_as_baseline() -> None:
    freeze = _freeze()

    with pytest.raises(
        ValueError,
        match="baseline shadow must not block",
    ):
        LossContextPortfolioShadowPair(
            freeze=freeze,
            baseline_pipeline=_Pipeline(),  # type: ignore[arg-type]
            candidate_pipeline=_Pipeline(),  # type: ignore[arg-type]
            baseline_execution=_Execution(  # type: ignore[arg-type]
                equity="10000"
            ),
            candidate_execution=_Execution(  # type: ignore[arg-type]
                equity="10000"
            ),
            baseline_filter=LossContextPortfolioShadowEntryFilter(
                freeze,
                block_matching_context=True,
            ),
            candidate_filter=LossContextPortfolioShadowEntryFilter(
                freeze,
                block_matching_context=True,
            ),
        )
