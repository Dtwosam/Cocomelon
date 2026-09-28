from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.execution.funding import (
    FundingAccrual,
    funding_cash_delta,
)
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_contribution_decomposition_funding import (
    DelayedEntryFundingDecompositionOutcome,
    delayed_entry_funding_decomposition,
)
from cocomelon.research.delayed_entry_contribution_decomposition_funding import (
    _summary as _funding_decomposition_summary,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)

MARKET = MarketId("", "SOL")


def _funding(
    *,
    boundary_ms: int,
    rate: str,
    quantity: str = "1",
) -> FundingAccrual:
    signed_quantity = Decimal(quantity)
    oracle_price = Decimal("100")
    funding_rate = Decimal(rate)
    return FundingAccrual(
        market=MARKET,
        boundary_ms=boundary_ms,
        position_id=f"position-{boundary_ms}",
        signed_quantity=signed_quantity,
        oracle_price=oracle_price,
        funding_rate=funding_rate,
        cash_delta=funding_cash_delta(
            signed_quantity,
            oracle_price,
            funding_rate,
        ),
        oracle_event_key=f"oracle-{boundary_ms}",
        funding_source="fixture",
        funding_received_at_ms=boundary_ms + 100,
    )


def _loader(
    *accruals: FundingAccrual,
):
    def load(
        market: MarketId,
        start_ms: int,
    ) -> tuple[FundingAccrual, ...]:
        return tuple(
            item
            for item in accruals
            if item.market == market
            and item.boundary_ms >= start_ms
        )

    return load


def _trade(
    *,
    suffix: str,
    funding: tuple[FundingAccrual, ...],
    quantity: str = "1",
) -> TradeJournalEntry:
    qty = Decimal(quantity)
    funding_pnl = sum(
        (item.cash_delta for item in funding),
        Decimal("0"),
    )
    return TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=3_550_000,
        closed_at_ms=7_300_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"fill-open-{suffix}", f"fill-exit-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=tuple(
            item.accrual_id for item in funding
        ),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100"),
        filled_quantity=qty,
        gross_realized_pnl=Decimal("0"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=funding_pnl,
        net_pnl=funding_pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=3_750_000,
        mfe=None,
        mae=None,
        net_r=funding_pnl / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + funding_pnl,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str = "full_visible_book_ioc",
    quantity: str | None = None,
    price: str | None = "100",
) -> DelayedEntryOutcome:
    resolved_quantity = (
        trade.filled_quantity
        if quantity is None
        else Decimal(quantity)
    )
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=resolved_quantity,
        delayed_average_fill_price=(
            None if price is None else Decimal(price)
        ),
        delayed_fee=Decimal("0"),
        observation_lag_ms=0,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
        attempt_reason=None,
        capacity_cause=None,
    )


