from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path("scripts/restore_continuous_paper_state.sh")


def test_restore_script_is_valid_bash() -> None:
    subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=True,
    )


def test_restore_script_streams_packed_artifacts_without_giant_temps() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert (
        'grep -Fq -- "- name: Pack durable continuous paper state"'
        in source
    )
    assert "| funzip \\\n    | tar -xf - -C \"$state_root\"" in source
    assert (
        '"repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip"'
        in source
    )
    assert '> "$tmp_root/state.zip"' in source
    assert 'unzip -q "$tmp_root/state.zip" -d "$artifact_root"' in source
    assert 'cp -a "$artifact_root"/. "$state_root"/' in source
    assert "continuous-paper-state.tar" not in source
