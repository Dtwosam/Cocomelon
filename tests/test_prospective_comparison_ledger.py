from __future__ import annotations

from copy import deepcopy

import pytest

from cocomelon.research.prospective_comparison_ledger import (
    ProspectiveComparisonLedgerError,
    update_comparison_ledger,
    validate_comparison_ledger,
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
    return {
        "decision_id": decision_id,
        "boundary_ms": boundary_ms,
        "market": market,
        "direction": direction,
        "prediction_net_return": prediction,
        "admitted": float(prediction) > 0,
        "realized_net_return": realized,
    }


def _report(
    model_family: str,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "status": "collecting",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "model_family": model_family,
        "prospective_start_ms": 1_000,
        "cadence_ms": 900_000,
        "horizon_ms": 3_600_000,
        "frozen_training_rows": 652,
        "frozen_training_rows_sha256": "frozen-digest",
        "prospective_rows": len(rows),
        "scored_rows": rows,
    }


def _comparison(row_count: int) -> dict[str, object]:
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "source_run_id": 900,
        "source_run_attempt": 1,
        "prospective_start_ms": 1_000,
        "frozen_training_rows": 652,
        "frozen_training_rows_sha256": "frozen-digest",
        "prospective_rows": row_count,
    }


def _update(
    micro: dict[str, object],
    baseline: dict[str, object],
    previous: dict[str, object] | None = None,
    *,
    comparison_run_id: int = 100,
) -> dict[str, object]:
    rows = micro["scored_rows"]
    assert isinstance(rows, list)
    return update_comparison_ledger(
        _comparison(len(rows)),
        micro,
        baseline,
        previous=previous,
        source_comparison_run_id=comparison_run_id,
        source_comparison_run_attempt=1,
        source_artifact_name=f"comparison-{comparison_run_id}",
    )


def test_initial_paired_ledger_is_canonical_and_valid() -> None:
    micro = _report(
        "micro",
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
        ],
    )
    baseline = _report(
        "baseline",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.01",
                realized="-0.03",
            ),
            _row(
                "b",
                boundary_ms=3_000,
                prediction="-0.02",
                realized="0.02",
                market="ETH",
                direction="short",
            ),
        ],
    )

    ledger = _update(micro, baseline)

    assert ledger["row_count"] == 2
    assert ledger["previous_row_count"] == 0
    assert ledger["new_row_count"] == 2
    rows = ledger["rows"]
    assert isinstance(rows, tuple)
    assert [row["decision_id"] for row in rows] == ["a", "b"]
    assert rows[0]["microstructure_prediction_net_return"] == "0.02"
    assert rows[0]["baseline_prediction_net_return"] == "0.01"
    assert validate_comparison_ledger(ledger)["ledger_sha256"] == (
        ledger["ledger_sha256"]
    )


def test_append_only_extension_preserves_previous_rows() -> None:
    micro_first = _report(
        "micro",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.03",
            )
        ],
    )
    base_first = _report(
        "baseline",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="-0.01",
                realized="-0.03",
            )
        ],
    )
    first = _update(micro_first, base_first)

    micro_second = deepcopy(micro_first)
    baseline_second = deepcopy(base_first)
    assert isinstance(micro_second["scored_rows"], list)
    assert isinstance(baseline_second["scored_rows"], list)
    micro_second["scored_rows"].append(
        _row(
            "b",
            boundary_ms=3_000,
            prediction="-0.02",
            realized="0.04",
            direction="short",
        )
    )
    baseline_second["scored_rows"].append(
        _row(
            "b",
            boundary_ms=3_000,
            prediction="0.01",
            realized="0.04",
            direction="short",
        )
    )
    micro_second["prospective_rows"] = 2
    baseline_second["prospective_rows"] = 2

    second = _update(
        micro_second,
        baseline_second,
        first,
        comparison_run_id=101,
    )

    assert second["previous_row_count"] == 1
    assert second["new_row_count"] == 1
    assert second["row_count"] == 2
    assert second["prior_ledger_sha256"] == first["ledger_sha256"]
    assert len(second["source_history"]) == 2


