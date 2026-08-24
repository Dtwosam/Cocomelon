from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_right_censoring_guard_rejects_closed_samples_with_open_exposure() -> None:
    module = importlib.import_module("cocomelon.evaluation.mainnet_evidence")
    result = SimpleNamespace(
        opened_positions=2,
        closed_positions=1,
        closed_trade_ids=("trade-a",),
    )

    with pytest.raises(module.MainnetEvidenceError, match="finish flat"):
        module._require_no_right_censoring(result)


def test_right_censoring_guard_accepts_flat_closed_samples() -> None:
    module = importlib.import_module("cocomelon.evaluation.mainnet_evidence")
    result = SimpleNamespace(
        opened_positions=2,
        closed_positions=2,
        closed_trade_ids=("trade-a", "trade-b"),
    )

    module._require_no_right_censoring(result)


def test_right_censoring_guard_rejects_zero_trade_open_exposure() -> None:
    module = importlib.import_module("cocomelon.evaluation.mainnet_evidence")
    result = SimpleNamespace(
        opened_positions=1,
        closed_positions=0,
        closed_trade_ids=(),
    )

    with pytest.raises(module.MainnetEvidenceError, match="finish flat"):
        module._require_no_right_censoring(result)


def test_right_censoring_guard_accepts_flat_zero_trade_diagnostic() -> None:
    module = importlib.import_module("cocomelon.evaluation.mainnet_evidence")
    result = SimpleNamespace(
        opened_positions=0,
        closed_positions=0,
        closed_trade_ids=(),
    )

    module._require_no_right_censoring(result)


def test_existing_attested_target_rechecks_right_censoring(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = importlib.import_module("cocomelon.evaluation.mainnet_evidence")
    journal = tmp_path / "journal.sqlite3"
    facts = tmp_path / "facts.sqlite3"
    attestation_path = tmp_path / "mainnet-attestation.json"
    for path in (journal, facts, attestation_path):
        path.touch()

    manifest = SimpleNamespace(
        code_revision="a" * 40,
        manifest_id="manifest-a",
    )
    result = SimpleNamespace(
        run_id="run-a",
        result_digest="b" * 64,
        opened_positions=2,
        closed_positions=1,
        closed_trade_ids=("trade-a",),
    )
    attestation = SimpleNamespace(
        attestation_id="c" * 64,
        code_revision="a" * 40,
        run_ids=("run-a",),
        sources=(
            {
                "manifest_id": "manifest-a",
                "result_digest": "b" * 64,
                "run_id": "run-a",
                "workflow_head_sha": "a" * 40,
            },
        ),
    )
    monkeypatch.setattr(module, "_read_verified_attestation", lambda _: attestation)
    monkeypatch.setattr(module, "_load_replay_pairs", lambda _: ((manifest, result),))

    with pytest.raises(module.MainnetEvidenceError, match="finish flat"):
        module._verify_attested_target(journal, facts, attestation_path)
