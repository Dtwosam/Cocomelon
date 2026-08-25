from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

LEDGER_REVISION = "2a9f01d86218dca98d2d84a4ae0e2e28c69975a7"
TOOL_REVISION = "a" * 40
ATTESTATION_ID = "b" * 64


def _canonical_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _selection_audit(source_run_id: int, *, audit_suffix: str) -> dict[str, object]:
    attempt_ledger = {
        "schema_version": 1,
        "economic_claim": "none",
        "selection_audit_only": True,
        "attempt_count": 1,
        "admitted_attempt": 1,
        "attempts": [
            {
                "attempt": 1,
                "admitted": True,
                "status": "admitted",
                "rejection_reasons": [],
            }
        ],
        "network_access": False,
        "live_orders": False,
    }
    base: dict[str, object] = {
        "schema_version": 1,
        "economic_claim": "none",
        "source_run_id": source_run_id,
        "source_artifact_id": source_run_id + 10_000,
        "trigger_head_sha": audit_suffix * 40,
        "attempt_ledger_revision": LEDGER_REVISION,
        "attempt_count": 1,
        "rejected_attempt_count": 0,
        "admitted_attempt": 1,
        "attempt_ledger": attempt_ledger,
        "network_access": False,
        "live_orders": False,
    }
    return {**base, "selection_audit_id": _canonical_id(base)}


def _final_payload(*, attestation_id: str = ATTESTATION_ID) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "v2-phase9-one-shot",
        "protocol_state": "evaluated",
        "one_shot_oos": True,
        "economic_claim": "phase9_evaluation",
        "mainnet_attestation_id": attestation_id,
        "network_access": False,
        "live_orders": False,
    }
    return {**base, "final_id": _canonical_id(base)}


def _make_inputs(tmp_path: Path) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    final_path = tmp_path / "phase9-v2-final.json"
    _write_json(corpus / "selection-audits" / "101.json", _selection_audit(101, audit_suffix="c"))
    _write_json(corpus / "selection-audits" / "102.json", _selection_audit(102, audit_suffix="d"))
    _write_json(
        corpus / "mainnet-attestation.json",
        {
            "schema_version": 1,
            "attestation_id": ATTESTATION_ID,
            "source_count": 3,
            "sources": [{"run_id": "r1"}, {"run_id": "r2"}, {"run_id": "r3"}],
        },
    )
    _write_json(
        corpus / "corpus-index.json",
        {
            "schema_version": 1,
            "economic_claim": "none",
            "mainnet_attestation_id": ATTESTATION_ID,
            "selection_audit_count": 2,
        },
    )
    _write_json(final_path, _final_payload())
    return corpus, final_path


def _run_archive(
    corpus: Path,
    final_path: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "cocomelon.ops.selection_audit_archive",
            "--corpus-root",
            str(corpus),
            "--phase9-final",
            str(final_path),
            "--archive-tool-revision",
            TOOL_REVISION,
            "--out",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_selection_audit_archive_is_deterministic_and_binds_final_state(tmp_path: Path) -> None:
    corpus, final_path = _make_inputs(tmp_path)
    first = tmp_path / "archive-1.json"
    second = tmp_path / "archive-2.json"

    result_one = _run_archive(corpus, final_path, first)
    result_two = _run_archive(corpus, final_path, second)

    assert result_one.returncode == 0, result_one.stderr
    assert result_two.returncode == 0, result_two.stderr
    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    final_payload = json.loads(final_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["protocol_id"] == "v2-phase9-one-shot-selection-audits"
    assert payload["phase9_final_id"] == final_payload["final_id"]
    assert payload["mainnet_attestation_id"] == ATTESTATION_ID
    assert payload["archive_tool_revision"] == TOOL_REVISION
    assert payload["attested_source_count"] == 3
    assert payload["selection_audit_count"] == 2
    assert payload["legacy_source_count"] == 1
    assert payload["audited_source_run_ids"] == [101, 102]
    assert len(payload["selection_audits"]) == 2
    assert payload["economic_claim"] == "none"
    assert payload["network_access"] is False
    assert payload["live_orders"] is False
    archive_id = payload["archive_id"]
    base = {key: value for key, value in payload.items() if key != "archive_id"}
    assert archive_id == _canonical_id(base)


def test_selection_audit_archive_rejects_tampered_audit(tmp_path: Path) -> None:
    corpus, final_path = _make_inputs(tmp_path)
    path = corpus / "selection-audits" / "101.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["selection_audit_id"] = "0" * 64
    _write_json(path, payload)

    result = _run_archive(corpus, final_path, tmp_path / "archive.json")

    assert result.returncode != 0
    assert "selection audit id is invalid" in result.stderr


def test_selection_audit_archive_rejects_final_attestation_mismatch(tmp_path: Path) -> None:
    corpus, final_path = _make_inputs(tmp_path)
    _write_json(final_path, _final_payload(attestation_id="e" * 64))

    result = _run_archive(corpus, final_path, tmp_path / "archive.json")

    assert result.returncode != 0
    assert "mainnet attestation does not match Phase 9 final state" in result.stderr


def test_selection_audit_archive_rejects_corpus_count_mismatch(tmp_path: Path) -> None:
    corpus, final_path = _make_inputs(tmp_path)
    index_path = corpus / "corpus-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["selection_audit_count"] = 99
    _write_json(index_path, index)

    result = _run_archive(corpus, final_path, tmp_path / "archive.json")

    assert result.returncode != 0
    assert "selection audit count does not match corpus index" in result.stderr


def test_selection_audit_archive_rejects_duplicate_source_run_ids(tmp_path: Path) -> None:
    corpus, final_path = _make_inputs(tmp_path)
    _write_json(corpus / "selection-audits" / "102.json", _selection_audit(101, audit_suffix="d"))

    result = _run_archive(corpus, final_path, tmp_path / "archive.json")

    assert result.returncode != 0
    assert "selection audit source run id does not match filename" in result.stderr
