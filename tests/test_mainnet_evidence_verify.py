from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_verify_parser_requires_only_local_source() -> None:
    cli = importlib.import_module("cocomelon.mainnet_cli")
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["verify"])

    args = parser.parse_args(["verify", "--source-root", "artifact/output"])
    assert args.source_root == Path("artifact/output")

    forbidden_args = (
        ("--testnet",),
        ("--live",),
        ("--api-url", "https://example.invalid"),
        ("--ws-url", "wss://example.invalid/ws"),
    )
    for forbidden in forbidden_args:
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["verify", "--source-root", "artifact/output", *forbidden]
            )


def test_verify_cli_dispatches_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = importlib.import_module("cocomelon.mainnet_cli")
    calls: list[Path] = []

    def fake_verify(source_root: Path) -> dict[str, object]:
        calls.append(source_root)
        return {
            "real_evidence_eligible": True,
            "network_access": False,
            "live_orders": False,
        }

    monkeypatch.setattr(cli, "verify_payload", fake_verify, raising=False)
    cli.main(["verify", "--source-root", "artifact/output"])

    output = capsys.readouterr().out
    assert '"real_evidence_eligible": true' in output
    assert '"network_access": false' in output
    assert '"live_orders": false' in output
    assert calls == [Path("artifact/output")]


def test_verify_payload_reports_canonical_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = importlib.import_module("cocomelon.evaluation.mainnet_evidence")
    cohort = SimpleNamespace(
        manifest=SimpleNamespace(
            code_revision="a" * 40,
            manifest_id="manifest-a",
            start_ms=1_000,
            end_ms=2_000,
        ),
        result=SimpleNamespace(
            run_id="run-a",
            result_digest="b" * 64,
            strategy_decisions=3,
            risk_approvals=2,
            risk_rejections=1,
            execution_attempts=2,
            fills=4,
            opened_positions=1,
            closed_positions=1,
            closed_trade_ids=("trade-a",),
            data_complete=True,
        ),
        recording_session_id="c" * 64,
        source_digest="d" * 64,
        trigger_head_sha="e" * 40,
        workflow_head_sha="a" * 40,
    )
    roots: list[Path] = []

    def fake_validate(root: Path) -> object:
        roots.append(root)
        return cohort

    monkeypatch.setattr(module, "_validate_complete_mainnet_cohort", fake_validate)
    payload = module.verify_mainnet_evidence_cohort_payload(tmp_path / "artifact" / "output")

    assert roots == [(tmp_path / "artifact" / "output").resolve()]
    assert payload["evidence_kind"] == "genuine_public_hyperliquid_mainnet"
    assert payload["economic_claim"] == "none"
    assert payload["real_evidence_eligible"] is True
    assert payload["code_revision"] == "a" * 40
    assert payload["run_id"] == "run-a"
    assert payload["manifest_id"] == "manifest-a"
    assert payload["recording_session_id"] == "c" * 64
    assert payload["source_digest"] == "d" * 64
    assert payload["result_digest"] == "b" * 64
    assert payload["start_ms"] == 1_000
    assert payload["end_ms"] == 2_000
    assert payload["duration_ms"] == 1_000
    assert payload["closed_trade_count"] == 1
    assert payload["data_complete"] is True
    assert payload["network_access"] is False
    assert payload["live_orders"] is False
