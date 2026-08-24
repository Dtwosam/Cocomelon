from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType

import pytest


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

    for forbidden in ("--testnet", "--live", "--api-url", "--ws-url"):
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
                    forbidden,
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

    for forbidden in ("--testnet", "--live", "--api-url", "--ws-url"):
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
                    forbidden,
                ]
            )


def test_mainnet_cli_dispatches_only_to_attested_evidence_functions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _cli()
    aggregate_calls: list[tuple[Path, Path, tuple[Path, ...]]] = []
    freeze_calls: list[tuple[Path, Path, tuple[str, ...]]] = []

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

    monkeypatch.setattr(cli, "aggregate_payload", fake_aggregate)
    monkeypatch.setattr(cli, "freeze_dataset_payload", fake_freeze)

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
