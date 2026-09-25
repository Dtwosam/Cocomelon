from __future__ import annotations

from cocomelon.learning_dataset_cli import learning_dataset_payload


def test_empty_learning_dataset_payload_is_deterministic(tmp_path) -> None:
    payload = learning_dataset_payload(root=tmp_path, as_of_ms=123_456)

    assert payload["command"] == "learning-dataset"
    assert payload["as_of_ms"] == 123_456
    assert payload["eligible_record_count"] == 0
    assert payload["quarantined_record_count"] == 0
    assert payload["prospective_record_count"] == 0
    assert payload["paper_execution_record_count"] == 0
    assert payload["live_execution_record_count"] == 0
    assert payload["candidate_ids"] == ()
    assert len(payload["ledger_state_digest"]) == 64
    assert len(payload["dataset_id"]) == 64
