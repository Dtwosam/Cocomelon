from __future__ import annotations

from copy import deepcopy

import pytest

from cocomelon.research.prospective_candidate_failure_receipts import (
    ProspectiveCandidateFailureReceiptError,
    update_candidate_failure_receipts,
)


def _report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "prospective-trade-quality-readiness-v1",
        "status": "collecting",
        "cadence": {
            "model_family": "micro-v1",
            "prospective_start_ms": 100,
            "frozen_training_rows_sha256": "a" * 64,
            "prediction_ledger_sha256": "b" * 64,
            "comparison_ledger_sha256": "c" * 64,
            "lifecycle_state": "collecting",
            "irrecoverable_failure_components": (),
            "stability_blocks": (
                {
                    "block_index": 0,
                    "start_row": 1,
                    "end_row": 25,
                    "required_rows": 25,
                    "prospective_rows": 3,
                    "closed": False,
                    "passes": False,
                    "candidate_net_return_sum": "0",
                },
            ),
        },
        "comparison": {
            "incremental_stability_blocks": (
                {
                    "block_index": 0,
                    "start_row": 1,
                    "end_row": 25,
                    "required_rows": 25,
                    "paired_rows": 3,
                    "closed": False,
                    "passes": False,
                    "microstructure_minus_baseline_sum": "0",
                },
            ),
        },
        "timing": {
            "candidate_id": "timing-v1",
            "started_at_ms": 200,
            "timing_ledger_sha256": "d" * 64,
            "lifecycle_state": "collecting",
            "irrecoverable_failure_components": (),
            "temporal_blocks": (
                {
                    "block_index": 0,
                    "start_row": 1,
                    "end_row": 5,
                    "required_rows": 5,
                    "rows": 0,
                    "closed": False,
                    "passes": False,
                    "selected_minus_actual_pnl": "0",
                    "selected_minus_60s_pnl": "0",
                },
            ),
        },
    }


def test_collecting_report_has_empty_receipt_ledger() -> None:
    ledger = update_candidate_failure_receipts(
        _report(),
        source_readiness_run_id=10,
        source_readiness_run_attempt=1,
    )

    assert ledger["entry_count"] == 0
    assert ledger["entries"] == []
    assert len(ledger["ledger_sha256"]) == 64


def test_first_cadence_failure_is_preserved() -> None:
    report = _report()
    cadence = report["cadence"]
    comparison = report["comparison"]
    assert isinstance(cadence, dict)
    assert isinstance(comparison, dict)
    cadence["lifecycle_state"] = "failed_closed_block"
    cadence["irrecoverable_failure_components"] = (
        "standalone_stability",
    )
    cadence["stability_blocks"] = (
        {
            "block_index": 0,
            "start_row": 1,
            "end_row": 25,
            "required_rows": 25,
            "prospective_rows": 25,
            "closed": True,
            "passes": False,
            "candidate_net_return_sum": "-0.2",
        },
    )

    first = update_candidate_failure_receipts(
        report,
        source_readiness_run_id=20,
        source_readiness_run_attempt=1,
    )
    entry = first["entries"][0]
    assert entry["candidate_key"] == "cadence_microstructure"
    assert entry["source_readiness_run_id"] == 20
    assert entry["failed_closed_blocks"][0]["block_index"] == 0

    later = deepcopy(report)
    later_cadence = later["cadence"]
    assert isinstance(later_cadence, dict)
    later_cadence["stability_blocks"] = (
        {
            "block_index": 0,
            "start_row": 1,
            "end_row": 25,
            "required_rows": 25,
            "prospective_rows": 25,
            "closed": True,
            "passes": False,
            "candidate_net_return_sum": "-0.5",
        },
    )
    second = update_candidate_failure_receipts(
        later,
        source_readiness_run_id=30,
        source_readiness_run_attempt=1,
        previous=first,
    )

    assert second["entries"] == first["entries"]
    assert second["ledger_sha256"] == first["ledger_sha256"]


def test_second_candidate_failure_appends_without_rewriting_first() -> None:
    report = _report()
    cadence = report["cadence"]
    assert isinstance(cadence, dict)
    cadence["lifecycle_state"] = "failed_closed_block"
    cadence["irrecoverable_failure_components"] = (
        "standalone_stability",
    )
    cadence["stability_blocks"] = (
        {
            "block_index": 0,
            "start_row": 1,
            "end_row": 25,
            "required_rows": 25,
            "prospective_rows": 25,
            "closed": True,
            "passes": False,
            "candidate_net_return_sum": "-0.2",
        },
    )
    first = update_candidate_failure_receipts(
        report,
        source_readiness_run_id=20,
        source_readiness_run_attempt=1,
    )

    timing = report["timing"]
    assert isinstance(timing, dict)
    timing["lifecycle_state"] = "failed_closed_block"
    timing["irrecoverable_failure_components"] = (
        "temporal_stability",
    )
    timing["temporal_blocks"] = (
        {
            "block_index": 0,
            "start_row": 1,
            "end_row": 5,
            "required_rows": 5,
            "rows": 5,
            "closed": True,
            "passes": False,
            "selected_minus_actual_pnl": "-2",
            "selected_minus_60s_pnl": "-1",
        },
    )
    second = update_candidate_failure_receipts(
        report,
        source_readiness_run_id=40,
        source_readiness_run_attempt=1,
        previous=first,
    )

    assert second["entry_count"] == 2
    assert second["entries"][0] == first["entries"][0]
    assert second["entries"][1]["candidate_key"] == (
        "side_conditioned_timing"
    )


def test_previous_failure_cannot_recover() -> None:
    report = _report()
    cadence = report["cadence"]
    assert isinstance(cadence, dict)
    cadence["lifecycle_state"] = "failed_closed_block"
    cadence["irrecoverable_failure_components"] = (
        "standalone_stability",
    )
    cadence["stability_blocks"] = (
        {
            "block_index": 0,
            "start_row": 1,
            "end_row": 25,
            "required_rows": 25,
            "prospective_rows": 25,
            "closed": True,
            "passes": False,
            "candidate_net_return_sum": "-0.2",
        },
    )
    first = update_candidate_failure_receipts(
        report,
        source_readiness_run_id=20,
        source_readiness_run_attempt=1,
    )

    recovered = _report()
    with pytest.raises(
        ProspectiveCandidateFailureReceiptError,
        match="FIRST_FAILURE_CANDIDATE_RECOVERED",
    ):
        update_candidate_failure_receipts(
            recovered,
            source_readiness_run_id=30,
            source_readiness_run_attempt=1,
            previous=first,
        )


def test_previous_receipt_tampering_fails_closed() -> None:
    ledger = update_candidate_failure_receipts(
        _report(),
        source_readiness_run_id=10,
        source_readiness_run_attempt=1,
    )
    ledger["ledger_sha256"] = "0" * 64

    with pytest.raises(
        ProspectiveCandidateFailureReceiptError,
        match="LEDGER_DIGEST_MISMATCH",
    ):
        update_candidate_failure_receipts(
            _report(),
            source_readiness_run_id=11,
            source_readiness_run_attempt=1,
            previous=ledger,
        )


def test_pre_lifecycle_readiness_manifest_is_rejected() -> None:
    report = _report()
    cadence = report["cadence"]
    assert isinstance(cadence, dict)
    cadence.pop("lifecycle_state")

    with pytest.raises(
        ProspectiveCandidateFailureReceiptError,
        match="READINESS_LIFECYCLE_STATE_INVALID",
    ):
        update_candidate_failure_receipts(
            report,
            source_readiness_run_id=10,
            source_readiness_run_attempt=1,
        )
