from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cocomelon.research.forward_rest_depth_shadow import (
    COHORT,
    RestDepthShadow,
    RestShadowConfig,
)
from cocomelon.research.rest_depth_shadow_receipt_audit import (
    ShadowAuditError,
    audit_shadow_receipts,
)


def full_book(market: str, source_ms: int, *, depth: int = 20) -> dict[str, object]:
    return {
        "coin": market,
        "time": source_ms,
        "levels": [
            [{"px": str(200 - i), "sz": "2", "n": 1} for i in range(depth)],
            [{"px": str(201 + i), "sz": "2", "n": 1} for i in range(depth)],
        ],
    }


class NoHttpReader:
    def try_shadow_l2_book(self, market: object) -> tuple[bool, object | None]:
        raise AssertionError(f"auditing issued a network request for {market}")


def produce(
    directory: Path,
    *,
    missing: bool = False,
    missed: bool = False,
    shallow: bool = False,
    replay: bool = False,
    limited: bool = False,
) -> tuple[Path, Path]:
    directory.mkdir()
    start_ns = 1_000_000_000
    begin_utc = 1_800_000_000_000
    shadow = RestDepthShadow(
        NoHttpReader(),
        config=RestShadowConfig(enabled=True, duration_seconds=30),
        start_ns=start_ns,
    )
    receipts = directory / "shadow-attempts.jsonl"
    summary = directory / "summary.json"
    lines: list[str] = []
    for tick in range(30):
        for market in COHORT:
            if missing and tick == 12 and market == "BLUR":
                continue
            elapsed_ns = tick * 1_000_000_000
            now_utc = begin_utc + tick * 1_000
            if limited and tick > 10:
                row = shadow.record(
                    market, None,
                    now_ns=start_ns + elapsed_ns,
                    utc_ms=now_utc,
                    result="rate_limit_circuit_open",
                )
            elif limited and tick == 10 and market == "BLUR":
                row = shadow.record(
                    market, None,
                    now_ns=start_ns + elapsed_ns,
                    utc_ms=now_utc,
                    result="http_error",
                    is_rate_limit=True,
                )
            elif missed and tick == 12 and market == "BLUR":
                row = shadow.record(
                    market, None,
                    now_ns=start_ns + elapsed_ns,
                    utc_ms=now_utc,
                    result="missed_poll",
                )
            else:
                depth = 5 if shallow and tick == 12 and market == "BLUR" else 20
                time_ms = (
                    begin_utc + 10_000
                    if replay and market == "BLUR" and tick == 11
                    else now_utc - 300
                )
                row = shadow.record(
                    market, full_book(market, time_ms, depth=depth),
                    now_ns=start_ns + elapsed_ns,
                    utc_ms=now_utc,
                    result="ok",
                )
            row["slot_index"] = tick
            lines.append(json.dumps(row, sort_keys=True))
    raw = ("\n".join(lines) + "\n").encode()
    receipts.write_bytes(raw)
    report = shadow.summary(now_ns=start_ns + 30_000_000_000)
    report["ended_utc"] = begin_utc + 30_000
    report["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    report["observation_window_completed"] = (
        not (missing or missed or shallow or replay or limited)
    )
    summary.write_text(json.dumps(report))
    return summary, receipts


