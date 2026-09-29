from __future__ import annotations

import base64
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

SCRIPT = Path("scripts/restore_continuous_paper_state.sh")
SOURCE_SHA = "a" * 40


def _fake_gh(
    tmp_path: Path,
    *,
    workflow_source: str,
    artifact_zip: Path,
) -> tuple[Path, dict[str, str]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    workflow_b64 = tmp_path / "workflow.b64"
    workflow_b64.write_bytes(
        base64.b64encode(workflow_source.encode("utf-8"))
    )
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"/contents/.github/workflows/continuous-paper.yml?"* ]]; then
  cat "$FAKE_WORKFLOW_B64"
elif [[ "$*" == *"/actions/artifacts/"*"/zip"* ]]; then
  cat "$FAKE_ARTIFACT_ZIP"
else
  echo "unexpected fake gh call: $*" >&2
  exit 9
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "GITHUB_REPOSITORY": "Dtwosam/Cocomelon",
            "FAKE_WORKFLOW_B64": str(workflow_b64),
            "FAKE_ARTIFACT_ZIP": str(artifact_zip),
        }
    )
    return fake_bin, env


def test_restore_script_is_valid_bash() -> None:
    subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=True,
    )


def test_restore_script_streams_packed_artifact_end_to_end(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "runtime-state.json").write_text(
        '{"state":"exact"}\n',
        encoding="utf-8",
    )
    tar_path = tmp_path / "continuous-paper-state.tar"
    with tarfile.open(tar_path, "w") as archive:
        archive.add(
            source_root / "runtime-state.json",
            arcname="./runtime-state.json",
        )
    artifact_zip = tmp_path / "packed.zip"
    with zipfile.ZipFile(
        artifact_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.write(
            tar_path,
            arcname="continuous-paper-state.tar",
        )

    _, env = _fake_gh(
        tmp_path,
        workflow_source=(
            "steps:\n"
            "  - name: Pack durable continuous paper state\n"
        ),
        artifact_zip=artifact_zip,
    )
    state_root = tmp_path / "restored"
    subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "123",
            SOURCE_SHA,
            str(state_root),
        ],
        check=True,
        env=env,
    )

    assert (state_root / "runtime-state.json").read_text(
        encoding="utf-8"
    ) == '{"state":"exact"}\n'
    assert not (tmp_path / "state.zip").exists()


def test_restore_script_keeps_legacy_multifile_compatibility(
    tmp_path: Path,
) -> None:
    artifact_zip = tmp_path / "legacy.zip"
    with zipfile.ZipFile(
        artifact_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr("journal.sqlite3", b"journal")
        archive.writestr("nested/evidence.json", b"evidence")

    _, env = _fake_gh(
        tmp_path,
        workflow_source="steps:\n  - name: Legacy upload\n",
        artifact_zip=artifact_zip,
    )
    state_root = tmp_path / "restored-legacy"
    subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "456",
            SOURCE_SHA,
            str(state_root),
        ],
        check=True,
        env=env,
    )

    assert (state_root / "journal.sqlite3").read_bytes() == b"journal"
    assert (
        state_root / "nested" / "evidence.json"
    ).read_bytes() == b"evidence"


def test_restore_script_uses_stream_for_packed_artifacts() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert (
        'grep -Fq -- "- name: Pack durable continuous paper state"'
        in source
    )
    assert "| funzip \\\n    | tar -xf - -C \"$state_root\"" in source
    assert '> "$tmp_root/state.zip"' in source
    assert 'unzip -q "$tmp_root/state.zip" -d "$artifact_root"' in source
