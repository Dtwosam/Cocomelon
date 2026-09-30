from __future__ import annotations

from copy import deepcopy

import pytest

from cocomelon.research.prospective_prediction_ledger import (
    ProspectivePredictionLedgerError,
    update_prediction_ledger,
    validate_prediction_ledger,
)


def _row(
    decision_id: str,
    *,
    boundary_ms: int,
    prediction: str,
    realized: str,
    market: str = "BTC",
    direction: str = "long",
) -> dict[str, object]:
    value = float(prediction)
    return {
        "decision_id": decision_id,
        "boundary_ms": boundary_ms,
        "market": market,
        "direction": direction,
        "prediction_net_return": prediction,
        "admitted": value > 0,
        "realized_net_return": realized,
    }


def _report(
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "status": "collecting",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "model_family": "cadence_microstructure_tree_prospective_v1",
        "prospective_start_ms": 1_000,
        "cadence_ms": 900_000,
        "horizon_ms": 3_600_000,
        "frozen_training_rows": 652,
        "frozen_training_rows_sha256": "abc123",
        "scored_rows": rows,
    }


def _update(
    report: dict[str, object],
    previous: dict[str, object] | None = None,
    *,
    run_id: int = 100,
) -> dict[str, object]:
    return update_prediction_ledger(
        report,
        previous=previous,
        source_audit_run_id=run_id,
        source_audit_run_attempt=1,
        source_report_artifact_name=f"report-{run_id}",
    )


def test_initial_ledger_is_canonical_and_valid() -> None:
    report = _report(
        [
            _row(
                "b",
                boundary_ms=3_000,
                prediction="-0.01",
                realized="0.02",
                market="ETH",
                direction="short",
            ),
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.03",
            ),
        ]
    )

    ledger = _update(report)

    assert ledger["row_count"] == 2
    assert ledger["previous_row_count"] == 0
    assert ledger["new_row_count"] == 2
    assert [
        row["decision_id"]
        for row in ledger["rows"]
    ] == ["a", "b"]
    assert validate_prediction_ledger(ledger)["ledger_sha256"] == (
        ledger["ledger_sha256"]
    )


def test_append_only_extension_preserves_previous_rows() -> None:
    first_report = _report(
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.03",
            )
        ]
    )
    first = _update(first_report)
    second_report = _report(
        [
            deepcopy(first_report["scored_rows"][0]),
            _row(
                "b",
                boundary_ms=3_000,
                prediction="-0.01",
                realized="0.04",
                direction="short",
            ),
        ]
    )

    second = _update(second_report, first, run_id=101)

    assert second["previous_row_count"] == 1
    assert second["new_row_count"] == 1
    assert second["row_count"] == 2
    assert second["prior_ledger_sha256"] == first["ledger_sha256"]
    assert len(second["source_history"]) == 2


def test_repeated_audit_with_no_new_rows_is_valid() -> None:
    report = _report(
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.03",
            )
        ]
    )
    first = _update(report)
    second = _update(deepcopy(report), first, run_id=101)

    assert second["new_row_count"] == 0
    assert second["rows_sha256"] == first["rows_sha256"]


def test_changed_prior_prediction_fails_closed() -> None:
    report = _report(
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.03",
            )
        ]
    )
    first = _update(report)
    changed = _report(
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.01",
                realized="-0.03",
            )
        ]
    )

    with pytest.raises(
        ProspectivePredictionLedgerError,
        match="previous prospective row changed",
    ):
        _update(changed, first, run_id=101)


def test_changed_prior_outcome_fails_closed() -> None:
    report = _report(
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.03",
            )
        ]
    )
    first = _update(report)
    changed = _report(
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.02",
            )
        ]
    )

    with pytest.raises(
        ProspectivePredictionLedgerError,
        match="previous prospective row changed",
    ):
        _update(changed, first, run_id=101)


def test_disappeared_prior_row_fails_closed() -> None:
    report = _report(
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.03",
            )
        ]
    )
    first = _update(report)

    with pytest.raises(
        ProspectivePredictionLedgerError,
        match="previous prospective row disappeared",
    ):
        _update(_report([]), first, run_id=101)


def test_late_settled_older_boundary_can_append() -> None:
    first = _update(
        _report(
            [
                _row(
                    "a",
                    boundary_ms=3_000,
                    prediction="0.02",
                    realized="0.01",
                )
            ]
        )
    )
    second = _report(
        [
            _row(
                "late",
                boundary_ms=2_000,
                prediction="-0.01",
                realized="-0.01",
            ),
            _row(
                "a",
                boundary_ms=3_000,
                prediction="0.02",
                realized="0.01",
            ),
        ]
    )

    updated = _update(second, first, run_id=101)

    assert updated["new_row_count"] == 1
    assert updated["row_count"] == 2
    assert updated["first_boundary_ms"] == 2_000


def test_metadata_drift_fails_closed() -> None:
    report = _report(
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="0.01",
            )
        ]
    )
    first = _update(report)
    changed = deepcopy(report)
    changed["frozen_training_rows_sha256"] = "different"

    with pytest.raises(
        ProspectivePredictionLedgerError,
        match="metadata drift",
    ):
        _update(changed, first, run_id=101)


def test_corrupt_previous_digest_fails_closed() -> None:
    report = _report(
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="0.01",
            )
        ]
    )
    first = _update(report)
    first["rows_sha256"] = "corrupt"

    with pytest.raises(
        ProspectivePredictionLedgerError,
        match="row digest mismatch",
    ):
        _update(report, first, run_id=101)
