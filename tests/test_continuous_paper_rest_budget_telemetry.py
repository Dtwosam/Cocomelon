from __future__ import annotations

from inspect import signature
from pathlib import Path

from cocomelon.config import Settings
from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.hyperliquid.rate_limit import RollingRateBudget
from cocomelon import continuous_paper


def test_all_operational_paper_heartbeats_report_original_reader_budget() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    assert source.count("local_rest_budget=reader.rest_budget_snapshot()") == 4
    assert source.count("_emit_operational_live_status(") == 5
    assert '"local_public_rest_budget": local_rest_budget' in source
    assert "local_rest_budget" in signature(
        continuous_paper._operational_live_status_payload
    ).parameters
    assert "local_rest_budget" in signature(
        continuous_paper._emit_operational_live_status
    ).parameters


def test_authenticated_budget_payload_remains_local_only_and_nonexecuting() -> None:
    requests: list[str] = []
    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        del url, timeout
        requests.append(str(payload["type"]))
        return {}

    budget = RollingRateBudget(limit=1000)
    reader = InfoClient(Settings(), budget=budget, transport=transport)
    assert reader.meta_and_asset_ctxs() == {}
    allowed, _ = reader.try_shadow_l2_book(MarketId(dex="", coin="BLUR"))
    assert allowed is True
    snapshot = reader.rest_budget_snapshot()
    assert snapshot is not None
    assert snapshot["total_rolling_weight"] == 22
    assert snapshot["required_rolling_weight"] == 20
    assert snapshot["shadow_rolling_weight"] == 2
    assert snapshot["shadow_priority_reserve_weight"] == 300
    assert snapshot["external_process_ip_weight_verified"] is False
    assert snapshot["source_or_execution_authority"] is False
    assert requests == ["metaAndAssetCtxs", "l2Book"]


def test_reading_rest_quota_never_sends_http_or_consumes_rate_weight() -> None:
    requests = 0
    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        nonlocal requests
        del url, payload, timeout
        requests += 1
        return {}

    reader = InfoClient(Settings(), transport=transport)
    initial = reader.rest_budget_snapshot()
    followup = reader.rest_budget_snapshot()
    assert initial == followup
    assert initial is not None
    assert initial["total_rolling_weight"] == 0
    assert initial["required_rolling_weight"] == 0
    assert initial["shadow_rolling_weight"] == 0
    assert initial["source_or_execution_authority"] is False
    assert requests == 0
