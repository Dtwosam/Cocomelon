from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_clean_observer as observer
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_archive_clean_evidence import (
    ArchiveCleanEvidenceStore,
)
from cocomelon.research.historical_archive_clean_observer import (
    ArchiveCleanFrozenRuntime,
    ArchiveCleanSourceCaptureStore,
    HistoricalArchiveCleanObserverError,
    collect_archive_clean_features,
    load_archive_clean_frozen_runtime,
    latest_closed_anchor_ms,
    run_archive_clean_observer_cycle,
    settle_archive_clean_due_signals,
)
from cocomelon.research.historical_archive_paper_scorer import (
    ArchivePaperAnchorResult,
    ArchivePaperSignal,
    ArchivePaperState,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)
from cocomelon.research.prospective_context_evidence import (
    PROSPECTIVE_EVIDENCE_CLASS,
)

FIVE = 300_000
FIFTEEN = 900_000
HOUR = 3_600_000
DAY = 86_400_000
MARKETS = ("BTC", "ETH", "HYPE", "SOL")


def _spec() -> HistoricalArchiveCleanValidationSpec:
    return HistoricalArchiveCleanValidationSpec(
        preset_name="test-preset",
        preset_id="preset-id",
        source_evidence_class="touched_development",
        validation_evidence_class=PROSPECTIVE_EVIDENCE_CLASS,
        candidate_id="a" * 64,
        training_plan_id="b" * 64,
        calibration_id="c" * 64,
        model_artifact_id="d" * 64,
        model_payload_sha256="e" * 64,
        model_family="stable_horizon_ridge",
        calibration_variant="shared",
        model_format="ridge-directional-json-v1",
        markets=MARKETS,
        anchor_interval="5m",
        anchor_interval_ms=FIVE,
        anchor_end_offset_ms=FIVE - 1,
        horizon_thresholds=((FIFTEEN, Decimal("0.001")),),
        allow_coin_calibration=False,
        min_sample_count=50,
        decision_policy="cost_adjusted_directional_threshold_v1",
        execution_policy="independent_horizon",
        max_concurrent_positions=None,
        costs={
            "round_trip_fee_fraction": "0.0007",
            "round_trip_slippage_fraction": "0.0005",
            "funding_reserve_fraction_per_hour": "0.0001",
        },
        validation_start_ms=0,
        validation_end_ms=45 * DAY,
        min_capture_coverage=Decimal("0.90"),
        min_settled_trades=80,
        stability_blocks=4,
        min_block_trades=15,
        min_mean_net_return=Decimal("0"),
        min_block_mean_net_return=Decimal("0"),
    )


def _raw_candle(
    market: str,
    interval: str,
    *,
    start_ms: int,
    interval_ms: int,
    close: Decimal,
) -> dict[str, object]:
    return {
        "t": start_ms,
        "T": start_ms + interval_ms - 1,
        "s": market,
        "i": interval,
        "o": str(close),
        "c": str(close),
        "h": str(close + Decimal("1")),
        "l": str(close - Decimal("1")),
        "v": "10",
        "n": 5,
    }


def _raw_funding(
    market: str,
    *,
    time_ms: int,
    value: str = "0.0001",
) -> dict[str, object]:
    return {
        "coin": market,
        "time": time_ms,
        "fundingRate": value,
        "premium": "0.0002",
    }


