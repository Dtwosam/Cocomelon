from cocomelon.logging_utils import redact_mapping


def test_redacts_nested_secret_values() -> None:
    payload = {
        "market": "BTC",
        "secret_key": "0xabc",
        "nested": {"agent_private_key": "0xdef", "value": 12},
    }

    redacted = redact_mapping(payload)

    assert redacted["market"] == "BTC"
    assert redacted["secret_key"] == "[REDACTED]"
    assert redacted["nested"]["agent_private_key"] == "[REDACTED]"
    assert redacted["nested"]["value"] == 12
