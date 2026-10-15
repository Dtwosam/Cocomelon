"""A stale selected L2 lane or a captured gap never becomes v3 evidence."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayManifest, ReplayRecord, SourceRecordKind
from cocomelon.research import fresh_long_trend_forward_pair as study
from cocomelon.research.fresh_long_trend_source_integrity import (
    FreshLongTrendSourceError,
    audit_fresh_long_trend_original_records,
)

A = MarketId("", "AAA")
B = MarketId("", "BBB")
START = study.FORWARD_NOT_BEFORE_MS


def _record(
    at: int, *, market: MarketId = A, kind: str = "l2_book",
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at,
        source="captured-original-paper-market-fixture",
        schema_version=1,
        market=market.canonical,
        exchange_time_ms=at,
        event_key=f"{kind}:{market.canonical}:{at}",
        event_kind=kind,
        payload_json=json.dumps({
            "bids": [{"px": "99.9", "sz": "1000", "n": 1}],
            "asks": [{"px": "100.1", "sz": "1000", "n": 1}],
        }) if kind == "l2_book" else "{}",
    )


def _gap(at: int, *, market: MarketId | None = None) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=at,
        source="original-ws-gap-witness",
        schema_version=1,
        market=None if market is None else market.canonical,
        exchange_time_ms=at,
        event_key=f"gap:{at}",
        event_kind="data_gap",
        payload_json='{"started_ms":10,"ended_ms":15,"stream_id":"WS","reason":"lost"}',
    )


def _manifest(*, end: int | None = None, gap_refs: tuple[str, ...] = ()) -> ReplayManifest:
    from cocomelon.evidence.contracts import BaselineReplayConfig

    config = BaselineReplayConfig()
    return cast(ReplayManifest, SimpleNamespace(
        start_ms=START - 60_000,
        end_ms=START + study.MINIMUM_FORWARD_MS + 180_000
        if end is None else end,
        gap_refs=gap_refs,
        config_digest=config.config_digest,
        execution_config_version=config.execution.config_version,
        fee_schedule_id=config.execution.fee_schedule_id,
        feature_version=config.feature_version,
        strategy_version=config.strategy_version,
        risk_version=config.risk_version,
        replay_engine_version=config.replay_engine_version,
    ))


def _check(
    records: tuple[ReplayRecord, ...],
    *,
    selected_markets: tuple[MarketId, ...] = (A, B),
    manifest: ReplayManifest | None = None,
) -> dict[str, object]:
    return audit_fresh_long_trend_original_records(
        records, manifest=manifest or _manifest(),
        selected_markets=selected_markets,
        forward_not_before_ms=START,
    )


def test_market_common_horizon_requires_last_real_l2_for_each_market() -> None:
    # Densely captured genuine observations across the whole 72h horizon,
    # never only two sparse samples with a misleading calendar interval.
    rows = tuple(sorted((
        _record(START - 1, market=A),
        *(
            _record(START + step * 300_000, market=market)
            for step in range(865) for market in (A, B)
        ),
        _record(START + study.MINIMUM_FORWARD_MS + 10, market=A),
        _record(START + study.MINIMUM_FORWARD_MS + 11, market=B),
    ), key=lambda row: (row.available_at_ms, row.market or "")))
    report = _check(rows)
    assert report["recorded_source_gap_count"] == 0
    assert report["original_market_count"] == 2
    assert report["common_l2_forward_elapsed_ms"] == study.MINIMUM_FORWARD_MS + 10
    assert report["selected_market_post_embargo_l2_counts"] == {
        "AAA": 866, "BBB": 866,
    }
    assert report["local_canonical_record_stream_sha256"]
    assert report["continuous_l2_without_unrecorded_gaps_certified"] is False
    assert report["original_exchange_feed_independently_authenticated"] is False
    assert report["promotion_authority"] is False


def test_stale_market_cannot_borrow_active_other_market_or_calendar_end() -> None:
    rows = tuple(sorted((
        _record(START + 1, market=B),
        *(
            _record(START + step * 300_000, market=A)
            for step in range(865)
        ),
        _record(START + study.MINIMUM_FORWARD_MS + 41, market=A, kind="market_snapshot"),
    ), key=lambda row: (row.available_at_ms, row.market or "")))
    receipt = _check(rows)
    assert receipt["last_record_available_at_ms"] == START + study.MINIMUM_FORWARD_MS + 41
    assert receipt["common_selected_market_l2_end_ms"] == START + 1
    assert receipt["common_l2_forward_elapsed_ms"] == 1


def test_sparse_or_left_censored_l2_cannot_claim_72h_coverage() -> None:
    with pytest.raises(FreshLongTrendSourceError, match="L2 market drought"):
        _check((
            _record(START + 1, market=A),
            _record(START + 2, market=B),
            _record(START + study.MINIMUM_FORWARD_MS, market=A),
            _record(START + study.MINIMUM_FORWARD_MS + 1, market=B),
        ))
    with pytest.raises(FreshLongTrendSourceError, match="L2 market drought"):
        _check((
            _record(START + 301_000, market=A),
            _record(START + 301_001, market=B),
        ))


@pytest.mark.parametrize("when", [START - 2, START + 3])
@pytest.mark.parametrize("affected", [None, A])
def test_original_recorded_gap_never_credited_or_silently_ignored(
    when: int, affected: MarketId | None,
) -> None:
    rows = sorted(
        (_record(START + 1, market=A), _record(START + 2, market=B),
         _gap(when, market=affected)),
        key=lambda item: item.available_at_ms,
    )
    with pytest.raises(FreshLongTrendSourceError, match="original received DATA_GAP"):
        _check(tuple(rows))


@pytest.mark.parametrize("ref", ["gap:original", "historical-continuity-failed"])
def test_declared_manifest_gap_blocks_study_before_any_account(ref: str) -> None:
    with pytest.raises(FreshLongTrendSourceError, match="unresolved gaps"):
        _check(
            (_record(START + 1, market=A), _record(START + 2, market=B)),
            manifest=_manifest(gap_refs=(ref,)),
        )


def test_original_forward_extra_market_cannot_be_excluded_posthoc() -> None:
    rows = (
        _record(START + 1, market=A),
        _record(START + 2, market=B),
        _record(START + 3, market=MarketId("", "CCC")),
    )
    with pytest.raises(FreshLongTrendSourceError, match="posthoc selected-market subset"):
        _check(rows, selected_markets=(A, B))
    with pytest.raises(FreshLongTrendSourceError, match="posthoc selected-market subset"):
        _check((
            _record(START + 1, market=A),
            _record(START + 2, market=B),
            _record(START + 3, market=MarketId("", "CCC"),
                    kind="market_snapshot"),
        ), selected_markets=(A, B))


def test_complete_original_market_selection_preserves_nonpromotable_report() -> None:
    rows = (
        _record(START + 1, market=A),
        _record(START + 2, market=B),
    )
    receipt = _check(rows, selected_markets=(A, B))
    assert receipt["selected_market_covers_full_original_forward_universe"] is True
    assert receipt["all_original_forward_market_count"] == 2
    assert receipt["all_original_forward_l2_market_count"] == 2
    assert receipt["promotion_authority"] is False
    assert receipt["original_exchange_feed_independently_authenticated"] is False


def test_missing_market_l2_rejected_even_with_mature_other_market() -> None:
    with pytest.raises(FreshLongTrendSourceError, match="BBB"):
        _check((
            _record(START + 1, market=A),
            _record(START + 2, market=B, kind="market_snapshot"),
        ))


@pytest.mark.parametrize("bad_records", [
    (_record(START + 5, market=A), _record(START + 4, market=B)),
    (_record(START + 1, market=A), _record(START + 400_000_000, market=B)),
])
def test_out_of_order_or_outside_manifest_records_blocked(
    bad_records: tuple[ReplayRecord, ...],
) -> None:
    with pytest.raises(FreshLongTrendSourceError, match="source time"):
        _check(bad_records)


def test_absent_manifest_gap_list_is_not_empty_gap_evidence() -> None:
    missing = cast(ReplayManifest, SimpleNamespace(
        start_ms=START, end_ms=START + 1000,
    ))
    with pytest.raises(FreshLongTrendSourceError, match="identity missing"):
        _check(
            (_record(START + 1, market=A), _record(START + 2, market=B)),
            manifest=missing,
        )


def test_gap_or_no_l2_is_denied_before_v3_sqlite_directory_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cocomelon.domain.execution import PaperExecutionConfig
    from cocomelon.evidence.contracts import BaselineReplayConfig

    class OriginalStub:
        def __init__(
            self, *, root: Path, manifest: ReplayManifest,
            expected_manifest_id: str,
        ) -> None:
            del root, manifest, expected_manifest_id

        def verified_records(
            self, *, forward_not_before_ms: int,
        ) -> tuple[ReplayRecord, ...]:
            assert forward_not_before_ms == START
            return (_record(START + 1, market=A), _gap(START + 2))

    monkeypatch.setattr(study, "PinnedShortRankReplaySource", OriginalStub)
    # This test's synthetic source has no actual original sealed files.
    # Receipt-order validation is covered independently with real captured
    # source ZIP segments; keep this one focused on zero-gap denial.
    monkeypatch.setattr(
        study, "restore_original_v3_received_order",
        lambda _root, _manifest, rows: rows,
    )
    root = tmp_path / "must-remain-uncreated"
    with pytest.raises(FreshLongTrendSourceError, match="original received DATA_GAP"):
        study.run_digest_pinned_long_trend_matched_paper(
            source_root=tmp_path / "nonexistent-source",
            manifest=_manifest(),
            expected_manifest_id="0123456789abcdef01234567",
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(A,),
            account_root=root,
        )
    assert not root.exists()
