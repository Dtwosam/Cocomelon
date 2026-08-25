from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-campaign-scheduled.yml")
PINNED_CODE = "7cf19ab81fa609fed4171ea8ed1f06d85f91e793"
STATE_BRANCH = "phase9-v2-protocol-state"
STATE_FILE = "phase9-v2-final.json"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_scheduled_campaign_v2_is_fixed_revision_mainnet_paper_only() -> None:
    text = _workflow_text()

    assert "schedule:" in text
    assert "37 1,7,13,19 * * *" in text
    assert "workflow_dispatch:" in text
    assert "COCOMELON_EXECUTION_MODE: paper" in text
    assert "COCOMELON_API_URL: https://api.hyperliquid.xyz" in text
    assert "COCOMELON_WS_URL: wss://api.hyperliquid.xyz/ws" in text
    assert f"COHORT_CODE_REVISION: {PINNED_CODE}" in text
    assert f"ref: {PINNED_CODE}" in text
    assert "GAP_WATCH_REVISION" not in text
    assert "runner-control" not in text
    assert "testnet" not in text.lower()
    assert "COCOMELON_EXECUTION_MODE: live" not in text


def test_scheduled_campaign_v2_uses_redundant_transport_health_contract() -> None:
    text = _workflow_text()

    assert "group: genuine-mainnet-evidence-v2-7cf19ab8" in text
    assert "cancel-in-progress: false" in text
    assert "--seconds 2700" in text
    assert "--deep-limit 5" in text
    assert "for ATTEMPT in 1 2" in text
    assert "python -m cocomelon.ops.gap_watch" in text
    assert "record-transport.json" in text
    assert "normalize_redundant_record_payload" in text
    assert 'record["gap_count"] == 0' in text
    assert 'record["duplicate_count"] == 0' in text
    assert 'record["anomaly_count"] == 0' in text
    assert 'record["redundant_ws_lane_count"] == 2' in text
    assert 'record["transport_health_semantics"]' in text
    assert 'record["transport_duplicate_count"]' in text
    assert 'record["transport_anomaly_count"]' in text


def test_scheduled_campaign_v2_requires_complete_flat_replay_for_economics() -> None:
    text = _workflow_text()

    assert 'replay["data_complete"] is True' in text
    assert 'dataset["data_complete"] is True' in text
    assert 'replay["opened_positions"] == replay["closed_positions"]' in text
    assert '"economic_eligible"' in text
    assert '"economic_ineligibility_reasons"' in text
    assert '"economic_claim": "none"' in text
    assert 'assert "edge" not in replay' in text
    assert 'assert "profitable" not in replay' in text
    assert "retention-days: 90" in text


def test_scheduled_campaign_stops_after_durable_phase9_finalization() -> None:
    text = _workflow_text()

    assert STATE_BRANCH in text
    assert STATE_FILE in text
    assert "Check durable Phase 9 final state" in text
    assert "final_exists" in text
    guard = "steps.phase9_final.outputs.final_exists != 'true'"
    assert text.count(guard) >= 5
    check = text.index("Check durable Phase 9 final state")
    checkout = text.index("Checkout pinned V2 evidence revision")
    record = text.index("Record clean genuine public mainnet evidence")
    assert check < checkout < record


def test_scheduled_campaign_fails_closed_if_durable_state_branch_disappears() -> None:
    text = _workflow_text()

    branch_check = '"repos/$GITHUB_REPOSITORY/branches/$PHASE9_STATE_BRANCH"'
    state_endpoint = (
        'STATE_ENDPOINT="repos/$GITHUB_REPOSITORY/contents/'
        '$PHASE9_STATE_FILE?ref=$PHASE9_STATE_BRANCH"'
    )
    assert branch_check in text
    assert state_endpoint in text
    assert text.index(branch_check) < text.index(state_endpoint)


def test_scheduled_campaign_fails_closed_if_durable_final_was_deleted() -> None:
    text = _workflow_text()

    history_endpoint = (
        'STATE_HISTORY_ENDPOINT="repos/$GITHUB_REPOSITORY/commits?sha='
        '$PHASE9_STATE_BRANCH&path=$PHASE9_STATE_FILE&per_page=1"'
    )
    assert history_endpoint in text
    assert "phase9-state-history.json" in text
    assert "previously recorded but is now missing" in text
    check = text.index("Check durable Phase 9 final state")
    checkout = text.index("Checkout pinned V2 evidence revision")
    assert check < text.index(history_endpoint) < checkout
