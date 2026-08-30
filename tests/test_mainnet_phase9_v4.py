from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType

import pytest

from cocomelon.evaluation.mainnet_phase9 import MainnetPhase9Error, _canonical_digest


def _v4() -> ModuleType:
    return importlib.import_module("cocomelon.evaluation.mainnet_phase9_v4")


def _write_protocol(root: Path, payload: dict[str, object]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "protocol.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _expected_protocol() -> dict[str, object]:
    return {
        "schema_version": 1,
        "protocol": "v4-thesis-expiry-mainnet",
        "pinned_code_revision": "0c14c9cfa37c80babc65d050fed6d4465dcb9032",
        "replay_engine_version": "phase8-v3-thesis-expiry",
        "config_version": "phase9-baseline-replay-v3-thesis-expiry",
        "execution_config_version": "phase7-v2-4h-thesis-expiry",
        "entry_window_seconds": 2700,
        "capture_window_seconds": 18900,
        "max_position_age_seconds": 14400,
        "economic_claim": "none",
        "live_orders": False,
    }


def test_v4_phase9_identity_is_distinct_from_v3() -> None:
    module = _v4()
    assert module.V4_SNAPSHOT_NAME == "v4-phase9-frozen-snapshot"
    assert module.V4_EVALUATION_NAME == "v4-phase9-evaluation"
    assert module.V4_CANDIDATE_NAME == "v4-baseline-fixed"


def test_v4_source_protocol_is_exact_thesis_expiry_contract() -> None:
    assert _v4().V4_SOURCE_PROTOCOL == _expected_protocol()


def test_v4_corpus_protocol_accepts_only_exact_identity(tmp_path: Path) -> None:
    module = _v4()
    payload = _expected_protocol()
    _write_protocol(tmp_path, payload)

    observed = module._read_v4_corpus_protocol(tmp_path)

    assert observed == payload
    assert _canonical_digest(observed) == _canonical_digest(module.V4_SOURCE_PROTOCOL)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("protocol", "v3-lifecycle-aware-mainnet"),
        ("pinned_code_revision", "0" * 40),
        ("replay_engine_version", "phase8-v2-lifecycle-aware"),
        ("config_version", "phase9-baseline-replay-v2-lifecycle-aware"),
        ("execution_config_version", "phase7-v1"),
        ("entry_window_seconds", 5400),
        ("capture_window_seconds", 14400),
        ("max_position_age_seconds", 10800),
        ("economic_claim", "candidate_edge"),
        ("live_orders", True),
    ],
)
def test_v4_corpus_protocol_rejects_any_identity_drift(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    module = _v4()
    payload = _expected_protocol()
    payload[field] = value
    _write_protocol(tmp_path, payload)

    with pytest.raises(MainnetPhase9Error, match="V4 corpus protocol identity"):
        module._read_v4_corpus_protocol(tmp_path)


def test_v4_corpus_protocol_rejects_missing_protocol(tmp_path: Path) -> None:
    module = _v4()
    with pytest.raises(MainnetPhase9Error, match="V4 corpus protocol"):
        module._read_v4_corpus_protocol(tmp_path)
