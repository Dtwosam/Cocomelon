from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import (
    Candle,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evaluation.dataset import build_evaluation_dataset
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.bundle import load_baseline_replay_bundle
from cocomelon.evidence.cli_support import (
    freeze_baseline_replay_payload,
    run_baseline_replay_payload,
)
from cocomelon.evidence.contracts import (
    EvidenceRecordingConfig,
    EvidenceRecordingSession,
    SelectedEvidenceMarket,
)
from cocomelon.evidence.recording import write_recording_session
from cocomelon.journal.store import JournalStore
from cocomelon.recorder import DurableRecorder

MARKET = MarketId("", "BTC")
INTERVAL_MS = 15 * 60 * 1_000
BOUNDARY_MS = 21 * INTERVAL_MS
WARMUP_RECEIVE_MS = BOUNDARY_MS - 20_000
EVALUATED_AT_MS = BOUNDARY_MS + 30_000
PRE_DECISION_BOOK_MS = EVALUATED_AT_MS - 1_000
TRIGGER_MS = EVALUATED_AT_MS + 1
OPEN_BOOK_MS = EVALUATED_AT_MS + 250
STOP_MARK_MS = EVALUATED_AT_MS + 500
CLOSE_BOOK_MS = EVALUATED_AT_MS + 800


def _dt(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def _snapshot() -> PerpMarketSnapshot:
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=MARKET,
            wire_name=MARKET.wire_name,
            sz_decimals=4,
            max_leverage=20,
            margin_table_id=1,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=MARKET,
            mark_px=Decimal("100"),
            mid_px=Decimal("100"),
            oracle_px=Decimal("100"),
            funding=Decimal("0"),
            open_interest=Decimal("1000000"),
            day_ntl_vlm=Decimal("500000000"),
            premium=Decimal("0"),
            prev_day_px=Decimal("99"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=WARMUP_RECEIVE_MS,
        schema_version=1,
    )


def _candle(index: int) -> Candle:
    trigger = index == 20
    close = Decimal("101") if trigger else Decimal("95")
    low = Decimal("96") if trigger else Decimal("90")
    high = Decimal("120") if trigger else Decimal("100")
    volume = Decimal("130") if trigger else Decimal("100")
    start_ms = index * INTERVAL_MS
    return Candle(
        market=MARKET,
        interval="15m",
        start_ms=start_ms,
        end_ms=start_ms + INTERVAL_MS,
        open_px=close,
        high_px=high,
        low_px=low,
        close_px=close,
        volume=volume,
        trade_count=100,
        source="hyperliquid-mainnet-info",
        received_at_ms=WARMUP_RECEIVE_MS,
        schema_version=1,
    )


def _book(timestamp_ms: int, *, bid: str, ask: str, suffix: str) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=timestamp_ms,
        receive_time=_dt(timestamp_ms),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"l2Book:BTC:{suffix}:{timestamp_ms}",
        payload={
            "bids": ({"px": Decimal(bid), "sz": Decimal("1000"), "n": 1},),
            "asks": ({"px": Decimal(ask), "sz": Decimal("1000"), "n": 1},),
        },
    )


def _trade_trigger() -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.TRADE,
        market=MARKET,
        exchange_time_ms=TRIGGER_MS,
        receive_time=_dt(TRIGGER_MS),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"trade:BTC:{TRIGGER_MS}",
        payload={
            "side": "B",
            "price": Decimal("100"),
            "size": Decimal("1"),
            "hash": "0xphase9bridge",
            "tid": 1,
            "users": ("0xa", "0xb"),
        },
    )


def _stop_mark() -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=None,
        receive_time=_dt(STOP_MARK_MS),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"activeAssetCtx:BTC:{STOP_MARK_MS}",
        payload={
            "mark_px": Decimal("95"),
            "mid_px": Decimal("95"),
            "oracle_px": Decimal("95"),
            "funding": Decimal("0"),
            "open_interest": Decimal("1000000"),
        },
    )


