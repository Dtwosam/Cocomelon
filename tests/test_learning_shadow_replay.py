from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest

from cocomelon.research import learning_shadow_replay
from cocomelon.research.learning_shadow_evidence import LearningShadowEvidenceStore
from cocomelon.research.learning_shadow_replay import (
    load_learning_shadow_replay_receipt,
    run_learning_shadow_replay,
    verify_learning_shadow_replay_receipt,
)
from cocomelon.strategies.engine import evaluate_strategies
from tests.test_learning_shadow_evidence import _shadow_inputs
from tests.test_research_cohort import _cohort_roots

cohort_module = import_module("cocomelon.research.cohort")


def _prepared_source(tmp_path: Path) -> tuple[Path, Path]:
    recording_root, source_root, _session = _cohort_roots(tmp_path)
    cohort_module.prepare_research_cohort_source(
        recording_root,
        source_root,
        Decimal("10000"),
        trigger_head_sha="f" * 40,
    )
    return recording_root, source_root / "bundle.json"


def _lineage(tmp_path: Path):
    (
        package_root,
        spec_path,
        clean_evidence_root,
        score_path,
        finalization_path,
        dossier_path,
        _decision,
        decision_path,
        admission,
        admission_path,
    ) = _shadow_inputs(tmp_path)
    return {
        "package_root": package_root,
        "validation_spec_path": spec_path,
        "clean_evidence_root": clean_evidence_root,
        "validation_score_path": score_path,
        "finalization_path": finalization_path,
        "review_dossier_path": dossier_path,
        "review_decision_path": decision_path,
        "admission": admission,
        "shadow_admission_path": admission_path,
    }


def _run_kwargs(tmp_path: Path) -> dict[str, object]:
    recording_root, bundle_path = _prepared_source(tmp_path)
    lineage = _lineage(tmp_path)
    return {
        "recording_root": recording_root,
        "bundle_path": bundle_path,
        "output_root": tmp_path / "shadow-output",
        "shadow_evidence_root": tmp_path / "shadow-evidence",
        "runtime_code_revision": "c" * 40,
        "evidence_eligible_at_ms": 100_000_000,
        **{
            key: value
            for key, value in lineage.items()
            if key != "admission"
        },
    }


def test_shadow_replay_real_admission_refuses_pre_review_recording(tmp_path) -> None:
    kwargs = _run_kwargs(tmp_path)

    receipt = run_learning_shadow_replay(**kwargs)

    assert receipt.closed_trade_ids == ()
    assert receipt.created_shadow_records == 0
    assert receipt.existing_shadow_records == 0
    assert receipt.paper_only is True
    assert receipt.research_only is True
    assert receipt.promotion_eligible is False
    assert receipt.execution_ready is False
    assert receipt.live_promotion_authorized is False

    path = Path(cast_path(kwargs["output_root"])) / "shadow-replay-receipt.json"
    assert load_learning_shadow_replay_receipt(path) == receipt
    assert verify_learning_shadow_replay_receipt(
        path,
        **_verify_kwargs(kwargs),
    ) == receipt


def cast_path(value: object) -> str:
    return str(value)


def _verify_kwargs(kwargs: dict[str, object]) -> dict[str, Path]:
    keys = (
        "bundle_path",
        "output_root",
        "shadow_evidence_root",
        "shadow_admission_path",
        "review_decision_path",
        "review_dossier_path",
        "package_root",
        "validation_spec_path",
        "validation_score_path",
        "finalization_path",
        "clean_evidence_root",
    )
    return {key: Path(str(kwargs[key])) for key in keys}


def test_shadow_replay_candidate_decisions_drive_real_paper_trade_and_evidence(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = _run_kwargs(tmp_path)
    lineage = _lineage(tmp_path)
    early_admission = replace(
        lineage["admission"],
        reviewed_at_ms=0,
        shadow_start_ms=0,
    )

    def fake_open(root: Path, **_kwargs: object) -> LearningShadowEvidenceStore:
        store = LearningShadowEvidenceStore(root, admission=early_admission)
        store.verify()
        return store

    class AcceptTrustedSource:
        def evaluate(self, context):
            return evaluate_strategies(context).decision

    monkeypatch.setattr(
        learning_shadow_replay,
        "open_verified_learning_shadow_evidence_store",
        fake_open,
    )
    monkeypatch.setattr(
        learning_shadow_replay,
        "build_learning_shadow_strategy_evaluator",
        lambda **_kwargs: AcceptTrustedSource(),
    )

    receipt = run_learning_shadow_replay(**kwargs)

    assert len(receipt.closed_trade_ids) == 1
    assert receipt.created_shadow_records == 1
    assert receipt.existing_shadow_records == 0
    assert receipt.feature_snapshot_count > 0
    assert len(receipt.candidate_decisions_sha256) == 64
    assert len(receipt.shadow_campaign_id) == 64

    store = LearningShadowEvidenceStore(
        Path(str(kwargs["shadow_evidence_root"])),
        admission=early_admission,
    )
    records = store.iter_records()
    assert len(records) == 1
    assert records[0].source_record_id == receipt.closed_trade_ids[0]
    assert records[0].candidate_spec_id == early_admission.shadow_admission_id
    assert records[0].campaign_id == receipt.shadow_campaign_id
    assert records[0].opened_at_ms >= early_admission.shadow_start_ms

    path = Path(str(kwargs["output_root"])) / "shadow-replay-receipt.json"
    assert verify_learning_shadow_replay_receipt(
        path,
        **_verify_kwargs(kwargs),
    ) == receipt


def test_shadow_replay_receipt_rejects_decision_tampering(tmp_path) -> None:
    kwargs = _run_kwargs(tmp_path)
    receipt = run_learning_shadow_replay(**kwargs)
    output_root = Path(str(kwargs["output_root"]))
    decisions = output_root / "strategy-decisions.json"
    decisions.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="decision|candidate strategy",
    ):
        verify_learning_shadow_replay_receipt(
            output_root / "shadow-replay-receipt.json",
            **_verify_kwargs(kwargs),
        )

    assert receipt.closed_trade_ids == ()
