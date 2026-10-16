"""Phase-level checkpoint timing is research telemetry only, not state mutation."""
from __future__ import annotations

import json
from types import SimpleNamespace

from cocomelon.continuous_paper import _checkpoint_payload
from cocomelon.domain.market import MarketId


def test_checkpoint_phase_telemetry_preserves_exact_payload_and_gap_lineage() -> None:
    state = SimpleNamespace(
        open_lifecycle_checkpoints=(),
        unscoped_gap_intervals=((5, None), (10, 25)),
        known_gap_intervals_by_stream={
            "l2Book:TEST": ((100, None), (200, 220)),
        },
        known_global_gap_intervals_by_stream={
            "allMids": ((1, 15),),
        },
    )
    kwargs = {
        "last_available_at_ms": 123456,
        "selected_markets": (MarketId("", "TEST"),),
    }
    original = _checkpoint_payload(state, **kwargs)  # type: ignore[arg-type]
    timings: dict[str, int] = {}
    observed = _checkpoint_payload(  # type: ignore[arg-type]
        state, **kwargs, stage_timings_ms=timings,
    )
    assert json.dumps(original, sort_keys=True) == json.dumps(
        observed, sort_keys=True,
    )
    assert observed["known_gap_intervals"] == [[5, None], [10, 25]]
    assert observed["known_gap_intervals_by_stream"] == {
        "l2Book:TEST": [[100, None], [200, 220]],
    }
    assert observed["known_global_gap_intervals_by_stream"] == {
        "allMids": [[1, 15]],
    }
    assert set(timings) == {
        "checkpoint_open_lifecycles",
        "checkpoint_unscoped_gaps",
        "checkpoint_scoped_gaps",
        "checkpoint_global_gaps",
    }
    assert all(type(value) is int and value >= 0 for value in timings.values())
    assert observed["execution_mode"] == "paper"
    assert observed["live_orders"] is False


def test_phase_timings_do_not_enter_durable_checkpoint_schema() -> None:
    state = SimpleNamespace(
        open_lifecycle_checkpoints=(),
        unscoped_gap_intervals=(),
        known_gap_intervals_by_stream={},
        known_global_gap_intervals_by_stream={},
    )
    timings: dict[str, int] = {}
    payload = _checkpoint_payload(
        state,  # type: ignore[arg-type]
        last_available_at_ms=1,
        selected_markets=(MarketId("", "TEST"),),
        stage_timings_ms=timings,
    )
    assert timings
    assert all("checkpoint_" not in key for key in payload)
    assert payload["schema_version"] == 3
