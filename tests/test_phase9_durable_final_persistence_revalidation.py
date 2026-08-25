from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-corpus-curator.yml")


def test_persist_job_revalidates_existing_durable_final_id() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    persist = text.index("persist-phase9-state:")
    persist_text = text[persist:]

    assert "Existing durable Phase 9 final_id is invalid during persistence" in persist_text
