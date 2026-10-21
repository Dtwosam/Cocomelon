"""Real local-Git custody crash/fencing tests; no operational remote is mutated."""

import json
import sqlite3
import subprocess

import pytest

POLICY = "eca2816e42a1a0409737e179b45761a8a4ad0ebb2149ee7ad956b6867caffdaa"
IDENTITY = {
    "protocol_sha256": POLICY,
    "candidate_id": "candidate-original",
    "control_id": "control-original",
    "first_entry_ms": 864030000,
}


@pytest.fixture
def remote(tmp_path):
    path = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True)
    return str(path)


def custody(tmp_path, remote, owner="owner-original", identity=None):
    from cocomelon.research.volatility_custody import GitCustody

    return GitCustody(
        tmp_path,
        remote=remote,
        branch="codex/volatility-budget-v1-custody",
        identity=identity or IDENTITY,
        owner_id=owner,
    )


def files(balance=b"loss-preserved"):
    return {
        "candidate.sqlite": balance,
        "control.sqlite": b"10000-control",
        "trial.sqlite": b"original-history",
        "source/chunk-0001.json": b'{"received_ms":123,"raw":"native"}',
    }


def test_genesis_identity_and_complete_original_bytes_survive_remote_restore(tmp_path, remote):
    obj = custody(tmp_path / "first", remote)
    receipt = obj.initialize(files(), summary={"equity": "9987"}, now_ms=1000)
    assert receipt.revision == 1
    assert receipt.owner_generation == 1
    assert obj.latest() == receipt
    obj2 = custody(tmp_path / "new-cache", remote, "replacement")
    restored = obj2.restore(tmp_path / "restored")
    assert restored.commit == receipt.commit
    assert (tmp_path / "restored/candidate.sqlite").read_bytes() == b"loss-preserved"
    assert (tmp_path / "restored/source/chunk-0001.json").read_bytes() == files()[
        "source/chunk-0001.json"
    ]
    assert (
        json.loads((tmp_path / "restored/custody-receipt.json").read_text())["identity"] == IDENTITY
    )


def test_existing_remote_cannot_be_initialized_as_new_ten_thousand_account(tmp_path, remote):
    custody(tmp_path / "one", remote).initialize(files(), summary={}, now_ms=1000)
    obj = custody(tmp_path / "two", remote, "owner-two")
    with pytest.raises(RuntimeError, match="already exists"):
        obj.initialize(files(b"10000-reset"), summary={}, now_ms=2000)


def test_coherent_local_rollback_detected_against_independent_latest_state(tmp_path, remote):
    obj = custody(tmp_path / "one", remote)
    old = files()
    obj.initialize(old, summary={}, now_ms=1000)
    obj.publish(files(b"new-loss"), summary={}, now_ms=2000)
    with pytest.raises(RuntimeError, match="rollback|mismatch"):
        obj.assert_current(old)
    assert obj.assert_current(files(b"new-loss")).revision == 2


def test_owner_cannot_alternate_with_unexpired_independent_owner(tmp_path, remote):
    first = custody(tmp_path / "one", remote)
    first.initialize(files(), summary={}, now_ms=1000)
    second = custody(tmp_path / "two", remote, "owner-two")
    with pytest.raises(RuntimeError, match="owner|lease"):
        second.acquire(now_ms=2000)
    successor = second.acquire(now_ms=61000)
    assert successor.owner_generation == 2
    first_files = files(b"stale-new-loss")
    with pytest.raises(RuntimeError, match="stale|owner|lease"):
        first.publish(first_files, summary={}, now_ms=61001)
    assert second.latest().commit == successor.commit


def test_lease_expiry_and_clock_regression_fail_closed(tmp_path, remote):
    obj = custody(tmp_path / "one", remote)
    obj.initialize(files(), summary={}, now_ms=1000)
    with pytest.raises(RuntimeError, match="clock"):
        obj.publish(files(), summary={}, now_ms=999)
    with pytest.raises(RuntimeError, match="expired"):
        obj.publish(files(), summary={}, now_ms=61000)


def test_crash_after_remote_commit_before_local_ack_does_not_erase_latest_loss(tmp_path, remote):
    first = custody(tmp_path / "one", remote)
    initial = first.initialize(files(), summary={}, now_ms=1000)
    published = first.publish(files(b"9980-durable"), summary={"equity": "9980"}, now_ms=2000)
    # The process lost its new acknowledgment; its last known receipt is stale.
    first._held = initial
    with pytest.raises(RuntimeError, match="stale"):
        first.publish(files(b"10000-reset"), summary={}, now_ms=3000)
    successor = custody(tmp_path / "successor", remote, "successor")
    assert successor.latest().commit == published.commit
    assert successor.read_files(successor.latest())["candidate.sqlite"] == b"9980-durable"


