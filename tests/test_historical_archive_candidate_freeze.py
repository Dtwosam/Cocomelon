from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_candidate_freeze as candidate
from cocomelon.research.historical_archive_candidate_freeze import (
    HistoricalArchiveCandidateFreezeError,
    build_archive_candidate_freeze,
    verify_archive_candidate_freeze,
    write_archive_candidate_freeze,
)
from cocomelon.research.historical_archive_presets import JUL_SEP_2026_V2
from cocomelon.research.historical_archive_review import (
    HistoricalDevelopmentVariantReview,
)
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)


def _variant(
    *,
    family: str = "stable_tree",
    calibration: str = "shared",
    qualified: bool = True,
) -> HistoricalDevelopmentVariantReview:
    return HistoricalDevelopmentVariantReview(
        model_family=family,
        calibration_variant=calibration,
        fold_count=3,
        minimum_required_fold_count=2,
        minimum_required_trades_per_fold=20,
        minimum_required_mean_net_return=Decimal("0"),
        total_test_trades=90 if qualified else 30,
        long_test_trades=45 if qualified else 15,
        short_test_trades=45 if qualified else 15,
        total_realized_net_return=Decimal("0.45") if qualified else Decimal("-0.03"),
        mean_realized_net_return=Decimal("0.005") if qualified else Decimal("-0.001"),
        minimum_fold_trade_count=25 if qualified else 5,
        insufficient_activity_fold_indices=() if qualified else (2,),
        nonpositive_fold_indices=() if qualified else (2,),
        eligible_for_freeze_review=qualified,
        reason_codes=(
            ("qualified",)
            if qualified
            else (
                "insufficient_test_trades",
                "test_fold_not_above_floor",
                "overall_test_mean_not_above_floor",
            )
        ),
    )


def _review(
    variants: tuple[HistoricalDevelopmentVariantReview, ...],
) -> SimpleNamespace:
    status = (
        "freeze_review_available"
        if any(item.eligible_for_freeze_review for item in variants)
        else "no_candidate_qualified"
    )
    payload = {
        "preset_name": JUL_SEP_2026_V2.name,
        "preset_id": JUL_SEP_2026_V2.preset_id,
        "evidence_class": "touched_development",
        "preset_run_receipt_id": "f" * 64,
        "bundle_id": "b" * 64,
        "comparison_report_id": "e" * 64,
        "comparison_version": "historical-model-comparison-v7",
        "policy_id": "d" * 64,
        "minimum_required_trades_per_fold": 20,
        "minimum_required_mean_net_return": "0",
        "variants": tuple(item.to_dict() for item in variants),
        "status": status,
        "promotion_eligible": False,
        "schema_version": 1,
        "review_id": "c" * 64,
    }
    return SimpleNamespace(
        bundle_id="b" * 64,
        review_id="c" * 64,
        policy_id="d" * 64,
        comparison_report_id="e" * 64,
        comparison_version="historical-model-comparison-v7",
        variants=variants,
        to_dict=lambda: payload,
    )


def _persist_review(output_root: Path, review: SimpleNamespace) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "development-review.json").write_text(
        json.dumps(
            review.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _install_review(
    monkeypatch: pytest.MonkeyPatch,
    output_root: Path,
    review: SimpleNamespace,
) -> None:
    _persist_review(output_root, review)
    monkeypatch.setattr(
        candidate,
        "build_archive_development_review",
        lambda *args, **kwargs: review,
    )


def test_unique_qualified_variant_freezes_future_only_recipe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    review = _review((_variant(), _variant(qualified=False)))
    _install_review(monkeypatch, output_root, review)
    frozen_at_ms = JUL_SEP_2026_V2.end_ms + 60_000

    freeze = build_archive_candidate_freeze(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
        frozen_at_ms=frozen_at_ms,
    )

    assert freeze.model_family == "stable_tree"
    assert freeze.calibration_variant == "shared"
    assert freeze.selection_policy == "unique_qualified_variant_only"
    assert freeze.candidate_kind == "model_family_recipe"
    assert freeze.prospective_only is True
    assert freeze.promotion_eligible is False
    assert freeze.execution_ready is False
    assert freeze.total_test_trades == 90
    assert freeze.mean_realized_net_return == Decimal("0.005")
    assert freeze.validation_not_before_ms == (
        frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
    )
    assert len(freeze.qualified_variant_sha256) == 64
    assert len(freeze.candidate_id) == 64


def test_candidate_freeze_rejects_zero_qualified_variants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    review = _review((_variant(qualified=False),))
    _install_review(monkeypatch, output_root, review)

    with pytest.raises(
        HistoricalArchiveCandidateFreezeError,
        match="NO_QUALIFIED_ARCHIVE_CANDIDATE",
    ):
        build_archive_candidate_freeze(
            JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
            frozen_at_ms=JUL_SEP_2026_V2.end_ms + 60_000,
        )


def test_candidate_freeze_rejects_multiple_qualified_variants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    review = _review(
        (
            _variant(),
            _variant(
                family="stable_horizon_ridge",
                calibration="market",
            ),
        )
    )
    _install_review(monkeypatch, output_root, review)

    with pytest.raises(
        HistoricalArchiveCandidateFreezeError,
        match="MULTIPLE_QUALIFIED_ARCHIVE_CANDIDATES",
    ):
        build_archive_candidate_freeze(
            JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
            frozen_at_ms=JUL_SEP_2026_V2.end_ms + 60_000,
        )


def test_candidate_freeze_requires_persisted_review_to_match_recomputed_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    review = _review((_variant(),))
    _install_review(monkeypatch, output_root, review)
    (output_root / "development-review.json").write_text(
        '{"tampered":true}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCandidateFreezeError,
        match="DEVELOPMENT_REVIEW_RECEIPT_MISMATCH",
    ):
        build_archive_candidate_freeze(
            JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
            frozen_at_ms=JUL_SEP_2026_V2.end_ms + 60_000,
        )


def test_candidate_freeze_rejects_retrospective_freeze_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    review = _review((_variant(),))
    _install_review(monkeypatch, output_root, review)

    with pytest.raises(ValueError, match="frozen_at_ms must not precede"):
        build_archive_candidate_freeze(
            JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
            frozen_at_ms=JUL_SEP_2026_V2.end_ms - 1,
        )


def test_candidate_freeze_round_trips_and_detects_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    review = _review((_variant(),))
    _install_review(monkeypatch, output_root, review)
    freeze = build_archive_candidate_freeze(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
        frozen_at_ms=JUL_SEP_2026_V2.end_ms + 60_000,
    )
    path = write_archive_candidate_freeze(output_root, freeze)

    verified = verify_archive_candidate_freeze(
        path,
        preset=JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    assert verified == freeze

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["model_family"] = "stable_horizon_ridge"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        HistoricalArchiveCandidateFreezeError,
        match="ARCHIVE_CANDIDATE_FREEZE_ID_MISMATCH",
    ):
        verify_archive_candidate_freeze(
            path,
            preset=JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
        )


def test_candidate_freeze_write_refuses_conflicting_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    review = _review((_variant(),))
    _install_review(monkeypatch, output_root, review)
    freeze = build_archive_candidate_freeze(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
        frozen_at_ms=JUL_SEP_2026_V2.end_ms + 60_000,
    )
    path = write_archive_candidate_freeze(output_root, freeze)
    path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(
        HistoricalArchiveCandidateFreezeError,
        match="ARCHIVE_CANDIDATE_FREEZE_CONFLICT",
    ):
        write_archive_candidate_freeze(output_root, freeze)
