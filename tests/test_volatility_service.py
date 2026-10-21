"""Synthetic service admission/recovery; never prospective trading evidence."""

import json
from decimal import Decimal

import pytest
from test_flow_exhaustion_paper import spec
from test_volatility_budget_paper import T, mark, opened, quote, trial


def test_shared_unknown_network_denies_before_transport_or_account_creation(tmp_path):
    from cocomelon.research.volatility_service import validate_admission

    with pytest.raises(ValueError, match="aggregate"):
        validate_admission({"network": {"ownership": "shared_or_unknown"}}, now_ms=T)
    assert list(tmp_path.iterdir()) == []


def test_journal_fsync_chain_preserves_original_bad_and_good_receipts(tmp_path):
    from cocomelon.research.volatility_service import SourceJournal

    journal = SourceJournal(tmp_path / "source.sqlite")
    journal.append({"received_at_ms": T, "raw": {"broken": True}})
    journal.append({"received_at_ms": T - 1, "raw": {"actual_clock_regression": True}})
    assert list(journal.records())[-1]["received_at_ms"] == T - 1
    journal.close()
    recovered = SourceJournal(tmp_path / "source.sqlite")
    assert len(list(recovered.records())) == 2
    recovered.close()


def test_pending_custody_restart_keeps_position_and_disables_entries(tmp_path):
    from cocomelon.research.volatility_service import VolatilityService

    obj = trial(tmp_path / "trial")
    position = opened(obj)
    obj.close()
    obj = trial(tmp_path / "trial", authorized=False)
    clock = [T + 1000]
    service = VolatilityService(obj, clock=lambda: clock[0], unclean_recovery=True)
    assert service.trial.snapshot()["permanently_disabled"]
    assert service.trial.candidate.account.positions[0].position_id == position.position_id
    service.on_mark(mark(T + 1000, "97"))
    clock[0] = T + 1300
    service.on_book(quote(T + 1300, bid="96.99", ask="97.01"), spec())
    clock[0] = T + 1600
    service.on_book(quote(T + 1600, bid="96.99", ask="97.01"), spec())
    assert not service.trial.candidate.account.positions
    assert service.trial.candidate.account.cash < Decimal(10000)
    assert service.trial.snapshot()["permanently_disabled"]
    obj.close()


def test_freshness_uses_current_clock_never_source_time(tmp_path):
    from cocomelon.research.volatility_service import VolatilityService

    obj = trial(tmp_path)
    opened(obj)
    service = VolatilityService(obj, clock=lambda: T + 10_000)
    service.on_mark(mark(T + 1000, "97"))
    # A genuinely old receipt cannot be converted into a fresh stop fill.
    service.on_book(quote(T + 1300, bid="96.99", ask="97.01"), spec())
    assert service.trial.candidate.account.positions
    assert not service.trial.source_valid
    obj.close()


def test_protection_only_service_never_reauthorizes_trial(tmp_path):
    from cocomelon.research.volatility_service import VolatilityService

    obj = trial(tmp_path, authorized=False)
    service = VolatilityService(obj, clock=lambda: T + 1000)
    service.tick()
    assert not obj.entries_authorized
    obj.close()


def test_nonblocking_budget_charges_failed_request_and_preserves_reserve():
    from cocomelon.research.volatility_service import ServiceBudget

    budget = ServiceBudget()
    for _ in range(4):
        budget.acquire(22)
    budget.acquire(20)
    with pytest.raises(RuntimeError, match="quota"):
        budget.acquire(45)
    budget.priority = True
    for _ in range(4):
        budget.acquire(45)
    with pytest.raises(RuntimeError, match="quota"):
        budget.acquire(45)


def test_launchagent_is_paper_only_and_escapes_paths(tmp_path):
    import plistlib

    from cocomelon.research.volatility_service import launch_agent

    raw = launch_agent(tmp_path / "python", tmp_path / "config & space.json")
    p = plistlib.loads(raw)
    assert p["KeepAlive"] is True
    assert p["ThrottleInterval"] >= 10
    assert p["ProgramArguments"][-1].endswith("config & space.json")
    assert p["EnvironmentVariables"]["COCOMELON_EXECUTION_MODE"] == "paper"
    assert "live" not in json.dumps(p["ProgramArguments"]).lower()


