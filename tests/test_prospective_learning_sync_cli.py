from __future__ import annotations

from cocomelon.prospective_learning_sync_cli import prospective_learning_sync_payload
from cocomelon.research.prospective_context_report import HYPE_PROSPECTIVE_VALIDATION_V3


def test_empty_v3_learning_sync_creates_no_records(tmp_path) -> None:
    source_root = tmp_path / "source"
    learning_root = tmp_path / "learning"

    payload = prospective_learning_sync_payload(
        source_root=source_root,
        learning_root=learning_root,
        campaign="v3",
    )

    assert payload["command"] == "prospective-learning-sync"
    assert payload["campaign_version"] == "v3"
    assert payload["scanned_outcomes"] == 0
    assert payload["created_records"] == 0
    assert payload["existing_records"] == 0
    assert payload["learning_record_count"] == 0
    assert isinstance(payload["learning_state_digest"], str)
    assert len(payload["learning_state_digest"]) == 64
    assert (
        payload["research_eligible_at_ms"]
        == HYPE_PROSPECTIVE_VALIDATION_V3.finalization_not_before_ms
    )