class FakeReader:
    def __init__(self, *, anchor_end_ms: int) -> None:
        self.anchor_end_ms = anchor_end_ms
        self.candle_calls: list[tuple[str, str, int, int]] = []
        self.funding_calls: list[tuple[str, int, int | None]] = []
        self.settlement_close_by_market: dict[str, Decimal] = {
            "BTC": Decimal("102"),
            "ETH": Decimal("98"),
            "HYPE": Decimal("101"),
            "SOL": Decimal("99"),
        }

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        self.candle_calls.append(
            (market.canonical, interval, start_ms, end_ms)
        )
        if interval == "5m" and end_ms == self.anchor_end_ms:
            starts = (
                self.anchor_end_ms - (2 * FIVE) + 1,
                self.anchor_end_ms - FIVE + 1,
            )
            return [
                _raw_candle(
                    market.canonical,
                    "5m",
                    start_ms=value,
                    interval_ms=FIVE,
                    close=Decimal("100") + Decimal(index),
                )
                for index, value in enumerate(starts)
            ]

        if interval == "15m" and end_ms == self.anchor_end_ms:
            latest_start = self.anchor_end_ms - FIFTEEN + 1
            starts = tuple(
                latest_start - (FIFTEEN * offset)
                for offset in range(21, -1, -1)
            )
            return [
                _raw_candle(
                    market.canonical,
                    "15m",
                    start_ms=value,
                    interval_ms=FIFTEEN,
                    close=Decimal("80") + Decimal(index),
                )
                for index, value in enumerate(starts)
                if value >= 0
            ]

        if interval == "5m":
            starts: list[int] = []
            cursor = start_ms - (start_ms % FIVE)
            if cursor < start_ms:
                cursor += FIVE
            while cursor + FIVE - 1 <= end_ms:
                starts.append(cursor)
                cursor += FIVE
            close = self.settlement_close_by_market[market.canonical]
            return [
                _raw_candle(
                    market.canonical,
                    "5m",
                    start_ms=value,
                    interval_ms=FIVE,
                    close=close,
                )
                for value in starts
            ]
        raise AssertionError(f"unexpected interval: {interval}")

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        self.funding_calls.append((market.canonical, start_ms, end_ms))
        assert end_ms is not None
        latest = end_ms - (end_ms % HOUR)
        return [
            _raw_funding(
                market.canonical,
                time_ms=latest - HOUR,
            ),
            _raw_funding(
                market.canonical,
                time_ms=latest,
            ),
        ]


class StepClock:
    def __init__(self, start_ms: int) -> None:
        self.value = start_ms

    def __call__(self) -> int:
        current = self.value
        self.value += 1
        return current


def _signal(
    spec: HistoricalArchiveCleanValidationSpec,
    *,
    market: str,
    anchor_end_ms: int,
    direction: Direction,
) -> ArchivePaperSignal:
    gross = (
        Decimal("0.02")
        if direction is Direction.LONG
        else Decimal("-0.02")
        if direction is Direction.SHORT
        else Decimal("0")
    )
    cost = Decimal("0.001225")
    return ArchivePaperSignal(
        candidate_id=spec.candidate_id,
        validation_spec_id=spec.spec_id,
        model_artifact_id=spec.model_artifact_id,
        market=market,
        anchor_end_ms=anchor_end_ms,
        horizon_ms=FIFTEEN,
        target_end_ms=anchor_end_ms + FIFTEEN,
        direction=direction,
        expected_long_gross_return=gross,
        expected_short_gross_return=-gross,
        expected_long_net_return=gross - cost,
        expected_short_net_return=-gross - cost,
        expected_net_edge=max(gross - cost, -gross - cost),
        cost_fraction=cost,
        threshold=Decimal("0.001"),
        sample_count=100,
        estimate_source="shared_ridge",
        reason_codes=(
            ("long_edge_selected",)
            if direction is Direction.LONG
            else ("short_edge_selected",)
            if direction is Direction.SHORT
            else ("edge_not_above_threshold",)
        ),
    )


def _scored_result(
    spec: HistoricalArchiveCleanValidationSpec,
    anchor_end_ms: int,
) -> ArchivePaperAnchorResult:
    raw = tuple(
        _signal(
            spec,
            market=market,
            anchor_end_ms=anchor_end_ms,
            direction=(
                Direction.LONG
                if market == "BTC"
                else Direction.SHORT
                if market == "ETH"
                else Direction.NO_TRADE
            ),
        )
        for market in MARKETS
    )
    accepted = tuple(item for item in raw if item.is_trade)
    return ArchivePaperAnchorResult(
        anchor_end_ms=anchor_end_ms,
        raw_signals=raw,
        accepted_signals=accepted,
        no_trade_markets=("HYPE", "SOL"),
        occupied_skip_markets=(),
        capacity_skip_markets=(),
        next_state=ArchivePaperState(),
    )



def _runtime_artifact(spec: HistoricalArchiveCleanValidationSpec) -> SimpleNamespace:
    return SimpleNamespace(
        artifact_id=spec.model_artifact_id,
        model_payload_sha256=spec.model_payload_sha256,
        candidate_id=spec.candidate_id,
        training_plan_id=spec.training_plan_id,
        calibration_id=spec.calibration_id,
        model_family=spec.model_family,
        calibration_variant=spec.calibration_variant,
        model_format=spec.model_format,
        selected_horizon_thresholds=spec.horizon_thresholds,
        allow_coin_calibration=spec.allow_coin_calibration,
        min_sample_count=spec.min_sample_count,
        execution_policy=spec.execution_policy,
        max_concurrent_positions=spec.max_concurrent_positions,
        costs=spec.costs,
        validation_not_before_ms=spec.validation_start_ms,
        execution_ready=False,
        promotion_eligible=False,
    )


