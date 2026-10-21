"""Real-Git owner crash/restart tests with synthetic market observations only."""

import gzip
import hashlib
import json
import sqlite3
import subprocess

import pytest
from test_flow_exhaustion_paper import spec
from test_volatility_budget_paper import T, mark, opened, quote, trial

from cocomelon.research.volatility_custody import GitCustody, capture_trial_files

POLICY = "eca2816e42a1a0409737e179b45761a8a4ad0ebb2149ee7ad956b6867caffdaa"
IDENTITY = {
    "protocol_sha256": POLICY,
    "candidate_id": "volatility-candidate",
    "control_id": "volatility-control",
    "first_entry_ms": T,
}


class Journal:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS receipts (payload TEXT)")
        self.db.commit()

    def append(self, value):
        with self.db:
            self.db.execute("INSERT INTO receipts VALUES (?)", (json.dumps(value, sort_keys=True),))

    def records(self):
        return (json.loads(row[0]) for row in self.db.execute("SELECT payload FROM receipts"))

    def archive(self):
        data = gzip.compress(
            b"\n".join(json.dumps(r, sort_keys=True).encode() for r in self.records()), mtime=0
        )
        return {f"source/{hashlib.sha256(data).hexdigest()}.jsonl.gz": data}

    def close(self):
        self.db.close()


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path / "original"
    obj = trial(root)
    opened(obj)
    obj.close()
    journal = Journal(root / "source.sqlite")
    journal.append({"received_ms": T + 300, "original": "synthetic-open"})
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    custody = GitCustody(
        tmp_path / "cache",
        remote=str(remote),
        branch="codex/volatility-budget-v1-custody",
        identity=IDENTITY,
        owner_id="original",
    )
    custody.initialize(
        {**capture_trial_files(root), **journal.archive()}, summary={}, now_ms=T + 300
    )
    journal.close()
    return root, str(remote), tmp_path


def owner(prepared, *, clock, name="new", journal_factory=Journal):
    from cocomelon.research.volatility_owner import TrialOwner

    root, remote, tmp = prepared
    custody = GitCustody(
        tmp / f"cache-{name}",
        remote=remote,
        branch="codex/volatility-budget-v1-custody",
        identity=IDENTITY,
        owner_id=name,
    )
    return TrialOwner(
        root,
        identity=IDENTITY,
        custody=custody,
        journal_factory=journal_factory,
        clock=clock,
    )


def test_owner_flock_precedes_any_second_source_access_and_remains_through_close(prepared):
    def clock():
        return T + 61_000

    obj = owner(prepared, clock=clock)
    touched = []
    with pytest.raises(RuntimeError, match="lease|owner"):
        owner(prepared, clock=clock, name="duplicate", journal_factory=lambda p: touched.append(p))
    assert touched == []
    obj.close()


def test_clean_close_captures_actual_final_sqlite_revision_before_remote_receipt(prepared):
    now = [T + 61_000]
    obj = owner(prepared, clock=lambda: now[0])
    obj.checkpoint()
    obj.close()
    receipt = obj.custody.assert_current(
        {**capture_trial_files(prepared[0]), **Journal(prepared[0] / "source.sqlite").archive()}
    )
    assert receipt.pending is None
    now[0] += 61_000
    restored = owner(prepared, clock=lambda: now[0], name="successor")
    assert not restored.unclean_recovery
    assert restored.trial.candidate.account.positions
    restored.close()


