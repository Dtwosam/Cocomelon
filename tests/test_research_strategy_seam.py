from __future__ import annotations

import json
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest

from cocomelon.evidence.bundle import load_baseline_replay_bundle
from cocomelon.research.artifact import verify_research_batch_artifact
from cocomelon.strategies.engine import evaluate_strategies
from tests.test_research_cohort import _cohort_roots

cohort_module = import_module("cocomelon.research.cohort")
strategy_seam = import_module("cocomelon.research.strategy_seam")


def _local_strategy(payload: dict[str, object]) -> dict[str, object]:
    context = strategy_seam.strategy_context_from_payload(payload["context"])
    decision = evaluate_strategies(context).decision
    return strategy_seam.strategy_decision_to_payload(decision)


def _prepared(tmp_path: Path) -> tuple[Path, Path, Path]:
    recording_root, output_root, _ = _cohort_roots(tmp_path)
    cohort_module.prepare_research_cohort_source(
        recording_root,
        output_root,
        Decimal("10000"),
        trigger_head_sha="f" * 40,
    )
    decisions_path = output_root / "strategy-decisions.json"
    strategy_seam.build_candidate_strategy_decisions(
        recording_root=recording_root,
        bundle_path=output_root / "bundle.json",
        output_path=decisions_path,
        candidate_code_revision="1" * 40,
        evaluator=_local_strategy,
    )
    return recording_root, output_root, decisions_path


def test_trusted_replay_accepts_complete_candidate_decision_stream(tmp_path: Path) -> None:
    recording_root, output_root, decisions_path = _prepared(tmp_path)

    result = cohort_module.complete_research_cohort(
        recording_root,
        output_root,
        strategy_decisions_path=decisions_path,
    )
    verified = verify_research_batch_artifact(
        output_root,
        batch_id="strategy-seam-batch",
        source_id="strategy-seam-source",
    )
    bundle = load_baseline_replay_bundle(output_root / "bundle.json")

    assert result.replay_run_id == verified.replay_run_id
    assert verified.code_revision == "1" * 40
    assert verified.candidate_config_digest == bundle.replay_config.config_digest
    assert verified.code_revision != bundle.manifest.code_revision


def test_trusted_replay_rejects_missing_candidate_decision(tmp_path: Path) -> None:
    recording_root, output_root, decisions_path = _prepared(tmp_path)
    payload = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert payload["decisions"]
    payload["decisions"] = payload["decisions"][1:]
    decisions_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="decision coverage|missing candidate decision"):
        cohort_module.complete_research_cohort(
            recording_root,
            output_root,
            strategy_decisions_path=decisions_path,
        )


def test_candidate_decisions_are_bound_to_exact_trusted_source(tmp_path: Path) -> None:
    recording_root, output_root, decisions_path = _prepared(tmp_path)
    payload = json.loads(decisions_path.read_text(encoding="utf-8"))
    payload["recording_session_digest"] = "a" * 64
    decisions_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="recording|source"):
        cohort_module.complete_research_cohort(
            recording_root,
            output_root,
            strategy_decisions_path=decisions_path,
        )


def test_trusted_completion_rejects_preexisting_economic_products(tmp_path: Path) -> None:
    recording_root, output_root, decisions_path = _prepared(tmp_path)
    (output_root / "replay.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="pre-existing product"):
        cohort_module.complete_research_cohort(
            recording_root,
            output_root,
            strategy_decisions_path=decisions_path,
        )
