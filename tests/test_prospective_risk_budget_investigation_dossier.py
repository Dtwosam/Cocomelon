from __future__ import annotations

from copy import deepcopy

import pytest

import cocomelon.research.prospective_risk_budget_investigation_dossier as dossier
from cocomelon.research.prospective_risk_budget_investigation_dossier import (
    RiskBudgetInvestigationDossierError,
    build_risk_budget_investigation_dossier,
    validate_risk_budget_investigation_dossier,
)


def _identity(run_id: int = 10) -> dict[str, object]:
    return {
        "paper_run_id": run_id,
        "paper_run_attempt": 1,
        "artifact_name": f"compact-{run_id}-1",
        "artifact_digest": "sha256:" + f"{run_id:064x}",
    }


def _return_ledger(
    *,
    run_id: int = 10,
    integrity: bool = True,
    ready: bool = True,
    current_gate: bool = True,
    post_ready: bool | None = None,
    post_started_at_ms: int = 2_000,
    rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "integrity_clean": integrity,
    }
    if current_gate:
        summary["risk_budget_investigation_readiness"] = {
            "scope": "risk_rejected_stack_admit_only",
            "ready_reasons": (
                ["weekly_drawdown_lockout"] if ready else []
            ),
            "by_reason": {
                "weekly_drawdown_lockout": {
                    "ready_for_risk_budget_investigation": ready,
                    "horizons": {
                        "300000": {"ready": ready},
                        "900000": {"ready": ready},
                        "3600000": {"ready": ready},
                    },
                }
            },
        }
    if post_ready is not None:
        summary["post_integrity_miss"] = {
            "boundary_known": True,
            "last_miss_at_ms": post_started_at_ms - 1,
            "started_at_ms": post_started_at_ms,
            "terminal_opportunity_count": 12,
            "risk_budget_investigation_readiness": {
                "scope": "risk_rejected_stack_admit_only",
                "ready_reasons": (
                    ["weekly_drawdown_lockout"] if post_ready else []
                ),
                "by_reason": {
                    "weekly_drawdown_lockout": {
                        "ready_for_risk_budget_investigation": post_ready,
                        "horizons": {
                            "300000": {"ready": post_ready},
                            "900000": {"ready": post_ready},
                            "3600000": {"ready": post_ready},
                        },
                    }
                },
            },
        }
    return {
        "overlap_started_at_ms": 1_000,
        "source_history": [_identity(run_id)],
        "summary": summary,
        "ledger_sha256": f"return-{run_id}",
        "rows": [] if rows is None else rows,
    }


def _stop_ledger(
    *,
    run_id: int = 10,
    integrity: bool = True,
    ready: bool = True,
    current_gate: bool = True,
    post_ready: bool | None = None,
    post_started_at_ms: int = 2_000,
    rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "integrity_clean": integrity,
    }
    if current_gate:
        summary["risk_budget_stop_investigation"] = {
            "scope": "risk_rejected_stack_admit_stop_survival_only",
            "ready_reasons": (
                ["weekly_drawdown_lockout"] if ready else []
            ),
            "by_reason": {
                "weekly_drawdown_lockout": {
                    "ready_for_risk_budget_stop_investigation": ready,
                    "horizons": {
                        "300000": {"ready": ready},
                        "900000": {"ready": ready},
                        "3600000": {"ready": ready},
                    },
                }
            },
        }
    if post_ready is not None:
        summary["post_integrity_miss"] = {
            "boundary_known": True,
            "last_miss_at_ms": post_started_at_ms - 1,
            "started_at_ms": post_started_at_ms,
            "terminal_opportunity_count": 12,
            "risk_budget_stop_investigation": {
                "scope": (
                    "risk_rejected_stack_admit_stop_survival_only"
                ),
                "ready_reasons": (
                    ["weekly_drawdown_lockout"] if post_ready else []
                ),
                "by_reason": {
                    "weekly_drawdown_lockout": {
                        "ready_for_risk_budget_stop_investigation": (
                            post_ready
                        ),
                        "horizons": {
                            "300000": {"ready": post_ready},
                            "900000": {"ready": post_ready},
                            "3600000": {"ready": post_ready},
                        },
                    }
                },
            },
        }
    return {
        "overlap_started_at_ms": 1_000,
        "source_history": [_identity(run_id)],
        "summary": summary,
        "ledger_sha256": f"stop-{run_id}",
        "rows": [] if rows is None else rows,
    }


