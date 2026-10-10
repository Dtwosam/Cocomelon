from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from cocomelon.research.prospective_risk_rejected_forward_markout_ledger import (
    ProspectiveRiskRejectedForwardMarkoutLedgerError,
    update_risk_rejected_forward_markout_ledger,
)
from cocomelon.research.terminal_source_parity import (
    TerminalSourceParityError,
    audit_terminal_source_parity,
)

START = 100_000_000


def _row(identity: str = "private-opportunity-123") -> dict[str, object]:
    ts = START + 400_000
    return {
        "opportunity_id": identity,
        "timestamp_ms": ts,
        "market": "PRIVATE_MARKET",
        "direction": "short",
        "lead_strategy": "breakout",
        "rank_ordinal": 3,
        "rank_age_ms": 100,
        "baseline_risk_approved": False,
        "baseline_risk_reason_codes": ["weekly_drawdown_lockout"],
        "combined_block_reason": None,
        "two_strike_prior_strikes": 2,
        "momentum_decision": None,
        "momentum_reason": None,
        "momentum_prior_strikes": None,
        "signed_return_1h": None,
        "signed_day_return": None,
        "stack_decision": "BLOCK",
        "block_layer": "two_strike",
        "markouts": {
            str(horizon): {
                "status": "settled",
                "target_at_ms": ts + horizon,
                "observed_at_ms": ts + horizon,
                "observation_lag_ms": 0,
                "mark_px": "101",
                "directional_return": "-0.05",
            }
            for horizon in (300_000, 900_000, 3_600_000)
        },
    }


def _ledger() -> dict[str, object]:
    summary = {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "candidate_stack": "combined+two_strike+momentum",
        "overlap_started_at_ms": START,
        "combined_started_at_ms": START - 2_000,
        "two_strike_started_at_ms": START - 1_000,
        "momentum_started_at_ms": START,
        "forward_horizons_ms": [300_000, 900_000, 3_600_000],
        "max_mark_lag_ms": 120_000,
        "risk_rejected_stack_evaluated": 1,
        "risk_rejected_integrity_clean": True,
        "risk_rejected_integrity_last_miss_at_ms": None,
        "risk_rejected_rows": [_row()],
    }
    return update_risk_rejected_forward_markout_ledger(
        summary,
        previous=None,
        source_paper_run_id=42,
        source_paper_run_attempt=1,
        source_artifact_name="signed-original",
        source_artifact_digest="sha256:" + "a" * 64,
    )


def _source(
    row: dict[str, object] | None = None,
    *,
    integrity_clean: bool = True,
    exposures: int = 0,
) -> dict[str, object]:
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "risk_rejected_integrity_clean": integrity_clean,
        "risk_rejected_stack_evaluated": 1 if row is not None else 0,
        "risk_rejected_rows": [row] if row is not None else [],
        "risk_rejected_journal_future_close_exposure_opportunities": exposures,
        "journal_asof_provenance": (
            "closed_trades_only_no_original_open_event_witness"
        ),
    }


def test_exact_sealed_rows_are_descriptive_not_promotion_authority() -> None:
    original = _ledger()
    source = _source(_row())
    report = audit_terminal_source_parity(original, source)
    assert report["previous_terminal_rows"] == 1
    assert report["previous_rows_unchanged"] == 1
    assert report["previous_rows_changed"] == 0
    assert report["previous_rows_missing"] == 0
    assert report["historical_terminal_parity"] is True
    assert report["research_readiness_blocked"] is False
    assert report["diagnostic_only"] is True
    assert report["research_readiness_grant"] is False
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
    assert report["accepted_ledger_sha256"] == original["ledger_sha256"]
    assert report["drift_receipts"] == []


