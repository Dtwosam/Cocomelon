from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_prediction_ledger import (
    update_prediction_ledger,
)
from cocomelon.research.prospective_trade_overlap_ledger import (
    ProspectiveTradeOverlapLedgerError,
    update_trade_overlap_ledger,
    validate_trade_overlap_ledger,
)


def _trade(
    suffix: str,
    *,
    decision_id: str,
    direction: Direction,
    net_pnl: str,
    opened_at_ms: int,
) -> TradeJournalEntry:
    net = Decimal(net_pnl)
    initial_risk = Decimal("10")
    return TradeJournalEntry(
        market=MarketId("", "BTC"),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=decision_id,
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-open-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"attempt-exit-{suffix}",),
        fill_ids=(f"fill-open-{suffix}", f"fill-exit-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=Decimal("99"),
        initial_risk_amount=initial_risk,
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=net,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=net / initial_risk,
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="test_exit",
        health_refs=(),
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
        replay_run_id=None,
    )


def _prediction_report() -> dict[str, object]:
    return {
        "status": "collecting",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "model_family": "test-model",
        "prospective_start_ms": 1_000,
        "cadence_ms": 900_000,
        "horizon_ms": 3_600_000,
        "frozen_training_rows": 652,
        "frozen_training_rows_sha256": "a" * 64,
        "scored_rows": (
            {
                "decision_id": "decision-blocked-loser",
                "boundary_ms": 2_000,
                "market": "BTC",
                "direction": "long",
                "prediction_net_return": "-0.01",
                "admitted": False,
                "realized_net_return": "-0.02",
            },
            {
                "decision_id": "decision-blocked-winner",
                "boundary_ms": 3_000,
                "market": "BTC",
                "direction": "short",
                "prediction_net_return": "-0.01",
                "admitted": False,
                "realized_net_return": "0.03",
            },
            {
                "decision_id": "decision-admitted-winner",
                "boundary_ms": 4_000,
                "market": "BTC",
                "direction": "long",
                "prediction_net_return": "0.01",
                "admitted": True,
                "realized_net_return": "0.04",
            },
        ),
    }


def _prediction_ledger() -> dict[str, object]:
    return update_prediction_ledger(
        _prediction_report(),
        previous=None,
        source_audit_run_id=10,
        source_audit_run_attempt=1,
        source_report_artifact_name="report",
    )


def test_overlap_separates_avoided_losses_from_sacrificed_wins() -> None:
    prediction = _prediction_ledger()
    trades = (
        _trade(
            "a",
            decision_id="decision-blocked-loser",
            direction=Direction.LONG,
            net_pnl="-12",
            opened_at_ms=2_100,
        ),
        _trade(
            "b",
            decision_id="decision-blocked-winner",
            direction=Direction.SHORT,
            net_pnl="7",
            opened_at_ms=3_100,
        ),
        _trade(
            "c",
            decision_id="decision-admitted-winner",
            direction=Direction.LONG,
            net_pnl="5",
            opened_at_ms=4_100,
        ),
    )

    ledger = update_trade_overlap_ledger(
        prediction,
        trades,
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_learning_artifact_name="learning",
        source_learning_artifact_digest="sha256:" + "b" * 64,
    )

    overall = ledger["summary"]["overall"]
    assert overall["matched_closed_trades"] == 3
    assert overall["blocked_losers"] == 1
    assert overall["blocked_winners"] == 1
    assert overall["admitted_winners"] == 1
    assert overall["admitted_losers"] == 0
    assert overall["blocked_loser_pnl_avoided"] == "12"
    assert overall["blocked_winner_pnl_sacrificed"] == "7"
    assert overall["blocked_loss_minus_sacrificed_win"] == "5"
    assert overall["actual_net_pnl_sum"] == "0"
    assert overall["candidate_matched_net_pnl_sum"] == "5"
    assert overall["candidate_minus_actual_net_pnl_sum"] == "5"
    robustness = ledger["robustness"]
    assert robustness["leave_one_trade_out_min_delta"] == "-7"
    assert robustness["positive_delta_after_removing_any_one_trade"] is False
    readiness = ledger["readiness"]
    assert readiness["sample_complete"] is False
    assert readiness["ready_for_overlap_review"] is False
    assert readiness["missing_matched_closed_trades"] == 27


def test_overlap_is_append_only_when_new_trade_closes() -> None:
    prediction = _prediction_ledger()
    first_trade = _trade(
        "a",
        decision_id="decision-blocked-loser",
        direction=Direction.LONG,
        net_pnl="-12",
        opened_at_ms=2_100,
    )
    first = update_trade_overlap_ledger(
        prediction,
        (first_trade,),
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_learning_artifact_name="learning-20",
        source_learning_artifact_digest="sha256:" + "b" * 64,
    )
    second = update_trade_overlap_ledger(
        prediction,
        (
            first_trade,
            _trade(
                "c",
                decision_id="decision-admitted-winner",
                direction=Direction.LONG,
                net_pnl="5",
                opened_at_ms=4_100,
            ),
        ),
        previous=first,
        source_paper_run_id=21,
        source_paper_run_attempt=1,
        source_learning_artifact_name="learning-21",
        source_learning_artifact_digest="sha256:" + "c" * 64,
    )

    assert first["row_count"] == 1
    assert second["row_count"] == 2
    assert second["previous_row_count"] == 1
    assert second["new_row_count"] == 1
    assert second["prior_ledger_sha256"] == first["ledger_sha256"]
    validate_trade_overlap_ledger(second)


