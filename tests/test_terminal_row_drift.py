from __future__ import annotations

import hashlib

import pytest

from cocomelon.research.terminal_row_drift import (
    MAX_DRIFT_PATHS,
    changed_field_paths,
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


def test_receipt_exposes_all_decision_drift_fields_without_values() -> None:
    old = {
        "block_layer": "none",
        "carveout_block_layer": "none",
        "markouts": {"300000": {"status": "settled"}},
        "momentum_decision": "ADMIT",
        "stack_decision": "ADMIT",
        "two_strike_prior_strikes": 0,
    }
    current = {
        "block_layer": "two_strike",
        "carveout_block_layer": "two_strike",
        "markouts": {"300000": {"status": "stale"}},
        "momentum_decision": "BLOCK",
        "stack_decision": "BLOCK",
        "two_strike_prior_strikes": 2,
    }
    paths = changed_field_paths(old, current)
    assert paths == (
        "/block_layer",
        "/carveout_block_layer",
        "/markouts/300000/status",
        "/momentum_decision",
        "/stack_decision",
        "/two_strike_prior_strikes",
    )
    receipt = terminal_row_drift_receipt("private-opportunity", old, current)
    assert "changed_json_pointer=/block_layer" in receipt
    assert "changed_json_pointers=" + ",".join(paths) in receipt
    assert "drift_paths_truncated=false" in receipt
    for secret in ("private-opportunity", "two_strike", "ADMIT", "BLOCK"):
        assert secret not in receipt


def test_receipt_bounded_paths_do_not_dump_unbounded_history() -> None:
    old = {f"field_{i:02}": "private-old" for i in range(40)}
    current = {f"field_{i:02}": "private-new" for i in range(40)}
    paths = changed_field_paths(old, current)
    assert len(paths) == MAX_DRIFT_PATHS
    assert paths[0] == "/field_00"
    assert paths[-1] == "/field_11"
    assert "drift_paths_truncated=true" in terminal_row_drift_receipt(
        "private-id", old, current
    )
    assert changed_field_paths({"a": 1}, {"a": 2}, limit=1) == ("/a",)
    with pytest.raises(ValueError, match="positive"):
        changed_field_paths(old, current, limit=0)
    with pytest.raises(ValueError, match="positive"):
        changed_field_paths(old, current, limit=True)


def test_multi_field_paths_include_missing_list_and_type_changes() -> None:
    old = {"items": [{"x": 1}, {"y": 2}], "type": None}
    current = {"items": [{"x": 3}], "type": "text"}
    assert changed_field_paths(old, current) == (
        "/items/0/x",
        "/items/1",
        "/type",
    )
