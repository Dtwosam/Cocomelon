from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from cocomelon.research.rollout_verifier import verify_research_fanout_rollout

ROOT = "scheduled-research-root"
CHALLENGER = "research-r1-exit-15m-v1"


def _write_audit(
    tmp_path: Path, *, challenger_end_ms: int = 2000, challenger_horizon: int = 900_000
) -> Path:
    campaign = tmp_path / "research-campaign"
    (campaign / "state").mkdir(parents=True)
    (campaign / "audit" / "capture" / "output").mkdir(parents=True)
    source_id = "research-mainnet-123-1"
    candidates = [
        {
            "candidate_id": ROOT,
            "required": True,
            "source_id": source_id,
            "attempt_id": "root-attempt",
            "batch_id": "root-batch",
            "execution_config_json": json.dumps({"max_position_age_ms": 1_200_000}),
        },
        {
            "candidate_id": CHALLENGER,
            "required": False,
            "source_id": source_id,
            "attempt_id": "challenger-attempt",
            "batch_id": "challenger-batch",
            "execution_config_json": json.dumps({"max_position_age_ms": challenger_horizon}),
        },
    ]
    (campaign / "state" / "research-fanout.json").write_text(
        json.dumps({"schema_version": 1, "candidates": candidates}), encoding="utf-8"
    )
    (campaign / "audit" / "capture" / "output" / "capture-source.json").write_text(
        json.dumps({"start_ms": 1000, "end_ms": 2000}), encoding="utf-8"
    )
    connection = sqlite3.connect(campaign / "state" / "research.sqlite3")
    connection.execute(
        """CREATE TABLE research_runner_attempts (
        attempt_id TEXT, candidate_id TEXT, batch_id TEXT, source_id TEXT, status TEXT,
        start_ms INTEGER, end_ms INTEGER, report_id TEXT, error_type TEXT, error_message TEXT)"""
    )
    connection.executemany(
        "INSERT INTO research_runner_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "root-attempt",
                ROOT,
                "root-batch",
                source_id,
                "succeeded",
                1000,
                2000,
                "r1",
                None,
                None,
            ),
            (
                "challenger-attempt",
                CHALLENGER,
                "challenger-batch",
                source_id,
                "succeeded",
                1000,
                challenger_end_ms,
                "r2",
                None,
                None,
            ),
        ],
    )
    connection.commit()
    connection.close()
    return campaign


def test_verifier_accepts_expected_root_challenger_shared_capture(tmp_path: Path) -> None:
    result = verify_research_fanout_rollout(_write_audit(tmp_path))
    assert result.root_candidate_id == ROOT
    assert result.challenger_candidate_id == CHALLENGER
    assert result.source_interval == (1000, 2000)
    assert result.root_max_position_age_ms == 1_200_000
    assert result.challenger_max_position_age_ms == 900_000


def test_verifier_rejects_candidate_interval_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="shared capture interval"):
        verify_research_fanout_rollout(_write_audit(tmp_path, challenger_end_ms=1999))


def test_verifier_rejects_wrong_challenger_horizon(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="15-minute"):
        verify_research_fanout_rollout(_write_audit(tmp_path, challenger_horizon=1_000_000))


def test_verifier_uses_exact_fanout_attempt_not_historical_candidate_row(tmp_path: Path) -> None:
    campaign = _write_audit(tmp_path)
    connection = sqlite3.connect(campaign / "state" / "research.sqlite3")
    connection.execute(
        "INSERT INTO research_runner_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "old-root-attempt",
            ROOT,
            "old-root-batch",
            "old-source",
            "succeeded",
            10,
            20,
            "old",
            None,
            None,
        ),
    )
    connection.commit()
    connection.close()

    result = verify_research_fanout_rollout(campaign)
    assert result.source_id == "research-mainnet-123-1"


def test_verifier_cli_emits_machine_readable_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from cocomelon.research import rollout_verifier

    code = rollout_verifier.main([str(_write_audit(tmp_path))])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["verified"] is True
    assert payload["root_candidate_id"] == ROOT
    assert payload["challenger_candidate_id"] == CHALLENGER
    assert payload["source_interval"] == [1000, 2000]