def test_frozen_runtime_loads_files_without_rebuild_and_binds_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    artifact_value = _runtime_artifact(spec)
    monkeypatch.setattr(
        observer,
        "load_archive_candidate_model_artifact",
        lambda path: artifact_value,
    )
    monkeypatch.setattr(
        observer,
        "load_archive_clean_validation_spec",
        lambda path: spec,
    )

    runtime = load_archive_clean_frozen_runtime(tmp_path)

    assert runtime.artifact is artifact_value
    assert runtime.spec is spec


def test_frozen_runtime_rejects_model_spec_lineage_drift() -> None:
    spec = _spec()
    artifact_value = _runtime_artifact(spec)
    artifact_value.model_payload_sha256 = "9" * 64

    with pytest.raises(
        HistoricalArchiveCleanObserverError,
        match="ARCHIVE_CLEAN_RUNTIME_LINEAGE_MISMATCH",
    ):
        ArchiveCleanFrozenRuntime(
            artifact=artifact_value,  # type: ignore[arg-type]
            spec=spec,
        )

def test_latest_closed_anchor_uses_frozen_5m_end_offset() -> None:
    spec = _spec()

    assert latest_closed_anchor_ms(FIVE * 10 - 1, spec) == FIVE * 10 - 1
    assert latest_closed_anchor_ms(FIVE * 10, spec) == FIVE * 10 - 1
    assert latest_closed_anchor_ms(FIVE * 10 + 123_456, spec) == FIVE * 10 - 1


def test_feature_collection_reuses_historical_builder_and_persists_sources(
    tmp_path: Path,
) -> None:
    spec = _spec()
    anchor = 36 * FIFTEEN - 1
    reader = FakeReader(anchor_end_ms=anchor)
    source_store = ArchiveCleanSourceCaptureStore(tmp_path / "sources")

    collection = collect_archive_clean_features(
        reader,
        spec=spec,
        anchor_end_ms=anchor,
        clock_ms=StepClock(anchor + 1_000),
        source_store=source_store,
    )

    assert tuple(item.market.canonical for item in collection.features) == MARKETS
    assert all(item.anchor_end_ms == anchor for item in collection.features)
    assert all(item.schema_version == 3 for item in collection.features)
    assert all(item.retrieved_after_anchor for item in collection.features)
    assert len(collection.capture_ids) == 4
    assert all(
        tuple(item.source_manifest_ids) == collection.capture_ids
        for item in collection.features
    )
    assert len(tuple((tmp_path / "sources" / "feature").glob("*/*.json"))) == 4
    assert len(reader.funding_calls) == 4


def test_cycle_records_only_latest_anchor_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    anchor = 36 * FIFTEEN - 1
    reader = FakeReader(anchor_end_ms=anchor)
    evidence = ArchiveCleanEvidenceStore(tmp_path / "evidence", spec=spec)
    sources = ArchiveCleanSourceCaptureStore(tmp_path / "sources")
    scoring_calls = 0

    def fake_score(
        artifact: object,
        resolved_spec: HistoricalArchiveCleanValidationSpec,
        features: tuple[object, ...],
        *,
        state: ArchivePaperState | None = None,
    ) -> ArchivePaperAnchorResult:
        nonlocal scoring_calls
        scoring_calls += 1
        assert resolved_spec == spec
        assert state == ArchivePaperState()
        assert len(features) == 4
        return _scored_result(spec, anchor)

    monkeypatch.setattr(observer, "score_archive_candidate_anchor", fake_score)
    first_clock = StepClock(anchor + 1_000)
    first = run_archive_clean_observer_cycle(
        reader,
        artifact=SimpleNamespace(),  # type: ignore[arg-type]
        spec=spec,
        evidence_store=evidence,
        source_store=sources,
        clock_ms=first_clock,
    )

    assert first.status == "recorded"
    assert first.anchor_end_ms == anchor
    assert first.observation_id is not None
    assert scoring_calls == 1
    assert len(evidence.iter_anchors()) == 1

    calls_before = len(reader.candle_calls)
    second = run_archive_clean_observer_cycle(
        reader,
        artifact=SimpleNamespace(),  # type: ignore[arg-type]
        spec=spec,
        evidence_store=evidence,
        source_store=sources,
        clock_ms=StepClock(anchor + 2_000),
    )

    assert second.status == "already_recorded"
    assert second.observation_id == first.observation_id
    assert scoring_calls == 1
    assert len(reader.candle_calls) == calls_before


