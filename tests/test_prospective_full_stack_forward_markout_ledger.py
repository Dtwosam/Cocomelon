from __future__ import annotations

from copy import deepcopy

import pytest

from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.research.prospective_full_stack_forward_markout_ledger import (
    ProspectiveFullStackForwardMarkoutLedgerError,
    update_full_stack_forward_markout_ledger,
    validate_full_stack_forward_markout_ledger,
)
from cocomelon.research.prospective_momentum_band_entry import (
    EMBARGO_MS,
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_momentum_band_forward_markout import (
    FORWARD_HORIZONS_MS,
    MAX_MARK_LAG_MS,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
)


def _digest(char: str) -> str:
    return "sha256:" + char * 64


def _states() -> tuple[
    ProspectiveCombinedEntryFilterState,
    ProspectiveTwoStrikeStopFilterState,
    ProspectiveMomentumBandEntryState,
]:
    frozen = 1_000_000
    started = frozen + EMBARGO_MS
    return (
        ProspectiveCombinedEntryFilterState(started_at_ms=started),
        ProspectiveTwoStrikeStopFilterState(frozen_at_ms=frozen),
        ProspectiveMomentumBandEntryState(frozen_at_ms=frozen),
    )


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
    combined, _two_strike, _momentum = _states()
    timestamp = combined.started_at_ms + 100_000 + suffix
    blocked = decision == "BLOCK"
    return {
        "opportunity_id": f"opportunity-{suffix}",
        "timestamp_ms": timestamp,
        "market": market,
        "direction": direction,
        "lead_strategy": "breakout",
        "rank_ordinal": 3,
        "rank_age_ms": 100,
        "combined_block_reason": None,
        "two_strike_prior_strikes": 0,
        "momentum_decision": decision,
        "momentum_reason": (
            "momentum_band" if blocked else "momentum_band_pass"
        ),
        "momentum_prior_strikes": 0,
        "signed_return_1h": "0.005" if blocked else "0.03",
        "signed_day_return": "0.05",
        "stack_decision": decision,
        "block_layer": "momentum" if blocked else "none",
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
    rows: list[dict[str, object]],
    *,
    integrity_clean: bool = True,
) -> dict[str, object]:
    combined, two_strike, momentum = _states()
    overlap = max(
        combined.started_at_ms,
        two_strike.started_at_ms,
        momentum.started_at_ms,
    )
    return {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "candidate_stack": "combined+two_strike+momentum",
        "overlap_started_at_ms": overlap,
        "combined_started_at_ms": combined.started_at_ms,
        "two_strike_started_at_ms": two_strike.started_at_ms,
        "momentum_started_at_ms": momentum.started_at_ms,
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "prospective_opportunities": len(rows),
        "baseline_risk_rejected": 0,
        "missing_rank": 0 if integrity_clean else 1,
        "stale_rank": 0,
        "momentum_feature_integrity_misses": 0,
        "stack_risk_approved_evaluated": len(rows),
        "stack_admitted": sum(
            row["stack_decision"] == "ADMIT" for row in rows
        ),
        "stack_blocked": sum(
            row["stack_decision"] == "BLOCK" for row in rows
        ),
        "block_layer_counts": {},
        "integrity_clean": integrity_clean,
        "horizons": {},
        "rows": rows,
    }


def _update(
    source: object,
    *,
    previous: dict[str, object] | None = None,
    run_id: int = 10,
    digest: str = "a",
) -> dict[str, object]:
    combined, two_strike, momentum = _states()
    return update_full_stack_forward_markout_ledger(
        source,
        combined,
        two_strike,
        momentum,
        previous=previous,
        source_paper_run_id=run_id,
        source_paper_run_attempt=1,
        source_artifact_name=f"learning-{run_id}-1",
        source_artifact_digest=_digest(digest),
    )


def test_full_stack_fast_ledger_waits_for_all_horizons() -> None:
    pending = _row(
        1,
        statuses=("settled", "settled", "pending"),
    )
    first = _update(_summary([pending]))

    assert first["row_count"] == 0
    assert first["pending_opportunity_count"] == 1

    settled = _row(1)
    second = _update(
        _summary([settled]),
        previous=first,
        run_id=11,
        digest="b",
    )
    assert second["previous_row_count"] == 0
    assert second["new_row_count"] == 1
    assert second["row_count"] == 1
    assert second["pending_opportunity_count"] == 0
    validate_full_stack_forward_markout_ledger(second)


def test_full_stack_fast_ledger_treats_stale_as_terminal() -> None:
    row = _row(
        1,
        statuses=("settled", "stale", "settled"),
    )
    ledger = _update(_summary([row]))
    assert ledger["row_count"] == 1
    summary = ledger["summary"]
    assert isinstance(summary, dict)
    horizons = summary["horizons"]
    assert isinstance(horizons, dict)
    middle = horizons[str(FORWARD_HORIZONS_MS[1])]
    assert middle["settled_opportunities"] == 0
    assert middle["stale_opportunities"] == 1


def test_full_stack_fast_ledger_rejects_changed_terminal_row() -> None:
    row = _row(1)
    first = _update(_summary([row]))
    changed = deepcopy(row)
    markouts = changed["markouts"]
    assert isinstance(markouts, dict)
    one_hour = markouts[str(FORWARD_HORIZONS_MS[-1])]
    assert isinstance(one_hour, dict)
    one_hour["directional_return"] = "0.50"

    with pytest.raises(
        ProspectiveFullStackForwardMarkoutLedgerError,
        match="previous terminal full-stack markout row changed",
    ):
        _update(
            _summary([changed]),
            previous=first,
            run_id=11,
            digest="b",
        )


def test_full_stack_fast_ledger_is_idempotent_for_same_source() -> None:
    source = _summary([_row(1)])
    first = _update(source)
    repeated = _update(source, previous=first)

    assert repeated == validate_full_stack_forward_markout_ledger(first)


def test_full_stack_fast_ledger_rejects_layer_tamper() -> None:
    row = _row(1, decision="ADMIT")
    row["stack_decision"] = "BLOCK"
    row["block_layer"] = "two_strike"

    with pytest.raises(
        ProspectiveFullStackForwardMarkoutLedgerError,
        match="stack decision does not match frozen layer ordering",
    ):
        _update(_summary([row]))


def test_full_stack_fast_ledger_review_bar_can_pass() -> None:
    markets = ("BTC", "ETH", "SOL", "ENA")
    rows = [
        _row(
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
    ledger = _update(_summary(rows))
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
        assert item["market_count"] == 4
        assert readiness["sample_complete"] is True
        assert readiness["separation_positive"] is True
        assert readiness["single_opportunity_robust"] is True
        assert readiness["single_market_robust"] is True
        assert readiness["ready_for_early_evidence_review"] is True
        assert readiness["changes_closed_trade_readiness_gate"] is False


def test_full_stack_fast_ledger_integrity_miss_blocks_review() -> None:
    markets = ("BTC", "ETH", "SOL", "ENA")
    rows = [
        _row(
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
    ledger = _update(_summary(rows, integrity_clean=False))
    summary = ledger["summary"]
    assert isinstance(summary, dict)
    horizons = summary["horizons"]
    one_hour = horizons[str(FORWARD_HORIZONS_MS[-1])]
    readiness = one_hour["review_readiness"]
    assert readiness["sample_complete"] is True
    assert readiness["separation_positive"] is True
    assert readiness["ready_for_early_evidence_review"] is False
