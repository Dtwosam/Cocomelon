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


def test_mainnet_aggregation_parser_requires_only_local_inputs() -> None:
    cli = _cli()
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["aggregate"])

    args = parser.parse_args(
        [
            "aggregate",
            "--journal",
            "aggregate/journal.sqlite3",
            "--facts",
            "aggregate/facts.sqlite3",
            "--source-root",
            "artifact-a/output",
        ]
    )
    assert args.journal == Path("aggregate/journal.sqlite3")
    assert args.facts == Path("aggregate/facts.sqlite3")
    assert args.source_root == [Path("artifact-a/output")]

    for forbidden in FORBIDDEN_OPTIONS:
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "aggregate",
                    "--journal",
                    "aggregate/journal.sqlite3",
                    "--facts",
                    "aggregate/facts.sqlite3",
                    "--source-root",
                    "artifact-a/output",
                    *forbidden,
                ]
            )


def test_mainnet_dataset_parser_requires_only_attested_local_inputs() -> None:
    cli = _cli()
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["freeze-dataset"])

    args = parser.parse_args(
        [
            "freeze-dataset",
            "--journal",
            "aggregate/journal.sqlite3",
            "--facts",
            "aggregate/facts.sqlite3",
            "--run-id",
            "run-a",
        ]
    )
    assert args.journal == Path("aggregate/journal.sqlite3")
    assert args.facts == Path("aggregate/facts.sqlite3")
    assert args.run_id == ["run-a"]

    for forbidden in FORBIDDEN_OPTIONS:
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "freeze-dataset",
                    "--journal",
                    "aggregate/journal.sqlite3",
                    "--facts",
                    "aggregate/facts.sqlite3",
                    "--run-id",
                    "run-a",
                    *forbidden,
                ]
            )


def test_phase9_snapshot_parser_requires_only_local_inputs() -> None:
    cli = _cli()
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["prepare-phase9-v2"])

    args = parser.parse_args(
        [
            "prepare-phase9-v2",
            "--corpus-root",
            "corpus",
            "--out-root",
            "phase9-snapshot",
        ]
    )
    assert args.corpus_root == Path("corpus")
    assert args.out_root == Path("phase9-snapshot")

    for forbidden in FORBIDDEN_OPTIONS:
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "prepare-phase9-v2",
                    "--corpus-root",
                    "corpus",
                    "--out-root",
                    "phase9-snapshot",
                    *forbidden,
                ]
            )


def test_phase9_evaluation_parser_requires_only_frozen_local_snapshot() -> None:
    cli = _cli()
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["evaluate-phase9-v2"])

    args = parser.parse_args(
        [
            "evaluate-phase9-v2",
            "--snapshot-root",
            "phase9-snapshot",
        ]
    )
    assert args.snapshot_root == Path("phase9-snapshot")

    for forbidden in FORBIDDEN_OPTIONS:
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "evaluate-phase9-v2",
                    "--snapshot-root",
                    "phase9-snapshot",
                    *forbidden,
                ]
            )


def test_mainnet_cli_dispatches_only_to_attested_evidence_functions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _cli()
    aggregate_calls: list[tuple[Path, Path, tuple[Path, ...]]] = []
    freeze_calls: list[tuple[Path, Path, tuple[str, ...]]] = []
    prepare_calls: list[tuple[Path, Path]] = []
    evaluate_calls: list[Path] = []

    def fake_aggregate(
        journal: Path,
        facts: Path,
        roots: tuple[Path, ...],
    ) -> dict[str, object]:
        aggregate_calls.append((journal, facts, roots))
        return {
            "mainnet_attestation_id": "a" * 64,
            "network_access": False,
            "live_orders": False,
        }

    def fake_freeze(
        journal: Path,
        facts: Path,
        run_ids: tuple[str, ...],
    ) -> dict[str, object]:
        freeze_calls.append((journal, facts, run_ids))
        return {
            "mainnet_attestation_id": "a" * 64,
            "real_evidence_eligible": True,
            "network_access": False,
            "live_orders": False,
        }

    def fake_prepare(corpus_root: Path, out_root: Path) -> dict[str, object]:
        prepare_calls.append((corpus_root, out_root))
        return {
            "snapshot_id": "b" * 64,
            "ready_for_untouched_evaluation": False,
            "network_access": False,
            "live_orders": False,
        }

    def fake_evaluate(snapshot_root: Path) -> dict[str, object]:
        evaluate_calls.append(snapshot_root)
        return {
            "snapshot_id": "b" * 64,
            "edge_status": "insufficient_evidence",
            "network_access": False,
            "live_orders": False,
        }

    monkeypatch.setattr(cli, "aggregate_payload", fake_aggregate)
    monkeypatch.setattr(cli, "freeze_dataset_payload", fake_freeze)
    monkeypatch.setattr(cli, "prepare_phase9_v2_snapshot", fake_prepare)
    monkeypatch.setattr(cli, "evaluate_phase9_v2_snapshot", fake_evaluate)

    cli.main(
        [
            "aggregate",
            "--journal",
            "aggregate/journal.sqlite3",
            "--facts",
            "aggregate/facts.sqlite3",
            "--source-root",
            "artifact-a/output",
        ]
    )
    aggregate_payload = json.loads(capsys.readouterr().out)
    assert aggregate_payload["network_access"] is False
    assert aggregate_payload["live_orders"] is False
    assert aggregate_calls == [
        (
            Path("aggregate/journal.sqlite3"),
            Path("aggregate/facts.sqlite3"),
            (Path("artifact-a/output"),),
        )
    ]

    cli.main(
        [
            "freeze-dataset",
            "--journal",
            "aggregate/journal.sqlite3",
            "--facts",
            "aggregate/facts.sqlite3",
            "--run-id",
            "run-a",
        ]
    )
    freeze_payload = json.loads(capsys.readouterr().out)
    assert freeze_payload["real_evidence_eligible"] is True
    assert freeze_payload["network_access"] is False
    assert freeze_payload["live_orders"] is False
    assert freeze_calls == [
        (
            Path("aggregate/journal.sqlite3"),
            Path("aggregate/facts.sqlite3"),
            ("run-a",),
        )
    ]

    cli.main(
        [
            "prepare-phase9-v2",
            "--corpus-root",
            "corpus",
            "--out-root",
            "phase9-snapshot",
        ]
    )
    prepare_payload = json.loads(capsys.readouterr().out)
    assert prepare_payload["network_access"] is False
    assert prepare_payload["live_orders"] is False
    assert prepare_calls == [(Path("corpus"), Path("phase9-snapshot"))]

    cli.main(
        [
            "evaluate-phase9-v2",
            "--snapshot-root",
            "phase9-snapshot",
        ]
    )
    evaluation_payload = json.loads(capsys.readouterr().out)
    assert evaluation_payload["network_access"] is False
    assert evaluation_payload["live_orders"] is False
    assert evaluate_calls == [Path("phase9-snapshot")]