def test_unclean_pending_tail_preserves_position_for_protection_and_permanent_disqualification(
    prepared,
):
    now = [T + 61_000]
    original = owner(prepared, clock=lambda: now[0])
    original.checkpoint()
    original.journal.append({"received_ms": now[0], "unacknowledged": "original"})
    # Simulate process termination after local durable writes, without final publish.
    original.abandon()
    now[0] += 61_000
    restored = owner(prepared, clock=lambda: now[0], name="successor")
    assert restored.unclean_recovery
    assert not restored.entries_allowed
    assert restored.trial.snapshot()["permanently_disabled"]
    now[0] += 100
    restored.trial.on_mark(mark(now[0], "97"), now_ms=now[0])
    restored.trial.on_book(quote(now[0], bid="96.99", ask="97.01"), spec(), now_ms=now[0])
    now[0] += 300
    restored.trial.on_book(quote(now[0], bid="96.99", ask="97.01"), spec(), now_ms=now[0])
    assert not restored.trial.candidate.account.positions
    assert restored.trial.candidate.account.cash < 10000
    restored.close()


def test_missing_original_root_or_source_never_creates_genesis(prepared):
    root = prepared[0]
    (root / "source.sqlite").unlink()
    with pytest.raises(ValueError, match="original"):
        owner(prepared, clock=lambda: T + 61_000)
    assert not (root / "source.sqlite").exists()


def test_checkpoint_transport_failure_disables_entries_but_preserves_valid_lease_protection(
    prepared, monkeypatch
):
    now = [T + 61_000]
    obj = owner(prepared, clock=lambda: now[0])
    obj.trial.entries_authorized = True

    def failed(*args, **kwargs):
        raise RuntimeError("transport unavailable")

    monkeypatch.setattr(obj.custody, "publish", failed)
    with pytest.raises(RuntimeError, match="transport"):
        obj.checkpoint()
    assert not obj.entries_allowed
    assert not obj.trial.entries_authorized
    assert obj.lease_valid()
    obj.trial.on_mark(mark(now[0], "97"), now_ms=now[0])
    obj.trial.on_book(quote(now[0], bid="96.99", ask="97.01"), spec(), now_ms=now[0])
    now[0] += 300
    obj.trial.on_book(quote(now[0], bid="96.99", ask="97.01"), spec(), now_ms=now[0])
    assert not obj.trial.candidate.account.positions
    obj.abandon()


def test_prepare_checkpoint_is_actor_local_and_published_snapshot_is_immutable(prepared):
    now = [T + 61_000]
    obj = owner(prepared, clock=lambda: now[0])
    prepared_snapshot = obj.prepare_checkpoint()
    obj.journal.append({"received_ms": now[0], "later": "tail"})
    obj.trial.tick(now_ms=now[0] + 100)
    published = obj.publish_checkpoint(prepared_snapshot)
    assert published.pending is not None
    with pytest.raises(RuntimeError, match="rollback|mismatch"):
        obj.custody.assert_current({**capture_trial_files(prepared[0]), **obj.journal.archive()})
    obj.close()


def test_confirmed_immutable_account_prefix_rollback_rejected_even_with_pending_tail(prepared):
    from pathlib import Path

    now = [T + 61_000]
    obj = owner(prepared, clock=lambda: now[0])
    obj.checkpoint()
    obj.abandon()
    # Removing a remote-confirmed fill row cannot become an unclean recovery.
    with sqlite3.connect(Path(prepared[0]) / "candidate.sqlite") as connection:
        connection.execute("DELETE FROM paper_fills")
    now[0] += 61_000
    with pytest.raises(ValueError, match="immutable history rollback"):
        owner(prepared, clock=lambda: now[0], name="successor")


def test_unclean_disqualification_survives_clean_protective_shutdown(prepared):
    now = [T + 61_000]
    first = owner(prepared, clock=lambda: now[0])
    first.checkpoint()
    first.abandon()
    now[0] += 61_000
    second = owner(prepared, clock=lambda: now[0], name="second")
    assert second.unclean_recovery
    second.close()
    now[0] += 61_000
    third = owner(prepared, clock=lambda: now[0], name="third")
    assert third.unclean_recovery
    assert not third.entries_allowed
    third.close()


def test_global_lease_expiry_fences_publication_without_erasing_local_position(prepared):
    now = [T + 61_000]
    obj = owner(prepared, clock=lambda: now[0])
    now[0] = obj.receipt.lease_until_ms
    assert not obj.lease_valid()
    assert not obj.entries_allowed
    with pytest.raises(RuntimeError, match="expired"):
        obj.checkpoint()
    assert obj.trial.candidate.account.positions
    obj.abandon()


