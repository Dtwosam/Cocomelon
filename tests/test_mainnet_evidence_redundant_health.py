from __future__ import annotations

import importlib

import pytest


def _module():  # type: ignore[no-untyped-def]
    return importlib.import_module("cocomelon.evaluation.mainnet_evidence")


def _record(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "network_access": True,
        "live_orders": False,
        "gap_count": 0,
        "duplicate_count": 7,
        "anomaly_count": 2,
        "reconnect_count": 3,
    }
    payload.update(overrides)
    return payload


def _summary(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "recorded_gap_count": 0,
        "recorded_duplicate_count": 7,
        "recorded_anomaly_count": 2,
        "recorded_reconnect_count": 3,
    }
    payload.update(overrides)
    return payload


def test_redundant_lane_diagnostics_do_not_invalidate_gap_free_evidence() -> None:
    module = _module()

    module._require_redundant_record_health(_summary(), _record())


def test_redundant_record_health_still_rejects_merged_gap() -> None:
    module = _module()

    with pytest.raises(module.MainnetEvidenceError, match="gap_count"):
        module._require_redundant_record_health(
            _summary(recorded_gap_count=1),
            _record(gap_count=1),
        )


def test_redundant_record_health_cross_checks_lane_diagnostics() -> None:
    module = _module()

    with pytest.raises(module.MainnetEvidenceError, match="anomaly"):
        module._require_redundant_record_health(
            _summary(recorded_anomaly_count=1),
            _record(anomaly_count=2),
        )
