from __future__ import annotations

from copy import deepcopy

import pytest

from cocomelon.research.prospective_consecutive_loss_cooldown_ledger import (
    ProspectiveConsecutiveLossCooldownLedgerError,
    update_cooldown_ledger,
    validate_cooldown_ledger,
)
from cocomelon.research.prospective_consecutive_loss_cooldown_shadow import (
    EMBARGO_MS,
    FORWARD_HORIZONS_MS,
    ProspectiveConsecutiveLossCooldownShadowState,
)


def _digest(char: str) -> str:
    return "sha256:" + char * 64


def _markout(
    *,
    horizon_ms: int,
    status: str,
    timestamp_ms: int,
    pnl: str = "2",
) -> dict[str, object]:
    target = timestamp_ms + horizon_ms
    if status in {"pending", "missing_path"}:
        return {
            "status": status,
            "horizon_ms": horizon_ms,
            "target_at_ms": target,
            "observed_at_ms": None,
            "observation_lag_ms": None,
            "mark_px": None,
            "directional_return_fraction": None,
            "gross_mark_to_market_pnl": None,
            "entry_fee_adjusted_mark_to_market_pnl": None,
        }
    if status == "stale":
        return {
            "status": "stale",
            "horizon_ms": horizon_ms,
            "target_at_ms": target,
            "observed_at_ms": target + 180_000,
            "observation_lag_ms": 180_000,
            "mark_px": "101",
            "directional_return_fraction": None,
            "gross_mark_to_market_pnl": None,
            "entry_fee_adjusted_mark_to_market_pnl": None,
        }
    return {
        "status": "settled",
        "horizon_ms": horizon_ms,
        "target_at_ms": target,
        "observed_at_ms": target + 30_000,
        "observation_lag_ms": 30_000,
        "mark_px": "101",
        "directional_return_fraction": "0.01",
        "gross_mark_to_market_pnl": "2.5",
        "entry_fee_adjusted_mark_to_market_pnl": pnl,
    }


def _filled_option(
    state: ProspectiveConsecutiveLossCooldownShadowState,
    suffix: str,
    *,
    direction: str = "long",
    elapsed_ms: int = 2_000_000,
    statuses: tuple[str, str, str] = (
        "settled",
        "settled",
        "settled",
    ),
    one_hour_pnl: str = "2",
) -> dict[str, object]:
    timestamp = state.started_at_ms + 100_000 + int(suffix)
    markouts = {}
    for index, horizon_ms in enumerate(FORWARD_HORIZONS_MS):
        pnl = one_hour_pnl if index == 2 else "1"
        markouts[str(horizon_ms)] = _markout(
            horizon_ms=horizon_ms,
            status=statuses[index],
            timestamp_ms=timestamp,
            pnl=pnl,
        )
    return {
        "opportunity_id": f"option-{suffix}",
        "timestamp_ms": timestamp,
        "market": "SOL" if suffix != "2" else "ETH",
        "direction": direction,
        "lead_strategy": "breakout",
        "rank_ordinal": 3,
        "baseline_consecutive_losses": 3,
        "baseline_elapsed_since_last_close_ms": elapsed_ms,
        "baseline_cooldown_ms": 3_600_000,
        "elapsed_bucket": (
            "0-15m"
            if elapsed_ms < 900_000
            else (
                "15-30m"
                if elapsed_ms < 1_800_000
                else (
                    "30-45m"
                    if elapsed_ms < 2_700_000
                    else "45m+"
                )
            )
        ),
        "counterfactual_risk_approved": True,
        "counterfactual_risk_reason_codes": [],
        "planning_approved": True,
        "planning_rejection": None,
        "execution_result": "filled",
        "filled_quantity": "2",
        "average_fill_price": "100",
        "entry_fee": "0.5",
        "markouts": markouts,
    }


