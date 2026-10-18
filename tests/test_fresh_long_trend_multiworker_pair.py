"""Only fresh contiguous original workers can enter the frozen v3 PAPER pair.

Synthetic fixtures test the workflow mechanics, NEVER Hyperliquid returns.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import (
    EvidenceClass, ReplayManifest, ReplayRecord, SourceRecordKind, SourceSegment,
)
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research import fresh_long_trend_multiworker_pair as study
from cocomelon.research.fresh_long_trend_forward_pair import FORWARD_NOT_BEFORE_MS
from cocomelon.research.fresh_long_trend_source_chain import (
    OriginalV3WorkerSourceWitness,
)

M = MarketId("", "TEST")
STEP = 240_000
HOURS_36 = 36 * 3_600_000


def _snapshot(timestamp: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=timestamp, source="synthetic-test-source",
        schema_version=1, market=M.canonical,
        exchange_time_ms=timestamp - 1,
        event_key=f"snapshot-{timestamp}", event_kind="market_snapshot",
        payload_json=json.dumps({
            "meta": {
                "wire_name": M.wire_name, "sz_decimals": 4,
                "max_leverage": 20, "margin_table_id": 1,
                "only_isolated": False, "is_delisted": False,
                "margin_mode": None,
            },
            "context": {
                "mark_px": "100", "mid_px": "100", "oracle_px": "100",
                "funding": "0", "open_interest": "1000000",
                "day_ntl_vlm": "500000000", "premium": "0",
                "prev_day_px": "101",
            },
        }, sort_keys=True),
    )


def _book(timestamp: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=timestamp, source="synthetic-test-source",
        schema_version=1, market=M.canonical,
        exchange_time_ms=timestamp - 1,
        event_key=f"book-{timestamp}", event_kind="l2_book",
        payload_json=json.dumps({
            "bids": [{"px": "99.9", "sz": "1000", "n": 1}],
            "asks": [{"px": "100.1", "sz": "1000", "n": 1}],
        }, sort_keys=True),
    )


def _fixture(
    tmp_path: Path, *,
    short_source: bool = False,
) -> tuple[
    BaselineReplayConfig,
    tuple[study.OriginalV3PinnedWorker, ...],
    dict[str, tuple[ReplayRecord, ...]],
]:
    cutoff = FORWARD_NOT_BEFORE_MS
    config = BaselineReplayConfig(execution=PaperExecutionConfig())
    first = (_snapshot(cutoff - 1000),) + tuple(
        _book(cutoff + 10 + t)
        for t in range(0, HOURS_36 + 1, STEP)
    )
    second = tuple(
        _book(cutoff + HOURS_36 + 70_000 + t)
        for t in range(0, HOURS_36 + 1, STEP)
    )
    if short_source:
        second = second[:3]
    result: list[study.OriginalV3PinnedWorker] = []
    sources: dict[str, tuple[ReplayRecord, ...]] = {}
    for number, rows, predecessor in ((101, first, None), (102, second, 101)):
        root = tmp_path / f"source-{number}"
        root.mkdir()
        segment = SourceSegment(
            relative_path=f"events/l2_book/TEST/segment-{number}.jsonl",
            partition="events/l2_book/TEST",
            sha256=f"{number:064x}",
            byte_count=100, row_count=len(rows), schema_version=1,
            first_available_at_ms=rows[0].available_at_ms,
            last_available_at_ms=rows[-1].available_at_ms,
        )
        manifest = ReplayManifest(
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            start_ms=rows[0].available_at_ms, end_ms=rows[-1].available_at_ms,
            segments=(segment,), gap_refs=(), code_revision="a" * 40,
            config_digest=config.config_digest,
            feature_version=config.feature_version,
            strategy_version=config.strategy_version,
            risk_version=config.risk_version,
            execution_config_version=config.execution.config_version,
            fee_schedule_id=config.execution.fee_schedule_id,
            replay_engine_version=config.replay_engine_version,
            dataset_manifest_id=None,
        )
        origin: dict[str, object] = {
            "run_id": number, "run_attempt": 1,
            "run_head_sha": "a" * 40,
            "original_artifact_id": number + 9000,
            "original_zip_sha256": f"{number + 5000:064x}",
            "manifest_id": manifest.manifest_id,
            "declared_predecessor_run_id": (
                str(predecessor) if predecessor is not None else None
            ),
            "declared_predecessor_run_attempt": (
                "1" if predecessor is not None else None
            ),
            "original_zip_bytes_match_supplied_github_digest": True,
            "supplied_github_run_job_artifact_identity_crosschecked": True,
            "source_records_not_changed_by_audit": True,
            "original_worker_link_receipt_matches_run": True,
            "signed_cross_worker_handoff_proven": False,
            "net_after_cost_profitability_proven": False,
            "promotion_authority": False,
            "execution_authority": False,
        }
        witness = OriginalV3WorkerSourceWitness(
            github_source=origin, manifest=manifest,
        )
        result.append(study.OriginalV3PinnedWorker(root, witness))
        sources[manifest.manifest_id] = rows
    return config, tuple(result), sources


class _FakePinned:
    loaded: dict[str, tuple[ReplayRecord, ...]] = {}

    def __init__(
        self, *, root: Path, manifest: ReplayManifest, expected_manifest_id: str,
    ) -> None:
        assert root.is_dir()
        assert expected_manifest_id == manifest.manifest_id
        self.manifest = manifest

    def verified_records(
        self, *, forward_not_before_ms: int,
    ) -> tuple[ReplayRecord, ...]:
        assert self.manifest.start_ms <= forward_not_before_ms
        assert forward_not_before_ms <= self.manifest.end_ms
        return self.loaded[self.manifest.manifest_id]


def _mock_source(
    monkeypatch: pytest.MonkeyPatch,
    sources: dict[str, tuple[ReplayRecord, ...]],
) -> None:
    _FakePinned.loaded = sources
    monkeypatch.setattr(study, "PinnedShortRankReplaySource", _FakePinned)
    # Production ordinal decoder is covered separately with real JSONL rows.
    monkeypatch.setattr(
        study, "restore_original_v3_received_order",
        lambda _root, _manifest, rows: rows,
    )


def test_two_worker_72h_original_paper_uses_same_records_and_net_cash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, workers, sources = _fixture(tmp_path)
    _mock_source(monkeypatch, sources)
    out = study.run_frozen_long_trend_multiworker_paper(
        workers=workers, config=config, selected_markets=(M,),
        account_root=tmp_path / "fresh-pair",
    )
    assert out["original_worker_count"] == 2
    assert out["source_original_row_count"] == sum(map(len, sources.values()))
    assert out["source_second_pass_exact_digest_and_row_parity"] is True
    assert out["actual_local_72h_common_l2_observed"] is True
    account = out["local_sqlite_paired_account_audit"]
    assert account["baseline"]["starting_cash_usd"] == "10000"
    assert account["candidate"]["starting_cash_usd"] == "10000"
    assert account["both_accounts_positive"] is False
    assert out["local_after_cost_economic_hurdle"][
        "positive_absolute_baseline_and_candidate_and_delta"
    ] is False
    for key in (
        "externally_witnessed_source_and_signed_handoff_continuity",
        "independent_mainnet_venue_completeness_certified",
        "whole_account_profitable_edge_verified",
        "promotion_authority", "execution_authority",
    ):
        assert out[key] is False


@pytest.mark.parametrize("failure", [
    "single_worker", "late_first", "short_72h", "broken_predecessor",
    "fee_drift", "source_gap", "backdated_handoff", "account_reuse",
    "source_account_overlap",
])
def test_broken_multiworker_archive_never_creates_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    config, workers, sources = _fixture(tmp_path, short_source=failure=="short_72h")
    _mock_source(monkeypatch, sources)
    root = tmp_path / "fresh-pair"
    if failure == "single_worker":
        workers = workers[:1]
    elif failure == "late_first":
        first = workers[0]
        changed = replace(
            first.witness.manifest,
            start_ms=FORWARD_NOT_BEFORE_MS + 1,
        )
        origin = dict(first.witness.github_source)
        origin["manifest_id"] = changed.manifest_id
        workers = (
            study.OriginalV3PinnedWorker(
                first.source_root,
                replace(first.witness, manifest=changed, github_source=origin),
            ), workers[1],
        )
    elif failure == "broken_predecessor":
        second = workers[1]
        origin = dict(second.witness.github_source)
        origin["declared_predecessor_run_id"] = "999"
        workers = (
            workers[0],
            study.OriginalV3PinnedWorker(
                second.source_root,
                replace(second.witness, github_source=origin),
            ),
        )
    elif failure == "fee_drift":
        second = workers[1]
        changed = replace(
            second.witness.manifest, fee_schedule_id="cheaper-paper-fees",
        )
        origin = dict(second.witness.github_source)
        origin["manifest_id"] = changed.manifest_id
        workers = (
            workers[0],
            study.OriginalV3PinnedWorker(
                second.source_root,
                replace(second.witness, manifest=changed, github_source=origin),
            ),
        )
    elif failure == "source_gap":
        second = workers[1]
        old = sources[second.witness.manifest.manifest_id]
        sources[second.witness.manifest.manifest_id] = old[:5] + old[8:]
    elif failure == "backdated_handoff":
        second = workers[1]
        old = sources[second.witness.manifest.manifest_id]
        sources[second.witness.manifest.manifest_id] = (
            _book(FORWARD_NOT_BEFORE_MS + 50), *old[1:]
        )
    elif failure == "account_reuse":
        root.mkdir()
        (root / "old-losses.txt").write_text("original account")
    elif failure == "source_account_overlap":
        root = workers[0].source_root / "output"
    with pytest.raises((ValueError, RuntimeError, AssertionError)):
        study.run_frozen_long_trend_multiworker_paper(
            workers=workers, config=config, selected_markets=(M,),
            account_root=root,
        )
    if failure not in {"account_reuse", "source_account_overlap"}:
        assert not root.exists()


def test_second_pass_mutation_does_not_publish_economic_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, workers, sources = _fixture(tmp_path)
    _mock_source(monkeypatch, sources)
    original = _FakePinned.verified_records
    reads = {"number": 0}

    def _switch(
        self: _FakePinned, *, forward_not_before_ms: int,
    ) -> tuple[ReplayRecord, ...]:
        rows = original(self, forward_not_before_ms=forward_not_before_ms)
        reads["number"] += 1
        # The second-pass first worker gets a changed original record,
        # still valid-shaped but with materially different payload.
        if reads["number"] == 3:
            return rows[:-1] + (replace(rows[-1], event_key="substitute"),)
        return rows

    monkeypatch.setattr(_FakePinned, "verified_records", _switch)
    with pytest.raises(study.OriginalV3MultiworkerPairError, match="source changed"):
        study.run_frozen_long_trend_multiworker_paper(
            workers=workers, config=config, selected_markets=(M,),
            account_root=tmp_path / "fresh-pair",
        )