def _recording(root: Path) -> None:
    recording_config = EvidenceRecordingConfig(duration_seconds=3_600, deep_limit=1)
    session = EvidenceRecordingSession(
        started_at_ms=WARMUP_RECEIVE_MS - 1_000,
        recorder_code_revision="a" * 40,
        selected=(
            SelectedEvidenceMarket(
                market=MARKET,
                rank=1,
                feature_snapshot_id="recording-selection-feature",
                score=Decimal("80"),
            ),
        ),
        recording_config_digest=recording_config.config_digest,
        api_url=recording_config.api_url,
        ws_url=recording_config.ws_url,
        selection_policy_id=recording_config.selection_policy_id,
    )
    write_recording_session(root, session)
    recorder = DurableRecorder(root)
    recorder.append_market_snapshot(_snapshot())
    for index in range(21):
        recorder.append_candle(_candle(index))
    recorder.append_event(
        _book(
            PRE_DECISION_BOOK_MS,
            bid="99.99",
            ask="100.01",
            suffix="decision",
        )
    )
    recorder.append_event(_trade_trigger())
    recorder.append_event(
        _book(OPEN_BOOK_MS, bid="99.99", ask="100.01", suffix="open")
    )
    recorder.append_event(_stop_mark())
    recorder.append_event(
        _book(CLOSE_BOOK_MS, bid="94.99", ask="95.01", suffix="close")
    )


def _paths(tmp_path: Path, suffix: str) -> tuple[Path, Path, Path]:
    return (
        tmp_path / f"journal-{suffix}.sqlite3",
        tmp_path / f"execution-{suffix}.sqlite3",
        tmp_path / f"facts-{suffix}.sqlite3",
    )


def _dataset(
    journal_path: Path,
    facts_path: Path,
    *,
    run_id: str,
    code_revision: str,
):
    journal = JournalStore(journal_path)
    facts = EvaluationFactStore(facts_path)
    try:
        return build_evaluation_dataset(
            journal,
            facts,
            replay_run_ids=(run_id,),
            code_revision=code_revision,
        )
    finally:
        facts.close()
        journal.close()


def test_recorded_rows_replay_into_phase9_dataset_without_performance_claim(
    tmp_path: Path,
) -> None:
    root = tmp_path / "recording"
    bundle_path = tmp_path / "artifacts" / "bundle.json"
    _recording(root)
    freeze = freeze_baseline_replay_payload(root, bundle_path, Decimal("10000"))
    journal_path, execution_path, facts_path = _paths(tmp_path, "first")

    summary = run_baseline_replay_payload(
        bundle_path,
        journal_path,
        execution_path,
        facts_path,
    )
    bundle = load_baseline_replay_bundle(bundle_path)
    dataset = _dataset(
        journal_path,
        facts_path,
        run_id=str(summary["run_id"]),
        code_revision=bundle.manifest.code_revision,
    )

    assert summary["bundle_id"] == freeze["bundle_id"]
    assert summary["network_access"] is False
    assert summary["live_orders"] is False
    assert "edge" not in summary
    assert "profitable" not in summary
    assert summary["strategy_decisions"] >= 1
    assert summary["opened_positions"] == 1
    assert summary["closed_positions"] == 1
    assert len(summary["closed_trade_ids"]) == 1
    assert dataset.manifest.sources[0].result_digest == summary["result_digest"]
    assert dataset.manifest.trade_ids == tuple(summary["closed_trade_ids"])
    assert len(dataset.samples) == 1

    facts = EvaluationFactStore(facts_path)
    try:
        decision_facts = tuple(facts.iter_decision_facts())
    finally:
        facts.close()
    assert decision_facts
    assert decision_facts[0].feature_snapshot_id != "recording-selection-feature"


def test_same_bundle_is_deterministic_across_fresh_and_reopened_stores(tmp_path: Path) -> None:
    root = tmp_path / "recording"
    bundle_path = tmp_path / "artifacts" / "bundle.json"
    _recording(root)
    freeze_baseline_replay_payload(root, bundle_path, Decimal("10000"))
    bundle = load_baseline_replay_bundle(bundle_path)

    first_paths = _paths(tmp_path, "a")
    first = run_baseline_replay_payload(bundle_path, *first_paths)
    repeated = run_baseline_replay_payload(bundle_path, *first_paths)
    first_dataset = _dataset(
        first_paths[0],
        first_paths[2],
        run_id=str(first["run_id"]),
        code_revision=bundle.manifest.code_revision,
    )

    second_paths = _paths(tmp_path, "b")
    second = run_baseline_replay_payload(bundle_path, *second_paths)
    second_dataset = _dataset(
        second_paths[0],
        second_paths[2],
        run_id=str(second["run_id"]),
        code_revision=bundle.manifest.code_revision,
    )

    assert repeated == first
    assert second["result_digest"] == first["result_digest"]
    assert second["closed_trade_ids"] == first["closed_trade_ids"]
    assert second["final_account_state_id"] == first["final_account_state_id"]
    assert first_dataset.manifest.manifest_id == second_dataset.manifest.manifest_id
    assert tuple(sample.sample_id for sample in first_dataset.samples) == tuple(
        sample.sample_id for sample in second_dataset.samples
    )
