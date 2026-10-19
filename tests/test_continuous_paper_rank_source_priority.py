"""Strict original-v3 PAPER capture supersedes *optional* rank research.

Disabling the giant historical research restore deliberately invalidates
rank-source continuity. It MUST NOT convert missing rank rows into qualified
PAPER market evidence, re-label old failed rows, or change live execution.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from cocomelon import continuous_paper
from cocomelon.continuous_paper import (
    _disqualify_optional_rank_research_for_v3,
)


@pytest.mark.parametrize(
    "source_name",
    ["rank_snapshot", "rank_full_features", "rank_market_context"],
)
def test_source_first_rank_retirement_is_permanent_negative_receipt(
    tmp_path: Path, source_name: str,
) -> None:
    archive = tmp_path / "prospective-short-rank-first-seen" / "snapshots"
    archive.mkdir(parents=True)
    historical = archive / "0000000000001000.json"
    historical.write_bytes(b"original historical rank bytes must stay unchanged\n")
    receipt = tmp_path / f"{source_name}-error.json"
    reason = _disqualify_optional_rank_research_for_v3(
        receipt, source_name=source_name,
    )
    persisted = json.loads(receipt.read_text(encoding="utf-8"))
    assert persisted == {
        "error": reason,
        "research_only": True,
        "source_continuity_certified": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    assert reason.endswith(
        "_research_discontinued_for_original_v3_source_priority"
    )
    assert historical.read_bytes() == (
        b"original historical rank bytes must stay unchanged\n"
    )
    assert not any(path.name.endswith(".tmp") for path in tmp_path.iterdir())


def test_source_first_receipt_does_not_succeed_when_disk_refuses_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_path: Path, _payload: object) -> None:
        raise OSError("rank research source retirement fsync failed")

    monkeypatch.setattr(continuous_paper, "_write_json_atomic", fail)
    receipt = tmp_path / "rank-error.json"
    with pytest.raises(OSError, match="fsync failed"):
        _disqualify_optional_rank_research_for_v3(
            receipt, source_name="rank_snapshot",
        )
    assert not receipt.exists()


def test_unknown_rank_research_source_cannot_claim_valid_receipt(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="invalid optional rank"):
        _disqualify_optional_rank_research_for_v3(
            tmp_path / "invented.json", source_name="original_v3",
        )
    assert not (tmp_path / "invented.json").exists()


def test_worker_routes_all_three_rank_archives_around_heavy_restore() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/cocomelon/continuous_paper.py"
    ).read_text(encoding="utf-8")
    module = ast.parse(source)
    candidate_branches = [
        node for node in ast.walk(module)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "rank_source_priority_requested"
    ]
    assert len(candidate_branches) == 3
    source_names: list[str] = []
    for branch in candidate_branches:
        calls = [
            node for statement in branch.body for node in ast.walk(statement)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_disqualify_optional_rank_research_for_v3"
        ]
        assert len(calls) == 1
        keyword = next(
            item for item in calls[0].keywords if item.arg == "source_name"
        )
        assert isinstance(keyword.value, ast.Constant)
        source_names.append(keyword.value.value)
        # Never call a heavy historical constructor, emit an original
        # market event, or turn off actual PAPER execution in this branch.
        serialized = ast.dump(branch.body[0])
        assert "FirstSeenRankSnapshotStore" not in serialized
        assert "OriginalRankFeatureInputBatchStore" not in serialized
        assert "OriginalRankEligibilityContextStore" not in serialized
        assert "LiveExecution" not in serialized
    assert set(source_names) == {
        "rank_snapshot", "rank_full_features", "rank_market_context",
    }
    assert 'os.environ.get("V3_CAPTURE_ORIGINAL_SOURCE") == "1"' in source
    assert "rank_tracker = LatestCoarseRankTracker()" in source
    assert "capture_rank_first_seen(" in source
    # Missing rank research inputs are never treated as rank-qualified.
    assert "if rank_snapshot_capture_error is not None:" in source


def test_existing_rank_failure_receipts_remain_first_priority() -> None:
    worker = (
        Path(__file__).resolve().parents[1]
        / "src/cocomelon/continuous_paper.py"
    ).read_text(encoding="utf-8")
    for item in (
        "rank_snapshot_error_path",
        "rank_input_error_path",
        "rank_context_error_path",
    ):
        test = worker.index(f"if {item}.exists():", worker.index(
            "rank_source_started = time.perf_counter()",
        ))
        priority = worker.index("elif rank_source_priority_requested:", test)
        assert test < priority
