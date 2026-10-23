from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cocomelon.research.learning_shadow_campaign_sequence import (
    LearningShadowCampaignSequenceError,
    build_learning_shadow_campaign_sequence_status,
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


def _bootstrap(root: Path, *, as_of_ms: int = 1_500) -> None:
    _write_identity(
        root / "bootstrap.json",
        {
            "schema_version": 1,
            "as_of_ms": as_of_ms,
            "candidate_id": "a" * 64,
            "paper_only": True,
            "research_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
            "live_promotion_authorized": False,
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
            "candidate_id": "a" * 64,
            "paper_only": True,
            "research_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
            "live_promotion_authorized": False,
        },
        "generation_id",
    )


def _run(
    *,
    run_id: int,
    created_at: str,
    updated_at: str,
    attempt: int = 1,
    conclusion: str = "success",
) -> dict[str, object]:
    return {
        "id": run_id,
        "run_attempt": attempt,
        "created_at": created_at,
        "updated_at": updated_at,
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


def test_shadow_sequence_requires_campaign_started_before_but_completed_after_review(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _history(
        history,
        [
            _run(
                run_id=20,
                created_at="1970-01-01T00:00:01Z",
                updated_at="1970-01-01T00:00:02Z",
            )
        ],
    )

    status = build_learning_shadow_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
    )

    assert status.action == "missing_campaign"
    assert status.next_required_run_id == 20
    assert status.next_required_created_at_ms == 1_000
    assert status.next_required_completed_at_ms == 2_000
    assert status.remaining_campaign_count == 1


def test_shadow_sequence_skips_campaign_completed_before_review(tmp_path: Path) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=2_500)
    _history(
        history,
        [
            _run(
                run_id=20,
                created_at="1970-01-01T00:00:01Z",
                updated_at="1970-01-01T00:00:02Z",
            )
        ],
    )

    status = build_learning_shadow_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
        current_run_id=20,
    )

    assert status.action == "skip_completed_before_bootstrap"
    assert status.remaining_campaign_count == 0


def test_shadow_sequence_rejects_newer_campaign_while_gap_exists(tmp_path: Path) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _history(
        history,
        [
            _run(
                run_id=20,
                created_at="1970-01-01T00:00:02Z",
                updated_at="1970-01-01T00:00:03Z",
            ),
            _run(
                run_id=30,
                created_at="1970-01-01T00:00:04Z",
                updated_at="1970-01-01T00:00:05Z",
            ),
        ],
    )

    status = build_learning_shadow_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
        current_run_id=30,
    )

    assert status.action == "gap"
    assert status.current_run_id == 30
    assert status.next_required_run_id == 20


def test_shadow_sequence_processes_exact_oldest_missing_campaign(tmp_path: Path) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _history(
        history,
        [
            _run(
                run_id=20,
                created_at="1970-01-01T00:00:02Z",
                updated_at="1970-01-01T00:00:03Z",
            ),
            _run(
                run_id=30,
                created_at="1970-01-01T00:00:04Z",
                updated_at="1970-01-01T00:00:05Z",
            ),
        ],
    )

    status = build_learning_shadow_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
        current_run_id=20,
    )

    assert status.action == "process"
    assert status.next_required_run_id == 20
    assert status.paper_only is True
    assert status.research_only is True
    assert status.promotion_eligible is False
    assert status.execution_ready is False
    assert status.live_promotion_authorized is False


def test_shadow_sequence_keys_processed_campaigns_by_logical_run_id(tmp_path: Path) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _generation(state, run_id=20, attempt=1)
    _history(
        history,
        [
            _run(
                run_id=20,
                attempt=2,
                created_at="1970-01-01T00:00:02Z",
                updated_at="1970-01-01T00:00:03Z",
            ),
            _run(
                run_id=30,
                created_at="1970-01-01T00:00:04Z",
                updated_at="1970-01-01T00:00:05Z",
            ),
        ],
    )

    processed = build_learning_shadow_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
        current_run_id=20,
    )
    pending = build_learning_shadow_campaign_sequence_status(
        state_root=state,
        campaign_history_path=history,
        repository=REPO,
    )

    assert processed.action == "skip_already_processed"
    assert pending.next_required_run_id == 30


def test_shadow_sequence_rejects_tampered_generation(tmp_path: Path) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state)
    _generation(state, run_id=20)
    path = state / "generations" / "20-1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["campaign_run_id"] = 21
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    _history(
        history,
        [
            _run(
                run_id=20,
                created_at="1970-01-01T00:00:02Z",
                updated_at="1970-01-01T00:00:03Z",
            )
        ],
    )

    with pytest.raises(
        LearningShadowCampaignSequenceError,
        match="identity mismatch",
    ):
        build_learning_shadow_campaign_sequence_status(
            state_root=state,
            campaign_history_path=history,
            repository=REPO,
        )
