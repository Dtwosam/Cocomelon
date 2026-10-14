from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cocomelon.research.full_depth_cadence_probe import DEFAULT_MARKETS
from cocomelon.research.paired_full_depth_source_screen import (
    BASELINE,
    CANDIDATE,
    ReceiptAuditError,
    _integrate,
    compare_sources,
    inspect_source,
)


def write_source(
    folder: Path, *,
    schema: str, spacing_ms: int, ended: datetime,
    short_depth: bool = False, bad_age: bool = False,
) -> tuple[Path, Path]:
    folder.mkdir(parents=True)
    duration = 180_050
    public = schema == BASELINE
    summary_path = folder / "summary.json"
    receipts_path = folder / "source-receipts.jsonl"
    lines: list[str] = []
    by_market: dict[str, dict[str, int | float]] = {}
    count = 0
    for market in DEFAULT_MARKETS:
        observed = []
        for idx, elapsed in enumerate(range(0, 180_001, spacing_ms)):
            exchange = 1_800_000_000_000 + elapsed
            level_count = 5 if short_depth and market == "BLUR" else 20
            obj = {
                "schema": schema,
                "market": market,
                "result": "unique",
                "receipt_elapsed_ms": elapsed,
                "receive_utc_ms": exchange,
                "source_age_ms": 100 if bad_age and idx == 2 and market == "BLUR" else 0,
                "bid_levels": level_count,
                "ask_levels": level_count,
                "raw_message_sha256" if public else "wire_sha256": hashlib.sha256(
                    f"{schema}:{market}:{idx}".encode()
                ).hexdigest(),
            }
            if public:
                obj["exchange_ms"] = exchange
            else:
                obj["exchange_time_ms"] = exchange
                obj["block_number"] = idx + 1
            lines.append(json.dumps(obj, sort_keys=True))
            observed.append((float(elapsed), int(obj["source_age_ms"]), level_count == 20))
            count += 1
        bps3 = _integrate(observed, duration, 3_000)
        bps5 = _integrate(observed, duration, 5_000)
        common = {
            "unique" if public else "unique_blocks": len(observed),
            "fresh_3s_time_fraction" if public else "full_depth_fresh3_time_fraction":
                round(bps3 / 10_000, 6),
            "fresh_5s_time_fraction" if public else "full_depth_fresh5_time_fraction":
                round(bps5 / 10_000, 6),
        }
        if not public:
            common.update({
                "height_regressions": 0,
                "time_regressions": 0,
                "conflicting_blocks": 0,
                "books_under_20_levels_per_side": int(short_depth and market == "BLUR")
                * len(observed),
                "future_dated_books": 0,
            })
        by_market[market] = common

    data = ("\n".join(lines) + "\n").encode()
    receipts_path.write_bytes(data)
    summary: dict[str, object] = {
        "schema": schema,
        "observation_window_completed": True,
        "duration_ms" if public else "elapsed_ms": duration,
        "market_cohort" if public else "cohort": list(DEFAULT_MARKETS),
        "receipts_sha256": hashlib.sha256(data).hexdigest(),
        "wall_clock_ended_utc" if public else "ended_utc": ended.isoformat(),
        "markets": by_market,
        "unique_books" if public else "unique_blocks": count,
    }
    if public:
        summary.update({"connections": 1, "connection_errors": 0, "protocol_errors": 0})
    else:
        summary.update({"stream_errors": 0, "parse_errors": 0, "n_levels_requested": 20})
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return summary_path, receipts_path


@pytest.fixture
def source_pair(tmp_path: Path) -> tuple[tuple[Path, Path], tuple[Path, Path]]:
    now = datetime(2026, 10, 14, 20, 50, tzinfo=UTC)
    baseline = write_source(tmp_path / "public", schema=BASELINE, spacing_ms=5000, ended=now)
    candidate = write_source(
        tmp_path / "candidate", schema=CANDIDATE, spacing_ms=1000, ended=now
    )
    return baseline, candidate


def test_paired_raw_evidence_passes_preliminary_source_screen_only(
    source_pair: tuple[tuple[Path, Path], tuple[Path, Path]],
) -> None:
    a, b = source_pair
    result = compare_sources(*a, *b)
    assert result["paired_windows"] is True
    assert result["paired_overlap_ms"] == 180_050
    assert result["baseline"]["minimum_fresh3_basis_points"] < 6_500
    assert result["candidate_minimum_fresh3_basis_points"] == 10_000
    assert result["preliminary_source_diagnostic_screen_passed"] is True
    for flag in (
        "source_completeness_certified", "signed_paper_evidence_reconciled",
        "production_source_switch_authorized", "live_trading_authorized",
        "profitability_verified",
    ):
        assert result[flag] is False
    assert result["account_or_order_state_changed"] is False