def test_pending_original_obligation_cannot_be_cleared_by_local_rollback(tmp_path, remote):
    obj = custody(tmp_path / "one", remote)
    original = files()
    obj.initialize(original, summary={}, now_ms=1000)
    pending = {"kind": "book-before-fill", "event_key": "original-receipt-7"}
    receipt = obj.publish(
        original, summary={"open_intent": "must-recover"}, now_ms=2000, pending=pending
    )
    restarted = custody(tmp_path / "new", remote, "new-owner")
    assert restarted.latest().pending == pending
    assert restarted.latest().summary["open_intent"] == "must-recover"
    assert restarted.latest().commit == receipt.commit


def test_six_push_rolling_budget_is_durable_across_new_process(tmp_path, remote):
    obj = custody(tmp_path / "one", remote)
    obj.initialize(files(), summary={}, now_ms=1000)
    for now in range(1001, 1006):
        obj.publish(files(), summary={}, now_ms=now)
    with pytest.raises(RuntimeError, match="push budget"):
        obj.publish(files(), summary={}, now_ms=1006)
    # An expired lease can be reacquired; budget is read from remote rather than reset.
    obj2 = custody(tmp_path / "two", remote, "other")
    obj2.acquire(now_ms=61006)
    assert obj2.latest().revision == 7


def test_identity_changes_and_wrong_policy_rejected(tmp_path, remote):
    custody(tmp_path / "one", remote).initialize(files(), summary={}, now_ms=1000)
    changed = dict(IDENTITY, candidate_id="reset-candidate")
    obj = custody(tmp_path / "two", remote, "other", changed)
    with pytest.raises(RuntimeError, match="identity"):
        obj.latest()
    with pytest.raises(ValueError, match="policy"):
        custody(tmp_path / "three", remote, identity=dict(IDENTITY, protocol_sha256="0" * 64))


@pytest.mark.parametrize("bad", ["../escape", "/absolute", "x/../../escape", ".git/config"])
def test_payload_path_traversal_rejected_before_any_remote_write(tmp_path, remote, bad):
    obj = custody(tmp_path / "one", remote)
    with pytest.raises(ValueError, match="path"):
        obj.initialize({**files(), bad: b"malicious"}, summary={}, now_ms=1000)
    assert obj.latest() is None


def test_restore_never_overwrites_existing_accounts(tmp_path, remote):
    obj = custody(tmp_path / "one", remote)
    obj.initialize(files(), summary={}, now_ms=1000)
    dest = tmp_path / "original"
    dest.mkdir()
    (dest / "candidate.sqlite").write_bytes(b"existing-loss")
    with pytest.raises(ValueError, match="empty"):
        obj.restore(dest)
    assert (dest / "candidate.sqlite").read_bytes() == b"existing-loss"