def test_overlap_fails_if_previous_trade_changes() -> None:
    prediction = _prediction_ledger()
    first = update_trade_overlap_ledger(
        prediction,
        (
            _trade(
                "a",
                decision_id="decision-blocked-loser",
                direction=Direction.LONG,
                net_pnl="-12",
                opened_at_ms=2_100,
            ),
        ),
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_learning_artifact_name="learning-20",
        source_learning_artifact_digest="sha256:" + "b" * 64,
    )

    with pytest.raises(
        ProspectiveTradeOverlapLedgerError,
        match="previous matched trade changed",
    ):
        update_trade_overlap_ledger(
            prediction,
            (
                _trade(
                    "a2",
                    decision_id="decision-blocked-loser",
                    direction=Direction.LONG,
                    net_pnl="-11",
                    opened_at_ms=2_100,
                ),
            ),
            previous=first,
            source_paper_run_id=21,
            source_paper_run_attempt=1,
            source_learning_artifact_name="learning-21",
            source_learning_artifact_digest="sha256:" + "c" * 64,
        )


def test_overlap_rejects_duplicate_trade_decision_ids() -> None:
    prediction = _prediction_ledger()
    duplicate = (
        _trade(
            "a",
            decision_id="decision-blocked-loser",
            direction=Direction.LONG,
            net_pnl="-12",
            opened_at_ms=2_100,
        ),
        _trade(
            "b",
            decision_id="decision-blocked-loser",
            direction=Direction.LONG,
            net_pnl="-4",
            opened_at_ms=2_200,
        ),
    )
    with pytest.raises(
        ProspectiveTradeOverlapLedgerError,
        match="multiple closed trades share strategy_decision_id",
    ):
        update_trade_overlap_ledger(
            prediction,
            duplicate,
            previous=None,
            source_paper_run_id=20,
            source_paper_run_attempt=1,
            source_learning_artifact_name="learning",
            source_learning_artifact_digest="sha256:" + "b" * 64,
        )



def test_overlap_review_requires_broad_profitable_robust_sample() -> None:
    scored_rows = []
    trades = []
    for index in range(30):
        direction = Direction.LONG if index % 2 == 0 else Direction.SHORT
        admitted = index >= 20
        decision_id = f"readiness-{index}"
        boundary_ms = 10_000 + index * 10_000
        scored_rows.append(
            {
                "decision_id": decision_id,
                "boundary_ms": boundary_ms,
                "market": "BTC",
                "direction": direction.value,
                "prediction_net_return": "0.01" if admitted else "-0.01",
                "admitted": admitted,
                "realized_net_return": "0.01" if admitted else "-0.01",
            }
        )
        trades.append(
            _trade(
                f"ready-{index}",
                decision_id=decision_id,
                direction=direction,
                net_pnl="1" if admitted else "-1",
                opened_at_ms=boundary_ms + 100,
            )
        )

    prediction = update_prediction_ledger(
        {
            "status": "collecting",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "model_family": "test-model",
            "prospective_start_ms": 1_000,
            "cadence_ms": 900_000,
            "horizon_ms": 3_600_000,
            "frozen_training_rows": 652,
            "frozen_training_rows_sha256": "a" * 64,
            "scored_rows": tuple(scored_rows),
        },
        previous=None,
        source_audit_run_id=10,
        source_audit_run_attempt=1,
        source_report_artifact_name="report",
    )
    ledger = update_trade_overlap_ledger(
        prediction,
        tuple(trades),
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_learning_artifact_name="learning",
        source_learning_artifact_digest="sha256:" + "b" * 64,
    )

    readiness = ledger["readiness"]
    assert readiness["sample_complete"] is True
    assert readiness["economics_positive"] is True
    assert readiness["single_trade_robust"] is True
    assert readiness["ready_for_overlap_review"] is True
    assert readiness["missing_matched_closed_trades"] == 0
    assert readiness["missing_candidate_admitted_trades"] == 0
    assert readiness["missing_candidate_blocked_trades"] == 0
    assert readiness["missing_long_matched_trades"] == 0
    assert readiness["missing_short_matched_trades"] == 0
    assert readiness["missing_long_admitted_trades"] == 0
    assert readiness["missing_short_admitted_trades"] == 0

    robustness = ledger["robustness"]
    assert robustness["total_candidate_minus_actual_net_pnl"] == "20"
    assert robustness["leave_one_trade_out_min_delta"] == "19"
    assert robustness["positive_delta_after_removing_any_one_trade"] is True



def test_overlap_accepts_legacy_ledger_without_review_diagnostics() -> None:
    prediction = _prediction_ledger()
    first_trade = _trade(
        "legacy",
        decision_id="decision-blocked-loser",
        direction=Direction.LONG,
        net_pnl="-12",
        opened_at_ms=2_100,
    )
    current = update_trade_overlap_ledger(
        prediction,
        (first_trade,),
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_learning_artifact_name="learning-20",
        source_learning_artifact_digest="sha256:" + "b" * 64,
    )
    legacy = dict(current)
    legacy.pop("readiness")
    legacy.pop("robustness")
    digest_payload = {
        key: value
        for key, value in legacy.items()
        if key != "ledger_sha256"
    }
    legacy["ledger_sha256"] = hashlib.sha256(
        json.dumps(
            digest_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    validated = validate_trade_overlap_ledger(legacy)
    assert validated["row_count"] == 1
    extended = update_trade_overlap_ledger(
        prediction,
        (first_trade,),
        previous=legacy,
        source_paper_run_id=21,
        source_paper_run_attempt=1,
        source_learning_artifact_name="learning-21",
        source_learning_artifact_digest="sha256:" + "c" * 64,
    )
    assert extended["prior_ledger_sha256"] == legacy["ledger_sha256"]
    assert "readiness" in extended
    assert "robustness" in extended