def test_cycle_does_not_backfill_missed_decision_anchors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    anchor = 36 * FIFTEEN - 1
    reader = FakeReader(anchor_end_ms=anchor)
    evidence = ArchiveCleanEvidenceStore(tmp_path / "evidence", spec=spec)
    sources = ArchiveCleanSourceCaptureStore(tmp_path / "sources")
    monkeypatch.setattr(
        observer,
        "score_archive_candidate_anchor",
        lambda *args, **kwargs: _scored_result(spec, anchor),
    )

    result = run_archive_clean_observer_cycle(
        reader,
        artifact=SimpleNamespace(),  # type: ignore[arg-type]
        spec=spec,
        evidence_store=evidence,
        source_store=sources,
        clock_ms=StepClock(anchor + 1_000),
    )

    assert result.status == "recorded"
    assert result.captured_elapsed_anchor_count == 1
    assert result.expected_elapsed_anchor_count > 1
    assert len(evidence.iter_anchors()) == 1


def test_settlement_requires_exact_target_candle_and_is_idempotent(
    tmp_path: Path,
) -> None:
    spec = _spec()
    anchor = 36 * FIFTEEN - 1
    evidence = ArchiveCleanEvidenceStore(tmp_path / "evidence", spec=spec)
    sources = ArchiveCleanSourceCaptureStore(tmp_path / "sources")
    features_reader = FakeReader(anchor_end_ms=anchor)
    collection = collect_archive_clean_features(
        features_reader,
        spec=spec,
        anchor_end_ms=anchor,
        clock_ms=StepClock(anchor + 1_000),
        source_store=sources,
    )
    evidence.record_anchor_result(
        features=collection.features,
        state_before=ArchivePaperState(),
        result=_scored_result(spec, anchor),
    )

    target = anchor + FIFTEEN
    settlement_reader = FakeReader(anchor_end_ms=anchor)
    result = settle_archive_clean_due_signals(
        settlement_reader,
        spec=spec,
        evidence_store=evidence,
        source_store=sources,
        clock_ms=StepClock(target + 1_000),
    )

    assert len(result.settled) == 2
    assert result.missing_signal_ids == ()
    assert {item.market for item in result.settled} == {"BTC", "ETH"}
    by_market = {item.market: item for item in result.settled}
    assert by_market["BTC"].gross_return == (
        by_market["BTC"].exit_px / by_market["BTC"].entry_px - Decimal("1")
    )
    assert by_market["ETH"].gross_return == -(
        by_market["ETH"].exit_px / by_market["ETH"].entry_px - Decimal("1")
    )
    assert len(evidence.iter_outcomes()) == 2

    repeated = settle_archive_clean_due_signals(
        settlement_reader,
        spec=spec,
        evidence_store=evidence,
        source_store=sources,
        clock_ms=StepClock(target + 2_000),
    )
    assert repeated.settled == ()
    assert evidence.due_unsettled_signals(as_of_ms=target + 2_000) == ()


def test_settlement_leaves_signal_due_when_exact_target_missing(
    tmp_path: Path,
) -> None:
    spec = _spec()
    anchor = 36 * FIFTEEN - 1
    evidence = ArchiveCleanEvidenceStore(tmp_path / "evidence", spec=spec)
    sources = ArchiveCleanSourceCaptureStore(tmp_path / "sources")
    feature_reader = FakeReader(anchor_end_ms=anchor)
    collection = collect_archive_clean_features(
        feature_reader,
        spec=spec,
        anchor_end_ms=anchor,
        clock_ms=StepClock(anchor + 1_000),
        source_store=sources,
    )
    evidence.record_anchor_result(
        features=collection.features,
        state_before=ArchivePaperState(),
        result=_scored_result(spec, anchor),
    )
    target = anchor + FIFTEEN

    class MissingReader(FakeReader):
        def candles(
            self,
            market: MarketId,
            interval: str,
            *,
            start_ms: int,
            end_ms: int,
        ) -> object:
            if interval == "5m" and end_ms >= target:
                self.candle_calls.append(
                    (market.canonical, interval, start_ms, end_ms)
                )
                return []
            return super().candles(
                market,
                interval,
                start_ms=start_ms,
                end_ms=end_ms,
            )

    missing_reader = MissingReader(anchor_end_ms=anchor)
    result = settle_archive_clean_due_signals(
        missing_reader,
        spec=spec,
        evidence_store=evidence,
        source_store=sources,
        clock_ms=StepClock(target + 1_000),
    )

    assert result.settled == ()
    assert len(result.missing_signal_ids) == 2
    assert len(evidence.due_unsettled_signals(as_of_ms=target + 2_000)) == 2