def _candidate_rows(
    *,
    count: int = 20,
    first_return: str = "0.01",
    stop_crossings: int = 0,
    start_ms: int = dossier.WEEKLY_DRAWDOWN_5M_FROZEN_AT_MS + 1,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    return_rows: list[dict[str, object]] = []
    stop_rows: list[dict[str, object]] = []
    markets = ("BTC", "ETH", "SOL", "HYPE", "DOGE")
    for index in range(count):
        opportunity_id = f"candidate-{index}"
        timestamp_ms = start_ms + index
        market = markets[index % len(markets)]
        direction = "long" if index % 2 == 0 else "short"
        directional_return = (
            first_return if index == 0 else "0.01"
        )
        return_rows.append(
            {
                "opportunity_id": opportunity_id,
                "timestamp_ms": timestamp_ms,
                "market": market,
                "direction": direction,
                "baseline_risk_approved": False,
                "baseline_risk_reason_codes": [
                    dossier.WEEKLY_DRAWDOWN_REASON
                ],
                "stack_decision": "ADMIT",
                "block_layer": "none",
                "markouts": {
                    "300000": {
                        "status": "settled",
                        "directional_return": directional_return,
                    }
                },
            }
        )
        crossed = index < stop_crossings
        stop_rows.append(
            {
                "opportunity_id": opportunity_id,
                "timestamp_ms": timestamp_ms,
                "market": market,
                "direction": direction,
                "baseline_risk_approved": False,
                "baseline_risk_reason_codes": [
                    dossier.WEEKLY_DRAWDOWN_REASON
                ],
                "stack_decision": "ADMIT",
                "block_layer": "none",
                "stop_path": {
                    "horizons": {
                        "300000": {
                            "status": (
                                "observed_stop_crossing"
                                if crossed
                                else "observed_path_survivor"
                            )
                        }
                    }
                },
            }
        )
    return return_rows, stop_rows


@pytest.fixture(autouse=True)
def _identity_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dossier,
        "validate_risk_rejected_forward_markout_ledger",
        lambda raw: raw,
    )
    monkeypatch.setattr(
        dossier,
        "validate_risk_rejected_stop_path_ledger",
        lambda raw: raw,
    )


def test_dossier_requires_both_aligned_gates() -> None:
    report = build_risk_budget_investigation_dossier(
        _return_ledger(),
        _stop_ledger(),
    )

    assert report["status"] == "aligned_evaluated"
    assert report["source_aligned"] is True
    assert report["gates_current"] is True
    assert report["integrity_clean"] is True
    assert report["ready_reasons"] == ["weekly_drawdown_lockout"]
    reason = report["by_reason"]["weekly_drawdown_lockout"]
    assert reason["economic_ready"] is True
    assert reason["stop_survival_ready"] is True
    assert reason["conjunctive_ready_for_investigation"] is True
    assert report["changes_risk_limits"] is False
    assert report["execution_authority"] is False
    validate_risk_budget_investigation_dossier(report)


def test_dossier_waits_for_source_alignment() -> None:
    report = build_risk_budget_investigation_dossier(
        _return_ledger(run_id=10),
        _stop_ledger(run_id=11),
    )

    assert report["status"] == "waiting_for_aligned_sources"
    assert report["source_aligned"] is False
    assert report["ready_reasons"] == []
    reason = report["by_reason"]["weekly_drawdown_lockout"]
    assert reason["economic_ready"] is True
    assert reason["stop_survival_ready"] is True
    assert reason["conjunctive_ready_for_investigation"] is False