def test_multiple_partial_source_exports_restart_without_dropping_original_chunks(prepared):
    now = [T + 61_000]
    obj = owner(prepared, clock=lambda: now[0])
    obj.journal.append({"received_ms": now[0], "first": "genuine-shape"})
    obj.checkpoint()
    obj.journal.append({"received_ms": now[0] + 1, "second": "genuine-shape"})
    obj.checkpoint()
    obj.close()
    now[0] += 61_000
    successor = owner(prepared, clock=lambda: now[0], name="successor")
    assert not successor.unclean_recovery
    assert len(list(successor.journal.records())) == 3
    assert sum(n.startswith("source/") for n in successor.receipt.manifest) == 3
    successor.close()


def test_confirmed_original_source_deletion_is_not_a_recoverable_pending_tail(prepared):
    now = [T + 61_000]
    obj = owner(prepared, clock=lambda: now[0])
    obj.journal.append({"received_ms": now[0], "confirmed": "original-source"})
    obj.checkpoint()
    obj.abandon()
    with sqlite3.connect(prepared[0] / "source.sqlite") as connection:
        connection.execute("DELETE FROM receipts WHERE rowid=2")
    now[0] += 61_000
    with pytest.raises(ValueError, match="original source rollback"):
        owner(prepared, clock=lambda: now[0], name="successor")


def test_same_clock_original_receipts_cannot_be_reordered_inside_confirmed_prefix():
    from cocomelon.research.volatility_owner import _source_prefix

    first = {"received_ms": T, "kind": "mark", "original": "first"}
    second = {"received_ms": T, "kind": "book", "original": "second"}

    def chunk(rows):
        return gzip.compress(b"\n".join(json.dumps(r).encode() for r in rows), mtime=0)

    with pytest.raises(ValueError, match="source rollback|ordering"):
        _source_prefix(
            {"source/original.jsonl.gz": chunk([first, second])},
            {"source/current.jsonl.gz": chunk([second, first])},
        )


def test_overlapping_partial_chunks_cannot_fake_confirmed_duplicate_receipt_ordinals():
    from cocomelon.research.volatility_owner import _source_prefix

    row = {"received_ms": T, "original": "same-actual-value"}

    def chunk(rows):
        return gzip.compress(b"\n".join(json.dumps(r).encode() for r in rows), mtime=0)

    def name(count, suffix):
        return f"source/source-0000000000-{count:03d}-{suffix * 64}.jsonl.gz"

    with pytest.raises(ValueError, match="source rollback|ordering"):
        _source_prefix(
            {name(2, "a"): chunk([row, row])},
            {name(1, "b"): chunk([row]), name(1, "c"): chunk([row])},
        )


def test_real_normalized_and_wire_journal_chunks_recover_through_partial_boundaries(tmp_path):
    from cocomelon.research.volatility_owner import TrialOwner
    from cocomelon.research.volatility_service import JournalSet

    root = tmp_path / "actual-journal-root"
    obj = trial(root)
    opened(obj)
    obj.close()
    journal = JournalSet(root / "source.sqlite")
    for i in range(3):
        journal.append({"received_ms": T + i, "normalized": i})
        journal.ingress.append({"received_ms": T + i, "raw_wire": str(i)})
    remote = tmp_path / "actual-remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    def custodian(owner_id):
        return GitCustody(
            tmp_path / ("actual-cache-" + owner_id),
            remote=str(remote),
            branch="codex/volatility-budget-v1-custody",
            identity=IDENTITY,
            owner_id=owner_id,
        )

    custodian("genesis").initialize(
        {**capture_trial_files(root), **journal.archive()}, summary={}, now_ms=T + 300
    )
    journal.close()
    now = [T + 61_000]
    first = TrialOwner(
        root,
        identity=IDENTITY,
        custody=custodian("first"),
        journal_factory=JournalSet,
        clock=lambda: now[0],
    )
    for i in range(3, 140):
        first.journal.append({"received_ms": T + i, "normalized": i})
        first.journal.ingress.append({"received_ms": T + i, "raw_wire": str(i)})
    first.checkpoint()
    first.journal.append({"received_ms": T + 140, "normalized": 140})
    first.journal.ingress.append({"received_ms": T + 140, "raw_wire": "140"})
    first.close()
    now[0] += 61_000
    second = TrialOwner(
        root,
        identity=IDENTITY,
        custody=custodian("second"),
        journal_factory=JournalSet,
        clock=lambda: now[0],
    )
    assert len(list(second.journal.records())) == 141
    assert len(list(second.journal.ingress.records())) == 141
    assert not second.unclean_recovery
    second.close()


