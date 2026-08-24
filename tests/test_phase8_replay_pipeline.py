from decimal import Decimal

from cocomelon.execution.accounting import empty_account
from cocomelon.journal.observations import observation_from_account_state


def test_replay_account_state_observation_preserves_deterministic_state_id() -> None:
    account = empty_account(Decimal("10000"), 30_000)

    first = observation_from_account_state(account, replay_run_id=None)
    second = observation_from_account_state(account, replay_run_id=None)

    assert first.kind.value == "account_state"
    assert first.timestamp_ms == account.updated_at_ms
    assert first.account_state_id == account.state_id
    assert first == second