def test_dossier_requires_both_component_gates() -> None:
    report = build_risk_budget_investigation_dossier(
        _return_ledger(ready=True),
        _stop_ledger(ready=False),
    )

    assert report["status"] == "aligned_evaluated"
    assert report["ready_reasons"] == []
    reason = report["by_reason"]["weekly_drawdown_lockout"]
    assert reason["economic_ready"] is True
    assert reason["stop_survival_ready"] is False
    assert reason["conjunctive_ready_for_investigation"] is False


def test_dossier_blocks_dirty_cumulative_integrity() -> None:
    report = build_risk_budget_investigation_dossier(
        _return_ledger(integrity=False),
        _stop_ledger(integrity=True),
    )

    assert report["status"] == "blocked_by_source_integrity"
    assert report["source_aligned"] is True
    assert report["integrity_clean"] is False
    assert report["ready_reasons"] == []
    assert report["by_reason"]["weekly_drawdown_lockout"][
        "conjunctive_ready_for_investigation"
    ] is False


def test_dossier_uses_aligned_post_integrity_cohort() -> None:
    report = build_risk_budget_investigation_dossier(
        _return_ledger(
            integrity=False,
            post_ready=True,
            post_started_at_ms=5_001,
        ),
        _stop_ledger(
            integrity=False,
            post_ready=True,
            post_started_at_ms=5_001,
        ),
    )

    assert report["status"] == "aligned_post_integrity_evaluated"
    assert report["integrity_clean"] is False
    assert report["effective_integrity_clean"] is True
    assert report["integrity_scope"] == "post_integrity_miss"
    assert report["post_integrity_source_aligned"] is True
    assert report["post_integrity_started_at_ms"] == 5_001
    assert report["ready_reasons"] == ["weekly_drawdown_lockout"]
    assert report["by_reason"]["weekly_drawdown_lockout"][
        "conjunctive_ready_for_investigation"
    ] is True


def test_dossier_rejects_mismatched_post_integrity_boundaries() -> None:
    report = build_risk_budget_investigation_dossier(
        _return_ledger(
            integrity=False,
            post_ready=True,
            post_started_at_ms=5_001,
        ),
        _stop_ledger(
            integrity=False,
            post_ready=True,
            post_started_at_ms=6_001,
        ),
    )

    assert report["status"] == "blocked_by_source_integrity"
    assert report["effective_integrity_clean"] is False
    assert report["integrity_scope"] == "blocked"
    assert report["post_integrity_source_aligned"] is False
    assert report["ready_reasons"] == []
    assert report["by_reason"]["weekly_drawdown_lockout"][
        "conjunctive_ready_for_investigation"
    ] is False


def test_dossier_waits_for_current_gate_format() -> None:
    report = build_risk_budget_investigation_dossier(
        _return_ledger(current_gate=False),
        _stop_ledger(),
    )

    assert report["status"] == "waiting_for_current_gate_format"
    assert report["gates_current"] is False
    assert report["ready_reasons"] == []


def test_dossier_digest_and_authority_fail_closed() -> None:
    report = build_risk_budget_investigation_dossier(
        _return_ledger(),
        _stop_ledger(),
    )
    tampered = deepcopy(report)
    tampered["changes_risk_limits"] = True
    with pytest.raises(
        RiskBudgetInvestigationDossierError,
        match="authority drift",
    ):
        validate_risk_budget_investigation_dossier(tampered)

    tampered = deepcopy(report)
    tampered["ready_reasons"] = []
    with pytest.raises(
        RiskBudgetInvestigationDossierError,
        match="digest mismatch",
    ):
        validate_risk_budget_investigation_dossier(tampered)


def test_dossier_rejects_invalid_latest_source_identity() -> None:
    returns = _return_ledger()
    history = returns["source_history"]
    assert isinstance(history, list)
    history[-1]["artifact_digest"] = "bad"

    with pytest.raises(
        RiskBudgetInvestigationDossierError,
        match="latest source identity is invalid",
    ):
        build_risk_budget_investigation_dossier(
            returns,
            _stop_ledger(),
        )



