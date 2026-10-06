from __future__ import annotations

import json
from pathlib import Path

from cocomelon.research.continuous_paper_capacity_release_books import (
    CapacityReleaseBookStore,
)
from cocomelon.research.correlation_holder_release_execution import (
    correlation_holder_release_execution_summary,
)

DEFAULT_OUTPUT_NAME = "correlation-holder-release-execution-summary.json"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _records(state_root: Path):
    root = state_root / "capacity-release-books"
    protocol_path = root / "protocol.json"
    if not protocol_path.is_file():
        return ()
    raw = json.loads(protocol_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("capacity release protocol must be an object")
    started_at_ms = raw.get("capture_started_at_ms")
    latency_ms = raw.get("latency_ms")
    max_book_age_ms = raw.get("max_book_age_ms")
    if (
        isinstance(started_at_ms, bool)
        or not isinstance(started_at_ms, int)
        or isinstance(latency_ms, bool)
        or not isinstance(latency_ms, int)
        or isinstance(max_book_age_ms, bool)
        or not isinstance(max_book_age_ms, int)
    ):
        raise RuntimeError("capacity release protocol timing is invalid")
    store = CapacityReleaseBookStore(
        root,
        capture_started_at_ms=started_at_ms,
        latency_ms=latency_ms,
        max_book_age_ms=max_book_age_ms,
    )
    return store.iter_records()


def write_deferred_correlation_holder_release_execution(
    state_root: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    root = Path(state_root)
    target = (
        root / DEFAULT_OUTPUT_NAME
        if output_path is None
        else Path(output_path)
    )
    payload = correlation_holder_release_execution_summary(
        _records(root)
    )
    payload["deferred_post_handoff_rebuild"] = True
    payload["source_state_root"] = str(root)
    payload["strategy_authority"] = False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        _canonical_json(payload) + "\n",
        encoding="utf-8",
    )
    return target
