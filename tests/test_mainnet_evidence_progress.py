from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

DAY_MS = 86_400_000


def test_progress_parser_requires_only_local_attested_stores() -> None:
    cli = importlib.import_module("cocomelon.mainnet_cli")
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["progress"])

    args = parser.parse_args(
        [
            "progress",
            "--journal",
            "aggregate/journal.sqlite3",
            "--facts",
            "aggregate/facts.sqlite3",
        ]
    )
    assert args.journal == Path("aggregate/journal.sqlite3")
    assert args.facts == Path("aggregate/facts.sqlite3")

    forbidden_args = (
        ("--testnet",),
        ("--live",),
        ("--api-url", "https://example.invalid"),
        ("--ws-url", "wss://example.invalid/ws"),
    )
    for forbidden in forbidden_args:
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "progress",
                    "--journal",
                    "aggregate/journal.sqlite3",
                    "--facts",
                    "aggregate/facts.sqlite3",
                    *forbidden,
                ]
            )


def test_progress_payload_reports_only_necessary_evidence_floor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = importlib.import_module("cocomelon.evaluation.mainnet_evidence")
    attestation = SimpleNamespace(
        attestation_id="a" * 64,
        code_revision="b" * 40,
        run_ids=("run-a", "run-b"),
        sources=({"run_id": "run-a"}, {"run_id": "run-b"}),
    )
    verify_calls: list[tuple[Path, Path, Path]] = []
    trade_calls: list[Path] = []

    def fake_verify(journal: Path, facts: Path, attestation_path: Path) -> object:
        verify_calls.append((journal, facts, attestation_path))
        return attestation

    def fake_trade_timestamps(journal: Path) -> tuple[int, ...]:
        trade_calls.append(journal)
        return (1_000, DAY_MS + 1_000, DAY_MS + 2_000)

    monkeypatch.setattr(module, "_verify_attested_target", fake_verify)
    monkeypatch.setattr(
        module,
        "_load_closed_trade_timestamps",
        fake_trade_timestamps,
        raising=False,
    )

    journal = tmp_path / "aggregate" / "journal.sqlite3"
    facts = tmp_path / "aggregate" / "facts.sqlite3"
    payload = module.mainnet_evidence_progress_payload(journal, facts)

    assert verify_calls == [(journal, facts, journal.parent / "mainnet-attestation.json")]
    assert trade_calls == [journal]
    assert payload["mainnet_attestation_id"] == "a" * 64
    assert payload["code_revision"] == "b" * 40
    assert payload["attested_run_count"] == 2
    assert payload["attested_source_count"] == 2
    assert payload["closed_trade_count"] == 3
    assert payload["closed_trade_days"] == 2
    assert payload["minimum_oos_trade_requirement"] == 100
    assert payload["minimum_oos_day_requirement"] == 30
    assert payload["closed_trades_shortfall"] == 97
    assert payload["closed_trade_days_shortfall"] == 28
    assert payload["raw_corpus_can_satisfy_oos_minimums"] is False
    assert payload["precheck_only"] is True
    assert payload["economic_claim"] == "none"
    assert payload["network_access"] is False
    assert payload["live_orders"] is False


def test_progress_cli_dispatches_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = importlib.import_module("cocomelon.mainnet_cli")
    calls: list[tuple[Path, Path]] = []

    def fake_progress(journal: Path, facts: Path) -> dict[str, object]:
        calls.append((journal, facts))
        return {
            "precheck_only": True,
            "raw_corpus_can_satisfy_oos_minimums": False,
            "economic_claim": "none",
            "network_access": False,
            "live_orders": False,
        }

    monkeypatch.setattr(cli, "progress_payload", fake_progress, raising=False)
    cli.main(
        [
            "progress",
            "--journal",
            "aggregate/journal.sqlite3",
            "--facts",
            "aggregate/facts.sqlite3",
        ]
    )

    output = capsys.readouterr().out
    assert '"precheck_only": true' in output
    assert '"raw_corpus_can_satisfy_oos_minimums": false' in output
    assert '"economic_claim": "none"' in output
    assert '"network_access": false' in output
    assert '"live_orders": false' in output
    assert calls == [
        (Path("aggregate/journal.sqlite3"), Path("aggregate/facts.sqlite3"))
    ]
