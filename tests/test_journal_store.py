import asyncio
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.journal import JournalObservation, ObservationKind, TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, SourceSegment
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import (
    TRADE_REF_INSERT_ROWS_PER_STATEMENT,
    JournalConsistencyError,
    JournalStore,
)

MARKET = MarketId("", "SOL")


def observation(*, reason_codes: tuple[str, ...] = ("trend",)) -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.STRATEGY_DECISION,
        timestamp_ms=1_000,
        market=MARKET,
        feature_snapshot_id="feature-1",
        strategy_decision_id="strategy-1",
        risk_decision_id=None,
        plan_id=None,
        attempt_id=None,
        position_action_id=None,
        account_state_id=None,
        reason_codes=reason_codes,
        health_refs=(),
        replay_run_id="run-1",
    )


def funding_observation() -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.FUNDING_EVENT,
        timestamp_ms=1_500,
        market=MARKET,
        feature_snapshot_id=None,
        strategy_decision_id="strategy-1",
        risk_decision_id="risk-1",
        plan_id="plan-1",
        attempt_id=None,
        position_action_id=None,
        account_state_id="account-2",
        reason_codes=("FUNDING_APPLIED",),
        health_refs=("funding-history-mainnet",),
        replay_run_id="run-1",
        funding_event_id="funding-1",
    )


