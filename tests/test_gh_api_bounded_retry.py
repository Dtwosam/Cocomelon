"""Fail-closed finite retry coverage for GitHub source artifact retrieval."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

HELPER = Path("scripts/gh_api_bounded_retry.sh")
WORKFLOW = Path(".github/workflows/prospective-cadence-prediction-ledger.yml")


def _fake_api(tmp_path: Path, *, failures: int, status: int) -> subprocess.CompletedProcess[str]:
    binary = tmp_path / "bin"
    binary.mkdir()
    gh = binary / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "counter = pathlib.Path(os.environ['FAKE_GH_ATTEMPTS'])\n"
        "attempt = int(counter.read_text()) + 1 if counter.exists() else 1\n"
        "counter.write_text(str(attempt))\n"
        "if attempt <= int(os.environ['FAKE_GH_FAILURES']):\n"
        "    sys.stdout.buffer.write(b'BROKEN-RESPONSE-DO-NOT-LEAK')\n"
        "    print(f'gh: Server Error (HTTP {os.environ[\"FAKE_GH_STATUS\"]})', file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "sys.stdout.buffer.write(b'good\\x00zip\\xffpayload')\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    sleep = binary / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    attempts = tmp_path / "attempts"
    return subprocess.run(
        [
            "bash", "-c",
            "set -euo pipefail; source scripts/gh_api_bounded_retry.sh; "
            "gh_api_bounded_retry -H 'Accept: application/vnd.github+json' "
            "'repos/example/ledger/artifacts/123/zip'",
        ],
        env={
            **os.environ,
            "PATH": f"{binary}:{os.environ['PATH']}",
            "FAKE_GH_ATTEMPTS": str(attempts),
            "FAKE_GH_FAILURES": str(failures),
            "FAKE_GH_STATUS": str(status),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    ), int(attempts.read_text())


def test_transient_502_is_retried_without_corrupting_download(tmp_path: Path) -> None:
    result, calls = _fake_api(tmp_path, failures=2, status=502)
    assert result.returncode == 0
    assert calls == 3
    assert result.stdout == b"good\x00zip\xffpayload"
    assert b"BROKEN-RESPONSE-DO-NOT-LEAK" not in result.stdout


def test_permanent_permission_error_fails_immediately(tmp_path: Path) -> None:
    result, calls = _fake_api(tmp_path, failures=8, status=403)
    assert result.returncode != 0
    assert calls == 1
    assert result.stdout == b""
    assert b"HTTP 403" in result.stderr


def test_exhausted_503_fails_closed_without_partial_payload(tmp_path: Path) -> None:
    result, calls = _fake_api(tmp_path, failures=8, status=503)
    assert result.returncode != 0
    assert calls == 4
    assert result.stdout == b""
    assert b"HTTP 503" in result.stderr


def test_previous_ledger_restore_and_current_artifact_use_retry() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert source.count("source scripts/gh_api_bounded_retry.sh") == 2
    start = source.index("- name: Download current prospective report")
    end = source.index("- name: Extend append-only prediction ledger")
    artifact_reads = source[start:end]
    assert artifact_reads.count("gh_api_bounded_retry ") == 5
    assert "unzip -q /tmp/previous-ledger.zip" in artifact_reads
    assert "previous_path=\"\"" in artifact_reads
    assert "gh workflow run" not in artifact_reads