def test_late_trade_history_drift_is_redacted_and_remains_blocked() -> None:
    original = _ledger()
    current = _row()
    current.update(
        {
            "two_strike_prior_strikes": 0,
            "momentum_decision": "BLOCK",
            "momentum_reason": "momentum_band",
            "momentum_prior_strikes": 0,
            "signed_return_1h": "secret-return-one",
            "signed_day_return": "secret-return-day",
            "block_layer": "momentum",
        }
    )
    report = audit_terminal_source_parity(
        original,
        _source(current, integrity_clean=False, exposures=2),
    )
    assert report["previous_rows_changed"] == 1
    assert report["changed_rows_classification_only"] == 1
    assert report["changed_rows_markout_drift"] == 0
    assert report["previous_rows_missing"] == 0
    assert report["source_future_finalized_open_exposures"] == 2
    assert report["source_integrity_clean"] is False
    assert report["historical_parity_blocked"] is True
    assert report["research_readiness_blocked"] is True
    receipt = report["drift_receipts"][0]
    assert receipt["opportunity_sha256_prefix"] == hashlib.sha256(
        b"private-opportunity-123"
    ).hexdigest()[:16]
    assert "/two_strike_prior_strikes" in receipt["changed_json_pointers"]
    assert receipt["markout_drift"] is False
    report_json = json.dumps(report)
    for value in (
        "private-opportunity-123",
        "PRIVATE_MARKET",
        "secret-return-one",
        "secret-return-day",
        "weekly_drawdown_lockout",
        "momentum_band",
        "-0.05",
    ):
        assert value not in report_json


def test_changed_price_outcome_is_not_masked_as_classification_drift() -> None:
    source_row = _row()
    source_row["markouts"]["3600000"]["directional_return"] = "-0.99"
    report = audit_terminal_source_parity(_ledger(), _source(source_row))
    assert report["changed_rows_markout_drift"] == 1
    assert report["changed_rows_classification_only"] == 0
    assert report["drift_receipts"][0]["markout_drift"] is True
    assert "/markouts/3600000/directional_return" in (
        report["drift_receipts"][0]["changed_json_pointers"]
    )
    assert report["historical_terminal_parity"] is False


def test_missing_historical_row_always_blocks_without_rewriting_ledger() -> None:
    original = _ledger()
    previous_serialized = json.dumps(original, sort_keys=True)
    report = audit_terminal_source_parity(original, _source(None))
    assert report["previous_rows_missing"] == 1
    assert report["previous_rows_changed"] == 0
    assert report["research_readiness_blocked"] is True
    assert report["missing_opportunity_sha256_prefixes"] == [
        hashlib.sha256(b"private-opportunity-123").hexdigest()[:16]
    ]
    assert json.dumps(original, sort_keys=True) == previous_serialized


def test_new_future_rows_are_not_spliced_into_old_immutable_history() -> None:
    source = _source(_row())
    source["risk_rejected_rows"].append(_row("next-opportunity"))
    source["risk_rejected_stack_evaluated"] = 2
    report = audit_terminal_source_parity(_ledger(), source)
    assert report["source_rows"] == 2
    assert report["previous_terminal_rows"] == 1
    assert report["previous_rows_unchanged"] == 1
    assert report["promotion_authority"] is False


def test_future_close_exposure_blocks_even_matching_terminal_rows() -> None:
    report = audit_terminal_source_parity(_ledger(), _source(_row(), exposures=1))
    assert report["historical_terminal_parity"] is True
    assert report["research_readiness_blocked"] is True


@pytest.mark.parametrize("change", ["duplicate", "authority", "count", "integrity", "exposure"])
def test_invalid_source_never_receives_a_parity_receipt(change: str) -> None:
    source = _source(_row())
    if change == "duplicate":
        source["risk_rejected_rows"].append(_row())
        source["risk_rejected_stack_evaluated"] = 2
    elif change == "authority":
        source["execution_authority"] = True
    elif change == "count":
        source["risk_rejected_stack_evaluated"] = 2
    elif change == "integrity":
        source["risk_rejected_integrity_clean"] = None
    else:
        source["risk_rejected_journal_future_close_exposure_opportunities"] = -1
    with pytest.raises(TerminalSourceParityError):
        audit_terminal_source_parity(_ledger(), source)


def test_old_ledger_digest_tamper_fails_closed() -> None:
    old = deepcopy(_ledger())
    old["ledger_sha256"] = "0" * 64
    with pytest.raises(ProspectiveRiskRejectedForwardMarkoutLedgerError):
        audit_terminal_source_parity(old, _source(_row()))


@pytest.mark.parametrize("limit", [0, -1, 13, True])
def test_invalid_receipt_limits_never_create_partial_evidence(limit: object) -> None:
    with pytest.raises(TerminalSourceParityError, match="receipt limit"):
        audit_terminal_source_parity(_ledger(), _source(_row()), receipt_limit=limit)
