from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.evaluation.mainnet_phase9 import (
    V3_CANDIDATE_NAME,
    V3_EVALUATION_NAME,
    V3_SNAPSHOT_NAME,
    V3_SOURCE_PROTOCOL,
    MainnetPhase9Error,
    _canonical_digest,
    _read_v3_corpus_protocol,
)


def _write_protocol(root: Path, payload: dict[str, object]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "protocol.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_v3_phase9_identity_is_distinct_from_v2() -> None:
    assert V3_SNAPSHOT_NAME == "v3-phase9-frozen-snapshot"
    assert V3_EVALUATION_NAME == "v3-phase9-evaluation"
    assert V3_CANDIDATE_NAME == "v3-baseline-fixed"


def test_v3_source_protocol_is_exact_repaired_four_hour_contract() -> None:
    assert V3_SOURCE_PROTOCOL == {
        "schema_version": 1,
        "protocol": "v3-lifecycle-aware-mainnet",
        "pinned_code_revision": "f8f84200dbc8b6fb262c5f6f99993b40714357be",
        "replay_engine_version": "phase8-v2-lifecycle-aware",
        "config_version": "phase9-baseline-replay-v2-lifecycle-aware",
        "entry_window_seconds": 2700,
        "capture_window_seconds": 14400,
        "economic_claim": "none",
        "live_orders": False,
    }


def test_v3_corpus_protocol_accepts_only_exact_identity(tmp_path: Path) -> None:
    payload = dict(V3_SOURCE_PROTOCOL)
    _write_protocol(tmp_path, payload)

    observed = _read_v3_corpus_protocol(tmp_path)

    assert observed == payload
    assert _canonical_digest(observed) == _canonical_digest(V3_SOURCE_PROTOCOL)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("protocol", "v2-mainnet"),
        ("pinned_code_revision", "0" * 40),
        ("replay_engine_version", "phase8-v1"),
        ("config_version", "phase9-baseline-replay-v2"),
        ("entry_window_seconds", 5400),
        ("capture_window_seconds", 5400),
        ("economic_claim", "candidate_edge"),
        ("live_orders", True),
    ],
)
def test_v3_corpus_protocol_rejects_any_identity_drift(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    payload = dict(V3_SOURCE_PROTOCOL)
    payload[field] = value
    _write_protocol(tmp_path, payload)

    with pytest.raises(MainnetPhase9Error, match="V3 corpus protocol identity"):
        _read_v3_corpus_protocol(tmp_path)


def test_v3_corpus_protocol_rejects_missing_protocol(tmp_path: Path) -> None:
    with pytest.raises(MainnetPhase9Error, match="V3 corpus protocol"):
        _read_v3_corpus_protocol(tmp_path)
