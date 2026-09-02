import pathlib

SYNC = pathlib.Path(".github/workflows/research-v4-registry-sync.yml")


def _inventory_block() -> str:
    source = SYNC.read_text(encoding="utf-8")
    return source.split("- name: Inventory actual V4 acquisition runs and capture evidence", 1)[1].split(
        "- name: Apply non-economic V4 acquisition authority inventory",
        1,
    )[0]


def test_capture_conclusion_is_not_bound_to_one_v4_job_layout() -> None:
    block = _inventory_block()

    assert 'select(.name == "Record thesis-expiry genuine public mainnet evidence")' in block
    assert 'select(.name == "acquire-evidence")' not in block


def test_v4_sync_falls_back_to_long_retention_evidence_for_same_attempt() -> None:
    block = _inventory_block()
    stage_name = 'v4-acquisition-stage-${RUN_ID}-attempt-${ATTEMPT}'
    retained_name = 'scheduled-genuine-mainnet-evidence-v4-${RUN_ID}-attempt-${ATTEMPT}'

    assert stage_name in block
    assert retained_name in block
    assert block.index(stage_name) < block.index(retained_name)
