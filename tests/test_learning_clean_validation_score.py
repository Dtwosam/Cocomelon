from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.domain import Direction, MarketId
from cocomelon.research.learning_candidate_freeze import (
    build_learning_candidate_freeze,
    write_learning_candidate_freeze,
)
from cocomelon.research.learning_candidate_package import (
    materialize_learning_candidate_package,
)
from cocomelon.research.learning_clean_validation_score import (
    LearningCleanValidationScoreError,
    load_learning_clean_validation_score,
    score_learning_clean_validation,
    verify_learning_clean_validation_score,
    write_learning_clean_validation_score,
)
from cocomelon.research.learning_clean_validation_spec import (
    build_learning_clean_validation_spec,
    write_learning_clean_validation_spec,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)
from tests.test_learning_experiment import _run


def _setup(tmp_path):
    _experiment, experiment_root = _run(tmp_path)
    freeze = build_learning_candidate_freeze(
        experiment_root=experiment_root,
        frozen_at_ms=200_000,
    )
    freeze_path = write_learning_candidate_freeze(tmp_path / "freeze", freeze)
    package_root = tmp_path / "package"
    materialize_learning_candidate_package(
        experiment_root=experiment_root,
        candidate_freeze_path=freeze_path,
        package_root=package_root,
    )
    spec = build_learning_clean_validation_spec(package_root)
    spec_path = write_learning_clean_validation_spec(tmp_path / "spec", spec)
    ledger_root = tmp_path / "clean-ledger"
    return freeze, package_root, spec, spec_path, ledger_root


def _record(
    *,
    candidate_id: str,
    spec_id: str,
    index: int,
    opened_at_ms: int,
    net_r: Decimal,
) -> LearningEvidenceRecord:
    closed_at_ms = opened_at_ms + 100
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=f"clean-paper-{index}",
        source_evidence_class="prospective_clean",
        candidate_id=candidate_id,
        candidate_spec_id=spec_id,
        campaign_id=f"clean-campaign-{candidate_id[:8]}",
        market=MarketId("", "HYPE"),
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=f"clean-feature-{index}",
        research_eligible_at_ms=closed_at_ms,
        gross_realized_pnl=net_r * Decimal("100"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        net_pnl=net_r * Decimal("100"),
        net_r=net_r,
    )


def _append(
    ledger_root,
    *,
    candidate_id: str,
    spec_id: str,
    validation_start_ms: int,
    values: list[Decimal],
    offset: int = 0,
) -> None:
    ledger = LearningEvidenceLedger(ledger_root)
    for index, value in enumerate(values, start=1 + offset):
        ledger.record(
            _record(
                candidate_id=candidate_id,
                spec_id=spec_id,
                index=index,
                opened_at_ms=validation_start_ms + index * 1_000,
                net_r=value,
            )
        )


def test_clean_validation_score_stays_economically_blind_until_complete(
    tmp_path,
) -> None:
    freeze, package_root, spec, spec_path, ledger_root = _setup(tmp_path)
    _append(
        ledger_root,
        candidate_id=freeze.candidate_id,
        spec_id=spec.spec_id,
        validation_start_ms=spec.validation_start_ms,
        values=[Decimal("0.1")] * 19,
    )

    score = score_learning_clean_validation(
        ledger_root=ledger_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )

    assert score.status == "collecting"
    assert score.eligible_settled_trade_count == 19
    assert len(score.selected_record_ids) == 19
    assert score.overall_mean_net_r is None
    assert score.blocks == ()
    assert score.qualifies_clean_validation is None
    assert score.promotion_eligible is False
    assert score.execution_ready is False


