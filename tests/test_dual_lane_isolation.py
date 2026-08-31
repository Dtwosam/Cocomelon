from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from pytest import raises

from cocomelon.domain.evaluation import EdgeEvidenceStatus
from cocomelon.domain.strategy import Direction
from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchContaminationError, ResearchRegistry
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

DAY_MS = 86_400_000
EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'


def _candidate(
    candidate_id: str,
    *,
    parent_candidate_id: str | None = None,
    ancestor_candidate_ids: tuple[str, ...] = (),
    digest_char: str = "a",
) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id="dual-lane-family",
        parent_candidate_id=parent_candidate_id,
        ancestor_candidate_ids=ancestor_candidate_ids,
        config_digest=digest_char * 64,
        code_revision="1" * 40,
        execution_config_json=EXECUTION_CONFIG,
        risk_config_json=RISK_CONFIG,
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def test_failed_v4_interval_blocks_research_economics_before_release(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    candidate = _candidate("research-r1")
    registry.create_candidate(candidate)
    registry.record_v4_interval(
        run_id="v4-failed-diagnostic",
        interval=TimeInterval(DAY_MS, 2 * DAY_MS),
        disposition="diagnostic_failure",
    )
    artifact = write_research_artifact(
        tmp_path / "overlap",
        batch_id="overlap-batch",
        source_id="overlap-source",
        replay_run_id="research-isolation-replay",
        start_ms=DAY_MS + 1,
        end_ms=3 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000,
                net_r=Decimal("99"),
                direction=Direction.SHORT,
            ),
        ),
    )

    with raises(ResearchContaminationError, match="v4-failed-diagnostic"):
        evaluate_research_checkpoint(
            registry=registry,
            candidate_id=candidate.candidate_id,
            artifact_batches=(artifact,),
        )

    assert (
        registry.load_candidate(candidate.candidate_id).state
        is ResearchCandidateState.REJECTED_CONTAMINATION
    )
    assert registry.effective_touched_intervals(candidate.candidate_id) == ()
    registry.close()


def test_descendant_inherits_all_touched_history_across_generations(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    root = _candidate("research-r1", digest_char="a")
    child = _candidate(
        "research-r2",
        parent_candidate_id=root.candidate_id,
        ancestor_candidate_ids=(root.candidate_id,),
        digest_char="b",
    )
    grandchild = _candidate(
        "research-r3",
        parent_candidate_id=child.candidate_id,
        ancestor_candidate_ids=(root.candidate_id, child.candidate_id),
        digest_char="c",
    )

    registry.create_candidate(root)
    registry.record_touched_interval(root.candidate_id, TimeInterval(10, 20), source_id="root")
    registry.create_candidate(child)
    registry.record_touched_interval(child.candidate_id, TimeInterval(30, 40), source_id="child")
    registry.create_candidate(grandchild)
    registry.record_touched_interval(
        grandchild.candidate_id,
        TimeInterval(19, 31),
        source_id="grandchild",
    )

    assert registry.effective_touched_intervals(grandchild.candidate_id) == (
        TimeInterval(10, 40),
    )
    loaded = registry.load_candidate(grandchild.candidate_id)
    assert loaded.local_touched_intervals == (TimeInterval(19, 31),)
    assert loaded.effective_touched_intervals == (TimeInterval(10, 40),)
    registry.close()


def test_research_promising_state_cannot_be_candidate_edge(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=10 * DAY_MS,
        source_id="authoritative-v4-test-inventory",
    )
    candidate = _candidate("research-r1")
    registry.create_candidate(candidate)
    artifact = write_research_artifact(
        tmp_path / "positive",
        batch_id="positive-research-batch",
        source_id="positive-research-source",
        replay_run_id="research-isolation-replay",
        start_ms=DAY_MS,
        end_ms=9 * DAY_MS,
        trades=tuple(
            ArtifactTradeSpec(
                closed_at_ms=(1 + (index % 7)) * DAY_MS + 20_000 + index * 1_000,
                net_r=Decimal("0.5"),
                market="BTC" if index % 2 == 0 else "ETH",
                direction=Direction.LONG if index % 2 == 0 else Direction.SHORT,
            )
            for index in range(40)
        ),
    )

    report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate.candidate_id,
        artifact_batches=(artifact,),
    )

    assert report.label == "TOUCHED / NON-PROMOTIONAL"
    assert report.candidate_state is ResearchCandidateState.RESEARCH_PROMISING
    assert EdgeEvidenceStatus.CANDIDATE_EDGE.value not in report.to_dict().values()
    assert "edge_evidence_status" not in report.to_dict()
    registry.close()


def test_research_source_tree_has_no_v4_curator_or_live_order_surface() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    research_paths = tuple(sorted((repo_root / "src" / "cocomelon" / "research").glob("*.py"))) + (
        repo_root / "src" / "cocomelon" / "research_cli.py",
    )
    forbidden_import_fragments = (
        "apply_v4_intake_diagnostics",
        "evidence_corpus_curator",
        "phase9_v4_one_shot",
    )

    for path in research_paths:
        source = path.read_text(encoding="utf-8")
        assert "live_orders" not in source
        assert "place_order" not in source
        tree = ast.parse(source, filename=str(path))
        imported_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.append(node.module)
        for imported_module in imported_modules:
            assert not any(
                fragment in imported_module for fragment in forbidden_import_fragments
            )
