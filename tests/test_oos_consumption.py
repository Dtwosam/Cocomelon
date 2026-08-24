from pathlib import Path

from cocomelon.domain.evaluation import (
    CandidateDefinition,
    EvaluationDatasetManifest,
    EvaluationPolicy,
    FrozenCandidateSet,
    OOSStatus,
    ReplayEvaluationSource,
    SplitName,
    TimePartition,
)
from cocomelon.domain.replay import EvidenceClass
from cocomelon.evaluation.splits import consume_untouched_test, freeze_split_manifest
from cocomelon.evaluation.store import EvaluationFactStore


def dataset() -> EvaluationDatasetManifest:
    return EvaluationDatasetManifest(
        sources=(
            ReplayEvaluationSource(
                run_id="run-1",
                manifest_id="manifest-1",
                result_digest="a" * 64,
                evidence_class=EvidenceClass.MICROSTRUCTURE,
                start_ms=0,
                end_ms=30_000,
                data_complete=True,
            ),
        ),
        trade_ids=(),
        decision_fact_ids=(),
        equity_fact_ids=(),
        start_ms=0,
        end_ms=30_000,
        code_revision="phase9-test",
        data_complete=True,
        gap_refs=(),
        mixed_evidence_diagnostic=False,
    )


def policy(*, min_oos_trades: int = 100) -> EvaluationPolicy:
    return EvaluationPolicy(min_oos_trades=min_oos_trades, split_embargo_ms=1_000)


def split(rules: EvaluationPolicy):
    return freeze_split_manifest(
        dataset(),
        train=TimePartition(SplitName.TRAIN, 0, 10_000),
        validation=TimePartition(SplitName.VALIDATION, 10_000, 20_000),
        test=TimePartition(SplitName.TEST, 20_000, 30_000),
        policy=rules,
    )


def candidates(
    rules: EvaluationPolicy,
    *,
    strategy_version: str = "phase5-v1",
    sensitivity_profile_ids: tuple[str, ...] = ("base", "combined_stress"),
) -> FrozenCandidateSet:
    return FrozenCandidateSet(
        candidates=(
            CandidateDefinition(
                name="baseline",
                strategy_version=strategy_version,
                risk_version="phase6-v1",
                execution_config_version="phase7-v1",
                code_revision="phase9-test",
                config_digest="c" * 64,
            ),
        ),
        sensitivity_profile_ids=sensitivity_profile_ids,
        policy_id=rules.policy_id,
    )


def test_same_candidate_set_reproduces_consumed_test_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "evaluation.sqlite3"
    rules = policy()
    frozen = split(rules)
    candidate_set = candidates(rules)
    store = EvaluationFactStore(path)

    assert consume_untouched_test(store, frozen, candidate_set, rules) is OOSStatus.UNTOUCHED
    assert store.load_split_manifest(frozen.split_manifest_id) == frozen
    assert store.load_candidate_set(candidate_set.candidate_set_id) == candidate_set
    store.close()

    reopened = EvaluationFactStore(path)
    assert (
        consume_untouched_test(reopened, frozen, candidate_set, rules)
        is OOSStatus.REPRODUCTION
    )
    count = reopened.connection.execute(
        "SELECT COUNT(*) FROM evaluation_oos_consumptions"
    ).fetchone()
    assert count == (1,)
    reopened.close()


def test_changed_candidate_set_marks_consumed_test_contaminated(tmp_path: Path) -> None:
    store = EvaluationFactStore(tmp_path / "evaluation.sqlite3")
    rules = policy()
    frozen = split(rules)

    assert (
        consume_untouched_test(store, frozen, candidates(rules), rules)
        is OOSStatus.UNTOUCHED
    )
    changed = candidates(rules, strategy_version="phase5-v2")
    assert consume_untouched_test(store, frozen, changed, rules) is OOSStatus.CONTAMINATED

    row = store.connection.execute(
        """
        SELECT candidate_set_id, policy_id
        FROM evaluation_oos_consumptions
        WHERE test_partition_digest = ?
        """,
        (frozen.test_partition_digest,),
    ).fetchone()
    assert row == (candidates(rules).candidate_set_id, rules.policy_id)
    store.close()


def test_changed_policy_cannot_reuse_revealed_test_as_untouched(tmp_path: Path) -> None:
    store = EvaluationFactStore(tmp_path / "evaluation.sqlite3")
    first_policy = policy(min_oos_trades=100)
    second_policy = policy(min_oos_trades=101)
    first_split = split(first_policy)
    second_split = split(second_policy)

    assert first_split.test_partition_digest == second_split.test_partition_digest
    assert (
        consume_untouched_test(
            store,
            first_split,
            candidates(first_policy),
            first_policy,
        )
        is OOSStatus.UNTOUCHED
    )
    assert (
        consume_untouched_test(
            store,
            second_split,
            candidates(second_policy),
            second_policy,
        )
        is OOSStatus.CONTAMINATED
    )
    store.close()


def test_changed_sensitivity_profile_set_contaminates_reuse(tmp_path: Path) -> None:
    store = EvaluationFactStore(tmp_path / "evaluation.sqlite3")
    rules = policy()
    frozen = split(rules)
    first = candidates(rules, sensitivity_profile_ids=("base", "combined_stress"))
    changed = candidates(rules, sensitivity_profile_ids=("base", "fees_1_25x"))

    assert consume_untouched_test(store, frozen, first, rules) is OOSStatus.UNTOUCHED
    assert consume_untouched_test(store, frozen, changed, rules) is OOSStatus.CONTAMINATED
    store.close()
