from datetime import UTC, datetime, timedelta

from cocomelon.hyperliquid.ws_protocol import normalize_ws_message

RECEIVED = datetime(2026, 8, 24, 18, 0, tzinfo=UTC)


def test_identical_all_mids_value_at_new_receive_time_is_distinct_evidence() -> None:
    message = {"channel": "allMids", "data": {"mids": {"#11610": "0.87462"}}}

    first = normalize_ws_message(message, receive_time=RECEIVED)[0]
    second = normalize_ws_message(
        message,
        receive_time=RECEIVED + timedelta(seconds=71),
    )[0]

    assert first.payload == second.payload
    assert first.exchange_time_ms is None
    assert second.exchange_time_ms is None
    assert first.event_key != second.event_key
