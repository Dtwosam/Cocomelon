from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.render_continuous_paper_live_status import render_live_status

TIMESTAMP_MS = 1_700_000_000_000
ACK = "runtime acknowledgment: `ENFORCED IN THIS HEARTBEAT`"
UNKNOWN = "runtime acknowledgment: `UNVERIFIED`"


def _policy() -> dict:
    return {
        "schema_version": 1,
        "scope": "ordinary_paper",
        "entries_suspended": True,
        "effective_at_ms": TIMESTAMP_MS - 10_000,
        "reason": "unvalidated_strategy_no_new_allocation",
        "origin_worker_run_id": 122,
        "origin_worker_head_sha": "a" * 40,
        "restore_status": "restored",
        "durable": True,
        "live_orders": False,
        "runtime_enforced": True,
        "adapter_entries_suspended": True,
        "new_exposure_cutoff_ms": 0,
        "session_opening_attempts": 0,
        "session_opening_fills": 0,
        "session_blocked_openings": 4,
        "pending_opening_candidate_count": 0,
        "pending_reduce_only_count": 1,
    }


def _payload(scope: str) -> dict:
    return {
        "heartbeat_scope": scope,
        "timestamp_ms": TIMESTAMP_MS,
        "paper_only": True,
        "live_orders": False,
        "starting_cash": "10000",
        "equity": "10000",
        "cash": "10000",
        "total_account_pnl": "0",
        "unrealized_pnl": "0",
        "realized_gross_pnl": "0",
        "cumulative_fees": "0",
        "cumulative_funding": "0",
        "closed_trades": 0,
        "execution_healthy": True,
        "selected_market_count": 0,
        "processed_records": 0,
        "journal_observations": 0,
        "positions": [],
        "entry_suspension": _policy(),
    }


def _render(payload: dict, *, run_id: str = "123", head_sha: str = "b" * 40) -> str:
    return render_live_status(payload, run_id=run_id, head_sha=head_sha, predecessor_run_id="122")


@pytest.mark.parametrize("scope", ("full", "operational"))
def test_only_current_runtime_evidence_acknowledges_suspension_in_both_views(scope: str) -> None:
    # Removing either render-path insertion must lose this real output section.
    rendered = _render(_payload(scope))
    assert "### PAPER entry suspension" in rendered
    assert ACK in rendered
    assert "acknowledging worker run / head: `123 / " + "b" * 40 + "`" in rendered
    assert "policy origin run / head: `122 / " + "a" * 40 + "`" in rendered
    assert "policy effective UTC (not observed activation): `2023-11-14T22:13:10+00:00`" in rendered
    assert "policy restore / durable: `restored / true`" in rendered
    assert "pending opening candidates / reduce-only exits: `0 / 1`" in rendered
    assert "direct blocked opening submissions: `4`" in rendered
    assert "not an outstanding-order inventory" in rendered
    assert "not independent activation verification" in rendered


@pytest.mark.parametrize("scope", ("full", "operational"))
@pytest.mark.parametrize("raw", (None, {}, {"entries_suspended": True}, "active"))
def test_absent_or_policy_file_only_data_is_unverified(scope: str, raw: object) -> None:
    payload = _payload(scope)
    payload["entry_suspension"] = raw
    rendered = _render(payload)
    assert UNKNOWN in rendered
    assert ACK not in rendered


@pytest.mark.parametrize("scope", ("full", "operational"))
@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("schema_version", True),
        ("schema_version", 2),
        ("scope", "research"),
        ("entries_suspended", "true"),
        ("runtime_enforced", False),
        ("runtime_enforced", "true"),
        ("adapter_entries_suspended", 1),
        ("new_exposure_cutoff_ms", False),
        ("new_exposure_cutoff_ms", "0"),
        ("new_exposure_cutoff_ms", 0.0),
        ("new_exposure_cutoff_ms", 1),
        ("session_opening_attempts", False),
        ("session_opening_attempts", "0"),
        ("session_opening_attempts", 0.0),
        ("session_opening_attempts", 1),
        ("session_opening_fills", False),
        ("session_opening_fills", "0"),
        ("session_opening_fills", 1),
        ("session_blocked_openings", -1),
        ("pending_opening_candidate_count", False),
        ("pending_reduce_only_count", "0"),
        ("live_orders", 0),
        ("durable", "true"),
        ("effective_at_ms", True),
        ("effective_at_ms", "1700000000000"),
        ("effective_at_ms", TIMESTAMP_MS + 1),
        ("effective_at_ms", 10**100),
        ("origin_worker_run_id", True),
    ),
)
def test_malformed_or_nonzero_runtime_evidence_never_acknowledges(
    scope: str, field: str, bad: object
) -> None:
    # Truthiness/int coercion would falsely acknowledge these malformed values.
    payload = _payload(scope)
    payload["entry_suspension"][field] = bad
    rendered = _render(payload)
    assert UNKNOWN in rendered
    assert ACK not in rendered


@pytest.mark.parametrize("scope", ("full", "operational"))
@pytest.mark.parametrize(
    ("field", "malicious"),
    (
        ("origin_worker_head_sha", "a" * 30 + "`\n# INJECT"),
        ("restore_status", "restored`\n# INJECT"),
        ("reason", "unvalidated`\n# INJECT"),
        ("effective_at_ms", "`\n# INJECT"),
    ),
)
def test_policy_metadata_cannot_inject_markdown_or_forge_acknowledgment(
    scope: str, field: str, malicious: str
) -> None:
    payload = _payload(scope)
    payload["entry_suspension"][field] = malicious
    rendered = _render(payload)
    assert "# INJECT" not in rendered
    assert UNKNOWN in rendered
    assert ACK not in rendered


@pytest.mark.parametrize("scope", ("full", "operational"))
@pytest.mark.parametrize("restore_status", ("write_failed", "invalid_preserved"))
def test_runtime_enforcement_can_be_acknowledged_without_claiming_policy_durability(
    scope: str, restore_status: str
) -> None:
    payload = _payload(scope)
    payload["entry_suspension"].update(restore_status=restore_status, durable=False)
    rendered = _render(payload)
    assert ACK in rendered
    assert f"policy restore / durable: `{restore_status} / false`" in rendered
    assert "Policy durability is not execution health" in rendered


@pytest.mark.parametrize("scope", ("full", "operational"))
def test_counters_do_not_claim_a_suppressed_signal_census_or_all_order_inventory(
    scope: str,
) -> None:
    payload = _payload(scope)
    payload["entry_suspension"].update(
        session_blocked_openings=0, pending_opening_candidate_count=2
    )
    rendered = _render(payload)
    assert ACK in rendered
    assert "direct blocked opening submissions: `0`" in rendered
    assert "not a count of all suppressed signals" in rendered
    assert "not an outstanding-order inventory" in rendered


@pytest.mark.parametrize("scope", ("full", "operational"))
def test_unknown_outer_worker_or_nonpaper_identity_cannot_bind_an_ack(scope: str) -> None:
    payload = _payload(scope)
    assert UNKNOWN in _render(payload, run_id="unknown")
    assert UNKNOWN in _render(payload, head_sha="unknown")
    for field, bad in (("paper_only", False), ("live_orders", True)):
        other = deepcopy(payload)
        other[field] = bad
        assert UNKNOWN in _render(other)