def _risk_rejected_option(
    state: ProspectiveConsecutiveLossCooldownShadowState,
    suffix: str,
) -> dict[str, object]:
    return {
        "opportunity_id": f"risk-{suffix}",
        "timestamp_ms": state.started_at_ms + 200_000 + int(suffix),
        "market": "BTC",
        "direction": "short",
        "lead_strategy": "trend",
        "rank_ordinal": 5,
        "baseline_consecutive_losses": 4,
        "baseline_elapsed_since_last_close_ms": 1_000_000,
        "baseline_cooldown_ms": 3_600_000,
        "elapsed_bucket": "15-30m",
        "counterfactual_risk_approved": False,
        "counterfactual_risk_reason_codes": ["aggregate_risk_limit"],
        "planning_approved": False,
        "planning_rejection": None,
        "execution_result": None,
        "filled_quantity": None,
        "average_fill_price": None,
        "entry_fee": None,
        "markouts": {},
    }


def _summary(
    state: ProspectiveConsecutiveLossCooldownShadowState,
    options: list[dict[str, object]],
) -> dict[str, object]:
    return {
        **state.payload(),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_risk_limits": False,
        "option_results": options,
    }


def test_cooldown_ledger_appends_only_terminal_rows() -> None:
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=1_000_000
    )
    pending = _filled_option(
        state,
        "1",
        statuses=("settled", "settled", "pending"),
    )
    rejected = _risk_rejected_option(state, "1")
    first = update_cooldown_ledger(
        _summary(state, [pending, rejected]),
        state,
        previous=None,
        source_paper_run_id=10,
        source_paper_run_attempt=1,
        source_artifact_name="learning-10-1",
        source_artifact_digest=_digest("a"),
    )

    assert first["row_count"] == 1
    assert first["new_row_count"] == 1
    assert first["pending_option_count"] == 1
    rows = first["rows"]
    assert isinstance(rows, tuple)
    assert rows[0]["opportunity_id"] == "risk-1"

    settled = _filled_option(state, "1", one_hour_pnl="4")
    second = update_cooldown_ledger(
        _summary(state, [settled, rejected]),
        state,
        previous=first,
        source_paper_run_id=11,
        source_paper_run_attempt=1,
        source_artifact_name="learning-11-1",
        source_artifact_digest=_digest("b"),
    )

    assert second["previous_row_count"] == 1
    assert second["new_row_count"] == 1
    assert second["row_count"] == 2
    assert second["pending_option_count"] == 0
    assert second["prior_ledger_sha256"] == first["ledger_sha256"]
    second_rows = second["rows"]
    assert isinstance(second_rows, tuple)
    assert second_rows[0] == rows[0]
    validate_cooldown_ledger(second)


def test_cooldown_ledger_keeps_missing_paths_pending() -> None:
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=2_000_000
    )
    missing = _filled_option(
        state,
        "1",
        statuses=("settled", "settled", "missing_path"),
    )
    ledger = update_cooldown_ledger(
        _summary(state, [missing]),
        state,
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_artifact_name="learning-20-1",
        source_artifact_digest=_digest("c"),
    )

    assert ledger["row_count"] == 0
    assert ledger["pending_option_count"] == 1


def test_cooldown_ledger_rejects_changed_terminal_row() -> None:
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=3_000_000
    )
    option = _filled_option(state, "1", one_hour_pnl="3")
    first = update_cooldown_ledger(
        _summary(state, [option]),
        state,
        previous=None,
        source_paper_run_id=30,
        source_paper_run_attempt=1,
        source_artifact_name="learning-30-1",
        source_artifact_digest=_digest("d"),
    )
    changed = deepcopy(option)
    markouts = changed["markouts"]
    assert isinstance(markouts, dict)
    one_hour = markouts[str(60 * 60 * 1_000)]
    assert isinstance(one_hour, dict)
    one_hour["entry_fee_adjusted_mark_to_market_pnl"] = "9"

    with pytest.raises(
        ProspectiveConsecutiveLossCooldownLedgerError,
        match="previous terminal cooldown row changed",
    ):
        update_cooldown_ledger(
            _summary(state, [changed]),
            state,
            previous=first,
            source_paper_run_id=31,
            source_paper_run_attempt=1,
            source_artifact_name="learning-31-1",
            source_artifact_digest=_digest("e"),
        )


def test_cooldown_ledger_rejects_freeze_drift() -> None:
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=4_000_000
    )
    option = _risk_rejected_option(state, "1")
    first = update_cooldown_ledger(
        _summary(state, [option]),
        state,
        previous=None,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_artifact_name="learning-40-1",
        source_artifact_digest=_digest("f"),
    )
    shifted = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=state.frozen_at_ms + 1
    )

    with pytest.raises(
        ProspectiveConsecutiveLossCooldownLedgerError,
        match="metadata drift: frozen_at_ms",
    ):
        update_cooldown_ledger(
            _summary(shifted, []),
            shifted,
            previous=first,
            source_paper_run_id=41,
            source_paper_run_attempt=1,
            source_artifact_name="learning-41-1",
            source_artifact_digest=_digest("1"),
        )


