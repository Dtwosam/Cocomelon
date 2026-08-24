from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest

from cocomelon.cli import build_parser
from cocomelon.config import ExecutionMode, Settings


def _support_module():
    return import_module("cocomelon.evidence.cli_support")


def test_record_mainnet_evidence_parser_is_public_capture_only() -> None:
    args = build_parser().parse_args(
        [
            "record-mainnet-evidence",
            "--root",
            "/tmp/evidence",
            "--seconds",
            "3600",
            "--deep-limit",
            "20",
        ]
    )

    assert args.command == "record-mainnet-evidence"
    assert args.root == Path("/tmp/evidence")
    assert args.seconds == 3600
    assert args.deep_limit == 20
    for forbidden in (
        "wallet",
        "private_key",
        "secret",
        "user",
        "order",
        "withdraw",
        "transfer",
        "live_ack",
    ):
        assert not hasattr(args, forbidden)


def test_record_mainnet_evidence_rejects_live_mode_before_runner(tmp_path: Path) -> None:
    support = _support_module()
    called = False

    def runner(settings, root, config):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        return {"unexpected": True}

    with pytest.raises(ValueError, match="paper mode"):
        support.record_mainnet_evidence_payload(
            Settings(execution_mode=ExecutionMode.LIVE),
            root=tmp_path,
            seconds=60,
            deep_limit=5,
            runner=runner,
        )
    assert called is False


def test_record_mainnet_evidence_rejects_non_mainnet_endpoints(tmp_path: Path) -> None:
    support = _support_module()

    def runner(settings, root, config):  # type: ignore[no-untyped-def]
        raise AssertionError("invalid endpoint must fail before runner")

    with pytest.raises(ValueError, match="mainnet"):
        support.record_mainnet_evidence_payload(
            Settings(api_url="https://api.hyperliquid-testnet.xyz"),
            root=tmp_path,
            seconds=60,
            deep_limit=5,
            runner=runner,
        )


def test_record_mainnet_evidence_payload_freezes_requested_public_config(tmp_path: Path) -> None:
    support = _support_module()
    observed: dict[str, object] = {}

    def runner(settings, root, config):  # type: ignore[no-untyped-def]
        observed["settings"] = settings
        observed["root"] = root
        observed["config"] = config
        return {
            "session_id": "session-1",
            "selected_markets": ["SOL"],
            "duration_seconds": config.duration_seconds,
            "event_count": 10,
            "gap_count": 0,
            "reconnect_count": 0,
            "duplicate_count": 0,
            "anomaly_count": 0,
            "root": str(root),
            "network_access": True,
            "live_orders": False,
        }

    payload = support.record_mainnet_evidence_payload(
        Settings(),
        root=tmp_path,
        seconds=3600,
        deep_limit=20,
        runner=runner,
    )

    config = observed["config"]
    assert config.duration_seconds == 3600
    assert config.deep_limit == 20
    assert observed["root"] == tmp_path
    assert payload["session_id"] == "session-1"
    assert payload["network_access"] is True
    assert payload["live_orders"] is False
