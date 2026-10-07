from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.continuous_paper_capacity_release_books import (
    CapacityReleaseBookEvidence,
    CapacityReleaseBookRegistration,
    PendingCapacityReleaseExecution,
    paper_execution_config_payload,
)
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
)
from cocomelon.research.loss_context_holder_release_execution import (
    LossContextHolderReleaseExecutionError,
    loss_context_holder_release_execution_summary,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    CandidateCausedCapacityRelease,
)

BTC = MarketId("", "BTC")


def _freeze() -> LossContextCandidateFreeze:
    frozen_at_ms = 10_000
    return LossContextCandidateFreeze(
        source_audit_digest="a" * 64,
        source_max_timestamp_ms=9_000,
        source_paper_run_id=123,
        source_paper_run_attempt=1,
        source_paper_head_sha="b" * 40,
        dimensions=("lead_strategy", "trend_regime"),
        values=("mean_reversion", "down"),
        discovery_rows=20,
        discovery_markets=5,
        discovery_loss_share=Decimal("0.70"),
        discovery_filter_delta_pnl=Decimal("30"),
        validation_rows=12,
        validation_markets=4,
        validation_loss_share=Decimal("0.75"),
        validation_filter_delta_pnl=Decimal("20"),
        validation_leave_one_trade_min_delta_pnl=Decimal("15"),
        validation_leave_one_market_min_delta_pnl=Decimal("10"),
        frozen_at_ms=frozen_at_ms,
        prospective_not_before_ms=(
            frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ),
    )


def _release(
    *,
    freeze: LossContextCandidateFreeze,
    opportunity_id: str = "opportunity-sol-short-1",
) -> CandidateCausedCapacityRelease:
    return CandidateCausedCapacityRelease(
        opportunity_id=opportunity_id,
        opportunity_timestamp_ms=freeze.prospective_not_before_ms + 1_000,
        opportunity_market="SOL",
        release_market="BTC",
        release_correlation_bucket="majors",
        release_opening_plan_id="holder-plan-btc",
        release_block_reason="frozen_loss_context",
    )


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=BTC,
        sz_decimals=3,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="hyperliquid-mainnet-meta",
    )