def test_cooldown_ledger_is_idempotent_for_same_source() -> None:
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=5_000_000
    )
    option = _risk_rejected_option(state, "1")
    source = _summary(state, [option])
    first = update_cooldown_ledger(
        source,
        state,
        previous=None,
        source_paper_run_id=50,
        source_paper_run_attempt=1,
        source_artifact_name="learning-50-1",
        source_artifact_digest=_digest("2"),
    )
    repeated = update_cooldown_ledger(
        source,
        state,
        previous=first,
        source_paper_run_id=50,
        source_paper_run_attempt=1,
        source_artifact_name="learning-50-1",
        source_artifact_digest=_digest("2"),
    )

    assert repeated == validate_cooldown_ledger(first)


def test_cooldown_ledger_rejects_duplicate_source_drift() -> None:
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=6_000_000
    )
    option = _risk_rejected_option(state, "1")
    source = _summary(state, [option])
    first = update_cooldown_ledger(
        source,
        state,
        previous=None,
        source_paper_run_id=60,
        source_paper_run_attempt=1,
        source_artifact_name="learning-60-1",
        source_artifact_digest=_digest("3"),
    )

    with pytest.raises(
        ProspectiveConsecutiveLossCooldownLedgerError,
        match="duplicate cooldown source artifact drift",
    ):
        update_cooldown_ledger(
            source,
            state,
            previous=first,
            source_paper_run_id=60,
            source_paper_run_attempt=1,
            source_artifact_name="learning-60-1",
            source_artifact_digest=_digest("4"),
        )


def test_cooldown_ledger_summarizes_fixed_windows_robustly() -> None:
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=7_000_000
    )
    first = _filled_option(
        state,
        "1",
        elapsed_ms=2_000_000,
        one_hour_pnl="5",
    )
    second = _filled_option(
        state,
        "2",
        direction="short",
        elapsed_ms=3_000_000,
        one_hour_pnl="3",
    )
    ledger = update_cooldown_ledger(
        _summary(state, [first, second]),
        state,
        previous=None,
        source_paper_run_id=70,
        source_paper_run_attempt=1,
        source_artifact_name="learning-70-1",
        source_artifact_digest=_digest("5"),
    )

    summary = ledger["summary"]
    assert isinstance(summary, dict)
    windows = summary["relaxation_windows"]
    assert isinstance(windows, dict)

    fifteen = windows[str(15 * 60 * 1_000)]
    assert fifteen["terminal_options"] == 2
    assert fifteen["filled_options"] == 2
    robustness = fifteen["robustness"]
    assert isinstance(robustness, dict)
    assert robustness["settled_options"] == 2
    assert robustness["total_entry_fee_adjusted_1h_pnl"] == "8"
    assert robustness["leave_one_option_out_min_pnl"] == "3"
    assert robustness["positive_after_removing_any_one_option"] is True
    assert robustness["market_count"] == 2
    assert robustness["leave_one_market_out_min_pnl"] == "3"
    assert robustness["positive_after_removing_any_one_market"] is True

    thirty = windows[str(30 * 60 * 1_000)]
    assert thirty["terminal_options"] == 2
    forty_five = windows[str(45 * 60 * 1_000)]
    assert forty_five["terminal_options"] == 1
    assert forty_five["filled_options"] == 1


def test_cooldown_ledger_requires_clean_embargo() -> None:
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=8_000_000
    )
    option = _risk_rejected_option(state, "1")
    option["timestamp_ms"] = state.frozen_at_ms + EMBARGO_MS - 1

    with pytest.raises(
        ProspectiveConsecutiveLossCooldownLedgerError,
        match="predates clean start",
    ):
        update_cooldown_ledger(
            _summary(state, [option]),
            state,
            previous=None,
            source_paper_run_id=80,
            source_paper_run_attempt=1,
            source_artifact_name="learning-80-1",
            source_artifact_digest=_digest("6"),
        )
