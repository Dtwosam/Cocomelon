"""Incomplete forward-only research payloads must not become compact evidence."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/verify_compact_long_trend_exact_source.py")
FILES = (
    "prospective-full-stack-forward-markout-summary.json",
    "prospective-long-trend-execution-shadow-source.json",
)
DIRS = (
    "opening-opportunities/records",
    "opening-opportunity-exit-books/records",
    "replacement-funding-boundaries/records",
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _fixture(root: Path) -> None:
    root.mkdir(exist_ok=True)
    summary = {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "risk_rejected_integrity_clean": True,
        "risk_rejected_missing_rank": 0,
        "risk_rejected_stack_evaluated": 0,
        "risk_rejected_rows": [],
        "overlap_started_at_ms": 1_791_000_000_000,
    }
    source = {
        "schema_version": 2,
        "kind": "prospective-long-trend-carveout-execution-shadow-source-v2",
        "candidate_id": "prospective-top10-two-strike-momentum-no-long-trend-v1",
        "baseline_risk_reason": "weekly_drawdown_lockout",
        "overlap_started_at_ms": summary["overlap_started_at_ms"],
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "durable_gate_required": True,
        "durable_gate_source": "prospective-long-trend-carveout-fast-markout-ledger",
        "execution_config": {"test_execution_config": True},
        "source_opportunity_count": 0,
        "missing_opportunity_evidence": 0,
        "missing_forward_paths": 0,
        "opportunities": [],
    }
    source["execution_config_sha256"] = _hash(source["execution_config"])
    source["source_sha256"] = _hash(source)
    source["enabled"] = True
    source["error"] = None
    (root / FILES[0]).write_text(json.dumps(summary), encoding="utf-8")
    (root / FILES[1]).write_text(json.dumps(source), encoding="utf-8")
    for name in DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)


def _run(root: Path, report: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root), "--json-out", str(report)],
        check=False,
        capture_output=True,
        text=True,
    )


def _receipt(tmp_path: Path) -> tuple[Path, dict[str, object], str]:
    report = tmp_path / "preflight.json"
    result = _run(tmp_path / "state", report)
    return report, json.loads(report.read_text(encoding="utf-8")), result.stdout


@pytest.mark.parametrize("missing_kind", ["file", "directory"])
def test_missing_input_fails_closed_with_diagnostic_receipt(
    tmp_path: Path, missing_kind: str
) -> None:
    root = tmp_path / "state"
    _fixture(root)
    missing = FILES[1] if missing_kind == "file" else DIRS[1]
    if missing_kind == "file":
        (root / missing).unlink()
    else:
        (root / missing).rmdir()
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    report, payload, stdout = _receipt(tmp_path)
    assert report.is_file()
    assert "unusable authenticated LONG-trend input" in stdout
    assert payload["ready"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert {item["path"] for item in payload["inputs"] if not item["valid"]} == {
        missing
    }
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before


def test_complete_inputs_accept_empty_real_record_directories(tmp_path: Path) -> None:
    root = tmp_path / "state"
    _fixture(root)
    report = tmp_path / "preflight.json"
    result = _run(root, report)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ready"] is True
    assert payload["schema_version"] == 2
    assert len(payload["inputs"]) == 5
    assert all(item["valid"] is True for item in payload["inputs"])


def test_empty_required_summary_is_not_authenticated(tmp_path: Path) -> None:
    root = tmp_path / "state"
    _fixture(root)
    (root / FILES[0]).write_text("", encoding="utf-8")
    assert _receipt(tmp_path)[1]["inputs"][0]["reason"] == "missing_or_empty"


@pytest.mark.parametrize(
    ("mutate", "expected_reason"),
    [
        (
            lambda doc: doc.update(risk_rejected_integrity_clean=False, risk_rejected_missing_rank=67),
            "risk_rejected_integrity_not_clean",
        ),
        (
            lambda doc: doc.update(enabled=False, error="producer_failed"),
            "full_stack_enabled_invalid",
        ),
        (
            lambda doc: doc.update(risk_rejected_stack_evaluated=1),
            "risk_rejected_row_count_mismatch",
        ),
        (
            lambda doc: doc.update(execution_authority=True),
            "full_stack_execution_authority_invalid",
        ),
    ],
)
def test_bad_summary_fails_closed_with_explicit_reason(
    tmp_path: Path, mutate: object, expected_reason: str
) -> None:
    root = tmp_path / "state"
    _fixture(root)
    target = root / FILES[0]
    doc = json.loads(target.read_text(encoding="utf-8"))
    mutate(doc)
    target.write_text(json.dumps(doc), encoding="utf-8")
    report, payload, _ = _receipt(tmp_path)
    assert report.is_file()
    assert payload["ready"] is False
    assert payload["inputs"][0]["reason"] == expected_reason
    if expected_reason == "risk_rejected_integrity_not_clean":
        assert payload["inputs"][0]["metrics"]["risk_rejected_missing_rank"] == 67


@pytest.mark.parametrize(
    ("mutate", "expected_reason"),
    [
        (
            lambda doc: doc.update(source_sha256="a" * 64),
            "long_source_digest_mismatch",
        ),
        (
            lambda doc: doc.update(execution_config_sha256="a" * 64),
            "execution_config_digest_mismatch",
        ),
        (
            lambda doc: doc.update(enabled=False, error="source_unavailable"),
            "long_source_enabled_invalid",
        ),
        (
            lambda doc: doc.update(source_opportunity_count=3),
            "long_source_record_count_mismatch",
        ),
        (
            lambda doc: doc.update(overlap_started_at_ms=12),
            "long_source_digest_mismatch",
        ),
    ],
)
def test_bad_long_source_fails_closed_with_explicit_reason(
    tmp_path: Path, mutate: object, expected_reason: str
) -> None:
    root = tmp_path / "state"
    _fixture(root)
    target = root / FILES[1]
    doc = json.loads(target.read_text(encoding="utf-8"))
    mutate(doc)
    target.write_text(json.dumps(doc), encoding="utf-8")
    assert _receipt(tmp_path)[1]["inputs"][1]["reason"] == expected_reason


def test_cross_file_overlap_mismatch_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "state"
    _fixture(root)
    target = root / FILES[0]
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["overlap_started_at_ms"] += 1
    target.write_text(json.dumps(doc), encoding="utf-8")
    assert _receipt(tmp_path)[1]["inputs"][1]["reason"] == (
        "source_summary_overlap_mismatch"
    )


def test_malformed_payload_is_explained_and_not_uploaded(tmp_path: Path) -> None:
    root = tmp_path / "state"
    _fixture(root)
    (root / FILES[1]).write_text("{invalid", encoding="utf-8")
    assert _receipt(tmp_path)[1]["inputs"][1]["reason"] == "unreadable_json_object"


def test_workflow_diagnostic_does_not_override_compact_pack_gate() -> None:
    source = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    verify = source.index("- name: Verify compact exact LONG trend research source")
    diagnostics = source.index("- name: Upload compact LONG trend source preflight diagnostics")
    pack = source.index("- name: Pack compact exact LONG trend research source")
    actual_upload = source.index("- name: Upload compact exact LONG trend research source")
    assert verify < diagnostics < pack < actual_upload
    segment = source[verify:pack]
    assert "continue-on-error: true" in segment
    assert "verify_compact_long_trend_exact_source.py" in segment
    assert "compact-long-trend-source-preflight.json" in segment
    assert "continuous-paper-long-trend-exact-source-preflight-" in segment
    pack_step = source[pack:actual_upload]
    assert "steps.compact_long_trend_source_manifest.outcome == 'success'" in pack_step
    assert "live_orders: true" not in segment