def test_sqlite_backup_includes_uncheckpointed_wal_pages(tmp_path):
    from cocomelon.research.volatility_custody import capture_trial_files

    root = tmp_path / "trial"
    root.mkdir()
    connections = []
    for name in ("trial.sqlite", "candidate.sqlite", "control.sqlite"):
        connection = sqlite3.connect(root / name)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE evidence (value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('original-loss')")
        connection.commit()
        connections.append(connection)
    captured = capture_trial_files(root)
    for name, value in captured.items():
        path = tmp_path / name
        path.write_bytes(value)
        with sqlite3.connect(path) as restored:
            assert restored.execute("SELECT value FROM evidence").fetchone()[0] == "original-loss"
    for connection in connections:
        connection.close()


def test_original_source_bytes_cannot_be_deleted_or_rewritten(tmp_path, remote):
    obj = custody(tmp_path / "one", remote)
    obj.initialize(files(), summary={}, now_ms=1000)
    for updated in (
        {k: v for k, v in files().items() if not k.startswith("source/")},
        {**files(), "source/chunk-0001.json": b"rewritten-original"},
    ):
        with pytest.raises(RuntimeError, match="original source"):
            obj.publish(updated, summary={}, now_ms=2000)
    assert obj.latest().revision == 1


def test_original_decision_and_account_identity_recovery_have_exact_parent_chain(tmp_path, remote):
    obj = custody(tmp_path / "one", remote)
    first = obj.initialize(files(), summary={"floor_latched": False}, now_ms=1000)
    second = obj.publish(files(b"9949-loss"), summary={"floor_latched": True}, now_ms=2000)
    raw = subprocess.run(
        ["git", "--git-dir", remote, "show", f"{second.commit}:receipt.json"],
        check=True,
        capture_output=True,
    ).stdout
    assert json.loads(raw)["parent"] == first.commit
    parents = subprocess.run(
        ["git", "--git-dir", remote, "rev-list", "--parents", "-n", "1", second.commit],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert parents == [second.commit, first.commit]
    successor = custody(tmp_path / "successor", remote, "successor")
    assert successor.latest().summary["floor_latched"] is True
    assert successor.latest().identity == IDENTITY


def test_same_owner_label_cannot_reacquire_unexpired_lease_from_copied_root(tmp_path, remote):
    obj = custody(tmp_path / "one", remote)
    obj.initialize(files(), summary={}, now_ms=1000)
    clone = custody(tmp_path / "clone", remote)
    with pytest.raises(RuntimeError, match="lease"):
        clone.acquire(now_ms=2000)
    with pytest.raises(RuntimeError, match="not acquired"):
        clone.publish(files(b"10000-reset"), summary={}, now_ms=2000)


def test_missing_remote_history_is_not_implicit_genesis_during_recovery(tmp_path, remote):
    obj = custody(tmp_path / "one", remote)
    with pytest.raises(RuntimeError, match="missing"):
        obj.acquire(now_ms=1000)
    with pytest.raises(RuntimeError, match="latest"):
        obj.restore(tmp_path / "new-root")
    assert not (tmp_path / "new-root").exists()


def test_real_cas_race_cannot_overwrite_concurrent_genesis(tmp_path, remote, monkeypatch):
    first = custody(tmp_path / "one", remote)
    second = custody(tmp_path / "two", remote, "winner")
    run = first._run
    raced = False

    def race(arguments, **kwargs):
        nonlocal raced
        if arguments[0] == "push" and not raced:
            raced = True
            second.initialize(files(b"winner-history"), summary={}, now_ms=1000)
        return run(arguments, **kwargs)

    monkeypatch.setattr(first, "_run", race)
    with pytest.raises(RuntimeError, match="Git operation failed"):
        first.initialize(files(b"loser-reset"), summary={}, now_ms=1000)
    receipt = second.latest()
    assert receipt.owner_id == "winner"
    assert second.read_files(receipt)["candidate.sqlite"] == b"winner-history"


def test_publication_ack_failure_retains_remote_obligation_and_prevents_reset(
    tmp_path, remote, monkeypatch
):
    first = custody(tmp_path / "one", remote)
    latest = first.latest
    calls = 0

    def failed_ack():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("remote acknowledgment lost")
        return latest()

    monkeypatch.setattr(first, "latest", failed_ack)
    with pytest.raises(RuntimeError, match="acknowledgment"):
        first.initialize(
            files(b"original-9950"),
            summary={"protection_required": True},
            pending={"open_intent": "original"},
            now_ms=1000,
        )
    successor = custody(tmp_path / "successor", remote, "successor")
    receipt = successor.latest()
    assert receipt.pending == {"open_intent": "original"}
    assert receipt.summary["protection_required"] is True
    with pytest.raises(RuntimeError, match="already exists"):
        successor.initialize(files(b"10000-reset"), summary={}, now_ms=2000)


def test_snapshot_size_budget_fails_without_destroying_protection_receipt(
    tmp_path, remote, monkeypatch
):
    import cocomelon.research.volatility_custody as module

    monkeypatch.setattr(module, "_MAX_FILE", 1024)
    obj = custody(tmp_path / "one", remote)
    receipt = obj.initialize(files(), summary={"position": "must-protect"}, now_ms=1000)
    with pytest.raises(ValueError, match="capacity"):
        obj.publish(files(b"x" * 1025), summary={}, now_ms=2000)
    assert obj.latest() == receipt


def test_ordinary_main_ref_and_credentials_in_remote_url_rejected(tmp_path, remote):
    from cocomelon.research.volatility_custody import GitCustody

    with pytest.raises(ValueError, match="branch"):
        GitCustody(
            tmp_path / "one", remote=remote, branch="main", identity=IDENTITY, owner_id="one"
        )
    with pytest.raises(ValueError, match="authorized"):
        custody(tmp_path / "two", "https://credential@github.com/Dtwosam/Cocomelon.git")


def test_sqlite_backup_is_stable_for_unchanged_committed_account(tmp_path):
    from cocomelon.research.volatility_custody import capture_trial_files

    root = tmp_path / "trial"
    root.mkdir()
    for name in ("trial.sqlite", "candidate.sqlite", "control.sqlite"):
        with sqlite3.connect(root / name) as connection:
            connection.execute("CREATE TABLE evidence (value TEXT)")
            connection.execute("INSERT INTO evidence VALUES ('unreset-loss')")
    first = capture_trial_files(root)
    assert capture_trial_files(root) == first
    restored = tmp_path / "restored"
    restored.mkdir()
    for name, value in first.items():
        (restored / name).write_bytes(value)
    assert capture_trial_files(restored) == first


def test_remote_payload_corruption_is_detected_by_manifest_before_restore(tmp_path, remote):
    obj = custody(tmp_path / "one", remote)
    receipt = obj.initialize(files(), summary={}, now_ms=1000)
    # Real remote objects still exist, but a supplied manifest may never weaken
    # byte validation merely because its commit identifier is authentic.
    from dataclasses import replace

    corrupted = replace(receipt, manifest={**receipt.manifest, "candidate.sqlite": "0" * 64})
    with pytest.raises(RuntimeError, match="digest"):
        obj.read_files(corrupted)


def test_custody_cache_and_sqlite_aliases_are_rejected(tmp_path, remote):
    from cocomelon.research.volatility_custody import capture_trial_files

    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="alias"):
        custody(alias, remote)
    source = tmp_path / "source.sqlite"
    source.write_bytes(b"not-read")
    trial_root = tmp_path / "trial-root"
    trial_root.mkdir()
    (trial_root / "candidate.sqlite").symlink_to(source)
    with pytest.raises(ValueError, match="alias"):
        capture_trial_files(trial_root)


def test_shared_cache_concurrent_staging_cannot_publish_another_owners_payload(
    tmp_path, remote, monkeypatch
):
    first = custody(tmp_path / "shared-cache", remote, "first")
    second = custody(tmp_path / "shared-cache", remote, "second")
    first_run, second_run = first._run, second._run
    interrupted = False

    def stop_second_before_push(arguments, **kwargs):
        if arguments[0] == "push":
            raise RuntimeError("other process interrupted after staging")
        return second_run(arguments, **kwargs)

    def interleave_staging(arguments, **kwargs):
        nonlocal interrupted
        if arguments[0] == "write-tree" and not interrupted:
            interrupted = True
            with pytest.raises(RuntimeError, match="interrupted"):
                second.initialize(files(b"other-owner-payload"), summary={}, now_ms=1000)
        return first_run(arguments, **kwargs)

    monkeypatch.setattr(second, "_run", stop_second_before_push)
    monkeypatch.setattr(first, "_run", interleave_staging)
    receipt = first.initialize(files(b"first-owner-payload"), summary={}, now_ms=1000)
    assert receipt.owner_id == "first"
    assert first.read_files(receipt)["candidate.sqlite"] == b"first-owner-payload"


def test_page_addressed_snapshot_growth_charges_only_new_compressed_pages(tmp_path, remote):
    import random

    randomizer = random.Random(91)
    first_page = randomizer.randbytes(65536)
    second_page = randomizer.randbytes(65536)
    obj = custody(tmp_path / "pages", remote)
    initial = obj.initialize(files(first_page), summary={}, now_ms=1000)
    assert len(initial.layout["candidate.sqlite"]) == 1
    updated = obj.publish(files(first_page + second_page), summary={}, now_ms=2000)
    assert updated.layout["candidate.sqlite"][0] == initial.layout["candidate.sqlite"][0]
    assert len(updated.layout["candidate.sqlite"]) == 2
    assert 65536 <= updated.cumulative_bytes - initial.cumulative_bytes <= 65600
    assert obj.read_files(updated)["candidate.sqlite"] == first_page + second_page
    unchanged = obj.publish(files(first_page + second_page), summary={}, now_ms=3000)
    assert unchanged.cumulative_bytes == updated.cumulative_bytes
    paths = subprocess.run(
        ["git", "--git-dir", remote, "ls-tree", "-r", "--name-only", updated.commit],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert any(name.startswith("pages/") for name in paths)
    assert not any(name.startswith("payload/") for name in paths)


def test_reintroduced_old_page_is_reused_from_committed_history_after_cache_restart(
    tmp_path, remote
):
    import random

    rng = random.Random(71)
    first, second = rng.randbytes(65536), rng.randbytes(65536)
    obj = custody(tmp_path / "history-pages", remote)
    obj.initialize(files(first), summary={}, now_ms=1000)
    latest = obj.publish(files(second), summary={}, now_ms=2000)
    successor = custody(tmp_path / "fresh-cache", remote, "successor")
    successor.acquire(now_ms=62000)
    returned = successor.publish(files(first), summary={}, now_ms=62001)
    assert returned.cumulative_bytes == latest.cumulative_bytes
    assert successor.read_files(returned)["candidate.sqlite"] == first


def test_compressed_page_tamper_and_expansion_limit_fail_closed(tmp_path, remote):
    from dataclasses import replace

    obj = custody(tmp_path / "tampered-pages", remote)
    receipt = obj.initialize(files(b"original-exact"), summary={}, now_ms=1000)
    bad_layout = {**receipt.layout, "candidate.sqlite": ("0" * 64,)}
    with pytest.raises(RuntimeError):
        obj.read_files(replace(receipt, layout=bad_layout))
    page = obj._run(["show", f"{receipt.commit}:pages/{receipt.layout['candidate.sqlite'][0]}.gz"])
    assert page[9] == 255  # deterministic across Mac/Linux Python3.12 zlib headers


def test_synthetic_24_hour_page_growth_is_linear_not_full_snapshot_copies(
    tmp_path, remote, record_property
):
    """24 hourly storage epochs, synthetic entropy only; no market/PnL evidence."""
    import random
    import time

    rng = random.Random(20261021)
    state = bytearray(rng.randbytes(65536))
    obj = custody(tmp_path / "synthetic-day", remote)
    obj.initialize(files(bytes(state)), summary={"synthetic_capacity_only": True}, now_ms=1000)
    full_copy_bytes = len(state)
    began = time.perf_counter()
    receipt = None
    for hour in range(1, 25):
        now = 1000 + hour * 3_600_000
        # Deliberately sparse synthetic epochs reacquire expired ownership; this
        # storage test does not claim continuous position/source supervision.
        obj.acquire(now_ms=now)
        state[:8] = hour.to_bytes(8, "big")
        state.extend(rng.randbytes(1024 * 1024))
        full_copy_bytes += len(state)
        receipt = obj.publish(files(bytes(state)), summary={"synthetic_hour": hour}, now_ms=now + 1)
    assert receipt is not None
    assert receipt.cumulative_bytes < len(state) * 1.15
    assert receipt.cumulative_bytes < full_copy_bytes / 8
    assert obj.read_files(receipt)["candidate.sqlite"] == bytes(state)
    record_property(
        "synthetic_24h_storage",
        json.dumps(
            {
                "hours": 24,
                "raw_final_bytes": len(state),
                "full_snapshot_copy_bytes": full_copy_bytes,
                "new_compressed_page_bytes": receipt.cumulative_bytes,
                "elapsed_seconds": round(time.perf_counter() - began, 3),
                "is_market_or_economic_evidence": False,
            },
            sort_keys=True,
        ),
    )


def test_authenticated_page_cannot_expand_beyond_page_budget(tmp_path, remote, monkeypatch):
    import gzip
    import hashlib
    from dataclasses import replace

    obj = custody(tmp_path / "expansion-pages", remote)
    receipt = obj.initialize(files(), summary={}, now_ms=1000)
    oversized = gzip.compress(b"x" * 65537, mtime=0)
    digest = hashlib.sha256(oversized).hexdigest()
    layout = {**receipt.layout, "candidate.sqlite": (digest,)}
    run = obj._run

    def injected(arguments, **kwargs):
        if arguments == ["cat-file", "--batch"]:
            result = b""
            for expression in kwargs["data"].splitlines():
                if expression == f"{receipt.commit}:pages/{digest}.gz".encode():
                    result += b"0" * 40 + f" blob {len(oversized)}\n".encode() + oversized + b"\n"
                else:
                    result += run(arguments, data=expression + b"\n")
            return result
        return run(arguments, **kwargs)

    monkeypatch.setattr(obj, "_run", injected)
    with pytest.raises(RuntimeError, match="compressed page"):
        obj.read_files(replace(receipt, layout=layout))


def test_large_recovery_reads_pages_in_one_git_batch_not_one_process_per_page(
    tmp_path, remote, monkeypatch
):
    import random

    obj = custody(tmp_path / "batch-pages", remote)
    original = random.Random(44).randbytes(10 * 65536)
    receipt = obj.initialize(files(original), summary={}, now_ms=1000)
    calls = []
    run = obj._run

    def counted(arguments, **kwargs):
        calls.append(arguments)
        return run(arguments, **kwargs)

    monkeypatch.setattr(obj, "_run", counted)
    assert obj.read_files(receipt)["candidate.sqlite"] == original
    assert not any(a[0] == "show" and ":pages/" in a[-1] for a in calls)
    assert sum(a == ["cat-file", "--batch"] for a in calls) == 1
