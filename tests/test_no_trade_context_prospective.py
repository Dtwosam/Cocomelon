from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.research.no_trade_context_candidate import (
    verify_no_trade_context_candidate_freeze,
)
from cocomelon.research.no_trade_context_prospective import (
    build_no_trade_context_prospective_report,
)

SOURCE = Path(
    "research/no_trade_context_candidates/"
    "mon-normal-short-1h-v1-source.json"
)
FREEZE = Path(
    "research/no_trade_context_candidates/"
    "mon-normal-short-1h-v1.json"
)


def _outcome(
    *,
    timestamp_ms: int,
    value: str,
    market: str = "MON",
    volatility: str = "normal",
    stage: str = "strategy_abstained",
) -> dict[str, object]:
    numeric = Decimal(value)
    direction = "long" if numeric > 0 else "short" if numeric < 0 else "no_trade"
    return {
        "decision_fact_id": f"fact-{timestamp_ms}-{market}",
        "strategy_decision_id": f"decision-{timestamp_ms}-{market}",
        "market": market,
        "decision_timestamp_ms": timestamp_ms,
        "feature_snapshot_id": f"feature-{timestamp_ms}-{market}",
        "feature_as_of_ms": timestamp_ms,
        "horizon_ms": 3_600_000,
        "target_as_of_ms": timestamp_ms + 3_600_000,
        "forward_mark_return": value,
        "favored_direction": direction,
        "reason_codes": ["no_primary_thesis"],
        "decision_stage": stage,
        "trend_regime": "mixed",
        "volatility_regime": volatility,
        "return_15m_sign": "negative",
        "return_1h_sign": "negative",
        "funding_sign": "positive",
        "book_imbalance_sign": "negative",
    }


def _forward_report(
    outcomes: list[dict[str, object]],
    *,
    as_of_ms: int,
) -> dict[str, object]:
    return {
        "as_of_ms": as_of_ms,
        "decision_state_digest": "e" * 64,
        "feature_state_digest": "f" * 64,
        "diagnostic_only": True,
        "hypothetical_pnl": False,
        "execution_authority": False,
        "schema_version": 2,
        "outcomes": outcomes,
    }


def test_prospective_score_uses_only_post_freeze_matching_abstentions() -> None:
    freeze = verify_no_trade_context_candidate_freeze(
        FREEZE,
        selection_record_path=SOURCE,
    )
    start = freeze.prospective_not_before_ms
    outcomes = [
        _outcome(timestamp_ms=start - 1, value="-0.02"),
        _outcome(timestamp_ms=start + 1, value="-0.01"),
        _outcome(timestamp_ms=start + 2, value="-0.007"),
        _outcome(timestamp_ms=start + 3, value="0.008"),
        _outcome(timestamp_ms=start + 4, value="-0.002"),
        _outcome(
            timestamp_ms=start + 5,
            value="-0.02",
            market="PUMP",
        ),
        _outcome(
            timestamp_ms=start + 6,
            value="-0.02",
            volatility="high",
        ),
        _outcome(
            timestamp_ms=start + 7,
            value="-0.02",
            stage="eligibility_blocked",
        ),
    ]

    report = build_no_trade_context_prospective_report(
        _forward_report(
            outcomes,
            as_of_ms=start + freeze.horizon_ms + 10,
        ),
        freeze,
    )
    payload = report.to_dict()

    assert payload["candidate_id"] == freeze.candidate_id
    assert payload["prospective_label_window_open"] is True
    assert payload["matching_outcomes"] == 4
    assert payload["material_outcomes"] == 3
    assert payload["same_direction_material_outcomes"] == 2
    assert payload["opposite_direction_material_outcomes"] == 1
    assert payload["material_same_direction_share"] == (
        "0.6666666666666666666666666667"
    )
    assert Decimal(str(payload["mean_directional_markout_return"])) > 0
    assert payload["hypothetical_pnl"] is False
    assert payload["cost_complete"] is False
    assert payload["execution_authority"] is False
    assert payload["ready_for_review"] is False


def test_prospective_score_is_empty_before_frozen_boundary() -> None:
    freeze = verify_no_trade_context_candidate_freeze(
        FREEZE,
        selection_record_path=SOURCE,
    )
    report = build_no_trade_context_prospective_report(
        _forward_report(
            [
                _outcome(
                    timestamp_ms=freeze.prospective_not_before_ms - 1,
                    value="-0.02",
                )
            ],
            as_of_ms=freeze.prospective_not_before_ms - 1,
        ),
        freeze,
    )
    payload = report.to_dict()

    assert payload["prospective_label_window_open"] is False
    assert payload["matching_outcomes"] == 0
    assert payload["material_outcomes"] == 0
    assert payload["material_same_direction_share"] is None
    assert payload["ready_for_review"] is False



def _review_gate_report(
    freeze,
    *,
    middle_same_direction: int,
) -> dict[str, object]:
    outcomes: list[dict[str, object]] = []
    timestamp = freeze.prospective_not_before_ms
    same_counts = (8, middle_same_direction, 8)

    for same_count in same_counts:
        for index in range(10):
            outcomes.append(
                _outcome(
                    timestamp_ms=timestamp,
                    value="-0.01" if index < same_count else "0.01",
                )
            )
            timestamp += 1
        timestamp += 1_000

    return _forward_report(
        outcomes,
        as_of_ms=timestamp + freeze.horizon_ms,
    )


def test_prospective_review_gate_rejects_one_flipped_future_block() -> None:
    freeze = verify_no_trade_context_candidate_freeze(
        FREEZE,
        selection_record_path=SOURCE,
    )

    report = build_no_trade_context_prospective_report(
        _review_gate_report(
            freeze,
            middle_same_direction=3,
        ),
        freeze,
    )
    payload = report.to_dict()

    assert payload["material_outcomes"] == 30
    assert payload["material_same_direction_share"] == (
        "0.6333333333333333333333333333"
    )
    assert payload["prospective_block_outcomes"] == (10, 10, 10)
    assert payload["prospective_block_same_direction_shares"] == (
        "0.8",
        "0.3",
        "0.8",
    )
    assert payload["prospective_blocks_meeting_row_floor"] == 3
    assert payload["prospective_blocks_directionally_consistent"] == 2
    assert payload["ready_for_review"] is False


def test_prospective_review_gate_opens_only_after_consistent_future_evidence() -> None:
    freeze = verify_no_trade_context_candidate_freeze(
        FREEZE,
        selection_record_path=SOURCE,
    )

    report = build_no_trade_context_prospective_report(
        _review_gate_report(
            freeze,
            middle_same_direction=7,
        ),
        freeze,
    )
    payload = report.to_dict()

    assert payload["material_outcomes"] == 30
    assert payload["material_same_direction_share"] == (
        "0.7666666666666666666666666667"
    )
    assert payload["prospective_block_outcomes"] == (10, 10, 10)
    assert payload["prospective_block_same_direction_shares"] == (
        "0.8",
        "0.7",
        "0.8",
    )
    assert payload["prospective_blocks_meeting_row_floor"] == 3
    assert payload["prospective_blocks_directionally_consistent"] == 3
    assert payload["ready_for_review"] is True
    assert payload["promotion_authority"] is False
    assert payload["execution_authority"] is False
