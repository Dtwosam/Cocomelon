from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_review as review
from cocomelon.research.historical_archive_presets import JUL_SEP_2026_V2
from cocomelon.research.historical_archive_review import (
    FROZEN_ARCHIVE_DEVELOPMENT_REVIEW_V1,
    HistoricalArchiveReviewError,
    build_archive_development_review,
    write_archive_development_review,
)


def _evaluation(
    *,
    trades: int,
    mean: str | None,
    total: str,
) -> dict[str, object]:
    long_count = trades // 2
    return {
        "trade_count": trades,
        "long_count": long_count,
        "short_count": trades - long_count,
        "total_realized_net_return": total,
        "mean_realized_net_return": mean,
    }


def _fold(
    index: int,
    *,
    shared: dict[str, object],
    market: dict[str, object],
) -> dict[str, object]:
    return {
        "fold_index": index,
        "shared_test": shared,
        "market_test": market,
    }


def _comparison_payload(
    *,
    qualifying_family: str | None = None,
    low_activity_family: str | None = None,
) -> dict[str, object]:
    positive = _evaluation(trades=25, mean="0.01", total="0.25")
    negative = _evaluation(trades=25, mean="-0.01", total="-0.25")
    low_activity = _evaluation(trades=19, mean="0.01", total="0.19")

    payload: dict[str, object] = {
        "report_id": "r" * 64,
        "comparison_version": "historical-directional-model-comparison-test",
        "evidence_class": "touched_development",
        "config": {
            "min_validation_trades": 20,
            "min_validation_mean_net_return": "0",
        },
    }
    field_by_family = dict(review.VARIANT_SPECS)
    for family, field in field_by_family.items():
        shared_second = (
            positive
            if family == qualifying_family
            else (
                low_activity
                if family == low_activity_family
                else negative
            )
        )
        payload[field] = [
            _fold(1, shared=positive, market=positive),
            _fold(2, shared=shared_second, market=negative),
        ]
    return payload


def _prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    comparison: dict[str, object],
) -> Path:
    output_root = tmp_path / "output"
    output_root.mkdir()
    (output_root / "comparison.json").write_text(
        json.dumps(comparison, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        review,
        "verify_archive_preset_bundle_receipt",
        lambda *args, **kwargs: SimpleNamespace(bundle_id="b" * 64),
    )
    monkeypatch.setattr(
        review,
        "verify_archive_preset_run_receipt",
        lambda *args, **kwargs: SimpleNamespace(
            receipt_id="p" * 64,
            comparison_report_id="r" * 64,
            comparison_version="historical-directional-model-comparison-test",
        ),
    )
    return output_root


def test_frozen_review_policy_identity_is_deterministic() -> None:
    first = FROZEN_ARCHIVE_DEVELOPMENT_REVIEW_V1
    second = type(first)()

    assert first == second
    assert first.min_test_folds == 2
    assert first.test_trades_per_fold_source == (
        "comparison_config.min_validation_trades"
    )
    assert first.minimum_mean_source == (
        "comparison_config.min_validation_mean_net_return"
    )
    assert len(first.policy_id) == 64


def test_review_only_qualifies_every_fold_positive_stable_variant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = _prepare(
        monkeypatch,
        tmp_path,
        comparison=_comparison_payload(
            qualifying_family="stable_horizon_ridge",
        ),
    )

    result = build_archive_development_review(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    assert result.status == "freeze_review_available"
    assert result.promotion_eligible is False
    assert len(result.variants) == 8
    qualified = tuple(
        item
        for item in result.variants
        if item.eligible_for_freeze_review
    )
    assert len(qualified) == 1
    candidate = qualified[0]
    assert candidate.model_family == "stable_horizon_ridge"
    assert candidate.calibration_variant == "shared"
    assert candidate.total_test_trades == 50
    assert candidate.minimum_fold_trade_count == 25
    assert candidate.mean_realized_net_return is not None
    assert candidate.mean_realized_net_return > 0
    assert candidate.reason_codes == ("qualified",)
    assert len(result.review_id) == 64


def test_review_rejects_positive_aggregate_when_one_fold_loses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _comparison_payload()
    folds = payload["stable_tree_folds"]
    assert isinstance(folds, list)
    folds[0] = _fold(
        1,
        shared=_evaluation(trades=25, mean="0.04", total="1.00"),
        market=_evaluation(trades=25, mean="-0.01", total="-0.25"),
    )
    folds[1] = _fold(
        2,
        shared=_evaluation(trades=25, mean="-0.01", total="-0.25"),
        market=_evaluation(trades=25, mean="-0.01", total="-0.25"),
    )
    output_root = _prepare(monkeypatch, tmp_path, comparison=payload)

    result = build_archive_development_review(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    tree_shared = next(
        item
        for item in result.variants
        if item.model_family == "stable_tree"
        and item.calibration_variant == "shared"
    )
    assert tree_shared.mean_realized_net_return is not None
    assert tree_shared.mean_realized_net_return > 0
    assert tree_shared.eligible_for_freeze_review is False
    assert tree_shared.nonpositive_fold_indices == (2,)
    assert "test_fold_not_above_floor" in tree_shared.reason_codes


def test_review_rejects_undertraded_test_fold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = _prepare(
        monkeypatch,
        tmp_path,
        comparison=_comparison_payload(
            low_activity_family="portfolio_capacity_stable_ridge",
        ),
    )

    result = build_archive_development_review(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    candidate = next(
        item
        for item in result.variants
        if item.model_family == "portfolio_capacity_stable_ridge"
        and item.calibration_variant == "shared"
    )
    assert candidate.eligible_for_freeze_review is False
    assert candidate.insufficient_activity_fold_indices == (2,)
    assert "insufficient_test_trades" in candidate.reason_codes


def test_review_reports_no_candidate_when_every_variant_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = _prepare(
        monkeypatch,
        tmp_path,
        comparison=_comparison_payload(),
    )

    result = build_archive_development_review(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    assert result.status == "no_candidate_qualified"
    assert not any(
        item.eligible_for_freeze_review for item in result.variants
    )


def test_review_fails_if_comparison_identity_does_not_match_run_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _comparison_payload(
        qualifying_family="stable_horizon_ridge",
    )
    payload["report_id"] = "x" * 64
    output_root = _prepare(monkeypatch, tmp_path, comparison=payload)

    with pytest.raises(
        HistoricalArchiveReviewError,
        match="COMPARISON_REPORT_ID_MISMATCH",
    ):
        build_archive_development_review(
            JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
        )


def test_development_review_write_is_idempotent_and_conflict_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = _prepare(
        monkeypatch,
        tmp_path,
        comparison=_comparison_payload(
            qualifying_family="stable_horizon_ridge",
        ),
    )
    result = build_archive_development_review(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    path = write_archive_development_review(output_root, result)
    second = write_archive_development_review(output_root, result)

    assert second == path
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["review_id"] == result.review_id
    path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(
        HistoricalArchiveReviewError,
        match="DEVELOPMENT_REVIEW_CONFLICT",
    ):
        write_archive_development_review(output_root, result)
