from __future__ import annotations

from copy import deepcopy

import pytest

from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_momentum_band_forward_markout import (
    FORWARD_HORIZONS_MS,
    MAX_MARK_LAG_MS,
)
from cocomelon.research.prospective_momentum_band_forward_markout_ledger import (
    ProspectiveMomentumBandForwardMarkoutLedgerError,
    update_momentum_forward_markout_ledger,
    validate_momentum_forward_markout_ledger,
)


def _digest(char: str) -> str:
    return "sha256:" + char * 64


def _markout(
    timestamp_ms: int,
    horizon_ms: int,
    *,
    status: str = "settled",
    directional_return: str = "0.01",
) -> dict[str, object]:
    target = timestamp_ms + horizon_ms
    if status in {"pending", "missing_path"}:
        return {
            "status": status,
            "target_at_ms": target,
            "observed_at_ms": None,
            "observation_lag_ms": None,
            "mark_px": None,
            "directional_return": None,
        }
    if status == "stale":
        lag = MAX_MARK_LAG_MS + 1
        return {
            "status": "stale",
            "target_at_ms": target,
            "observed_at_ms": target + lag,
            "observation_lag_ms": lag,
            "mark_px": "101",
            "directional_return": None,
        }
    return {
        "status": "settled",
        "target_at_ms": target,
        "observed_at_ms": target + 1_000,
        "observation_lag_ms": 1_000,
        "mark_px": "101",
        "directional_return": directional_return,
    }


def _row(
    state: ProspectiveMomentumBandEntryState,
    suffix: int,
    *,
    decision: str = "ADMIT",
    direction: str = "long",
    market: str = "SOL",
    statuses: tuple[str, str, str] = (
        "settled",
        "settled",
        "settled",
    ),
    returns: tuple[str, str, str] = ("0.01", "0.02", "0.03"),
) -> dict[str, object]:
    timestamp = state.started_at_ms + 100_000 + suffix
    reason = "momentum_band_pass" if decision == "ADMIT" else "momentum_band"
    return {
        "opportunity_id": f"opportunity-{suffix}",
        "timestamp_ms": timestamp,
        "market": market,
        "direction": direction,
        "lead_strategy": "breakout",
        "rank_ordinal": 3,
        "rank_age_ms": 100,
        "two_strike_prior_strikes": 0,
        "momentum_decision": decision,
        "momentum_reason": reason,
        "momentum_prior_strikes": 0,
        "signed_return_1h": "0.03",
        "signed_day_return": "0.05",
        "markouts": {
            str(horizon_ms): _markout(
                timestamp,
                horizon_ms,
                status=statuses[index],
                directional_return=returns[index],
            )
            for index, horizon_ms in enumerate(FORWARD_HORIZONS_MS)
        },
    }


def _summary(
    state: ProspectiveMomentumBandEntryState,
    rows: list[dict[str, object]],
    *,
    integrity_clean: bool = True,
) -> dict[str, object]:
    return {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "candidate_id": state.candidate_id,
        "overlap_started_at_ms": state.started_at_ms,
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "prospective_opportunities": len(rows),
        "baseline_risk_rejected": 0,
        "missing_rank": 0 if integrity_clean else 1,
        "stale_rank": 0,
        "base_combined_blocked": 0,
        "base_two_strike_blocked": 0,
        "momentum_feature_integrity_misses": 0,
        "base_stack_risk_approved_evaluated": len(rows),
        "momentum_admitted": sum(
            row["momentum_decision"] == "ADMIT" for row in rows
        ),
        "momentum_blocked": sum(
            row["momentum_decision"] == "BLOCK" for row in rows
        ),
        "momentum_reason_counts": {},
        "integrity_clean": integrity_clean,
        "horizons": {},
        "rows": rows,
    }


