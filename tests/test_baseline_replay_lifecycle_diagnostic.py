from test_baseline_replay_lifecycle import (
    MARKET,
    OPEN_BOOK_MS,
    _book,
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
