import subprocess
from pathlib import Path


SYNC = Path(".github/workflows/research-v4-registry-sync.yml")


def test_non_whitespace_attempt_metadata_delimiter_preserves_empty_conclusion() -> None:
    completed = subprocess.run(
        [
            "bash",
            "-c",
            "row='in_progress||2026-09-02T17:18:39Z|.github/workflows/evidence-campaign-v4-scheduled.yml'; "
            "IFS='|' read -r status conclusion started path <<< \"$row\"; "
            "printf '%s\\n%s\\n%s\\n%s\\n' \"$status\" \"$conclusion\" \"$started\" \"$path\"",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.splitlines() == [
        "in_progress",
        "",
        "2026-09-02T17:18:39Z",
        ".github/workflows/evidence-campaign-v4-scheduled.yml",
    ]


def test_v4_sync_uses_non_whitespace_delimiter_for_attempt_metadata() -> None:
    source = SYNC.read_text(encoding="utf-8")

    assert '| join("|")' in source
    assert "IFS='|' read -r RUN_STATUS RUN_CONCLUSION RUN_STARTED_AT ATTEMPT_WORKFLOW_PATH" in source
