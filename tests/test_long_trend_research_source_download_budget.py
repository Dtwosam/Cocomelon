"""Bound legacy research downloads without weakening exact artifact authentication."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

WORKFLOWS = Path(".github/workflows")
COMPACT = "continuous-paper-long-trend-exact-source-123-1"
DURABLE = "continuous-paper-state-123-1"
DIGEST = "sha256:" + ("a" * 64)
MAX_LEGACY_BYTES = 512 * 1024 * 1024


def _artifact_script(horizon: str) -> str:
    source = (
        WORKFLOWS / f"prospective-long-trend-{horizon}-exact.yml"
    ).read_text(encoding="utf-8")
    marker = (
        'ARTIFACT_COMPACT_NAME="$compact_name" '
        'ARTIFACT_DURABLE_NAME="$durable_name" python -c \'\n'
    )
    assert source.count(marker) == 1
    body = source.split(marker, 1)[1].split("\n          '\n", 1)[0]
    return textwrap.dedent(body)


def _artifact(name: str, size: object, *, digest: str = DIGEST) -> dict[str, object]:
    return {
        "id": 456,
        "name": name,
        "size_in_bytes": size,
        "expired": False,
        "digest": digest,
    }


def _resolve(horizon: str, artifacts: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _artifact_script(horizon)],
        input=json.dumps({"artifacts": artifacts}),
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "ARTIFACT_COMPACT_NAME": COMPACT,
            "ARTIFACT_DURABLE_NAME": DURABLE,
        },
    )


@pytest.mark.parametrize("horizon", ["5m", "15m"])
def test_compact_source_preferred_over_oversized_durable_archive(
    horizon: str,
) -> None:
    result = _resolve(
        horizon,
        [_artifact(DURABLE, 1_622_000_000), _artifact(COMPACT, 128_000)],
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"456\t{COMPACT}\t{DIGEST}"


@pytest.mark.parametrize("horizon", ["5m", "15m"])
def test_oversized_legacy_archive_is_not_downloaded(horizon: str) -> None:
    result = _resolve(horizon, [_artifact(DURABLE, MAX_LEGACY_BYTES + 1)])
    assert result.returncode == 0, result.stderr
    assert not result.stdout.strip()


@pytest.mark.parametrize("horizon", ["5m", "15m"])
def test_legacy_fallback_remains_available_within_budget(horizon: str) -> None:
    result = _resolve(horizon, [_artifact(DURABLE, MAX_LEGACY_BYTES)])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"456\t{DURABLE}\t{DIGEST}"


@pytest.mark.parametrize("horizon", ["5m", "15m"])
@pytest.mark.parametrize("bad_size", [None, True, "1024", -1, 0])
def test_bad_artifact_metadata_rejected(horizon: str, bad_size: object) -> None:
    result = _resolve(horizon, [_artifact(DURABLE, bad_size)])
    assert result.returncode != 0
    assert "artifact size is absent or invalid" in result.stderr


@pytest.mark.parametrize("horizon", ["5m", "15m"])
def test_digest_still_required_on_compact_artifact(horizon: str) -> None:
    result = _resolve(horizon, [_artifact(COMPACT, 1234, digest="unsigned")])
    assert result.returncode != 0
    assert "digest is missing or invalid" in result.stderr


@pytest.mark.parametrize("horizon", ["5m", "15m"])
def test_workflow_still_verifies_downloaded_zip_sha256(horizon: str) -> None:
    source = (
        WORKFLOWS / f"prospective-long-trend-{horizon}-exact.yml"
    ).read_text(encoding="utf-8")
    assert "512 * 1024 * 1024" in source
    assert "no authenticated LONG-trend source within 512 MiB" in source
    assert "state artifact digest mismatch" in source
    assert "sha256sum" in source
    assert "continuous-paper-long-trend-exact-source.tar" in source
    assert "actions: write" not in source
