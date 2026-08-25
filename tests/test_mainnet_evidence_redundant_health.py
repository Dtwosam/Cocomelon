from __future__ import annotations

import importlib

import pytest


def _module():  # type: ignore[no-untyped-def]
    return importlib.import_module("cocomelon.evidence.transport_health")


def _transport_record(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "network_access": True,
        "live_orders": False,
        "gap_count": 0,
        "duplicate_count": 7,
        "anomaly_count": 2,
        "reconnect_count": 3,
        "event_count": 100,
        "session_id": "session-a",
    }
    payload.update(overrides)
    return payload


def test_normalization_preserves_lane_diagnostics_but_keeps_merged_feed_clean() -> None:
    module = _module()

    payload = module.normalize_redundant_record_payload(_transport_record())

    assert payload["duplicate_count"] == 0
    assert payload["anomaly_count"] == 0
    assert payload["transport_duplicate_count"] == 7
    assert payload["transport_anomaly_count"] == 2
    assert payload["transport_reconnect_count"] == 3
    assert payload["reconnect_count"] == 3
    assert payload["redundant_ws_lane_count"] == 2


def test_normalization_never_hides_merged_gap_count() -> None:
    module = _module()

    payload = module.normalize_redundant_record_payload(
        _transport_record(gap_count=4)
    )

    assert payload["gap_count"] == 4


def test_normalization_rejects_invalid_transport_counter() -> None:
    module = _module()

    with pytest.raises(ValueError, match="anomaly_count"):
        module.normalize_redundant_record_payload(
            _transport_record(anomaly_count=-1)
        )
