from decimal import Decimal

from test_baseline_replay_lifecycle import (
    MARKET,
    OPEN_BOOK_MS,
    ORACLE_MS,
    STOP_MARK_MS,
    _asset_ctx,
    _book,
    _funding,
    _pipeline,
    _run_records,
    _snapshot_record,
    _trigger_record,
)


def test_lifecycle_fixture_opens_before_funding(tmp_path):
    pipeline, execution, facts = _pipeline(tmp_path, suffix="diagnostic")
    observations = _run_records(
        pipeline,
        (
            _snapshot_record(),
            _trigger_record(),
            _book(OPEN_BOOK_MS, bid="99.9", ask="100.1"),
        ),
    )
    assert len(execution.account.positions) == 1, (
        tuple(observation.kind.value for observation in observations),
        execution.store.table_counts(),
    )
    assert execution.account.positions[0].market == MARKET
    execution.close()
    facts.close()


def test_lifecycle_fixture_funds_then_stop_closes(tmp_path):
    pipeline, execution, facts = _pipeline(tmp_path, suffix="diagnostic-close")
    _run_records(
        pipeline,
        (
            _snapshot_record(),
            _trigger_record(),
            _book(OPEN_BOOK_MS, bid="99.9", ask="100.1"),
            _asset_ctx(ORACLE_MS, mark="100", oracle="100"),
            _funding(),
        ),
    )
    assert len(execution.account.positions) == 1
    assert execution.account.cumulative_funding < Decimal("0")

    mark_observations = _run_records(
        pipeline,
        (_asset_ctx(STOP_MARK_MS, mark="94", oracle="94"),),
    )
    assert execution.account.positions[0].latest_mark == Decimal("94")

    close_observations = _run_records(
        pipeline,
        (_book(STOP_MARK_MS + 300, bid="93.9", ask="94.0"),),
    )
    assert execution.account.positions == (), (
        tuple(observation.kind.value for observation in mark_observations),
        tuple(observation.kind.value for observation in close_observations),
        execution.store.table_counts(),
    )
    execution.close()
    facts.close()