def trade_entry() -> TradeJournalEntry:
    return TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        feature_snapshot_id="feature-1",
        strategy_decision_id="strategy-1",
        risk_decision_id="risk-1",
        opening_plan_id="plan-open",
        opening_attempt_id="attempt-open",
        exit_plan_ids=("plan-close",),
        exit_attempt_ids=("attempt-close",),
        fill_ids=("fill-open", "fill-close"),
        position_action_ids=("action-close",),
        funding_event_ids=("funding-1",),
        initial_stop=Decimal("95"),
        initial_risk_amount=Decimal("25"),
        entry_price=Decimal("100"),
        exit_price=Decimal("102"),
        filled_quantity=Decimal("10"),
        gross_realized_pnl=Decimal("20"),
        entry_fees=Decimal("0.45"),
        exit_fees=Decimal("0.459"),
        funding_cash_pnl=Decimal("-0.1"),
        net_pnl=Decimal("18.991"),
        entry_slippage_amount=Decimal("1"),
        exit_slippage_amount=Decimal("2"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.002"),
        holding_duration_ms=1_000,
        mfe=None,
        mae=None,
        net_r=Decimal("0.75964"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10018.991"),
        exit_reason="exit_thesis",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="run-1",
    )


def manifest() -> ReplayManifest:
    segment = SourceSegment(
        relative_path="events/a.jsonl",
        partition="events/2026-08-23/candle/SOL",
        sha256="a" * 64,
        byte_count=100,
        row_count=2,
        schema_version=1,
        first_available_at_ms=1_000,
        last_available_at_ms=2_000,
    )
    return ReplayManifest(
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
        start_ms=1_000,
        end_ms=2_000,
        segments=(segment,),
        gap_refs=(),
        code_revision="abc123",
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version=None,
        fee_schedule_id=None,
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def test_schema_contains_separate_journal_and_replay_tables(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    store.close()

    with sqlite3.connect(tmp_path / "journal.sqlite3") as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "journal_meta",
        "journal_observations",
        "journal_trades",
        "journal_trade_refs",
        "replay_manifests",
        "replay_runs",
        "compaction_manifests",
    } <= names


def test_existing_journal_rejects_unsupported_schema_version_without_rewriting(
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.sqlite3"
    store = JournalStore(path)
    store.close()

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE journal_meta SET value = '999' WHERE key = 'schema_version'"
        )

    with pytest.raises(JournalConsistencyError, match="unsupported journal schema version"):
        JournalStore(path)

    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "SELECT value FROM journal_meta WHERE key = 'schema_version'"
        ).fetchone()
    assert version == ("999",)


def test_existing_journal_rejects_missing_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    store = JournalStore(path)
    store.close()

    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM journal_meta WHERE key = 'schema_version'")

    with pytest.raises(JournalConsistencyError, match="missing journal schema version"):
        JournalStore(path)


def test_existing_journal_rejects_missing_required_table_without_recreating(
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.sqlite3"
    store = JournalStore(path)
    store.close()

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE journal_trades")

    with pytest.raises(JournalConsistencyError, match="incomplete journal schema"):
        JournalStore(path)

    with sqlite3.connect(path) as connection:
        missing = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'journal_trades'"
        ).fetchone()
    assert missing is None


def test_identical_observation_retry_is_idempotent(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    item = observation()

    store.record_observation(item)
    store.record_observation(item)

    assert store.load_observation(item.observation_id) == item
    store.close()


def test_funding_event_observation_round_trips_with_lineage(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    item = funding_observation()
    store = JournalStore(path)
    store.record_observation(item)
    store.close()

    reopened = JournalStore(path)
    assert reopened.load_observation(item.observation_id) == item
    reopened.close()


def test_closed_trade_async_write_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    item = trade_entry()
    store = JournalStore(path)

    asyncio.run(store.record_trade_async(item))

    assert store.load_trade(item.trade_id) == item
    store.close()


def test_many_closed_trade_references_are_atomic_ordered_and_idempotent(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    path = tmp_path / "journal.sqlite3"
    trade = replace(
        trade_entry(),
        health_refs=tuple(f"replay-gap-{i:05d}" for i in range(1_200)),
    )
    store = JournalStore(path)
    try:
        asyncio.run(store.record_trade_async(trade))
        asyncio.run(store.record_trade_async(trade))
        assert store.load_trade(trade.trade_id) == trade
        rows = store.connection.execute(
            "SELECT ref_kind,ordinal,ref_id FROM journal_trade_refs "
            "WHERE trade_id=? ORDER BY ref_kind,ordinal",
            (trade.trade_id,),
        ).fetchall()
        health = [
            (ordinal, ref_id) for kind, ordinal, ref_id in rows
            if kind == "health"
        ]
        assert health == list(enumerate(trade.health_refs))
        assert len(rows) == (
            1 + 1 + 2 + 1 + 1 + len(trade.health_refs)
        )
        assert store.connection.execute(
            "SELECT count(*) FROM journal_trades WHERE trade_id=?",
            (trade.trade_id,),
        ).fetchone() == (1,)
    finally:
        store.close()


def test_batched_ref_constraint_failure_rolls_back_trade_and_all_refs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.sqlite3"
    store = JournalStore(path)
    trade = trade_entry()
    with store.connection:
        store.connection.executescript(
            "CREATE TRIGGER reject_ref BEFORE INSERT ON journal_trade_refs "
            "WHEN NEW.ref_kind='fill' AND NEW.ordinal=1 "
            "BEGIN SELECT RAISE(ABORT, 'injected reference write failure'); END;"
        )
    try:
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            asyncio.run(store.record_trade_async(trade))
        assert store.load_trade(trade.trade_id) is None
        assert store.connection.execute(
            "SELECT count(*) FROM journal_trade_refs WHERE trade_id=?",
            (trade.trade_id,),
        ).fetchone() == (0,)
        assert store.connection.execute(
            "SELECT count(*) FROM journal_trades WHERE trade_id=?",
            (trade.trade_id,),
        ).fetchone() == (0,)
    finally:
        store.close()


def test_json1_bulk_refs_work_with_legacy_999_bind_limit(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    assert TRADE_REF_INSERT_ROWS_PER_STATEMENT == 200
    assert 4 * TRADE_REF_INSERT_ROWS_PER_STATEMENT <= 999
    trade = replace(
        trade_entry(),
        health_refs=tuple(f"source-gap-{i:05d}" for i in range(1_003)),
    )
    store = JournalStore(tmp_path / "journal.sqlite3")
    inserts: list[str] = []
    try:
        previous_limit = store.connection.setlimit(
            sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999
        )
        assert previous_limit >= 999
        store.connection.set_trace_callback(
            lambda sql: inserts.append(sql)
            if sql.startswith("INSERT INTO journal_trade_refs(")
            else None
        )
        store.record_trade(trade)
        store.record_trade(trade)  # idempotent; no duplicate SQL inserts
        store.connection.set_trace_callback(None)
        assert store.load_trade(trade.trade_id) == trade
        # Exactly one VM statement per nonempty ref kind, even for 1,003
        # health refs; no 999-variable violation or duplicate retry work.
        assert len(inserts) == 6
        assert all("json_each(" in sql for sql in inserts)
        assert sum("source-gap-" in sql for sql in inserts) == 1
        assert store.connection.execute(
            "SELECT COUNT(*) FROM journal_trade_refs WHERE trade_id=?",
            (trade.trade_id,),
        ).fetchone() == (1009,)
    finally:
        store.connection.set_trace_callback(None)
        store.close()


def test_json1_single_health_statement_preserves_4893_signed_ref_ids(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    trade = replace(
        trade_entry(),
        health_refs=tuple(
            f"source-gap-{i:05d}-unicode-☁-\\\""
            for i in range(4_893)
        ),
    )
    store = JournalStore(tmp_path / "journal.sqlite3")
    statements: list[str] = []
    try:
        store.connection.setlimit(
            sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999
        )
        store.connection.set_trace_callback(
            lambda sql: statements.append(sql)
            if sql.startswith("INSERT INTO journal_trade_refs(")
            else None
        )
        store.record_trade(trade)
        store.connection.set_trace_callback(None)
        assert len(statements) == 6
        assert all("json_each(" in sql for sql in statements)
        assert store.load_trade(trade.trade_id) == trade
        rows = store.connection.execute(
            "SELECT ordinal, ref_id FROM journal_trade_refs "
            "WHERE trade_id=? AND ref_kind='health' ORDER BY ordinal",
            (trade.trade_id,),
        ).fetchall()
        assert rows == list(enumerate(trade.health_refs))
        assert store.connection.execute(
            "SELECT COUNT(*) FROM journal_trade_refs WHERE trade_id=?",
            (trade.trade_id,),
        ).fetchone() == (4_899,)
    finally:
        store.connection.set_trace_callback(None)
        store.close()


def test_json1_missing_uses_previous_200_row_atomic_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    monkeypatch.setattr(
        JournalStore,
        "_sqlite_json_each_available",
        staticmethod(lambda _connection: False),
    )
    trade = replace(
        trade_entry(),
        health_refs=tuple(
            f"legacy-gap-{i:05d}" for i in range(1_003)
        ),
    )
    store = JournalStore(tmp_path / "journal.sqlite3")
    statements: list[str] = []
    try:
        store.connection.setlimit(
            sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999
        )
        store.connection.set_trace_callback(
            lambda sql: statements.append(sql)
            if sql.startswith("INSERT INTO journal_trade_refs(")
            else None
        )
        store.record_trade(trade)
        store.connection.set_trace_callback(None)
        assert len(statements) == 6
        assert all("json_each(" not in sql for sql in statements)
        assert store.load_trade(trade.trade_id) == trade
        assert store.connection.execute(
            "SELECT COUNT(*) FROM journal_trade_refs WHERE trade_id=?",
            (trade.trade_id,),
        ).fetchone() == (1_009,)
    finally:
        store.connection.set_trace_callback(None)
        store.close()


def test_multirow_reference_inserts_roll_back_later_statement_failure(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    trade = replace(
        trade_entry(),
        health_refs=tuple(f"event-gap-{i:05d}" for i in range(440)),
    )
    store = JournalStore(tmp_path / "journal.sqlite3")
    try:
        # Health ordinal 208 is in a *later* multi-row INSERT; previous
        # INSERT(s) and the journal trade must all roll back atomically.
        store.connection.executescript(
            "CREATE TRIGGER reject_later_ref BEFORE INSERT ON journal_trade_refs "
            "WHEN NEW.ref_kind='health' AND NEW.ordinal=208 "
            "BEGIN SELECT RAISE(ABORT, 'late multirow reference failure'); END;"
        )
        with pytest.raises(sqlite3.IntegrityError, match="late multirow"):
            store.record_trade(trade)
        assert store.load_trade(trade.trade_id) is None
        assert store.connection.execute(
            "SELECT COUNT(*) FROM journal_trade_refs WHERE trade_id=?",
            (trade.trade_id,),
        ).fetchone() == (0,)
        store.connection.execute("DROP TRIGGER reject_later_ref")
        store.record_trade(trade)
        assert store.load_trade(trade.trade_id) == trade
        assert store.connection.execute(
            "SELECT COUNT(*) FROM journal_trade_refs WHERE trade_id=?",
            (trade.trade_id,),
        ).fetchone() == (446,)
    finally:
        store.close()


def test_slow_trade_sql_warning_exposes_only_latency_stage_counts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="cocomelon.journal.store"):
        JournalStore._log_slow_trade_transaction(
            begin_wait_ms=19000, trade_row_ms=200, ref_insert_ms=100,
            commit_ms=1700, total_ms=21000, ref_rows=1200,
        )
        JournalStore._log_slow_trade_transaction(
            begin_wait_ms=100, trade_row_ms=1, ref_insert_ms=3,
            commit_ms=20, total_ms=124, ref_rows=5,
        )
    messages = [
        row.message for row in caplog.records
        if "SLOW_PAPER_JOURNAL_TRADE_SQL" in row.message
    ]
    assert len(messages) == 1
    assert "begin_wait_ms=19000" in messages[0]
    assert "ref_insert_ms=100" in messages[0]
    assert "commit_ms=1700" in messages[0]
    assert "ref_rows=1200" in messages[0]
    assert "trade_id=" not in messages[0]
    assert "payload_json" not in messages[0]


def test_async_slow_journal_stages_reach_heartbeat_without_trade_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the diagnostics gate; do not sleep or depend on runner I/O load.
    monkeypatch.setattr("cocomelon.journal.store.SLOW_TRADE_TRANSACTION_MS", 0)
    store = JournalStore(tmp_path / "journal.sqlite3")
    trade = trade_entry()
    try:
        asyncio.run(store.record_trade_async(trade))
        assert store.load_trade(trade.trade_id) == trade
        assert store.slow_trade_sql_count == 1
        assert store.last_slow_trade_sql is not None
        assert set(store.last_slow_trade_sql) == {
            "total_ms", "begin_wait_ms", "trade_row_ms",
            "ref_insert_ms", "commit_ms", "ref_rows",
        }
        assert all(value >= 0 for value in store.last_slow_trade_sql.values())
        assert store.slow_trade_sql_max_total_ms == (
            store.last_slow_trade_sql["total_ms"]
        )
        assert store.last_slow_trade_sql["ref_rows"] == 7
        assert trade.trade_id not in str(store.last_slow_trade_sql)
        # Identical retry must keep the original transaction and metric count.
        asyncio.run(store.record_trade_async(trade))
        assert store.slow_trade_sql_count == 1
    finally:
        store.close()


def test_closed_trade_round_trips_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    item = trade_entry()
    store = JournalStore(path)
    store.record_trade(item)
    store.close()

    reopened = JournalStore(path)
    assert reopened.load_trade(item.trade_id) == item
    reopened.close()


def test_conflicting_duplicate_observation_id_fails_closed(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    item = observation()
    store.record_observation(item)

    changed_payload = store._canonical_observation(observation(reason_codes=("other",)))
    with store.connection:
        store.connection.execute(
            "UPDATE journal_observations SET payload_json = ? WHERE observation_id = ?",
            (changed_payload, item.observation_id),
        )

    with pytest.raises(JournalConsistencyError, match="conflicting"):
        store.record_observation(item)
    store.close()


def test_manifest_retry_is_idempotent_and_restart_safe(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    item = manifest()
    first = JournalStore(path)
    first.record_manifest(item)
    first.record_manifest(item)
    first.close()

    reopened = JournalStore(path)
    assert reopened.load_manifest(item.manifest_id) == item
    reopened.close()


def test_failed_multirow_write_rolls_back(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    item = observation()

    def fail_after_primary() -> None:
        raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        store._record_observation_transaction(item, after_primary=fail_after_primary)

    assert store.load_observation(item.observation_id) is None
    store.close()


def test_canonical_payload_preserves_decimal_strings_not_floats(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    payload = store._canonical_json({"risk": Decimal("0.002500")})

    assert payload == '{"risk":"0.002500"}'
    store.close()


def test_readonly_canonical_paper_trade_journal_cannot_change_source(
    tmp_path: Path,
) -> None:
    import hashlib

    path = tmp_path / "original-journal.sqlite3"
    writer = JournalStore(path)
    original_trade = trade_entry()
    writer.record_trade(original_trade)
    writer.close()
    initial = hashlib.sha256(path.read_bytes()).hexdigest()

    reader = JournalStore(path, read_only=True)
    try:
        assert tuple(reader.iter_trades()) == (original_trade,)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.connection.execute(
                "INSERT INTO journal_meta(key, value) "
                "VALUES ('research_fake_key', 'profit')"
            )
        with pytest.raises(
            JournalConsistencyError, match="cannot record trades asynchronously",
        ):
            asyncio.run(reader.record_trade_async(original_trade))
    finally:
        reader.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == initial

    with sqlite3.connect(path) as untouched:
        assert untouched.execute(
            "SELECT count(*) FROM journal_trades"
        ).fetchone() == (1,)
        assert untouched.execute(
            "SELECT value FROM journal_meta "
            "WHERE key = 'research_fake_key'"
        ).fetchone() is None


def test_readonly_journal_rejects_missing_and_unsupported_schema(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "does-not-exist.sqlite3"
    with pytest.raises(
        JournalConsistencyError, match="read-only journal file missing",
    ):
        JournalStore(absent, read_only=True)
    assert not absent.exists()
    empty = tmp_path / "not-a-journal.sqlite3"
    with sqlite3.connect(empty):
        pass
    with pytest.raises(
        JournalConsistencyError, match="schema missing",
    ):
        JournalStore(empty, read_only=True)
    writer = JournalStore(tmp_path / "old-journal.sqlite3")
    writer.close()
    old = tmp_path / "old-journal.sqlite3"
    with sqlite3.connect(old) as conn:
        conn.execute(
            "UPDATE journal_meta SET value = '999' "
            "WHERE key = 'schema_version'"
        )
    before = old.read_bytes()
    with pytest.raises(
        JournalConsistencyError, match="unsupported journal schema version",
    ):
        JournalStore(old, read_only=True)
    assert old.read_bytes() == before


def test_net_edge_offline_journal_audit_preserves_hash_and_blocks_promotion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    import hashlib
    import json
    from dataclasses import replace

    from scripts.audit_readonly_prospective_net_edge_journal import main

    source = tmp_path / "original-completed.sqlite3"
    trade = trade_entry()
    prospective = replace(
        trade, opened_at_ms=21_600_100,
        closed_at_ms=21_601_100, holding_duration_ms=1_000,
    )
    writer = JournalStore(source)
    writer.record_trade(trade)
    writer.record_trade(prospective)
    writer.close()

    before = source.read_bytes()
    output = tmp_path / "offline-net-floor.json"
    assert main([
        str(source), "--freeze-ms", "0", "--json-out", str(output),
    ]) == 0
    printed = json.loads(capsys.readouterr().out)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert printed["original_closed_trades"] == 2
    assert printed["prospective_evaluated_trades"] == 1
    assert printed["prospective_admitted_trades"] == 0
    assert report["local_original_journal_trade_count"] == 2
    assert report["local_original_journal_sha256"] == (
        hashlib.sha256(before).hexdigest()
    )
    assert report["forward_original_rows"] == 1
    assert report["forward_original_admitted"] == 0
    assert report["forward_original_skipped"] == 1
    assert report["independent_signed_source_authentication_verified"] is False
    assert report["all_source_gaps_closed_and_72h_verified"] is False
    assert report["capital_matched_challenger_account_verified"] is False
    assert report["positive_absolute_after_cost_marked_equity_verified"] is False
    assert report["promotion_authority"] is False
    assert report["execution_authority"] is False
    assert source.read_bytes() == before

    with pytest.raises(SystemExit, match="2"):
        main([
            str(source), "--freeze-ms", "0", "--json-out", str(output),
        ])
    assert source.read_bytes() == before


def test_journal_audit_rejects_live_sqlite_sidecars_before_record_reads(
    tmp_path: Path,
) -> None:
    from scripts.audit_readonly_prospective_net_edge_journal import main

    source = tmp_path / "original.sqlite3"
    writer = JournalStore(source)
    writer.record_trade(trade_entry())
    writer.close()
    original = source.read_bytes()
    output = tmp_path / "should-not-exist.json"
    wal = Path(str(source) + "-wal")
    wal.write_bytes(b"unverified active SQLite WAL")
    try:
        with pytest.raises(SystemExit, match="2"):
            main([
                str(source), "--freeze-ms", "0", "--json-out", str(output),
            ])
        assert not output.exists()
        assert source.read_bytes() == original
    finally:
        wal.unlink()