def test_incremental_source_segments_retain_stable_full_chunks(tmp_path):
    from cocomelon.research.volatility_service import SourceJournal

    journal = SourceJournal(tmp_path / "source.sqlite")
    for i in range(128):
        journal.append({"received_at_ms": i, "raw": {"value": str(i)}})
    first = journal.archive()
    assert len(first) == 1
    journal.append({"received_at_ms": 128, "raw": {"value": "next"}})
    second = journal.archive()
    assert len(second) == 2
    assert first.items() <= second.items()
    journal.close()


def test_expired_entry_admission_keeps_protective_management(tmp_path):
    from cocomelon.research.volatility_service import VolatilityService

    obj = trial(tmp_path)
    opened(obj)
    clock = [T + 1000]
    service = VolatilityService(obj, clock=lambda: clock[0])
    assert not service.refresh_entry_authority({}, source_valid=True)
    service.on_mark(mark(T + 1000, "97"))
    for delta in (1300, 1600):
        clock[0] = T + delta
        service.on_book(quote(clock[0], bid="96.99", ask="97.01"), spec())
    assert not obj.candidate.account.positions
    assert obj.candidate.account.cash < 10000
    obj.close()


def test_actual_run_refuses_unknown_nat_before_any_resource_is_touched(monkeypatch):
    import asyncio

    import cocomelon.research.volatility_service as module

    def forbidden(*args, **kwargs):
        raise AssertionError("admission touched resources")

    monkeypatch.setattr(module, "SourceJournal", forbidden)
    monkeypatch.setattr(module, "GitCustody", forbidden)
    monkeypatch.setattr(module, "VolatilityPaperTrial", forbidden)
    with pytest.raises(ValueError, match="aggregate"):
        asyncio.run(module.run({"activation": {"network": {"ownership": "shared_or_unknown"}}}))


def test_preparation_refuses_unknown_network_without_creating_accounts(tmp_path):
    from cocomelon.research.volatility_service import prepare

    with pytest.raises(ValueError, match="aggregate"):
        prepare(
            {
                "root": str(tmp_path / "never-created"),
                "activation": {"network": {"ownership": "shared_or_unknown"}},
            }
        )
    assert not (tmp_path / "never-created").exists()


def admission(now):
    from cocomelon.research.volatility_budget import PROTOCOL_SHA256

    return {
        "network": {
            "ownership": "operator_verified",
            "all_consumers_accounted": True,
            "public_ip": "8.8.8.8",
            "other_rest_peak_weight": 0,
            "other_ws_peak_connections": 0,
            "other_ws_peak_subscriptions": 0,
            "other_ws_new_per_minute": 0,
            "other_ws_sent_per_minute": 0,
        },
        "policy_sha256": PROTOCOL_SHA256,
        "release_ms": T - 6 * 3_600_000,
        "first_entry_ms": T,
        "review_expires_ms": now + 400,
        "mandatory_checks": {str(i): "PASS" for i in range(1, 15)},
        "code_sha": "a" * 40,
        "independent_review_sha256": "b" * 64,
        "resource_evidence_sha256": "c" * 64,
    }


