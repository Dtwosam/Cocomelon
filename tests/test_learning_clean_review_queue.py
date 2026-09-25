from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

from cocomelon.research.learning_clean_finalization import (
    build_learning_clean_finalization,
    write_learning_clean_finalization,
)
from cocomelon.research.learning_clean_review_queue import (
    build_learning_clean_review_queue,
    render_learning_clean_review_markdown,
)
from cocomelon.research.learning_clean_state import (
    build_learning_clean_state,
    write_learning_clean_state,
)
from cocomelon.research.learning_clean_validation_score import (
    score_learning_clean_validation,
    write_learning_clean_validation_score,
)
from tests.test_learning_clean_validation_score import _append, _setup


def _lineage(
    tmp_path: Path,
    *,
    values: list[Decimal],
    finalize: bool,
) -> Path:
    source = tmp_path / "source"
    _freeze, package_root, spec, spec_path, evidence_root = _setup(source)
    if values:
        _append(evidence_root, spec=spec, values=values)

    root = tmp_path / "lineage"
    candidate = root / "candidates" / "baseline"
    candidate.mkdir(parents=True)
    shutil.copytree(package_root, candidate / "package")
    shutil.copy2(spec_path, candidate / "candidate-validation-spec.json")
    shutil.copytree(evidence_root, candidate / "evidence")

    as_of_ms = (
        spec.validation_start_ms - 1
        if not values
        else spec.validation_start_ms + 100_000
    )
    state = build_learning_clean_state(
        package_root=candidate / "package",
        validation_spec_path=candidate / "candidate-validation-spec.json",
        evidence_root=candidate / "evidence",
        as_of_ms=as_of_ms,
    )
    write_learning_clean_state(candidate, state)

    if finalize:
        score = score_learning_clean_validation(
            evidence_root=candidate / "evidence",
            package_root=candidate / "package",
            validation_spec_path=candidate / "candidate-validation-spec.json",
            as_of_ms=as_of_ms,
        )
        score_path = write_learning_clean_validation_score(
            candidate / "score",
            score,
        )
        finalization = build_learning_clean_finalization(
            package_root=candidate / "package",
            validation_spec_path=candidate / "candidate-validation-spec.json",
            validation_score_path=score_path,
            evidence_root=candidate / "evidence",
            finalized_at_ms=max(as_of_ms, score.as_of_ms),
        )
        write_learning_clean_finalization(
            candidate / "finalization",
            finalization,
        )
    return root


def test_review_queue_surfaces_verified_review_ready_candidate(tmp_path) -> None:
    root = _lineage(
        tmp_path,
        values=[Decimal("0.1")] * 20,
        finalize=True,
    )

    queue = build_learning_clean_review_queue([root])

    assert queue["candidate_count"] == 1
    assert queue["review_ready_count"] == 1
    assert queue["validation_failed_count"] == 0
    candidate = queue["candidates"][0]
    assert candidate["lifecycle_status"] == "review_ready"
    assert candidate["eligible_for_candidate_review"] is True
    assert candidate["settled_trade_count"] == 20
    assert candidate["promotion_eligible"] is False
    assert candidate["execution_ready"] is False

    markdown = render_learning_clean_review_markdown(queue)
    assert "REVIEW READY" in markdown
    assert "overall_mean_net_r" not in markdown
    assert "predicted_net_r" not in markdown
    assert "qualifies_clean_validation" not in markdown


def test_review_queue_records_terminal_validation_failure_without_economics(
    tmp_path,
) -> None:
    root = _lineage(
        tmp_path,
        values=[Decimal("-0.1")] * 5 + [Decimal("0.1")] * 15,
        finalize=True,
    )

    queue = build_learning_clean_review_queue([root])

    assert queue["review_ready_count"] == 0
    assert queue["validation_failed_count"] == 1
    candidate = queue["candidates"][0]
    assert candidate["lifecycle_status"] == "validation_failed"
    assert candidate["eligible_for_candidate_review"] is False
    markdown = render_learning_clean_review_markdown(queue)
    assert "REVIEW READY" not in markdown


def test_review_queue_tracks_collecting_candidate_without_finalization(
    tmp_path,
) -> None:
    root = _lineage(
        tmp_path,
        values=[Decimal("0.1")] * 5,
        finalize=False,
    )

    queue = build_learning_clean_review_queue([root])

    assert queue["collecting_count"] == 1
    assert queue["review_ready_count"] == 0
    candidate = queue["candidates"][0]
    assert candidate["lifecycle_status"] == "collecting"
    assert candidate["settled_trade_count"] == 5
    assert candidate["eligible_for_candidate_review"] is None


def test_review_queue_deduplicates_identical_candidate_lineages(tmp_path) -> None:
    root = _lineage(
        tmp_path,
        values=[Decimal("0.1")] * 20,
        finalize=True,
    )
    duplicate = tmp_path / "lineage-copy"
    shutil.copytree(root, duplicate)

    queue = build_learning_clean_review_queue([root, duplicate])

    assert queue["candidate_count"] == 1
    assert queue["review_ready_count"] == 1
