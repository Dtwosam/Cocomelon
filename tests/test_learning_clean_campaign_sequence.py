from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cocomelon.research.learning_clean_campaign_sequence import (
    LearningCleanCampaignSequenceError,
    build_learning_clean_campaign_sequence_status,
)

REPO = "Dtwosam/Cocomelon"


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _write_identity(path: Path, payload: dict[str, object], id_field: str) -> None:
    identity = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _canonical({**payload, id_field: identity}) + "\n",
        encoding="utf-8",
    )


def _bootstrap(root: Path, *, as_of_ms: int = 1_000) -> None:
    _write_identity(
        root / "bootstrap.json",
        {
            "schema_version": 1,
            "as_of_ms": as_of_ms,
            "candidate_count": 1,
            "paper_only": True,
            "prospective_only": True,
            "research_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
        },
        "bootstrap_id",
    )


def _generation(root: Path, *, run_id: int, attempt: int = 1) -> None:
    _write_identity(
        root / "generations" / f"{run_id}-{attempt}.json",
        {
            "schema_version": 1,
            "campaign_run_id": run_id,
            "campaign_run_attempt": attempt,
            "candidate_count": 1,
            "paper_only": True,
            "prospective_only": True,
            "research_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
        },
        "generation_id",
    )


def _run(
    *,
    run_id: int,
    created_at: str,
    attempt: int = 1,
    conclusion: str = "success",
) -> dict[str, object]:
    return {
        "id": run_id,
        "run_attempt": attempt,
        "created_at": created_at,
        "head_sha": f"{run_id:040x}"[-40:],
        "head_branch": "main",
        "status": "completed",
        "conclusion": conclusion,
        "event": "workflow_dispatch",
        "path": ".github/workflows/research-campaign-scheduled.yml",
        "name": "Scheduled Research Mainnet Replay Campaign",
        "head_repository": {"full_name": REPO},
    }


def _history(path: Path, runs: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps([{"workflow_runs": runs}], separators=(",", ":")),
        encoding="utf-8",
    )


def test_clean_sequence_identifies_oldest_missing_campaign(tmp_path: Path) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _history(
        history,
        [
            _run(run_id=10, created_at="1970-01-01T00:00:01Z"),
            _run(run_id=20, created_at="1970-01-01T00:00:02Z"),
            _run(run_id=30, created_at="1970-01-01T00:00:03Z"),
        ],
    )

    status = build_learning_clean_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
    )

    assert status.action == "missing_campaign"
    assert status.next_required_run_id == 20
    assert status.remaining_campaign_count == 2
    assert status.promotion_eligible is False
    assert status.execution_ready is False


def test_clean_sequence_rejects_newer_campaign_while_gap_exists(tmp_path: Path) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _history(
        history,
        [
            _run(run_id=20, created_at="1970-01-01T00:00:02Z"),
            _run(run_id=30, created_at="1970-01-01T00:00:03Z"),
        ],
    )

    status = build_learning_clean_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
        current_run_id=30,
    )

    assert status.action == "gap"
    assert status.current_run_id == 30
    assert status.next_required_run_id == 20


def test_clean_sequence_processes_exact_next_campaign(tmp_path: Path) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _history(
        history,
        [
            _run(run_id=20, created_at="1970-01-01T00:00:02Z"),
            _run(run_id=30, created_at="1970-01-01T00:00:03Z"),
        ],
    )

    status = build_learning_clean_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
        current_run_id=20,
    )

    assert status.action == "process"
    assert status.next_required_run_id == 20


def test_clean_sequence_skips_processed_and_predates_bootstrap(tmp_path: Path) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _generation(state, run_id=20)
    _history(
        history,
        [
            _run(run_id=10, created_at="1970-01-01T00:00:01Z"),
            _run(run_id=20, created_at="1970-01-01T00:00:02Z"),
            _run(run_id=30, created_at="1970-01-01T00:00:03Z"),
        ],
    )

    old = build_learning_clean_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
        current_run_id=10,
    )
    processed = build_learning_clean_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
        current_run_id=20,
    )
    next_status = build_learning_clean_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
    )

    assert old.action == "skip_predates_bootstrap"
    assert processed.action == "skip_already_processed"
    assert next_status.action == "missing_campaign"
    assert next_status.next_required_run_id == 30


def test_clean_sequence_does_not_invalidate_processed_run_after_failed_rerun(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _generation(state, run_id=20)
    _history(
        history,
        [
            _run(
                run_id=20,
                created_at="1970-01-01T00:00:02Z",
                attempt=2,
                conclusion="failure",
            ),
            _run(run_id=30, created_at="1970-01-01T00:00:03Z"),
        ],
    )

    status = build_learning_clean_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
    )

    assert status.action == "missing_campaign"
    assert status.next_required_run_id == 30


def test_clean_sequence_rejects_tampered_generation(tmp_path: Path) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state)
    _generation(state, run_id=20)
    path = state / "generations" / "20-1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["campaign_run_id"] = 21
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    _history(history, [_run(run_id=20, created_at="1970-01-01T00:00:02Z")])

    with pytest.raises(
        LearningCleanCampaignSequenceError,
        match="identity mismatch",
    ):
        build_learning_clean_campaign_sequence_status(
            state_root=state,
            campaign_history_path=history,
            repository=REPO,
        )