def test_fast_markout_ledger_waits_for_all_horizons() -> None:
    state = ProspectiveMomentumBandEntryState(frozen_at_ms=1_000_000)
    pending = _row(
        state,
        1,
        statuses=("settled", "settled", "pending"),
    )
    first = update_momentum_forward_markout_ledger(
        _summary(state, [pending]),
        state,
        previous=None,
        source_paper_run_id=10,
        source_paper_run_attempt=1,
        source_artifact_name="learning-10-1",
        source_artifact_digest=_digest("a"),
    )
    assert first["row_count"] == 0
    assert first["pending_opportunity_count"] == 1

    settled = _row(state, 1)
    second = update_momentum_forward_markout_ledger(
        _summary(state, [settled]),
        state,
        previous=first,
        source_paper_run_id=11,
        source_paper_run_attempt=1,
        source_artifact_name="learning-11-1",
        source_artifact_digest=_digest("b"),
    )
    assert second["previous_row_count"] == 0
    assert second["new_row_count"] == 1
    assert second["row_count"] == 1
    assert second["pending_opportunity_count"] == 0
    validate_momentum_forward_markout_ledger(second)


def test_fast_markout_ledger_treats_stale_as_terminal() -> None:
    state = ProspectiveMomentumBandEntryState(frozen_at_ms=2_000_000)
    row = _row(
        state,
        1,
        statuses=("settled", "stale", "settled"),
    )
    ledger = update_momentum_forward_markout_ledger(
        _summary(state, [row]),
        state,
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_artifact_name="learning-20-1",
        source_artifact_digest=_digest("c"),
    )
    assert ledger["row_count"] == 1
    summary = ledger["summary"]
    assert isinstance(summary, dict)
    horizons = summary["horizons"]
    assert isinstance(horizons, dict)
    middle = horizons[str(FORWARD_HORIZONS_MS[1])]
    assert middle["settled_opportunities"] == 0
    assert middle["stale_opportunities"] == 1


def test_fast_markout_ledger_rejects_changed_terminal_row() -> None:
    state = ProspectiveMomentumBandEntryState(frozen_at_ms=3_000_000)
    row = _row(state, 1)
    first = update_momentum_forward_markout_ledger(
        _summary(state, [row]),
        state,
        previous=None,
        source_paper_run_id=30,
        source_paper_run_attempt=1,
        source_artifact_name="learning-30-1",
        source_artifact_digest=_digest("d"),
    )
    changed = deepcopy(row)
    markouts = changed["markouts"]
    assert isinstance(markouts, dict)
    one_hour = markouts[str(FORWARD_HORIZONS_MS[-1])]
    assert isinstance(one_hour, dict)
    one_hour["directional_return"] = "0.50"

    with pytest.raises(
        ProspectiveMomentumBandForwardMarkoutLedgerError,
        match="previous terminal momentum markout row changed",
    ):
        update_momentum_forward_markout_ledger(
            _summary(state, [changed]),
            state,
            previous=first,
            source_paper_run_id=31,
            source_paper_run_attempt=1,
            source_artifact_name="learning-31-1",
            source_artifact_digest=_digest("e"),
        )


def test_fast_markout_ledger_rejects_overlap_drift() -> None:
    state = ProspectiveMomentumBandEntryState(frozen_at_ms=4_000_000)
    row = _row(state, 1)
    first = update_momentum_forward_markout_ledger(
        _summary(state, [row]),
        state,
        previous=None,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_artifact_name="learning-40-1",
        source_artifact_digest=_digest("f"),
    )
    shifted = _summary(state, [row])
    shifted["overlap_started_at_ms"] = state.started_at_ms + 1

    with pytest.raises(
        ProspectiveMomentumBandForwardMarkoutLedgerError,
        match="metadata drift: overlap_started_at_ms",
    ):
        update_momentum_forward_markout_ledger(
            shifted,
            state,
            previous=first,
            source_paper_run_id=41,
            source_paper_run_attempt=1,
            source_artifact_name="learning-41-1",
            source_artifact_digest=_digest("1"),
        )


