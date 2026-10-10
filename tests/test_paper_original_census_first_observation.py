"""Original census must never be created from a replayed old decision."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cocomelon import continuous_paper as paper


class _OpportunityStore:
    def __init__(self) -> None:
        self.existing: set[str] = set()
        self.calls = 0

    def record(self, evidence: SimpleNamespace) -> bool:
        self.calls += 1
        if evidence.opportunity_id in self.existing:
            return False
        self.existing.add(evidence.opportunity_id)
        return True


class _CensusStore:
    def __init__(self, *, failure: bool = False) -> None:
        self.calls: list[tuple[object, tuple[object, ...], int]] = []
        self.failure = failure

    def record(
        self,
        evidence: object,
        positions: tuple[object, ...],
        *,
        recorded_at_ms: int,
    ) -> bool:
        self.calls.append((evidence, positions, recorded_at_ms))
        if self.failure:
            raise RuntimeError("first census write failed")
        return True


def _sink(
    opportunity_store: _OpportunityStore,
    census: _CensusStore,
    *,
    positions: tuple[object, ...],
) -> paper._ContinuousOpeningOpportunitySink:
    register = SimpleNamespace(register=lambda **kwargs: None)
    return paper._ContinuousOpeningOpportunitySink(
        opportunity_store,  # type: ignore[arg-type]
        register,  # type: ignore[arg-type]
        register,  # type: ignore[arg-type]
        register,  # type: ignore[arg-type]
        SimpleNamespace(register_from_trace=lambda *args, **kwargs: None),  # type: ignore[arg-type]
        SimpleNamespace(snapshot_for_market=lambda *args, **kwargs: None),  # type: ignore[arg-type]
        inventory_store=census,  # type: ignore[arg-type]
        position_provider=lambda: positions,
    )


def _trace() -> SimpleNamespace:
    return SimpleNamespace(
        evaluation=SimpleNamespace(
            decision=SimpleNamespace(market=SimpleNamespace(canonical="ADA"))
        ),
        risk_request=SimpleNamespace(timestamp_ms=200),
    )


def _evidence() -> SimpleNamespace:
    return SimpleNamespace(
        opportunity_id="original-opportunity",
        market="ADA",
        direction="short",
        opportunity_timestamp_ms=200,
    )


def test_replayed_opportunity_cannot_backfill_missing_first_census(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _OpportunityStore()
    original.existing.add("original-opportunity")
    census = _CensusStore()
    sink = _sink(
        original, census,
        positions=(SimpleNamespace(opening_plan_id="future-state"),),
    )
    monkeypatch.setattr(
        paper, "opportunity_evidence_from_trace",
        lambda *args, **kwargs: _evidence(),
    )

    sink.record_opening_trace(_trace())  # type: ignore[arg-type]

    assert original.calls == 1
    assert census.calls == []
    assert sink.inventory_error is None
    assert sink.error is None


def test_new_opportunity_census_captured_once_but_never_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _OpportunityStore()
    census = _CensusStore()
    old_position = SimpleNamespace(opening_plan_id="original-plan")
    current_positions: list[object] = [old_position]
    sink = _sink(original, census, positions=())
    # A mutable provider simulates a later recovered account snapshot.
    sink._position_provider = lambda: tuple(current_positions)
    monkeypatch.setattr(
        paper, "opportunity_evidence_from_trace",
        lambda *args, **kwargs: _evidence(),
    )

    sink.record_opening_trace(_trace())  # type: ignore[arg-type]
    assert len(census.calls) == 1
    assert census.calls[0][1] == (old_position,)
    current_positions.append(SimpleNamespace(opening_plan_id="late-plan"))
    sink.record_opening_trace(_trace())  # type: ignore[arg-type]

    assert original.calls == 2
    assert len(census.calls) == 1
    assert sink.error is None
    assert sink.inventory_error is None


def test_first_census_failed_write_cannot_be_hidden_by_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _OpportunityStore()
    census = _CensusStore(failure=True)
    sink = _sink(original, census, positions=())
    monkeypatch.setattr(
        paper, "opportunity_evidence_from_trace",
        lambda *args, **kwargs: _evidence(),
    )

    sink.record_opening_trace(_trace())  # type: ignore[arg-type]
    assert sink.error is None
    assert sink.inventory_error == "RuntimeError: first census write failed"
    assert len(census.calls) == 1
    census.failure = False
    sink.record_opening_trace(_trace())  # type: ignore[arg-type]

    assert len(census.calls) == 1
    assert sink.inventory_error == "RuntimeError: first census write failed"


def test_research_source_marks_census_capture_failure_as_ineligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        paper,
        "prospective_full_stack_forward_markout_summary",
        lambda *args: {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "risk_rejected_integrity_clean": True,
        },
    )
    empty = SimpleNamespace(iter_records=lambda: ())
    journal = SimpleNamespace(iter_trades=lambda: ())
    paths = SimpleNamespace(iter_paths=lambda: ())
    state = SimpleNamespace(started_at_ms=100)

    failed = paper._prospective_full_stack_forward_markout_payload(
        empty, paths, journal, empty, state, state, state,  # type: ignore[arg-type]
        inventory_capture_error="RuntimeError: first census write failed",
    )
    clean = paper._prospective_full_stack_forward_markout_payload(
        empty, paths, journal, empty, state, state, state,  # type: ignore[arg-type]
    )
    assert failed["enabled"] is True
    assert failed["risk_rejected_integrity_clean"] is False
    assert failed["original_open_inventory_capture_clean"] is False
    assert failed["original_open_inventory_capture_error"] == (
        "RuntimeError: first census write failed"
    )
    assert clean["risk_rejected_integrity_clean"] is True
    assert clean["original_open_inventory_capture_clean"] is True
    assert failed["execution_authority"] is False
    assert failed["promotion_authority"] is False