def _book(
    *,
    received_ms: int,
    bid_size: str = "2",
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=BTC,
        exchange_time_ms=received_ms - 1,
        receive_time=datetime.fromtimestamp(
            received_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"book:BTC:{received_ms}",
        payload={
            "bids": (
                {
                    "px": Decimal("100.9"),
                    "sz": Decimal(bid_size),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": Decimal("101.1"),
                    "sz": Decimal("10"),
                    "n": 1,
                },
            ),
        },
    )


def _evidence(
    release: CandidateCausedCapacityRelease,
    *,
    quantity: str = "1",
    execution_bid_size: str = "2",
    bind_config: bool = True,
) -> CapacityReleaseBookEvidence:
    registration = CapacityReleaseBookRegistration(
        opportunity_id=release.opportunity_id,
        opportunity_timestamp_ms=release.opportunity_timestamp_ms,
        opportunity_market=release.opportunity_market,
        opportunity_direction="short",
        release_market=release.release_market,
        release_direction="long",
        release_correlation_bucket=release.release_correlation_bucket,
        strategy_decision_id="strategy-sol",
        risk_decision_id="risk-sol",
    )
    position = PaperPosition(
        market=BTC,
        side=PositionSide.LONG,
        quantity=Decimal(quantity),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        opening_plan_id=release.release_opening_plan_id,
        opened_at_ms=release.opportunity_timestamp_ms - 1_000,
        updated_at_ms=release.opportunity_timestamp_ms,
        initial_risk_decision_id="risk-holder-btc",
        correlation_bucket=release.release_correlation_bucket,
        planned_risk=Decimal("20"),
        cumulative_realized_gross_pnl=Decimal("0.05"),
        cumulative_fees=Decimal("0.1"),
        cumulative_funding=Decimal("0.02"),
        venue_max_leverage=Decimal("20"),
        latest_mark=Decimal("101"),
    )
    config = PaperExecutionConfig()
    plan_ms = release.opportunity_timestamp_ms + 100
    execution_ms = plan_ms + config.latency_ms
    pending = PendingCapacityReleaseExecution(
        registration=registration,
        release_position=position,
        plan_observed_at_ms=plan_ms,
        plan_reference_price=Decimal("101"),
        plan_book_event=_book(received_ms=plan_ms),
        plan_instrument=_instrument(),
        execution_config=(
            paper_execution_config_payload(config)
            if bind_config
            else None
        ),
    )
    return CapacityReleaseBookEvidence(
        pending=pending,
        execution_observed_at_ms=execution_ms,
        execution_book_event=_book(
            received_ms=execution_ms,
            bid_size=execution_bid_size,
        ),
        execution_instrument=_instrument(),
    )


def test_exact_full_holder_release_is_eligible_for_entry_investigation() -> None:
    freeze = _freeze()
    release = _release(freeze=freeze)

    result = loss_context_holder_release_execution_summary(
        (release,),
        (_evidence(release),),
        freeze=freeze,
    )

    assert result["causal_release_options"] == 1
    assert result["captured_release_books"] == 1
    assert result["missing_release_book_records"] == 0
    assert result["source_complete"] is True
    assert result["exact_execution_config_records"] == 1
    assert result["full_release_fills"] == 1
    assert result["exact_full_close_release_options"] == 1
    assert result["ready_for_replacement_entry_investigation"] is True
    assert result["all_causal_releases_fully_executable"] is True
    options = result["full_close_release_options"]
    assert isinstance(options, list)
    assert options[0]["release_option_id"] == (
        "opportunity-sol-short-1:holder-plan-btc"
    )
    assert Decimal(
        str(options[0]["full_close_terminal_contribution"])
    ) > 0
    assert result["replacement_entry_fills_modeled"] is False
    assert result["changes_strategy"] is False
    assert result["execution_authority"] is False


def test_missing_release_book_fails_source_complete_closed() -> None:
    freeze = _freeze()
    release = _release(freeze=freeze)

    result = loss_context_holder_release_execution_summary(
        (release,),
        (),
        freeze=freeze,
    )

    assert result["missing_release_book_records"] == 1
    assert result["source_complete"] is False
    assert result["full_release_fills"] == 0
    assert result["ready_for_replacement_entry_investigation"] is False
    assert result["all_causal_releases_fully_executable"] is False


def test_partial_holder_release_does_not_free_full_position_capacity() -> None:
    freeze = _freeze()
    release = _release(freeze=freeze)

    result = loss_context_holder_release_execution_summary(
        (release,),
        (
            _evidence(
                release,
                quantity="3",
                execution_bid_size="1",
            ),
        ),
        freeze=freeze,
    )

    assert result["source_complete"] is True
    assert result["partial_release_fills"] == 1
    assert result["full_release_fills"] == 0
    assert result["exact_full_close_release_options"] == 0
    assert result["ready_for_replacement_entry_investigation"] is False
    assert result["all_causal_releases_fully_executable"] is False


def test_unbound_execution_config_is_not_credited_as_exact_release() -> None:
    freeze = _freeze()
    release = _release(freeze=freeze)

    result = loss_context_holder_release_execution_summary(
        (release,),
        (_evidence(release, bind_config=False),),
        freeze=freeze,
    )

    assert result["source_complete"] is True
    assert result["execution_config_complete"] is False
    assert result["unbound_execution_config_records"] == 1
    assert result["full_release_fills"] == 0
    assert result["ready_for_replacement_entry_investigation"] is False


def test_release_lineage_mismatch_fails_closed() -> None:
    freeze = _freeze()
    release = _release(freeze=freeze)
    other = CandidateCausedCapacityRelease(
        opportunity_id=release.opportunity_id,
        opportunity_timestamp_ms=release.opportunity_timestamp_ms,
        opportunity_market="ETH",
        release_market=release.release_market,
        release_correlation_bucket=release.release_correlation_bucket,
        release_opening_plan_id=release.release_opening_plan_id,
        release_block_reason=release.release_block_reason,
    )

    with pytest.raises(
        LossContextHolderReleaseExecutionError,
        match="lineage mismatch",
    ):
        loss_context_holder_release_execution_summary(
            (other,),
            (_evidence(release),),
            freeze=freeze,
        )


def test_pre_boundary_release_is_rejected() -> None:
    freeze = _freeze()
    release = CandidateCausedCapacityRelease(
        opportunity_id="opportunity-old",
        opportunity_timestamp_ms=freeze.prospective_not_before_ms - 1,
        opportunity_market="SOL",
        release_market="BTC",
        release_correlation_bucket="majors",
        release_opening_plan_id="holder-plan-btc",
        release_block_reason="frozen_loss_context",
    )

    with pytest.raises(
        LossContextHolderReleaseExecutionError,
        match="predates prospective boundary",
    ):
        loss_context_holder_release_execution_summary(
            (release,),
            (),
            freeze=freeze,
        )



def test_holder_release_workflow_runs_after_causal_reflow() -> None:
    source = Path(
        ".github/workflows/continuous-paper.yml"
    ).read_text(encoding="utf-8")
    reflow_at = source.index(
        "- name: Rebuild loss-context capacity reflow sensitivity"
    )
    holder_at = source.index(
        "- name: Rebuild loss-context holder release execution"
    )
    upload_at = source.index(
        "- name: Upload loss-context holder release execution"
    )
    cooldown_at = source.index(
        "- name: Rebuild deferred cooldown evidence after handoff"
    )
    assert reflow_at < holder_at < upload_at < cooldown_at
    assert (
        "rebuild_deferred_loss_context_holder_release_execution.py"
        in source
    )
    assert "loss-context-holder-release-execution-summary.json" in source
    assert "RESEARCH ONLY / NO POSITION OR RISK CHANGE" in source
