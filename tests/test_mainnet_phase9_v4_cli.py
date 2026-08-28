from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType

import pytest

FORBIDDEN_OPTIONS = (
    ("--testnet",),
    ("--live",),
    ("--api-url", "https://example.invalid"),
    ("--ws-url", "wss://example.invalid/ws"),
)


def _cli() -> ModuleType:
    return importlib.import_module("cocomelon.mainnet_cli")


def test_phase9_v4_snapshot_parser_requires_only_local_inputs() -> None:
    parser = _cli().build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["prepare-phase9-v4"])

    args = parser.parse_args(
        [
            "prepare-phase9-v4",
            "--corpus-root",
            "v4-corpus",
            "--out-root",
            "v4-phase9-snapshot",
        ]
    )
    assert args.corpus_root == Path("v4-corpus")
    assert args.out_root == Path("v4-phase9-snapshot")

    for forbidden in FORBIDDEN_OPTIONS:
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "prepare-phase9-v4",
                    "--corpus-root",
                    "v4-corpus",
                    "--out-root",
                    "v4-phase9-snapshot",
                    *forbidden,
                ]
            )


def test_phase9_v4_evaluation_parser_requires_only_frozen_local_snapshot() -> None:
    parser = _cli().build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["evaluate-phase9-v4"])

    args = parser.parse_args(
        [
            "evaluate-phase9-v4",
            "--snapshot-root",
            "v4-phase9-snapshot",
        ]
    )
    assert args.snapshot_root == Path("v4-phase9-snapshot")

    for forbidden in FORBIDDEN_OPTIONS:
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "evaluate-phase9-v4",
                    "--snapshot-root",
                    "v4-phase9-snapshot",
                    *forbidden,
                ]
            )


def test_mainnet_cli_dispatches_v4_handoff_explicitly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _cli()
    prepare_calls: list[tuple[Path, Path]] = []
    evaluate_calls: list[Path] = []

    def fake_prepare(corpus_root: Path, out_root: Path) -> dict[str, object]:
        prepare_calls.append((corpus_root, out_root))
        return {
            "snapshot_name": "v4-phase9-frozen-snapshot",
            "snapshot_id": "d" * 64,
            "ready_for_untouched_evaluation": False,
            "network_access": False,
            "live_orders": False,
        }

    def fake_evaluate(snapshot_root: Path) -> dict[str, object]:
        evaluate_calls.append(snapshot_root)
        return {
            "evaluation_name": "v4-phase9-evaluation",
            "snapshot_id": "d" * 64,
            "edge_status": "insufficient_evidence",
            "network_access": False,
            "live_orders": False,
        }

    monkeypatch.setattr(cli, "prepare_phase9_v4_snapshot", fake_prepare)
    monkeypatch.setattr(cli, "evaluate_phase9_v4_snapshot", fake_evaluate)

    cli.main(
        [
            "prepare-phase9-v4",
            "--corpus-root",
            "v4-corpus",
            "--out-root",
            "v4-phase9-snapshot",
        ]
    )
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["snapshot_name"] == "v4-phase9-frozen-snapshot"
    assert prepare_calls == [(Path("v4-corpus"), Path("v4-phase9-snapshot"))]

    cli.main(
        [
            "evaluate-phase9-v4",
            "--snapshot-root",
            "v4-phase9-snapshot",
        ]
    )
    evaluated = json.loads(capsys.readouterr().out)
    assert evaluated["evaluation_name"] == "v4-phase9-evaluation"
    assert evaluate_calls == [Path("v4-phase9-snapshot")]