def test_actual_async_driver_keeps_exits_after_entry_review_expires(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import cocomelon.research.volatility_owner as owner_module
    import cocomelon.research.volatility_service as module
    import cocomelon.research.volatility_transport as transport_module
    from cocomelon.research.volatility_budget import PROTOCOL_SHA256

    root = tmp_path / "trial"
    obj = trial(root)
    opened(obj)
    journals = module.JournalSet(root / "source.sqlite")
    clock = [T + 1000]
    state = {"closed": False, "disabled": []}
    monkeypatch.setattr(module, "wall_ms", lambda: clock[0])
    monkeypatch.setattr(module, "verify_deployed_code", lambda *args: None)
    monkeypatch.setattr(module, "verify_egress", lambda *args: None)
    monkeypatch.setattr(module, "GitCustody", lambda *args, **kwargs: object())

    class Owner:
        def __init__(self, *args, **kwargs):
            self.trial, self.journal = obj, journals
            self.unclean_recovery = False
            self.entries_allowed = True
            self.receipt = SimpleNamespace(
                summary=obj.snapshot(), commit="a" * 40, time_ms=clock[0], pending={"running": True}
            )

        def lease_valid(self, *args):
            return True

        def disable(self, reason):
            state["disabled"].append(reason)
            obj.entries_authorized = False

        def prepare_checkpoint(self, **kwargs):
            return None

        def publish_checkpoint(self, prepared):
            return SimpleNamespace(lease_until_ms=T + 86_400_000)

        def close(self, *, clean):
            state.update(closed=True, clean=clean, cash=obj.candidate.account.cash)
            obj.close()
            journals.close()

    class Source:
        rejections = ()
        funding_rates = {}

        def __init__(self, *args):
            pass

        def restore(self, *args, **kwargs):
            pass

        def gap(self, *args, **kwargs):
            pass

        def ingest_ws(self, raw, **kwargs):
            return (raw,)

        def instruments(self):
            return {spec().market: spec()}

    class Transport:
        def __init__(self, **kwargs):
            pass

        async def run(self, queue, stop, desired):
            for delta, event in (
                (1000, mark(T + 1000, "97")),
                (1300, quote(T + 1300, bid="96.99", ask="97.01")),
                (1600, quote(T + 1600, bid="96.99", ask="97.01")),
            ):
                clock[0] = T + delta
                await queue.put(("ws", event, clock[0], None, None))
                await asyncio.sleep(0.01)
            assert not obj.candidate.account.positions
            assert not obj.entries_authorized  # The review expired at T+1400.
            stop.set()

    monkeypatch.setattr(owner_module, "TrialOwner", Owner)
    monkeypatch.setattr(transport_module, "VolatilityTransport", Transport)
    monkeypatch.setattr(module, "VolatilitySource", Source)
    config = {
        "root": str(root),
        "code_root": str(tmp_path),
        "custody_cache": str(tmp_path / "cache"),
        "custody_remote": "https://github.com/Dtwosam/Cocomelon.git",
        "custody_branch": "codex/volatility-synthetic-custody",
        "activation": admission(clock[0]),
        "identity": {
            "protocol_sha256": PROTOCOL_SHA256,
            "first_entry_ms": T,
            "candidate_id": "volatility-candidate",
            "control_id": "volatility-control",
        },
    }
    receipt_bytes = module._json(config["activation"])
    (root / "activation.json").write_bytes(receipt_bytes)
    config["identity"]["activation_sha256"] = (
        __import__("hashlib").sha256(receipt_bytes).hexdigest()
    )
    asyncio.run(module.run(config))
    assert state["closed"]
    assert state["cash"] < 10000


def test_journal_hardlink_cannot_alias_another_trial(tmp_path):
    import os

    from cocomelon.research.volatility_service import SourceJournal

    journal = SourceJournal(tmp_path / "original.sqlite")
    journal.close()
    os.link(tmp_path / "original.sqlite", tmp_path / "aliased.sqlite")
    with pytest.raises(ValueError, match="hardlink"):
        SourceJournal(tmp_path / "aliased.sqlite")


def test_expired_fence_rechecked_before_actual_book_mutation(tmp_path):
    from cocomelon.research.volatility_service import VolatilityService

    obj = trial(tmp_path)
    opened(obj)
    clock = [T + 1000]
    service = VolatilityService(obj, clock=lambda: clock[0], fence=lambda now: now < T + 1400)
    service.on_mark(mark(T + 1000, "97"))
    before = obj.candidate.store.table_counts()
    clock[0] = T + 1600  # Expired while a queued book was waiting.
    with pytest.raises(RuntimeError, match="fence"):
        service.on_book(quote(clock[0], bid="96.99", ask="97.01"), spec())
    assert obj.candidate.store.table_counts() == before
    assert not obj.entries_authorized
    obj.close()


@pytest.mark.parametrize("delay", [0, 1])
def test_daily_batch_uses_genuine_call_clock_exact_or_late(tmp_path, delay):
    from test_volatility_budget import window_at

    from cocomelon.research.volatility_service import VolatilityService

    obj = trial(tmp_path, authorized=False)
    w = window_at(T)

    class Source:
        def daily_windows(self, *args, **kwargs):
            return (w,)

        def instruments(self):
            return {spec().market: spec()}

        snapshots = {}
        books = {spec().market: w.book}

    service = VolatilityService(obj, clock=lambda: T + delay)
    service.evaluate_batch(Source(), epoch_ms=T)
    assert obj.snapshot()["last_decision_ms"] == T
    assert bool(obj.snapshot()["cooldowns"]) == (delay == 0)
    obj.close()


def test_new_preparation_rejects_past_eligibility_before_touching_resources(tmp_path, monkeypatch):
    import cocomelon.research.volatility_service as module

    monkeypatch.setattr(module, "wall_ms", lambda: T + 1000)
    config = {"activation": admission(T + 1000), "root": str(tmp_path / "must-not-exist")}
    with pytest.raises(ValueError, match="future six-hour"):
        module.prepare(config)
    assert not (tmp_path / "must-not-exist").exists()


def test_slow_genesis_cannot_release_a_shorter_prospective_boundary(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import cocomelon.research.volatility_service as module
    from cocomelon.research.volatility_budget import PROTOCOL_SHA256

    clock = [T - 7 * 3_600_000]
    receipt = admission(clock[0])
    receipt["release_ms"] = clock[0] - 1000
    receipt["review_expires_ms"] = T + 86_400_000
    monkeypatch.setattr(module, "wall_ms", lambda: clock[0])
    monkeypatch.setattr(module, "verify_deployed_code", lambda *args: None)
    monkeypatch.setattr(module, "verify_egress", lambda *args: None)

    class Custody:
        def __init__(self, *args, **kwargs):
            pass

        def latest(self):
            return None

        def initialize(self, files, **kwargs):
            assert "activation.json" in files
            clock[0] = T - 5 * 3_600_000
            return SimpleNamespace(commit="a" * 40)

    monkeypatch.setattr(module, "GitCustody", Custody)
    root = tmp_path / "preserved-originals"
    config = {
        "activation": receipt,
        "root": str(root),
        "code_root": str(tmp_path),
        "identity": {
            "protocol_sha256": PROTOCOL_SHA256,
            "candidate_id": "synthetic-candidate",
            "control_id": "synthetic-control",
            "first_entry_ms": T,
        },
        "custody_remote": "https://github.com/Dtwosam/Cocomelon.git",
        "custody_cache": str(tmp_path / "cache"),
        "custody_branch": "codex/volatility-synthetic-custody",
    }
    with pytest.raises(ValueError, match="acknowledgement"):
        module.prepare(config)
    assert (root / "candidate.sqlite").is_file()
    assert not (root / "activation.json").exists()
    assert not (root / "prepared-config.json").exists()


def test_partial_exit_interruption_retains_original_position_loss_and_retry(tmp_path):
    from cocomelon.research.volatility_service import VolatilityService

    obj = trial(tmp_path)
    position = opened(obj)
    clock = [T + 1000]
    service = VolatilityService(obj, clock=lambda: clock[0])
    service.on_mark(mark(clock[0], "97"))
    for delta in (1300, 1600):
        clock[0] = T + delta
        service.on_book(quote(clock[0], bid="96.99", ask="97.01", size="0.5"), spec())
    remaining = obj.candidate.account.positions[0].quantity
    assert 0 < remaining < position.quantity
    partial_cash = obj.candidate.account.cash
    obj.close()
    obj = trial(tmp_path, authorized=False)
    clock[0] = T + 2000
    service = VolatilityService(obj, clock=lambda: clock[0], unclean_recovery=True)
    assert obj.candidate.account.cash == partial_cash
    assert obj.candidate.account.positions[0].quantity == remaining
    service.on_mark(mark(clock[0], "97"))
    for delta in (2300, 2600, 2900):
        clock[0] = T + delta
        service.on_book(quote(clock[0], bid="96.99", ask="97.01"), spec())
    assert not obj.candidate.account.positions
    assert obj.candidate.account.cash < 10000
    assert obj.snapshot()["permanently_disabled"]
    assert obj.control.account.cash == 10000
    obj.close()


def test_hourly_rate_is_requested_and_reconciled_after_actual_position_close(tmp_path):
    from types import SimpleNamespace

    from cocomelon.domain.market import FundingRate
    from cocomelon.execution.funding import funding_cash_delta
    from cocomelon.research.volatility_service import VolatilityService, funding_requests

    obj = trial(tmp_path)
    position = opened(obj)
    hour = (T // 3_600_000 + 1) * 3_600_000
    clock = [hour - 1]
    service = VolatilityService(obj, clock=lambda: clock[0])
    service.on_mark(mark(clock[0]))
    clock[0] = hour
    service.tick()
    assert funding_requests(obj) == {position.market: hour}
    clock[0] = hour + 100
    service.on_mark(mark(clock[0], "97"))
    for delta in (300, 600):
        clock[0] = hour + delta
        service.on_book(quote(clock[0], bid="96.99", ask="97.01"), spec())
    assert not obj.candidate.account.positions
    assert funding_requests(obj) == {position.market: hour}
    before = obj.candidate.account.cash
    clock[0] = hour + 5000
    rate = FundingRate(
        position.market, hour, Decimal(".0001"), Decimal(0), "hyperliquid-mainnet-info", clock[0], 1
    )
    source = SimpleNamespace(funding_rates={(position.market, hour): rate})
    service.funding(source)
    expected = funding_cash_delta(position.quantity, Decimal(100), rate.funding_rate)
    assert obj.candidate.account.cash == before + expected
    service.funding(source)
    assert obj.candidate.account.cash == before + expected
    assert not funding_requests(obj)
    assert not obj.snapshot()["funding_unknown"]
    assert obj.control.account.cash == 10000
    obj.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("public_ip", "192.168.0.5"),
        ("other_rest_peak_weight", 601),
        ("other_ws_peak_connections", True),
        ("other_ws_peak_subscriptions", 985),
    ],
)
def test_resource_validation_does_not_allow_private_ip_or_missing_reserve(field, value):
    from cocomelon.research.volatility_service import validate_admission

    receipt = admission(T + 1000)
    receipt["network"][field] = value
    with pytest.raises(ValueError, match="resource"):
        validate_admission(receipt, now_ms=T + 1000)


def test_each_funding_mutation_rechecks_owner_fence_after_prior_account_write(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from cocomelon.domain.market import FundingRate
    from cocomelon.research.volatility_service import VolatilityService

    obj = trial(tmp_path)
    position = opened(obj)
    hour = (T // 3_600_000 + 1) * 3_600_000
    clock = [hour - 1]
    expires = hour + 3_600_000 + 1500
    service = VolatilityService(obj, clock=lambda: clock[0], fence=lambda now: now < expires)
    for boundary in (hour, hour + 3_600_000):
        clock[0] = boundary - 1
        service.on_mark(mark(clock[0]))
        clock[0] = boundary
        service.tick()
    clock[0] = hour + 3_600_000 + 1000
    source = SimpleNamespace(
        funding_rates={
            (position.market, boundary): FundingRate(
                position.market,
                boundary,
                Decimal(".0001"),
                Decimal(0),
                "hyperliquid-mainnet-info",
                clock[0],
                1,
            )
            for boundary in (hour, hour + 3_600_000)
        }
    )
    applied = []
    original = obj.apply_funding

    def slow_account_write(accrual, *, now_ms):
        original(accrual, now_ms=now_ms)
        applied.append(accrual.boundary_ms)
        clock[0] = expires + 1

    monkeypatch.setattr(obj, "apply_funding", slow_account_write)
    with pytest.raises(RuntimeError, match="fence"):
        service.funding(source)
    assert applied == [hour]
    assert obj.snapshot()["funding_unknown"]
    assert not obj.entries_authorized
    obj.close()
