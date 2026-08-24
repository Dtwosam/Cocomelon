from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.evaluation import mainnet_aggregate


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _metadata_source(
    root: Path,
    *,
    duplicate_count: int,
    anomaly_count: int,
) -> None:
    root.mkdir()
    (root / "journal.sqlite3").write_bytes(b"journal")
    (root / "facts.sqlite3").write_bytes(b"facts")
    _write_json(
        root / "cohort-summary.json",
        {
            "checked_out_code_revision": "a" * 40,
            "closed_trade_count": 0,
            "data_complete": True,
            "dataset_trade_count": 0,
            "economic_claim": "none",
            "evidence_kind": "genuine_public_hyperliquid_mainnet",
            "recorded_gap_count": 0,
            "recording_session_id": "session-a",
            "replay_run_id": "run-a",
        },
    )
    _write_json(
        root / "record.json",
        {
            "anomaly_count": anomaly_count,
            "duplicate_count": duplicate_count,
            "gap_count": 0,
            "live_orders": False,
            "network_access": True,
            "session_id": "session-a",
        },
    )
    _write_json(
        root / "replay.json",
        {
            "closed_trade_ids": [],
            "data_complete": True,
            "live_orders": False,
            "network_access": False,
            "run_id": "run-a",
        },
    )


@pytest.mark.parametrize(
    ("duplicate_count", "anomaly_count"),
    ((1, 0), (0, 1)),
)
def test_attestation_rejects_duplicate_or_anomalous_capture(
    tmp_path: Path,
    duplicate_count: int,
    anomaly_count: int,
) -> None:
    source = tmp_path / "source"
    _metadata_source(
        source,
        duplicate_count=duplicate_count,
        anomaly_count=anomaly_count,
    )

    with pytest.raises(
        mainnet_aggregate.EvidenceAggregationError,
        match="duplicate|anomal",
    ):
        mainnet_aggregate._load_attestation(source)
