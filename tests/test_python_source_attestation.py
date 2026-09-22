from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research.python_source_attestation import (
    PythonSourceAttestationError,
    build_python_source_tree_attestation,
    verify_python_source_tree_attestation,
    write_python_source_tree_attestation,
)


def _source_tree(root: Path) -> Path:
    package = root / "cocomelon"
    (package / "research").mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = 'test'\n", encoding="utf-8")
    (package / "research" / "alpha.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (package / "research" / "beta.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    return package


def test_source_attestation_is_deterministic_and_sorted(tmp_path: Path) -> None:
    root = _source_tree(tmp_path)

    first = build_python_source_tree_attestation(
        root,
        subject_type="historical_archive_preset",
        subject_id="preset-1",
    )
    second = build_python_source_tree_attestation(
        root,
        subject_type="historical_archive_preset",
        subject_id="preset-1",
    )

    assert first == second
    assert first.source_root_name == "cocomelon"
    assert first.source_tree_sha256 == second.source_tree_sha256
    assert len(first.source_tree_sha256) == 64
    assert len(first.attestation_id) == 64
    assert tuple(item.relative_path for item in first.files) == (
        "__init__.py",
        "research/alpha.py",
        "research/beta.py",
    )


def test_source_attestation_changes_when_source_bytes_change(tmp_path: Path) -> None:
    root = _source_tree(tmp_path)
    first = build_python_source_tree_attestation(
        root,
        subject_type="historical_archive_preset",
        subject_id="preset-1",
    )

    (root / "research" / "alpha.py").write_text(
        "VALUE = 99\n",
        encoding="utf-8",
    )
    second = build_python_source_tree_attestation(
        root,
        subject_type="historical_archive_preset",
        subject_id="preset-1",
    )

    assert first.source_tree_sha256 != second.source_tree_sha256
    assert first.attestation_id != second.attestation_id


def test_source_attestation_round_trips_and_detects_tampering(
    tmp_path: Path,
) -> None:
    root = _source_tree(tmp_path)
    attestation = build_python_source_tree_attestation(
        root,
        subject_type="historical_archive_preset",
        subject_id="preset-1",
    )
    path = tmp_path / "implementation.json"
    write_python_source_tree_attestation(path, attestation)

    verified = verify_python_source_tree_attestation(
        path,
        expected_subject_type="historical_archive_preset",
        expected_subject_id="preset-1",
    )
    assert verified == attestation

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["files"][0]["sha256"] = "0" * 64
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        PythonSourceAttestationError,
        match="SOURCE_TREE_SHA256_MISMATCH",
    ):
        verify_python_source_tree_attestation(
            path,
            expected_subject_type="historical_archive_preset",
            expected_subject_id="preset-1",
        )


def test_source_attestation_rejects_wrong_subject(tmp_path: Path) -> None:
    root = _source_tree(tmp_path)
    attestation = build_python_source_tree_attestation(
        root,
        subject_type="historical_archive_preset",
        subject_id="preset-1",
    )
    path = tmp_path / "implementation.json"
    write_python_source_tree_attestation(path, attestation)

    with pytest.raises(
        PythonSourceAttestationError,
        match="SOURCE_ATTESTATION_SUBJECT_MISMATCH",
    ):
        verify_python_source_tree_attestation(
            path,
            expected_subject_type="historical_archive_preset",
            expected_subject_id="preset-2",
        )


def test_source_attestation_refuses_conflicting_overwrite(tmp_path: Path) -> None:
    root = _source_tree(tmp_path)
    first = build_python_source_tree_attestation(
        root,
        subject_type="historical_archive_preset",
        subject_id="preset-1",
    )
    path = tmp_path / "implementation.json"
    write_python_source_tree_attestation(path, first)

    (root / "research" / "alpha.py").write_text("VALUE = 3\n", encoding="utf-8")
    second = build_python_source_tree_attestation(
        root,
        subject_type="historical_archive_preset",
        subject_id="preset-1",
    )

    with pytest.raises(
        PythonSourceAttestationError,
        match="SOURCE_ATTESTATION_CONFLICT",
    ):
        write_python_source_tree_attestation(path, second)