def test_fast_markout_ledger_is_idempotent_for_same_source() -> None:
    state = ProspectiveMomentumBandEntryState(frozen_at_ms=5_000_000)
    row = _row(state, 1)
    source = _summary(state, [row])
    first = update_momentum_forward_markout_ledger(
        source,
        state,
        previous=None,
        source_paper_run_id=50,
        source_paper_run_attempt=1,
        source_artifact_name="learning-50-1",
        source_artifact_digest=_digest("2"),
    )
    repeated = update_momentum_forward_markout_ledger(
        source,
        state,
        previous=first,
        source_paper_run_id=50,
        source_paper_run_attempt=1,
        source_artifact_name="learning-50-1",
        source_artifact_digest=_digest("2"),
    )
    assert repeated == validate_momentum_forward_markout_ledger(first)


def test_fast_markout_ledger_integrity_miss_blocks_early_review() -> None:
    state = ProspectiveMomentumBandEntryState(frozen_at_ms=6_000_000)
    markets = ("BTC", "ETH", "SOL", "ENA")
    rows = [
        _row(
            state,
            index,
            decision="ADMIT" if index % 2 == 0 else "BLOCK",
            direction="long" if index % 4 < 2 else "short",
            market=markets[index % len(markets)],
            returns=(
                "0.01" if index % 2 == 0 else "-0.01",
                "0.02" if index % 2 == 0 else "-0.02",
                "0.03" if index % 2 == 0 else "-0.03",
            ),
        )
        for index in range(20)
    ]
    ledger = update_momentum_forward_markout_ledger(
        _summary(state, rows, integrity_clean=False),
        state,
        previous=None,
        source_paper_run_id=60,
        source_paper_run_attempt=1,
        source_artifact_name="learning-60-1",
        source_artifact_digest=_digest("3"),
    )
    summary = ledger["summary"]
    assert isinstance(summary, dict)
    assert summary["integrity_clean"] is False
    horizons = summary["horizons"]
    assert isinstance(horizons, dict)
    one_hour = horizons[str(FORWARD_HORIZONS_MS[-1])]
    readiness = one_hour["review_readiness"]
    assert readiness["sample_complete"] is True
    assert readiness["separation_positive"] is True
    assert readiness["single_opportunity_robust"] is True
    assert readiness["single_market_robust"] is True
    assert readiness["ready_for_early_evidence_review"] is False


def test_fast_markout_ledger_review_bar_can_pass() -> None:
    state = ProspectiveMomentumBandEntryState(frozen_at_ms=7_000_000)
    markets = ("BTC", "ETH", "SOL", "ENA")
    rows = [
        _row(
            state,
            index,
            decision="ADMIT" if index % 2 == 0 else "BLOCK",
            direction="long" if index % 4 < 2 else "short",
            market=markets[index % len(markets)],
            returns=(
                "0.01" if index % 2 == 0 else "-0.01",
                "0.02" if index % 2 == 0 else "-0.02",
                "0.03" if index % 2 == 0 else "-0.03",
            ),
        )
        for index in range(20)
    ]
    ledger = update_momentum_forward_markout_ledger(
        _summary(state, rows),
        state,
        previous=None,
        source_paper_run_id=70,
        source_paper_run_attempt=1,
        source_artifact_name="learning-70-1",
        source_artifact_digest=_digest("4"),
    )
    summary = ledger["summary"]
    assert isinstance(summary, dict)
    horizons = summary["horizons"]
    assert isinstance(horizons, dict)
    for horizon_ms in FORWARD_HORIZONS_MS:
        item = horizons[str(horizon_ms)]
        readiness = item["review_readiness"]
        assert item["settled_opportunities"] == 20
        assert item["admit_settled"] == 10
        assert item["block_settled"] == 10
        assert item["long_settled"] == 10
        assert item["short_settled"] == 10
        assert item["market_count"] == 4
        assert readiness["sample_complete"] is True
        assert readiness["separation_positive"] is True
        assert readiness["single_opportunity_robust"] is True
        assert readiness["single_market_robust"] is True
        assert readiness["ready_for_early_evidence_review"] is True
        assert readiness["changes_closed_trade_readiness_gate"] is False
