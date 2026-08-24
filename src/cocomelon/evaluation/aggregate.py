from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cocomelon.domain.evaluation import AccountEquityFact, DecisionEvaluationFact
from cocomelon.domain.journal import JournalObservation, TradeJournalEntry
from cocomelon.domain.replay import ReplayManifest, ReplayResult
from cocomelon.evaluation.store import EvaluationConsistencyError, EvaluationFactStore
from cocomelon.journal.store import JournalConsistencyError, JournalStore

JOURNAL_NAME = "journal.sqlite3"
FACTS_NAME = "facts.sqlite3"


class EvidenceAggregationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EvidenceAggregationResult:
    code_revision: str
    run_ids: tuple[str, ...]
    source_count: int
    trade_count: int
    observation_count: int
    decision_fact_count: int
    equity_fact_count: int


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    root: Path
    manifests: tuple[ReplayManifest, ...]
    results: tuple[ReplayResult, ...]
    trades: tuple[TradeJournalEntry, ...]
    observations: tuple[JournalObservation, ...]
    decision_facts: tuple[DecisionEvaluationFact, ...]
    equity_facts: tuple[AccountEquityFact, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_paths(root: Path) -> tuple[Path, Path]:
    journal_path = root / JOURNAL_NAME
    facts_path = root / FACTS_NAME
    if not root.is_dir():
        raise EvidenceAggregationError(f"source root is not a directory: {root}")
    for path in (journal_path, facts_path):
        if not path.is_file():
            raise EvidenceAggregationError(f"source evidence store is missing: {path}")
    return journal_path, facts_path


def _load_source(root: Path) -> _SourceSnapshot:
    journal_path, facts_path = _source_paths(root)
    before = (_sha256(journal_path), _sha256(facts_path))

    with tempfile.TemporaryDirectory(prefix="cocomelon-evidence-source-") as temporary:
        work_root = Path(temporary)
        work_journal_path = work_root / JOURNAL_NAME
        work_facts_path = work_root / FACTS_NAME
        shutil.copy2(journal_path, work_journal_path)
        shutil.copy2(facts_path, work_facts_path)
        if (_sha256(work_journal_path), _sha256(work_facts_path)) != before:
            raise EvidenceAggregationError(f"source copy checksum mismatch: {root}")

        journal = JournalStore(work_journal_path)
        facts = EvaluationFactStore(work_facts_path)
        try:
            results = tuple(journal.iter_replay_results())
            if not results:
                raise EvidenceAggregationError(
                    f"source contains no finished replay results: {root}"
                )
            manifests: list[ReplayManifest] = []
            for result in results:
                manifest = journal.load_manifest(result.manifest_id)
                if manifest is None:
                    raise EvidenceAggregationError(
                        f"source replay manifest is missing: {result.manifest_id}"
                    )
                manifests.append(manifest)

            run_ids = {item.run_id for item in results}
            trades = tuple(
                item for item in journal.iter_trades() if item.replay_run_id in run_ids
            )
            observations = tuple(
                item
                for item in journal.iter_observations()
                if item.replay_run_id in run_ids
            )
            decision_facts = tuple(
                item for item in facts.iter_decision_facts() if item.replay_run_id in run_ids
            )
            equity_facts = tuple(
                item for item in facts.iter_equity_facts() if item.replay_run_id in run_ids
            )
        except (JournalConsistencyError, EvaluationConsistencyError) as exc:
            raise EvidenceAggregationError(f"invalid source evidence store: {root}") from exc
        finally:
            facts.close()
            journal.close()

    after = (_sha256(journal_path), _sha256(facts_path))
    if after != before:
        raise EvidenceAggregationError(f"source evidence changed during aggregation: {root}")

    trade_ids_by_run: dict[str, set[str]] = {item.run_id: set() for item in results}
    for trade in trades:
        if trade.replay_run_id is None:
            continue
        trade_ids_by_run[trade.replay_run_id].add(trade.trade_id)
    for result in results:
        expected = set(result.closed_trade_ids)
        actual = trade_ids_by_run[result.run_id]
        if actual != expected:
            raise EvidenceAggregationError(
                f"source closed-trade lineage does not match replay result: {result.run_id}"
            )

    return _SourceSnapshot(
        root=root,
        manifests=tuple(manifests),
        results=results,
        trades=trades,
        observations=observations,
        decision_facts=decision_facts,
        equity_facts=equity_facts,
    )


def _preflight_sources(
    source_roots: Sequence[str | Path],
    target_journal_path: Path,
    target_facts_path: Path,
) -> tuple[tuple[_SourceSnapshot, ...], str]:
    if not source_roots:
        raise EvidenceAggregationError("at least one source root is required")

    roots = tuple(Path(item).resolve() for item in source_roots)
    if len(set(roots)) != len(roots):
        raise EvidenceAggregationError("source roots must be unique")

    target_paths = {target_journal_path.resolve(), target_facts_path.resolve()}
    snapshots: list[_SourceSnapshot] = []
    revisions: set[str] = set()
    results_by_run: dict[str, ReplayResult] = {}
    manifests_by_id: dict[str, ReplayManifest] = {}

    for root in roots:
        journal_path, facts_path = _source_paths(root)
        if journal_path.resolve() in target_paths or facts_path.resolve() in target_paths:
            raise EvidenceAggregationError(
                "source evidence stores cannot also be aggregation targets"
            )
        snapshot = _load_source(root)
        snapshots.append(snapshot)
        revisions.update(item.code_revision for item in snapshot.manifests)
        for manifest in snapshot.manifests:
            existing_manifest = manifests_by_id.get(manifest.manifest_id)
            if existing_manifest is not None and existing_manifest != manifest:
                raise EvidenceAggregationError(
                    f"conflicting replay manifest across sources: {manifest.manifest_id}"
                )
            manifests_by_id[manifest.manifest_id] = manifest
        for result in snapshot.results:
            existing_result = results_by_run.get(result.run_id)
            if existing_result is not None and existing_result != result:
                raise EvidenceAggregationError(
                    f"conflicting replay result across sources: {result.run_id}"
                )
            results_by_run[result.run_id] = result

    if len(revisions) != 1:
        raise EvidenceAggregationError("source replay runs must share one code revision")
    return tuple(snapshots), next(iter(revisions))


def _work_path(target: Path, token: str) -> Path:
    return target.with_name(f".{target.name}.{token}.tmp")


def _backup_path(target: Path, token: str) -> Path:
    return target.with_name(f".{target.name}.{token}.bak")


def _prepare_work_store(target: Path, work: Path, *, exists: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if exists:
        shutil.copy2(target, work)


def _validate_target_revision(journal: JournalStore, expected_revision: str) -> None:
    revisions: set[str] = set()
    for result in journal.iter_replay_results():
        manifest = journal.load_manifest(result.manifest_id)
        if manifest is None:
            raise EvidenceAggregationError(
                f"target replay manifest is missing: {result.manifest_id}"
            )
        revisions.add(manifest.code_revision)
    if revisions and revisions != {expected_revision}:
        raise EvidenceAggregationError("target replay runs must share the source code revision")


def _merge_snapshot(
    snapshot: _SourceSnapshot,
    journal: JournalStore,
    facts: EvaluationFactStore,
) -> None:
    manifests = {item.manifest_id: item for item in snapshot.manifests}
    for result in snapshot.results:
        journal.record_manifest(manifests[result.manifest_id])
    for trade in snapshot.trades:
        journal.record_trade(trade)
    for observation in snapshot.observations:
        journal.record_observation(observation)
    for decision_fact in snapshot.decision_facts:
        facts.record_decision_fact(decision_fact)
    for equity_fact in snapshot.equity_facts:
        facts.record_equity_fact(equity_fact)
    for result in snapshot.results:
        existing = journal.load_replay_result(result.run_id)
        if existing is not None:
            if existing != result:
                raise EvidenceAggregationError(
                    f"conflicting target replay result: {result.run_id}"
                )
            continue
        journal.begin_run(result.manifest_id, result.run_id)
        journal.finish_run(result)


def _result_from_target(
    journal: JournalStore,
    facts: EvaluationFactStore,
    *,
    code_revision: str,
    source_count: int,
) -> EvidenceAggregationResult:
    results = tuple(journal.iter_replay_results())
    run_ids = tuple(sorted(item.run_id for item in results))
    run_id_set = set(run_ids)
    trades = tuple(
        item for item in journal.iter_trades() if item.replay_run_id in run_id_set
    )
    observations = tuple(
        item for item in journal.iter_observations() if item.replay_run_id in run_id_set
    )
    decision_facts = tuple(
        item for item in facts.iter_decision_facts() if item.replay_run_id in run_id_set
    )
    equity_facts = tuple(
        item for item in facts.iter_equity_facts() if item.replay_run_id in run_id_set
    )
    return EvidenceAggregationResult(
        code_revision=code_revision,
        run_ids=run_ids,
        source_count=source_count,
        trade_count=len(trades),
        observation_count=len(observations),
        decision_fact_count=len(decision_facts),
        equity_fact_count=len(equity_facts),
    )


def _commit_pair(
    target_journal: Path,
    target_facts: Path,
    work_journal: Path,
    work_facts: Path,
    *,
    existed: bool,
    token: str,
) -> None:
    backup_journal = _backup_path(target_journal, token)
    backup_facts = _backup_path(target_facts, token)
    if existed:
        shutil.copy2(target_journal, backup_journal)
        shutil.copy2(target_facts, backup_facts)
    try:
        os.replace(work_journal, target_journal)
        os.replace(work_facts, target_facts)
    except Exception:
        if existed:
            if backup_journal.exists():
                os.replace(backup_journal, target_journal)
            if backup_facts.exists():
                os.replace(backup_facts, target_facts)
        else:
            target_journal.unlink(missing_ok=True)
            target_facts.unlink(missing_ok=True)
        raise
    finally:
        backup_journal.unlink(missing_ok=True)
        backup_facts.unlink(missing_ok=True)
        work_journal.unlink(missing_ok=True)
        work_facts.unlink(missing_ok=True)


def aggregate_evaluation_evidence(
    target_journal_path: str | Path,
    target_facts_path: str | Path,
    source_roots: Sequence[str | Path],
) -> EvidenceAggregationResult:
    target_journal = Path(target_journal_path)
    target_facts = Path(target_facts_path)
    snapshots, code_revision = _preflight_sources(
        source_roots,
        target_journal,
        target_facts,
    )

    journal_exists = target_journal.exists()
    facts_exists = target_facts.exists()
    if journal_exists != facts_exists:
        raise EvidenceAggregationError(
            "aggregation targets must either both exist or both be absent"
        )
    if journal_exists and (not target_journal.is_file() or not target_facts.is_file()):
        raise EvidenceAggregationError("aggregation targets must be regular files")

    token = uuid.uuid4().hex
    work_journal = _work_path(target_journal, token)
    work_facts = _work_path(target_facts, token)
    _prepare_work_store(target_journal, work_journal, exists=journal_exists)
    _prepare_work_store(target_facts, work_facts, exists=facts_exists)

    journal: JournalStore | None = None
    facts: EvaluationFactStore | None = None
    try:
        journal = JournalStore(work_journal)
        facts = EvaluationFactStore(work_facts)
        _validate_target_revision(journal, code_revision)
        for snapshot in snapshots:
            _merge_snapshot(snapshot, journal, facts)
        result = _result_from_target(
            journal,
            facts,
            code_revision=code_revision,
            source_count=len(snapshots),
        )
    except (JournalConsistencyError, EvaluationConsistencyError) as exc:
        raise EvidenceAggregationError("conflicting evaluation evidence") from exc
    finally:
        if facts is not None:
            facts.close()
        if journal is not None:
            journal.close()

    try:
        _commit_pair(
            target_journal,
            target_facts,
            work_journal,
            work_facts,
            existed=journal_exists,
            token=token,
        )
    except OSError as exc:
        raise EvidenceAggregationError("unable to commit aggregated evidence stores") from exc
    return result
