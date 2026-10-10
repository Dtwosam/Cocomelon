from __future__ import annotations

import hashlib

import pytest

from cocomelon.research.terminal_row_drift import (
    first_changed_field,
    terminal_row_drift_receipt,
)


def test_first_difference_nested_immutable_pnl_and_source_fields() -> None:
    before = {
        "economic": {"markouts": [{"pnl": "-4", "status": "settled"}]},
        "source_digest": "verified",
    }
    after = {
        "economic": {"markouts": [{"pnl": "-9", "status": "settled"}]},
        "source_digest": "verified",
    }
    assert first_changed_field(before, after) == "/economic/markouts/0/pnl"
    assert first_changed_field(after, before) == "/economic/markouts/0/pnl"
    assert first_changed_field(before, before) is None


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ({"amount": 1}, {"amount": "1"}, "/amount"),
        ({"flags": [True]}, {"flags": [1]}, "/flags/0"),
        ({"marks": [1]}, {"marks": [1, 2]}, "/marks/1"),
        ({"marks": [1, 2]}, {"marks": [1]}, "/marks/1"),
        ({"a/b": {"~x": 5}}, {"a/b": {"~x": 6}}, "/a~1b/~0x"),
        ({"source": "known"}, {}, "/source"),
        ({}, {"source": "new"}, "/source"),
        ({"a": {"z": 8, "b": 2}}, {"a": {"z": 7, "b": 3}}, "/a/b"),
        ({"path": None}, {"path": 0}, "/path"),
    ],
)
def test_receipt_detects_first_structural_mutation_and_stable_json_pointer(
    old: dict[str, object],
    new: dict[str, object],
    expected: str,
) -> None:
    assert first_changed_field(old, new) == expected


def test_redacted_drift_receipt_never_discloses_record_values() -> None:
    identity = "simulated-private-source-opportunity"
    old = {"source_digest": "private-source-value", "pnl": "1234.5678"}
    new = {"source_digest": "private-source-value", "pnl": "-99999"}
    receipt = terminal_row_drift_receipt(identity, old, new)
    assert "changed_json_pointer=/pnl" in receipt
    assert hashlib.sha256(identity.encode()).hexdigest()[:16] in receipt
    for secret in (identity, "1234.5678", "-99999", "private-source-value"):
        assert secret not in receipt


def test_equal_terminal_rows_cannot_create_false_drift_receipt() -> None:
    with pytest.raises(ValueError, match="equal rows"):
        terminal_row_drift_receipt("known", {"a": "same"}, {"a": "same"})
    with pytest.raises(ValueError, match="nonempty"):
        terminal_row_drift_receipt("", {"a": 1}, {"a": 2})
