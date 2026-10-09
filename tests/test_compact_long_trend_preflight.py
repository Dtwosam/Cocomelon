"""Missing post-handoff research inputs must be visible without false evidence."""

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


def _run(state: Path, report: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(state), "--json-out", str(report)],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("missing_kind", ["file", "directory"])
def test_missing_input_fails_closed_with_authenticated_preflight_receipt(
    tmp_path: Path, missing_kind: str
) -> None:
    root = tmp_path / "state"
    root.mkdir()
    for name in FILES:
        (root / name).write_text("{}", encoding="utf-8")
    for name in DIRS:
        (root / name).mkdir(parents=True)
    missing = FILES[1] if missing_kind == "file" else DIRS[1]
    if missing_kind == "file":
        (root / missing).unlink()
    else:
        (root / missing).rmdir()

    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    report = tmp_path / "preflight.json"
    result = _run(root, report)
    assert result.returncode == 1
    assert "missing authenticated LONG-trend input" in result.stdout
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ready"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert {item["path"] for item in payload["inputs"] if not item["present"]} == {
        missing
    }
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before


def test_complete_inputs_accept_empty_authenticated_record_directories(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    root.mkdir()
    for name in FILES:
        (root / name).write_text("{}", encoding="utf-8")
    for name in DIRS:
        (root / name).mkdir(parents=True)
    report = tmp_path / "preflight.json"
    result = _run(root, report)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ready"] is True
    assert len(payload["inputs"]) == 5
    assert all(item["present"] is True for item in payload["inputs"])


def test_empty_required_summary_is_not_authenticated(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    root.mkdir()
    (root / FILES[0]).touch()
    (root / FILES[1]).write_text("{}", encoding="utf-8")
    for name in DIRS:
        (root / name).mkdir(parents=True)
    report = tmp_path / "preflight.json"
    assert _run(root, report).returncode == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["inputs"][0]["present"] is False


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
