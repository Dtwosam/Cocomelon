from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from pytest import raises

from cocomelon.domain.evaluation import EdgeEvidenceStatus, TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.evaluator import ResearchBatch, evaluate_research_checkpoint
from cocomelon.research.registry import ResearchContaminationError, ResearchRegistry

DAY_MS = 86_400_000


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
        state=ResearchCandidateState.DRAFT,
    )


def _sample(index: int, *, day: int, net_r: str = "0.5") -> TradeEvaluationSample:
    decision_ms = day * DAY_MS + 10_000 + index * 1_000
    opened_ms = decision_ms + 100
    closed_ms = opened_ms + 1_000
    pnl = Decimal(net_r) * Decimal("10")
    return TradeEvaluationSample(
        trade_id=f"isolation-trade-{index}",
        replay_run_id="research-isolation-replay",
        strategy_decision_id=f"isolation-decision-{index}",
        market=MarketId(dex="", coin="BTC" if index % 2 == 0 else "ETH"),
        direction=Direction.LONG if index % 2 == 0 else Direction.SHORT,
        decision_timestamp_ms=decision_ms,
        opened_at_ms=opened_ms,
        closed_at_ms=closed_ms,
        score=Decimal("75"),
        lead_strategy="research-isolation",
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        gross_realized_pnl=pnl + Decimal("0.02"),
        entry_fees=Decimal("0.01"),
        exit_fees=Decimal("0.01"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=pnl,
        entry_slippage_amount=Decimal("0.001"),
        exit_slippage_amount=Decimal("0.001"),
        net_r=Decimal(net_r),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + pnl,
        holding_duration_ms=1_000,
        reason_codes=("THESIS_EXPIRED",),
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
    batch = ResearchBatch(
        batch_id="overlap-batch",
        source_id="overlap-source",
        replay_run_id="research-isolation-replay",
        interval=TimeInterval(DAY_MS + 1, 3 * DAY_MS),
    )

    with raises(ResearchContaminationError, match="v4-failed-diagnostic"):
        evaluate_research_checkpoint(
            registry=registry,
            candidate_id=candidate.candidate_id,
            batches=(batch,),
            samples=(_sample(1, day=1, net_r="99"),),
        )

    assert registry.load_candidate(candidate.candidate_id).state is (
        ResearchCandidateState.REJECTED_CONTAMINATION
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
    registry.close()


def test_research_promising_state_cannot_be_candidate_edge(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    candidate = _candidate("research-r1")
    registry.create_candidate(candidate)
    batch = ResearchBatch(
        batch_id="positive-research-batch",
        source_id="positive-research-source",
        replay_run_id="research-isolation-replay",
        interval=TimeInterval(DAY_MS, 9 * DAY_MS),
    )
    samples = tuple(_sample(index, day=1 + (index % 7)) for index in range(40))

    report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate.candidate_id,
        batches=(batch,),
        samples=samples,
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
