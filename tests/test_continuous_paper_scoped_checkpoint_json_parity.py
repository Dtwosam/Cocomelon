"""Fast immutable scoped-gap checkpoint snapshot must preserve exact JSON bytes."""
from __future__ import annotations

import json
from pathlib import Path

from cocomelon.continuous_paper import _checkpoint_payload, _load_checkpoint
from cocomelon.domain.market import MarketId


class _MutatingGaps:
    def __init__(self, count: int) -> None:
        self.open_lifecycle_checkpoints = ()
        self.unscoped_gap_intervals = ((5, None),)
        self.rows = [(100 + 10 * n, 105 + 10 * n) for n in range(count)]
        self.rows.append((100 + 10 * count, None))
        self.known_global_gap_intervals_by_stream = {
            "allMids": ((10, 20),),
        }

    @property
    def known_gap_intervals_by_stream(
        self,
    ) -> dict[str, tuple[tuple[int, int | None], ...]]:
        # Exactly the immutable tuple snapshot used by the real pipeline.
        return {"l2Book:TEST": tuple(self.rows)}


def _legacy_payload(gaps: _MutatingGaps) -> dict[str, object]:
    return {
        "schema_version": 3,
        "run_id": "continuous-paper",
        "last_available_at_ms": 200_000,
        "selected_markets": ["TEST"],
        "open_lifecycles": [],
        "known_gap_intervals": [[5, None]],
        "known_gap_intervals_by_stream": {
            "l2Book:TEST": [[start, end] for start, end in gaps.rows],
        },
        "known_global_gap_intervals_by_stream": {"allMids": [[10, 20]]},
        "execution_mode": "paper",
        "live_orders": False,
    }


def test_scoped_gap_tuples_emit_byte_identical_json_and_survive_restore(
    tmp_path: Path,
) -> None:
    gaps = _MutatingGaps(8_000)
    payload = _checkpoint_payload(
        gaps,  # type: ignore[arg-type]
        last_available_at_ms=200_000,
        selected_markets=(MarketId("", "TEST"),),
    )
    # The serializer, NOT Python container class, defines immutable
    # checkpoint v3 bytes. No gaps are omitted or compacted.
    old = _legacy_payload(gaps)
    old["run_id"] = payload["run_id"]
    def canonical(value: object) -> str:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        )
    assert canonical(payload) == canonical(old)
    saved = canonical(payload)
    # Mutation after snapshot cannot silently rewrite already captured gaps.
    gaps.rows.append((99_999, 100_000))
    assert canonical(payload) == saved
    persisted = tmp_path / "checkpoint.json"
    persisted.write_text(saved)
    lifecycles, unscoped, scoped, global_scoped, last_ms = _load_checkpoint(
        persisted,
    )
    assert lifecycles == ()
    assert unscoped == ((5, None),)
    assert scoped["l2Book:TEST"] == tuple(
        _MutatingGaps(8_000).rows,
    )
    assert global_scoped == {"allMids": ((10, 20),)}
    assert last_ms == 200_000


def test_scoped_gap_tuples_are_snapshot_isolated_per_stream() -> None:
    gaps = _MutatingGaps(2)
    first = _checkpoint_payload(
        gaps,  # type: ignore[arg-type]
        last_available_at_ms=200_000,
        selected_markets=(MarketId("", "TEST"),),
    )
    gaps.rows[0] = (200, 201)
    second = _checkpoint_payload(
        gaps,  # type: ignore[arg-type]
        last_available_at_ms=200_000,
        selected_markets=(MarketId("", "TEST"),),
    )
    assert first["known_gap_intervals_by_stream"] != (
        second["known_gap_intervals_by_stream"]
    )
    assert json.loads(json.dumps(first))["known_gap_intervals_by_stream"][
        "l2Book:TEST"
    ][0] == [100, 105]