@pytest.mark.parametrize(
    ("model", "field", "value", "expected"),
    [
        (
            "micro",
            "prediction_net_return",
            "0.01",
            "previous paired row changed",
        ),
        (
            "micro",
            "admitted",
            False,
            "admitted does not match prediction sign",
        ),
        (
            "baseline",
            "prediction_net_return",
            "0.03",
            "previous paired row changed",
        ),
        (
            "baseline",
            "admitted",
            False,
            "admitted does not match prediction sign",
        ),
    ],
)
def test_changed_prior_model_prediction_fails_closed(
    model: str,
    field: str,
    value: object,
    expected: str,
) -> None:
    micro = _report(
        "micro",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.03",
            )
        ],
    )
    baseline = _report(
        "baseline",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.01",
                realized="-0.03",
            )
        ],
    )
    first = _update(micro, baseline)
    changed_micro = deepcopy(micro)
    changed_base = deepcopy(baseline)
    target = changed_micro if model == "micro" else changed_base
    rows = target["scored_rows"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    row[field] = value

    with pytest.raises(
        ProspectiveComparisonLedgerError,
        match=expected,
    ):
        _update(
            changed_micro,
            changed_base,
            first,
            comparison_run_id=101,
        )


def test_changed_prior_realized_return_fails_closed() -> None:
    micro = _report(
        "micro",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.03",
            )
        ],
    )
    baseline = _report(
        "baseline",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.01",
                realized="-0.03",
            )
        ],
    )
    first = _update(micro, baseline)
    changed_micro = deepcopy(micro)
    changed_base = deepcopy(baseline)
    for report in (changed_micro, changed_base):
        rows = report["scored_rows"]
        assert isinstance(rows, list)
        row = rows[0]
        assert isinstance(row, dict)
        row["realized_net_return"] = "-0.02"

    with pytest.raises(
        ProspectiveComparisonLedgerError,
        match="previous paired row changed",
    ):
        _update(
            changed_micro,
            changed_base,
            first,
            comparison_run_id=101,
        )


def test_pair_mismatch_fails_before_ledger_update() -> None:
    micro = _report(
        "micro",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="-0.03",
            )
        ],
    )
    baseline = _report(
        "baseline",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.01",
                realized="-0.02",
            )
        ],
    )

    with pytest.raises(
        ProspectiveComparisonLedgerError,
        match="paired model row mismatch: realized_net_return",
    ):
        _update(micro, baseline)


def test_disappeared_prior_row_fails_closed() -> None:
    micro = _report(
        "micro",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="0.01",
            )
        ],
    )
    baseline = _report(
        "baseline",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="-0.02",
                realized="0.01",
            )
        ],
    )
    first = _update(micro, baseline)

    with pytest.raises(
        ProspectiveComparisonLedgerError,
        match="previous paired row disappeared",
    ):
        _update(
            _report("micro", []),
            _report("baseline", []),
            first,
            comparison_run_id=101,
        )


def test_late_settled_older_boundary_can_append() -> None:
    first_micro = _report(
        "micro",
        [
            _row(
                "a",
                boundary_ms=3_000,
                prediction="0.02",
                realized="0.01",
            )
        ],
    )
    first_base = _report(
        "baseline",
        [
            _row(
                "a",
                boundary_ms=3_000,
                prediction="0.01",
                realized="0.01",
            )
        ],
    )
    first = _update(first_micro, first_base)

    second_micro = _report(
        "micro",
        [
            _row(
                "late",
                boundary_ms=2_000,
                prediction="-0.01",
                realized="-0.01",
            ),
            deepcopy(first_micro["scored_rows"][0]),
        ],
    )
    second_base = _report(
        "baseline",
        [
            _row(
                "late",
                boundary_ms=2_000,
                prediction="0.01",
                realized="-0.01",
            ),
            deepcopy(first_base["scored_rows"][0]),
        ],
    )

    updated = _update(
        second_micro,
        second_base,
        first,
        comparison_run_id=101,
    )

    assert updated["new_row_count"] == 1
    assert updated["row_count"] == 2
    assert updated["first_boundary_ms"] == 2_000


def test_metadata_drift_fails_closed() -> None:
    micro = _report(
        "micro",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="0.01",
            )
        ],
    )
    baseline = _report(
        "baseline",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.01",
                realized="0.01",
            )
        ],
    )
    first = _update(micro, baseline)
    changed_micro = deepcopy(micro)
    changed_base = deepcopy(baseline)
    changed_micro["frozen_training_rows_sha256"] = "different"
    changed_base["frozen_training_rows_sha256"] = "different"

    with pytest.raises(
        ProspectiveComparisonLedgerError,
        match="comparison metadata mismatch",
    ):
        _update(
            changed_micro,
            changed_base,
            first,
            comparison_run_id=101,
        )


def test_corrupt_previous_digest_fails_closed() -> None:
    micro = _report(
        "micro",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.02",
                realized="0.01",
            )
        ],
    )
    baseline = _report(
        "baseline",
        [
            _row(
                "a",
                boundary_ms=2_000,
                prediction="0.01",
                realized="0.01",
            )
        ],
    )
    first = _update(micro, baseline)
    first["rows_sha256"] = "corrupt"

    with pytest.raises(
        ProspectiveComparisonLedgerError,
        match="row digest mismatch",
    ):
        _update(
            micro,
            baseline,
            first,
            comparison_run_id=101,
        )
