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
    return {
        "overlap_started_at_ms": 1_000,
        "source_history": [_identity(run_id)],
        "summary": summary,
        "ledger_sha256": f"return-{run_id}",
    }


def _stop_ledger(
    *,
    run_id: int = 10,
    integrity: bool = True,
    ready: bool = True,
    current_gate: bool = True,
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
    return {
        "overlap_started_at_ms": 1_000,
        "source_history": [_identity(run_id)],
        "summary": summary,
        "ledger_sha256": f"stop-{run_id}",
    }


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