def test_noncontemporaneous_sources_never_count_as_paired(
    source_pair: tuple[tuple[Path, Path], tuple[Path, Path]],
) -> None:
    a, b = source_pair
    summary = json.loads(b[0].read_text())
    new_end = datetime.fromisoformat(summary["ended_utc"]) + timedelta(minutes=6)
    summary["ended_utc"] = new_end.isoformat()
    b[0].write_text(json.dumps(summary))
    report = compare_sources(*a, *b)
    assert report["paired_overlap_ms"] == 0
    assert report["paired_windows"] is False
    assert report["preliminary_source_diagnostic_screen_passed"] is False


def test_receipt_tamper_fails_even_if_summary_claims_pass(
    source_pair: tuple[tuple[Path, Path], tuple[Path, Path]],
) -> None:
    a, b = source_pair
    b[1].write_bytes(b[1].read_bytes().replace(b'"source_age_ms": 0', b'"source_age_ms": 1', 1))
    with pytest.raises(ReceiptAuditError, match="SHA-256"):
        compare_sources(*a, *b)


def test_source_age_arithmetic_mismatch_fails_after_valid_digest(tmp_path: Path) -> None:
    s, receipts = write_source(
        tmp_path / "modified", schema=CANDIDATE, spacing_ms=1000,
        ended=datetime(2026, 10, 14, tzinfo=UTC), bad_age=True,
    )
    with pytest.raises(ReceiptAuditError, match="arithmetic mismatch"):
        inspect_source(s, receipts, schema=CANDIDATE)


def test_five_level_candidate_cannot_qualify_as_20_by_20(tmp_path: Path) -> None:
    a, b = write_source(
        tmp_path / "shallow", schema=CANDIDATE, spacing_ms=1000,
        ended=datetime(2026, 10, 14, tzinfo=UTC), short_depth=True,
    )
    with pytest.raises(ReceiptAuditError, match="integrity or depth"):
        inspect_source(a, b, schema=CANDIDATE)


def test_summary_without_completed_window_is_rejected(
    source_pair: tuple[tuple[Path, Path], tuple[Path, Path]],
) -> None:
    a, b = source_pair
    summary = json.loads(a[0].read_text())
    summary["observation_window_completed"] = False
    a[0].write_text(json.dumps(summary))
    with pytest.raises(ReceiptAuditError, match="incomplete"):
        compare_sources(*a, *b)


def test_distinct_market_cohort_or_unseen_market_fails(
    source_pair: tuple[tuple[Path, Path], tuple[Path, Path]],
) -> None:
    a, b = source_pair
    summary = json.loads(b[0].read_text())
    summary["cohort"] = list(DEFAULT_MARKETS[:-1])
    b[0].write_text(json.dumps(summary))
    with pytest.raises(ReceiptAuditError, match="cohort differs"):
        compare_sources(*a, *b)


def test_replayed_blocks_do_not_inflate_freshness(
    source_pair: tuple[tuple[Path, Path], tuple[Path, Path]],
) -> None:
    a, b = source_pair
    rows = b[1].read_text().splitlines()
    obj = json.loads(rows[3])
    obj["result"] = "duplicate_block"
    rows[3] = json.dumps(obj, sort_keys=True)
    raw = ("\n".join(rows) + "\n").encode()
    b[1].write_bytes(raw)
    summary = json.loads(b[0].read_text())
    summary["receipts_sha256"] = hashlib.sha256(raw).hexdigest()
    b[0].write_text(json.dumps(summary))
    with pytest.raises(ReceiptAuditError, match="duplicate"):
        compare_sources(*a, *b)


def test_source_clock_report_cannot_overstate_raw_receipts(
    source_pair: tuple[tuple[Path, Path], tuple[Path, Path]],
) -> None:
    a, b = source_pair
    summary = json.loads(a[0].read_text())
    summary["markets"]["BLUR"]["fresh_3s_time_fraction"] = 1.0
    a[0].write_text(json.dumps(summary))
    with pytest.raises(ReceiptAuditError, match="freshness differs"):
        compare_sources(*a, *b)


def test_slow_full_depth_candidate_fails_per_market_95_percent_gate(tmp_path: Path) -> None:
    now = datetime(2026, 10, 14, 20, 50, tzinfo=UTC)
    a = write_source(tmp_path / "pub", schema=BASELINE, spacing_ms=5000, ended=now)
    b = write_source(tmp_path / "slow", schema=CANDIDATE, spacing_ms=4000, ended=now)
    report = compare_sources(*a, *b)
    assert report["paired_windows"] is True
    assert report["preliminary_source_diagnostic_screen_passed"] is False
    assert report["candidate_minimum_fresh3_basis_points"] < 9500
