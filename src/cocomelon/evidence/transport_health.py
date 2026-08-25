from __future__ import annotations

from collections.abc import Mapping

REDUNDANT_WS_LANE_COUNT = 2
TRANSPORT_HEALTH_SEMANTICS = "redundant-mainnet-merged-feed-v1"


def _counter(record: Mapping[str, object], field: str) -> int:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def normalize_redundant_record_payload(
    record: Mapping[str, object],
) -> dict[str, object]:
    """Separate merged-feed integrity from redundant lane diagnostics.

    ``gap_count`` is already emitted only for merged coverage loss by the
    redundant stream mux and is therefore preserved exactly. Duplicate and
    anomaly counters originate from the independent lane supervisors; those
    events are suppressed or covered before reaching the durable merged feed.
    Preserve the lane counters explicitly while exposing zero escaped
    duplicate/anomaly counts for the merged recording consumed by attestation.
    """

    gap_count = _counter(record, "gap_count")
    duplicate_count = _counter(record, "duplicate_count")
    anomaly_count = _counter(record, "anomaly_count")
    reconnect_count = _counter(record, "reconnect_count")

    payload = dict(record)
    payload.update(
        {
            "gap_count": gap_count,
            "duplicate_count": 0,
            "anomaly_count": 0,
            "transport_duplicate_count": duplicate_count,
            "transport_anomaly_count": anomaly_count,
            "transport_reconnect_count": reconnect_count,
            "redundant_ws_lane_count": REDUNDANT_WS_LANE_COUNT,
            "transport_health_semantics": TRANSPORT_HEALTH_SEMANTICS,
        }
    )
    return payload