def test_weekly_drawdown_5m_candidate_passes_frozen_first_twenty() -> None:
    return_rows, stop_rows = _candidate_rows()

    report = build_risk_budget_investigation_dossier(
        _return_ledger(rows=return_rows),
        _stop_ledger(rows=stop_rows),
    )

    candidate = report["weekly_drawdown_5m_candidate"]
    assert candidate["status"] == (
        "ready_for_execution_shadow_investigation"
    )
    assert candidate["review_rows"] == 20
    assert candidate["review_market_count"] == 5
    assert candidate["review_long_count"] == 10
    assert candidate["review_short_count"] == 10
    assert candidate["sample_complete"] is True
    assert candidate["economic_ready"] is True
    assert candidate["stop_survival_ready"] is True
    assert (
        candidate["ready_for_execution_shadow_investigation"]
        is True
    )
    assert candidate["discovery_cohort_reused_for_validation"] is False
    assert candidate["changes_risk_limits"] is False


def test_weekly_drawdown_5m_candidate_excludes_discovery_rows() -> None:
    discovery_returns, discovery_stops = _candidate_rows(
        count=20,
        start_ms=dossier.WEEKLY_DRAWDOWN_5M_FROZEN_AT_MS - 100,
    )
    prospective_returns, prospective_stops = _candidate_rows(
        count=19,
        start_ms=dossier.WEEKLY_DRAWDOWN_5M_FROZEN_AT_MS + 100,
    )
    for index, row in enumerate(prospective_returns):
        row["opportunity_id"] = f"prospective-{index}"
    for index, row in enumerate(prospective_stops):
        row["opportunity_id"] = f"prospective-{index}"

    report = build_risk_budget_investigation_dossier(
        _return_ledger(rows=[*discovery_returns, *prospective_returns]),
        _stop_ledger(rows=[*discovery_stops, *prospective_stops]),
    )

    candidate = report["weekly_drawdown_5m_candidate"]
    assert candidate["post_freeze_paired_evaluable_rows"] == 19
    assert candidate["review_rows"] == 19
    assert candidate["status"] == "collecting_frozen_review_cohort"
    assert (
        candidate["ready_for_execution_shadow_investigation"]
        is False
    )


def test_weekly_drawdown_5m_candidate_first_twenty_are_immutable_gate() -> None:
    first_returns, first_stops = _candidate_rows(
        first_return="-0.50",
    )
    later_returns, later_stops = _candidate_rows(
        count=20,
        start_ms=dossier.WEEKLY_DRAWDOWN_5M_FROZEN_AT_MS + 10_000,
    )
    for index, row in enumerate(later_returns):
        row["opportunity_id"] = f"later-{index}"
    for index, row in enumerate(later_stops):
        row["opportunity_id"] = f"later-{index}"

    report = build_risk_budget_investigation_dossier(
        _return_ledger(rows=[*first_returns, *later_returns]),
        _stop_ledger(rows=[*first_stops, *later_stops]),
    )

    candidate = report["weekly_drawdown_5m_candidate"]
    assert candidate["post_freeze_paired_evaluable_rows"] == 40
    assert candidate["review_rows"] == 20
    assert candidate["economic_ready"] is False
    assert candidate["status"] == "failed_frozen_review_cohort"


def test_weekly_drawdown_5m_candidate_requires_robust_stop_majority() -> None:
    return_rows, stop_rows = _candidate_rows(stop_crossings=10)

    report = build_risk_budget_investigation_dossier(
        _return_ledger(rows=return_rows),
        _stop_ledger(rows=stop_rows),
    )

    candidate = report["weekly_drawdown_5m_candidate"]
    assert candidate["economic_ready"] is True
    assert candidate["stop_survival_ready"] is False
    assert candidate["status"] == "failed_frozen_review_cohort"


def test_weekly_drawdown_5m_candidate_waits_for_source_alignment() -> None:
    return_rows, stop_rows = _candidate_rows()

    report = build_risk_budget_investigation_dossier(
        _return_ledger(run_id=10, rows=return_rows),
        _stop_ledger(run_id=11, rows=stop_rows),
    )

    candidate = report["weekly_drawdown_5m_candidate"]
    assert candidate["source_aligned"] is False
    assert candidate["status"] == "waiting_for_aligned_sources"
    assert (
        candidate["ready_for_execution_shadow_investigation"]
        is False
    )