def test_capacity_failure_can_renew_fence_for_protection_without_claiming_new_cash(
    prepared, monkeypatch
):
    import cocomelon.research.volatility_custody as module

    now = [T + 61_000]
    obj = owner(prepared, clock=lambda: now[0])
    confirmed = obj.checkpoint()
    confirmed_cash = confirmed.summary["candidate_cash"]
    largest_confirmed = max(map(len, obj._files.values()))
    monkeypatch.setattr(module, "_MAX_FILE", largest_confirmed)
    obj.trial._record("synthetic_storage_growth", now[0], {"data": "x" * 200000})
    obj.trial._save()
    with pytest.raises(ValueError, match="capacity"):
        obj.checkpoint()
    assert not obj.entries_allowed
    now[0] += 1000
    renewed = obj.renew_fence_only()
    assert renewed.cumulative_bytes == confirmed.cumulative_bytes
    assert renewed.summary["candidate_cash"] == confirmed_cash
    assert renewed.summary["latest_account_verified"] is False
    assert renewed.summary["entries_authorized"] is False
    assert renewed.summary["source_valid"] is False
    assert renewed.pending is not None
    assert obj.lease_valid()
    obj.trial.on_mark(mark(now[0], "97"), now_ms=now[0])
    obj.trial.on_book(quote(now[0], bid="96.99", ask="97.01"), spec(), now_ms=now[0])
    now[0] += 300
    obj.trial.on_book(quote(now[0], bid="96.99", ask="97.01"), spec(), now_ms=now[0])
    assert not obj.trial.candidate.account.positions
    from decimal import Decimal

    assert obj.trial.candidate.account.cash < Decimal(confirmed_cash)
    final = obj.renew_fence_only()
    assert final.summary["candidate_cash"] == confirmed_cash
    assert final.summary["current_account_has_unacknowledged_tail"] is True
    assert not obj.entries_allowed
    obj.abandon()


def test_qualified_owner_cannot_replace_current_custody_with_fence_only_receipt(prepared):
    obj = owner(prepared, clock=lambda: T + 61_000)
    with pytest.raises(RuntimeError, match="UNQUALIFIED"):
        obj.renew_fence_only()
    obj.close()


def test_interruption_during_trial_constructor_has_remote_pending_before_local_revision_change(
    prepared, monkeypatch
):
    import cocomelon.research.volatility_owner as module

    original_constructor = module.VolatilityPaperTrial
    now = [T + 61_000]

    def interrupted(*args, **kwargs):
        trial_obj = original_constructor(*args, **kwargs)
        trial_obj.close()
        raise RuntimeError("synthetic interruption after constructor save")

    monkeypatch.setattr(module, "VolatilityPaperTrial", interrupted)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        owner(prepared, clock=lambda: now[0])
    monkeypatch.setattr(module, "VolatilityPaperTrial", original_constructor)
    now[0] += 61_000
    successor = owner(prepared, clock=lambda: now[0], name="successor")
    assert successor.unclean_recovery
    assert successor.trial.candidate.account.positions
    assert not successor.entries_allowed
    successor.close()
