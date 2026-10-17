"""Per-study PAPER L2 stall attribution is bounded and observational only."""
from __future__ import annotations

import time

import pytest

from cocomelon.continuous_paper import (
    _POSITION_RESEARCH_OBSERVER_NAMES,
    _CompositePositionResearchObserver,
)
from cocomelon.evidence.lifecycle import BaselineReplayPipeline


class _ResearchSink:
    def __init__(self, name: str, calls: list[str], *, slow: bool = False) -> None:
        self.name = name
        self.calls = calls
        self.slow = slow

    def observe_book(
        self, _positions: object, _instrument: object, _book: object,
        *, reference_price: object, now_ms: int,
    ) -> None:
        self.calls.append(f"book:{self.name}")
        if self.slow:
            time.sleep(0.008)

    def observe_mark(
        self, _positions: object, _mark: object, *, now_ms: int,
    ) -> None:
        self.calls.append(f"mark:{self.name}")

    def record_closed_trade(self, _trade: object) -> None:
        self.calls.append(f"close:{self.name}")


def test_position_stall_attribution_preserves_every_research_callback() -> None:
    calls: list[str] = []
    names = _POSITION_RESEARCH_OBSERVER_NAMES
    sinks = tuple(
        _ResearchSink(name, calls, slow=(name == "original_stop_book"))
        for name in names
    )
    composite = _CompositePositionResearchObserver(*sinks)  # type: ignore[arg-type]
    composite.observe_book(
        (), object(), object(), reference_price=object(), now_ms=123,
    )  # type: ignore[arg-type]
    composite.observe_mark((), object(), now_ms=124)  # type: ignore[arg-type]
    composite.record_closed_trade(object())  # type: ignore[arg-type]

    assert calls == [
        f"{kind}:{name}"
        for kind in ("book", "mark", "close")
        for name in names
    ]
    maxima = composite.max_ms_by_component
    assert len(maxima) == 30
    assert maxima["position_book_original_stop_book"] >= 5
    assert all(type(value) is int and value >= 0 for value in maxima.values())
    assert all(
        key == f"position_{kind}_{name}"
        for kind in ("book", "mark", "close")
        for name in names
        for key in (f"position_{kind}_{name}",)
    )
    # The exposed diagnostics cannot mutate internal instrumentation.
    maxima["position_book_original_stop_book"] = -1
    assert composite.max_ms_by_component["position_book_original_stop_book"] >= 5

    pipeline = object.__new__(BaselineReplayPipeline)
    pipeline._position_research_observer = composite
    pipeline._runtime_max_ms_by_component = {
        "l2_position_research_observer": 9,
    }
    merged = pipeline.runtime_max_ms_by_component
    assert merged["l2_position_research_observer"] == 9
    assert merged["position_book_original_stop_book"] >= 5
    assert len(merged) == 31


def test_composite_preserves_exception_and_records_failed_study_duration() -> None:
    calls: list[str] = []

    class Broken(_ResearchSink):
        def observe_book(
            self, _positions: object, _instrument: object, _book: object,
            *, reference_price: object, now_ms: int,
        ) -> None:
            self.calls.append(f"book:{self.name}")
            raise RuntimeError("research_observer_failure")

    sinks = [
        _ResearchSink(name, calls) for name in _POSITION_RESEARCH_OBSERVER_NAMES
    ]
    sinks[4] = Broken(_POSITION_RESEARCH_OBSERVER_NAMES[4], calls)
    composite = _CompositePositionResearchObserver(*sinks)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="research_observer_failure"):
        composite.observe_book(
            (), object(), object(), reference_price=object(), now_ms=123,
        )  # type: ignore[arg-type]
    assert calls == [
        f"book:{name}" for name in _POSITION_RESEARCH_OBSERVER_NAMES[:5]
    ]
    assert "position_book_net_reserved_trailing" in composite.max_ms_by_component
    assert "position_book_early_reserved_trailing" not in (
        composite.max_ms_by_component
    )


def test_position_research_observer_count_is_fixed() -> None:
    with pytest.raises(ValueError, match="identity count mismatch"):
        _CompositePositionResearchObserver()
    assert len(_POSITION_RESEARCH_OBSERVER_NAMES) == 10