def test_clean_validation_score_freezes_first_twenty_settled_trades(
    tmp_path,
) -> None:
    freeze, package_root, spec, spec_path, ledger_root = _setup(tmp_path)
    _append(
        ledger_root,
        candidate_id=freeze.candidate_id,
        spec_id=spec.spec_id,
        validation_start_ms=spec.validation_start_ms,
        values=[Decimal("0.1")] * 20,
    )
    first = score_learning_clean_validation(
        ledger_root=ledger_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )
    assert first.status == "complete"
    assert first.qualifies_clean_validation is True
    assert first.overall_mean_net_r == Decimal("0.1")
    assert [block.mean_net_r for block in first.blocks] == [Decimal("0.1")] * 4
    selected = first.selected_record_ids

    _append(
        ledger_root,
        candidate_id=freeze.candidate_id,
        spec_id=spec.spec_id,
        validation_start_ms=spec.validation_start_ms,
        values=[Decimal("-100")],
        offset=20,
    )
    later = score_learning_clean_validation(
        ledger_root=ledger_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 100_000,
    )

    assert later.eligible_settled_trade_count == 21
    assert later.selected_record_ids == selected
    assert later.overall_mean_net_r == Decimal("0.1")
    assert later.qualifies_clean_validation is True


def test_clean_validation_requires_every_stability_block_to_clear_floor(
    tmp_path,
) -> None:
    freeze, package_root, spec, spec_path, ledger_root = _setup(tmp_path)
    values = [Decimal("-0.1")] * 5 + [Decimal("0.1")] * 15
    _append(
        ledger_root,
        candidate_id=freeze.candidate_id,
        spec_id=spec.spec_id,
        validation_start_ms=spec.validation_start_ms,
        values=values,
    )

    score = score_learning_clean_validation(
        ledger_root=ledger_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )

    assert score.status == "complete"
    assert score.overall_mean_net_r == Decimal("0.05")
    assert score.blocks[0].mean_net_r == Decimal("-0.1")
    assert score.qualifies_clean_validation is False


def test_clean_validation_ignores_wrong_candidate_spec_and_prestart_trades(
    tmp_path,
) -> None:
    freeze, package_root, spec, spec_path, ledger_root = _setup(tmp_path)
    ledger = LearningEvidenceLedger(ledger_root)
    ledger.record(
        _record(
            candidate_id=freeze.candidate_id,
            spec_id="f" * 64,
            index=100,
            opened_at_ms=spec.validation_start_ms + 10,
            net_r=Decimal("10"),
        )
    )
    ledger.record(
        _record(
            candidate_id=freeze.candidate_id,
            spec_id=spec.spec_id,
            index=101,
            opened_at_ms=spec.validation_start_ms - 1_000,
            net_r=Decimal("10"),
        )
    )
    _append(
        ledger_root,
        candidate_id=freeze.candidate_id,
        spec_id=spec.spec_id,
        validation_start_ms=spec.validation_start_ms,
        values=[Decimal("0.1")] * 20,
    )

    score = score_learning_clean_validation(
        ledger_root=ledger_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )

    assert score.eligible_settled_trade_count == 20
    assert score.qualifies_clean_validation is True


def test_clean_validation_score_receipt_reverifies_and_rejects_tampering(
    tmp_path,
) -> None:
    freeze, package_root, spec, spec_path, ledger_root = _setup(tmp_path)
    _append(
        ledger_root,
        candidate_id=freeze.candidate_id,
        spec_id=spec.spec_id,
        validation_start_ms=spec.validation_start_ms,
        values=[Decimal("0.1")] * 20,
    )
    score = score_learning_clean_validation(
        ledger_root=ledger_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )
    path = write_learning_clean_validation_score(tmp_path / "score", score)

    assert load_learning_clean_validation_score(path) == score
    assert verify_learning_clean_validation_score(
        path,
        ledger_root=ledger_root,
        package_root=package_root,
        validation_spec_path=spec_path,
    ) == score

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["qualifies_clean_validation"] = False
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        LearningCleanValidationScoreError,
        match="SCORE_ID_MISMATCH",
    ):
        load_learning_clean_validation_score(path)


def test_clean_validation_score_rejects_prestart_scoring(tmp_path) -> None:
    _freeze, package_root, spec, spec_path, ledger_root = _setup(tmp_path)

    with pytest.raises(
        LearningCleanValidationScoreError,
        match="BEFORE_START",
    ):
        score_learning_clean_validation(
            ledger_root=ledger_root,
            package_root=package_root,
            validation_spec_path=spec_path,
            as_of_ms=spec.validation_start_ms - 1,
        )
