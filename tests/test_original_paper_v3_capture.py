"""Actual PAPER source must be complete before research ZIP sealing."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayRecord,
    SourceRecordKind,
)
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.replay.clock import canonical_record_order
from cocomelon.replay.source import JsonlReplaySource, validate_recording
from cocomelon.research.fresh_long_trend_forward_pair import FORWARD_NOT_BEFORE_MS
from cocomelon.research.original_paper_v3_capture import OriginalPaperMicrostructureCapture
from scripts.seal_original_paper_v3_source import (
    OriginalV3CaptureSealError,
    seal_original_paper_v3_source,
)

RUN = "1002345"
ATTEMPT = "1"
HEAD = "c" * 40


def _book(at: int, key: str) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at,
        source="original-hyperliquid-mainnet-ws",
        schema_version=1,
        market="TEST",
        exchange_time_ms=at - 3,
        event_key=key,
        event_kind="l2_book",
        payload_json=json.dumps({
            "bids": [{"px": "99.9", "sz": "1200", "n": 1}],
            "asks": [{"px": "100.1", "sz": "1200", "n": 1}],
        }),
    )


async def _capture(
    root: Path, rows: tuple[ReplayRecord, ...], *,
    config: BaselineReplayConfig | None = None,
) -> dict[str, object]:
    recorder = OriginalPaperMicrostructureCapture(
        root, run_id=RUN, run_attempt=ATTEMPT, head_sha=HEAD,
        selected_markets=("TEST",),
        first_observed_ms=FORWARD_NOT_BEFORE_MS - 120_000,
            replay_config=config or BaselineReplayConfig(),
    )
    for row in rows:
        recorder.offer(row)
    return await recorder.close()


def _seal(tmp: Path) -> dict[str, object]:
    return seal_original_paper_v3_source(
        capture_root=tmp / "original", upload_root=tmp / "upload",
        run_id=RUN, run_attempt=ATTEMPT, head_sha=HEAD,
    )


def test_exact_original_source_is_sealed_from_received_paper_records(
    tmp_path: Path,
) -> None:
    rows = (
        _book(FORWARD_NOT_BEFORE_MS - 1, "pre-embargo"),
        _book(FORWARD_NOT_BEFORE_MS + 1, "post-embargo"),
        _book(FORWARD_NOT_BEFORE_MS + 2, "later-book"),
    )
    capture = asyncio.run(_capture(tmp_path / "original", rows))
    assert capture["complete"] is True
    assert capture["offered_count"] == capture["written_count"] == 3
    receipt = _seal(tmp_path)
    assert receipt["original_received_record_count"] == 3
    assert receipt["original_post_embargo_l2_market_count"] == 1
    assert receipt["original_received_gap_count"] == 0
    assert receipt["original_continuity_across_workers_certified"] is False
    assert receipt["promotion_authority"] is False
    segments = validate_recording(tmp_path / "upload" / "microstructure")
    assert sum(seg.row_count for seg in segments) == 3
    manifest = json.loads((tmp_path / "upload" / "replay-manifest.json").read_text())
    assert manifest["manifest_id"] == receipt["manifest_id"]
    assert manifest["manifest"]["code_revision"] == HEAD
    assert manifest["manifest"]["config_digest"] == BaselineReplayConfig().config_digest
    assert manifest["manifest"]["execution_config_version"] == (
        BaselineReplayConfig().execution.config_version
    )
    assert manifest["manifest"]["fee_schedule_id"] == (
        BaselineReplayConfig().execution.fee_schedule_id
    )
    assert manifest["manifest"]["gap_refs"] == []
    assert manifest["manifest"]["start_ms"] == FORWARD_NOT_BEFORE_MS - 1


def test_same_millisecond_received_order_survives_partitioned_replay(
    tmp_path: Path,
) -> None:
    at = FORWARD_NOT_BEFORE_MS + 1
    # The original input is z BEFORE a, although a legacy canonical sort
    # would place event-key "a" before "z" for an equal-ms market book.
    incoming = (_book(at, "z-original-first"), _book(at, "a-original-second"))
    assert asyncio.run(_capture(tmp_path / "original", incoming))[
        "complete"
    ] is True
    receipt = _seal(tmp_path)
    assert receipt["original_source_receive_ordinals_preserved"] is True
    root = tmp_path / "upload" / "microstructure"
    segments = validate_recording(root)
    manifest = cast(ReplayManifest, SimpleNamespace(
        segments=segments,
        start_ms=at,
        end_ms=at,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    ))
    decoded = tuple(JsonlReplaySource(root).iter_records(manifest))
    assert [r.event_key for r in decoded] == [
        "z-original-first", "a-original-second",
    ]
    assert [r.source_receive_ordinal for r in decoded] == [1, 2]
    assert [r.event_key for r in canonical_record_order(tuple(reversed(decoded)))] == [
        "z-original-first", "a-original-second",
    ]


def test_capture_disk_failure_cannot_block_paper_or_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object) -> None:
        raise OSError("research disk failure")

    monkeypatch.setattr(OriginalPaperMicrostructureCapture, "_write_batch", fail)
    status = asyncio.run(_capture(
        tmp_path / "original", (_book(FORWARD_NOT_BEFORE_MS + 1, "failure"),)
    ))
    assert status["complete"] is False
    assert "write_failed" in str(status["failure"])
    with pytest.raises(OriginalV3CaptureSealError, match="lost rows"):
        _seal(tmp_path)
    assert not (tmp_path / "upload").exists()


def test_bounded_source_queue_overflow_permanently_blocks_research(
    tmp_path: Path,
) -> None:
    async def run() -> dict[str, object]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "original", run_id=RUN, run_attempt=ATTEMPT,
            head_sha=HEAD, selected_markets=("TEST",),
            first_observed_ms=FORWARD_NOT_BEFORE_MS,
            replay_config=BaselineReplayConfig(),
        )
        record = _book(FORWARD_NOT_BEFORE_MS + 1, "unchanged")
        for _ in range(16_390):
            recorder.offer(record)
        return await recorder.close()

    status = asyncio.run(run())
    assert status["dropped_count"] > 0
    assert status["complete"] is False
    assert status["failure"] == "original_capture_queue_overflow"
    with pytest.raises(OriginalV3CaptureSealError, match="lost rows"):
        _seal(tmp_path)


def test_no_post_embargo_book_cannot_be_invented(
    tmp_path: Path,
) -> None:
    assert asyncio.run(_capture(
        tmp_path / "original", (_book(FORWARD_NOT_BEFORE_MS - 2, "warmup"),)
    ))["complete"] is True
    with pytest.raises(OriginalV3CaptureSealError, match="post-embargo genuine"):
        _seal(tmp_path)


def test_original_worker_identity_and_untruncated_rows_required(
    tmp_path: Path,
) -> None:
    asyncio.run(_capture(
        tmp_path / "original", (_book(FORWARD_NOT_BEFORE_MS + 1, "real"),)
    ))
    with pytest.raises(OriginalV3CaptureSealError, match="changed identity"):
        seal_original_paper_v3_source(
            capture_root=tmp_path / "original",
            upload_root=tmp_path / "upload", run_id=RUN,
            run_attempt="2", head_sha=HEAD,
        )
    with (tmp_path / "original" / "original-received-rows.jsonl").open("ab") as f:
        f.write(b'{"record_kind":')
    with pytest.raises(OriginalV3CaptureSealError, match="torn original"):
        _seal(tmp_path)


def test_paper_workflow_seals_after_successor_without_lifting_trade_controls() -> None:
    workflow = Path(".github/workflows/continuous-paper.yml").read_text()
    assert 'V3_CAPTURE_ORIGINAL_SOURCE: "1"' in workflow
    assert "seal_original_paper_v3_source.py" in workflow
    assert "original_paper_v3_capture.py" in workflow
    s = workflow.index("- name: Queue exact successor from fast resume")
    f = workflow.index("- name: Queue fallback exact successor continuous paper worker")
    seal = workflow.index("- name: Seal frozen v3 original microstructure source")
    upload = workflow.index("- name: Upload frozen v3 original microstructure source")
    assert s < f < seal < upload
    assert "steps.seal_v3_original_source.outcome == 'success'" in workflow[seal:upload+400]
    assert "continuous-paper-v3-microstructure-" in workflow[upload:upload+500]
    assert "live_orders: true" not in workflow[seal:upload]


def test_raw_original_clock_regression_never_becomes_clamped_replay_evidence(
    tmp_path: Path,
) -> None:
    async def scenario() -> dict[str, object]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "original", run_id=RUN, run_attempt=ATTEMPT,
            head_sha=HEAD, selected_markets=("TEST",),
            first_observed_ms=FORWARD_NOT_BEFORE_MS - 10_000,
            replay_config=BaselineReplayConfig(),
        )
        recorder.offer(_book(FORWARD_NOT_BEFORE_MS + 2, "earlier-received"))
        recorder.offer(_book(FORWARD_NOT_BEFORE_MS + 1, "late-arrival"))
        return await recorder.close()

    status = asyncio.run(scenario())
    assert status["original_received_clock_regressions"] == 1
    assert status["first_original_received_clock_regression"] == {
        "original_available_at_ms": FORWARD_NOT_BEFORE_MS + 1,
        "prior_original_or_paper_available_at_ms": FORWARD_NOT_BEFORE_MS + 2,
        "original_event_key": "late-arrival",
        "original_market": "TEST",
    }
    assert status["paper_monotonic_clock_adjustment_not_used_as_source"] is True
    assert status["failure"] == "original_received_clock_regression"
    assert status["complete"] is False
    with pytest.raises(OriginalV3CaptureSealError, match="lost rows"):
        _seal(tmp_path)
    assert not (tmp_path / "upload").exists()


def test_first_record_older_than_restored_paper_checkpoint_fails_source(
    tmp_path: Path,
) -> None:
    async def scenario() -> dict[str, object]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "original", run_id=RUN, run_attempt=ATTEMPT,
            head_sha=HEAD, selected_markets=("TEST",),
            first_observed_ms=FORWARD_NOT_BEFORE_MS - 10_000,
            replay_config=BaselineReplayConfig(),
        )
        recorder.offer(
            _book(FORWARD_NOT_BEFORE_MS + 1, "first-arrival"),
            paper_previous_at_ms=FORWARD_NOT_BEFORE_MS + 5,
        )
        return await recorder.close()

    status = asyncio.run(scenario())
    assert status["original_received_clock_regressions"] == 1
    assert status["last_original_offered_available_at_ms"] == (
        FORWARD_NOT_BEFORE_MS + 1
    )
    assert status["first_original_received_clock_regression"][
        "prior_original_or_paper_available_at_ms"
    ] == FORWARD_NOT_BEFORE_MS + 5
    assert status["complete"] is False
    with pytest.raises(OriginalV3CaptureSealError, match="lost rows"):
        _seal(tmp_path)


def test_record_pump_preserves_raw_input_for_capture_before_clock_clamp(
    tmp_path: Path,
) -> None:
    from cocomelon.continuous_paper import _RecordPump

    class Pipeline:
        processed: list[tuple[int, int]]

        def __init__(self) -> None:
            self.processed = []

        def on_record(
            self, record: ReplayRecord, now_ms: int,
        ) -> tuple[object, ...]:
            self.processed.append((record.available_at_ms, now_ms))
            return ()

        def finalize(self, _now_ms: int) -> tuple[object, ...]:
            return ()

    class Journal:
        def iter_trades(self) -> tuple[object, ...]:
            return ()

        def record_observation(self, _value: object) -> None:
            raise AssertionError("no observations expected")

    async def scenario() -> tuple[dict[str, object], list[tuple[int, int]]]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "original", run_id=RUN, run_attempt=ATTEMPT,
            head_sha=HEAD, selected_markets=("TEST",),
            first_observed_ms=FORWARD_NOT_BEFORE_MS - 10_000,
            replay_config=BaselineReplayConfig(),
        )
        pipeline = Pipeline()
        pump = _RecordPump(
            pipeline,  # type: ignore[arg-type]
            Journal(),  # type: ignore[arg-type]
            last_available_at_ms=FORWARD_NOT_BEFORE_MS + 6,
            original_v3_capture=recorder,
        )
        await pump.process(
            _book(FORWARD_NOT_BEFORE_MS + 2, "genuine-received-unclamped")
        )
        return await recorder.close(), pipeline.processed

    status, received = asyncio.run(scenario())
    assert received == [(
        FORWARD_NOT_BEFORE_MS + 6, FORWARD_NOT_BEFORE_MS + 6,
    )]
    assert status["first_original_received_clock_regression"][
        "original_available_at_ms"
    ] == FORWARD_NOT_BEFORE_MS + 2
    assert status["last_original_offered_available_at_ms"] == (
        FORWARD_NOT_BEFORE_MS + 2
    )
    assert status["failure"] == "original_received_clock_regression"
    assert status["complete"] is False
    with pytest.raises(OriginalV3CaptureSealError, match="lost rows"):
        _seal(tmp_path)



def test_original_worker_custom_fee_schedule_not_silently_replaced_by_defaults(
    tmp_path: Path,
) -> None:
    from decimal import Decimal

    config = BaselineReplayConfig(
        execution=PaperExecutionConfig(
            taker_fee_rate=Decimal("0.0023"),
            fee_schedule_id="original-custom-paper-fees-v1",
        )
    )
    status = asyncio.run(_capture(
        tmp_path / "original",
        (_book(FORWARD_NOT_BEFORE_MS + 1, "custom-fee-original"),),
        config=config,
    ))
    assert status["complete"] is True
    assert status["original_effective_replay_config_digest"] == config.config_digest
    assert status["original_effective_fee_schedule_id"] == (
        "original-custom-paper-fees-v1"
    )
    receipt = _seal(tmp_path)
    assert receipt["original_effective_replay_config_digest"] == (
        config.config_digest
    )
    manifest = json.loads(
        (tmp_path / "upload" / "replay-manifest.json").read_text()
    )["manifest"]
    assert manifest["config_digest"] == config.config_digest
    assert manifest["fee_schedule_id"] == "original-custom-paper-fees-v1"
    assert manifest["execution_config_version"] == config.execution.config_version
    assert manifest["config_digest"] != BaselineReplayConfig().config_digest


def test_missing_original_effective_paper_fee_and_risk_identity_blocks_seal(
    tmp_path: Path,
) -> None:
    assert asyncio.run(_capture(
        tmp_path / "original",
        (_book(FORWARD_NOT_BEFORE_MS + 1, "fee-missing"),),
    ))["complete"] is True
    terminal = tmp_path / "original" / "original-capture-terminal.json"
    recorded = json.loads(terminal.read_text())
    recorded.pop("original_effective_replay_config_digest")
    terminal.write_text(json.dumps(recorded))
    with pytest.raises(
        OriginalV3CaptureSealError,
        match="original effective PAPER replay/fee identity unavailable",
    ):
        _seal(tmp_path)
    assert not (tmp_path / "upload").exists()