def test_funding_decomposition_isolates_pre_delay_boundary(
    tmp_path: Path,
) -> None:
    first = _funding(boundary_ms=3_600_000, rate="0.01")
    second = _funding(boundary_ms=7_200_000, rate="0.02")
    trade = _trade(
        suffix="funding-bridge",
        funding=(first, second),
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        journal.record_trade(trade)
        result = delayed_entry_funding_decomposition(
            journal,
            (_outcome(trade),),
            _loader(first, second),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert Decimal(str(overall["price_effect_pnl"])) == Decimal("0")
    assert Decimal(str(overall["entry_fee_effect_pnl"])) == Decimal("0")
    assert Decimal(str(overall["exposure_effect_pnl"])) == Decimal("0")
    assert Decimal(
        str(overall["funding_timing_effect_pnl"])
    ) == Decimal("1")
    assert Decimal(
        str(overall["legacy_total_delta_pnl"])
    ) == Decimal("0")
    assert Decimal(
        str(overall["corrected_total_delta_pnl"])
    ) == Decimal("1")
    assert Decimal(
        str(overall["corrected_candidate_net_pnl"])
    ) == Decimal("-2")
    assert result["identity"] == (
        "price_effect + entry_fee_effect + exposure_effect + "
        "funding_timing_effect = corrected_total_delta"
    )


def test_funding_decomposition_no_fill_keeps_funding_effect_zero(
    tmp_path: Path,
) -> None:
    funding = _funding(
        boundary_ms=7_200_000,
        rate="0.01",
    )
    trade = _trade(
        suffix="no-fill",
        funding=(funding,),
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        journal.record_trade(trade)
        result = delayed_entry_funding_decomposition(
            journal,
            (
                _outcome(
                    trade,
                    source="no_fill",
                    quantity="0",
                    price=None,
                ),
            ),
            _loader(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert result["missing_funding_events"] == 0
    assert Decimal(
        str(overall["funding_timing_effect_pnl"])
    ) == Decimal("0")
    assert Decimal(
        str(overall["exposure_effect_pnl"])
    ) == Decimal("1")
    assert Decimal(
        str(overall["corrected_total_delta_pnl"])
    ) == Decimal("1")
    assert Decimal(
        str(overall["corrected_candidate_net_pnl"])
    ) == Decimal("0")


def test_funding_decomposition_missing_accrual_blocks_review(
    tmp_path: Path,
) -> None:
    funding = _funding(
        boundary_ms=7_200_000,
        rate="0.01",
    )
    trade = _trade(
        suffix="missing",
        funding=(funding,),
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        journal.record_trade(trade)
        result = delayed_entry_funding_decomposition(
            journal,
            (_outcome(trade),),
            _loader(),
        )
    finally:
        journal.close()

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert result["missing_funding_events"] == 1
    assert result["evaluated_delayed_attempts"] == 0
    assert readiness["ready_for_review"] is False


def test_funding_decomposition_partial_fill_reconciles_boundary_scaling(
    tmp_path: Path,
) -> None:
    funding = _funding(
        boundary_ms=7_200_000,
        rate="0.02",
        quantity="0.5",
    )
    trade = _trade(
        suffix="partial",
        funding=(funding,),
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        journal.record_trade(trade)
        result = delayed_entry_funding_decomposition(
            journal,
            (
                _outcome(
                    trade,
                    source="partial_visible_book_ioc",
                    quantity="0.5",
                ),
            ),
            _loader(funding),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert Decimal(
        str(overall["funding_timing_effect_pnl"])
    ) == Decimal("0")
    assert Decimal(
        str(overall["legacy_total_delta_pnl"])
    ) == Decimal("0.5")
    assert Decimal(
        str(overall["corrected_total_delta_pnl"])
    ) == Decimal("0.5")



def test_funding_summary_uses_exact_decimal_aggregation() -> None:
    rows = (
        (
            "-61.79181701745288526954939713",
            "53.26287865350763390079987960",
            "-31.88051929811547879706297324",
            "-40.40945766206073016581249077",
        ),
        (
            "97.15395567483577824256450709",
            "-66.80773600876273495781810057",
            "-92.78781362254566657740525614",
            "-62.44159395647262329265884962",
        ),
        (
            "-97.02566287103053593733501422",
            "79.41184222519113199729057211",
            "35.00649151432642571997655906",
            "17.39267086848702177993211695",
        ),
    )
    items = tuple(
        DelayedEntryFundingDecompositionOutcome(
            trade_id=f"trade-{index}",
            opening_plan_id=f"plan-{index}",
            market="SOL",
            direction="long",
            source="full_visible_book_ioc",
            capacity_cause="full_requested_fill",
            fill_fraction=Decimal("1"),
            actual_net_pnl=Decimal("0"),
            legacy_candidate_net_pnl=Decimal(total),
            corrected_candidate_net_pnl=Decimal(total),
            price_effect_pnl=Decimal(price),
            entry_fee_effect_pnl=Decimal(fee),
            exposure_effect_pnl=Decimal(exposure),
            funding_timing_effect_pnl=Decimal("0"),
            legacy_total_delta_pnl=Decimal(total),
            corrected_total_delta_pnl=Decimal(total),
            price_effect_r=Decimal("0"),
            entry_fee_effect_r=Decimal("0"),
            exposure_effect_r=Decimal("0"),
            funding_timing_effect_r=Decimal("0"),
            corrected_total_delta_r=Decimal("0"),
        )
        for index, (price, fee, exposure, total) in enumerate(rows)
    )

    summary = _funding_decomposition_summary(items)

    assert summary["legacy_total_delta_pnl"] == (
        "-85.45838075004633167853922344"
    )
    assert summary["corrected_total_delta_pnl"] == (
        "-85.45838075004633167853922344"
    )
    assert summary["corrected_candidate_net_pnl"] == (
        "-85.45838075004633167853922344"
    )