def mutate(
    pair: tuple[Path, Path],
    change: object,
) -> None:
    summ, receipts = pair
    rows = [json.loads(x) for x in receipts.read_text().splitlines()]
    assert callable(change)
    change(rows)
    raw = ("\n".join(json.dumps(x, sort_keys=True) for x in rows) + "\n").encode()
    receipts.write_bytes(raw)
    result = json.loads(summ.read_text())
    result["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    summ.write_text(json.dumps(result))


def test_three_market_30s_complete_receipt_slots_allow_research_only(
    tmp_path: Path,
) -> None:
    result = audit_shadow_receipts(*produce(tmp_path / "complete"))
    assert result["expected_slots"] == result["observed_slots"] == 90
    assert result["unique_20depth_books_by_market"] == {
        "BLUR": 30, "BOME": 30, "CASHCAT": 30,
    }
    assert result["observation_window_completed"] is True
    assert result["clean_research_receipts"] is True
    assert result["receipt_max_clock_drift_ms"] == 0
    for field in (
        "same_ip_external_processes_verified", "source_completeness_certified",
        "production_source_authorized", "paper_account_changed",
        "signed_gap_history_changed", "execution_authority",
        "profitability_verified",
    ):
        assert result[field] is False


def test_a_missing_poll_slot_is_rejected_even_with_matching_jsonl_digest(
    tmp_path: Path,
) -> None:
    with pytest.raises(ShadowAuditError, match="missing scheduled"):
        audit_shadow_receipts(*produce(tmp_path / "missing", missing=True))


def test_a_recorded_missed_poll_is_not_eligible_for_complete_window(
    tmp_path: Path,
) -> None:
    result = audit_shadow_receipts(*produce(tmp_path / "missed", missed=True))
    assert result["observation_window_completed"] is False
    assert result["clean_research_receipts"] is False


def test_shallow_and_source_clock_replay_fail_clean_source_eligibility(
    tmp_path: Path,
) -> None:
    result = audit_shadow_receipts(*produce(tmp_path / "shallow", shallow=True))
    assert result["observation_window_completed"] is False
    assert result["clean_research_receipts"] is False


def test_hash_mismatch_is_detected_without_trusting_summary(
    tmp_path: Path,
) -> None:
    summary, receipts = produce(tmp_path / "original")
    receipts.write_bytes(receipts.read_bytes() + b" \n")
    with pytest.raises(ShadowAuditError, match="SHA-256"):
        audit_shadow_receipts(summary, receipts)


def test_duplicate_slot_with_recomputed_sha_fails(
    tmp_path: Path,
) -> None:
    pair = produce(tmp_path / "dup")
    def forge(rows: list[dict[str, object]]) -> None:
        rows[3]["slot_index"] = rows[0]["slot_index"]
    mutate(pair, forge)
    with pytest.raises(ShadowAuditError, match="repeated market and scheduled slot"):
        audit_shadow_receipts(*pair)


def test_forged_exchange_age_with_recomputed_digest_is_rejected(
    tmp_path: Path,
) -> None:
    pair = produce(tmp_path / "fakeage")
    def forge(rows: list[dict[str, object]]) -> None:
        rows[4]["source_age_ms"] = 4
    mutate(pair, forge)
    with pytest.raises(ShadowAuditError, match="source-age arithmetic"):
        audit_shadow_receipts(*pair)


def test_forged_received_utc_clock_even_if_source_age_preserved_is_rejected(
    tmp_path: Path,
) -> None:
    pair = produce(tmp_path / "clock")
    def forge(rows: list[dict[str, object]]) -> None:
        rows[9]["receive_utc_ms"] = int(rows[9]["receive_utc_ms"]) + 9000
        rows[9]["exchange_ms"] = int(rows[9]["exchange_ms"]) + 9000
    mutate(pair, forge)
    with pytest.raises(ShadowAuditError, match="wall/monotonic clocks"):
        audit_shadow_receipts(*pair)


def test_forged_summary_freshness_is_not_trusted(
    tmp_path: Path,
) -> None:
    pair = produce(tmp_path / "freshness")
    report = json.loads(pair[0].read_text())
    report["markets"]["BLUR"]["full_depth_source_fresh_3000_fraction"] = 0.01
    pair[0].write_text(json.dumps(report))
    with pytest.raises(ShadowAuditError, match="freshness differs"):
        audit_shadow_receipts(*pair)


def test_summary_end_clock_tamper_cannot_fake_window(
    tmp_path: Path,
) -> None:
    pair = produce(tmp_path / "fakeend")
    report = json.loads(pair[0].read_text())
    report["ended_utc"] = int(report["ended_utc"]) + 60_000
    pair[0].write_text(json.dumps(report))
    with pytest.raises(ShadowAuditError, match="summary end UTC"):
        audit_shadow_receipts(*pair)


def test_bad_authority_or_ip_attestation_rejected(
    tmp_path: Path,
) -> None:
    pair = produce(tmp_path / "badAuthority")
    report = json.loads(pair[0].read_text())
    report["other_process_ip_weight_verified"] = True
    pair[0].write_text(json.dumps(report))
    with pytest.raises(ShadowAuditError, match="unsafe authority or IP"):
        audit_shadow_receipts(*pair)



def test_429_circuit_fails_completion_and_preserves_all_future_non_source_slots(
    tmp_path: Path,
) -> None:
    result = audit_shadow_receipts(*produce(tmp_path / "429", limited=True))
    assert result["expected_slots"] == result["observed_slots"] == 90
    assert result["observation_window_completed"] is False
    assert result["clean_research_receipts"] is False


def test_forged_http_after_429_circuit_is_rejected_with_rehashed_receipts(
    tmp_path: Path,
) -> None:
    pair = produce(tmp_path / "continued", limited=True)
    def forge(rows: list[dict[str, object]]) -> None:
        # A different market would be contacted on a later tick despite the
        # account-wide low-priority REST circuit being open.
        row = next(
            item for item in rows
            if item["market"] == "BLUR" and item["slot_index"] == 11
        )
        row["status"] = "shared_budget_skipped"
    mutate(pair, forge)
    with pytest.raises(ShadowAuditError, match="continued after rate-limit"):
        audit_shadow_receipts(*pair)


def test_forged_rate_limit_circuit_flag_must_match_original_429_receipts(
    tmp_path: Path,
) -> None:
    pair = produce(tmp_path / "circuitMissing", limited=True)
    summary = json.loads(pair[0].read_text())
    summary["rate_limit_circuit_open"] = False
    pair[0].write_text(json.dumps(summary))
    with pytest.raises(ShadowAuditError, match="circuit flag"):
        audit_shadow_receipts(*pair)
