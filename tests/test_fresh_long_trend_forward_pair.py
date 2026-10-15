"""New frozen LONG-only challenger cannot reuse losing prior paired accounts."""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayManifest, ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import EpochMarketEvaluation
from cocomelon.research import fresh_long_trend_forward_pair as study
from cocomelon.research.fresh_long_trend_account_audit import (
    V3AccountAuditError,
    audit_fresh_v3_paired_accounts,
)
from cocomelon.research.loss_context_portfolio_shadow_entry import (
    CONTEXT_BLOCK_REASON,
    PRE_BOUNDARY_REASON,
    LossContextPortfolioShadowEntryFilter,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    both_side_trend_matched_shadow_v2_freeze,
)

MARKET = MarketId("", "TEST")


def _evaluation(
    *, direction: Direction, lead: str,
) -> EpochMarketEvaluation:
    ts = study.FORWARD_NOT_BEFORE_MS + 60_000
    feature = FeatureSnapshot(
        market=MARKET,
        as_of_ms=ts,
        source_received_at_ms=ts - 1_000,
        schema_version=1,
        day_return=Decimal("-0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("500000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=Decimal("-0.001"),
        return_15m=Decimal("-0.01"),
        return_1h=Decimal("-0.02"),
        return_4h=None,
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("-0.1"),
        book_age_ms=10,
        trend_regime=TrendRegime.DOWN,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("original-received-research-fixture",),
    )
    decision = StrategyDecision(
        market=MARKET,
        direction=direction,
        score=Decimal("80"),
        timestamp_ms=ts,
        feature_snapshot_id=feature.snapshot_id,
        lead_strategy=lead,
        invalidation_price=Decimal("95"),
        signal_ids=("fixed-study-test",),
        reason_codes=("fixed-study-test",),
    )
    return EpochMarketEvaluation(
        feature=feature,
        decision=decision,
        eligibility=EligibilityDecision(
            market=MARKET, rankable=True, deep_ready=True, reasons=(),
        ),
    )


def _manifest(
    *, start_offset: int = -1, end_offset: int = 1_000,
) -> ReplayManifest:
    source_config = BaselineReplayConfig(execution=PaperExecutionConfig())
    return cast(ReplayManifest, SimpleNamespace(
        start_ms=study.FORWARD_NOT_BEFORE_MS + start_offset,
        end_ms=study.FORWARD_NOT_BEFORE_MS + end_offset,
        manifest_id="0123456789abcdef01234567",
        config_digest=source_config.config_digest,
        execution_config_version=source_config.execution.config_version,
        fee_schedule_id=source_config.execution.fee_schedule_id,
        feature_version=source_config.feature_version,
        strategy_version=source_config.strategy_version,
        risk_version=source_config.risk_version,
        replay_engine_version=source_config.replay_engine_version,
        gap_refs=(),
    ))


class _Source:
    loaded: tuple[ReplayRecord, ...] = ()
    last_forward: int | None = None
    deny = False

    def __init__(
        self, *, root: Path, manifest: ReplayManifest, expected_manifest_id: str,
    ) -> None:
        if expected_manifest_id != manifest.manifest_id:
            raise ValueError("manifest identity mismatch")
        self.root = root

    def verified_records(
        self, *, forward_not_before_ms: int,
    ) -> tuple[ReplayRecord, ...]:
        _Source.last_forward = forward_not_before_ms
        if _Source.deny:
            raise ValueError("source manifest incomplete or tampered")
        return _Source.loaded

    def verification_receipt(
        self, records: tuple[ReplayRecord, ...],
    ) -> dict[str, object]:
        assert records == _Source.loaded
        return {"pin_origin_independently_authenticated": False}


def _original_snapshot(at_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at_ms,
        source="test-captured-mainnet-paper-record",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=at_ms - 1,
        event_key=f"original-{at_ms}",
        event_kind="market_snapshot",
        payload_json=json.dumps({
            "meta": {
                "wire_name": MARKET.wire_name,
                "sz_decimals": 4,
                "max_leverage": 20,
                "margin_table_id": 1,
                "only_isolated": False,
                "is_delisted": False,
                "margin_mode": None,
            },
            "context": {
                "mark_px": "100",
                "mid_px": "100",
                "oracle_px": "100",
                "funding": "0",
                "open_interest": "1000000",
                "day_ntl_vlm": "500000000",
                "premium": "0",
                "prev_day_px": "101",
            },
        }, sort_keys=True),
    )


def _original_book(at_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at_ms,
        source="test-captured-mainnet-paper-l2",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=at_ms - 1,
        event_key=f"l2:{at_ms}",
        event_kind="l2_book",
        payload_json=json.dumps({
            "bids": [{"px": "99.9", "sz": "1000", "n": 1}],
            "asks": [{"px": "100.1", "sz": "1000", "n": 1}],
        }, sort_keys=True),
    )


def _original_source_rows() -> tuple[ReplayRecord, ...]:
    return (
        _original_snapshot(study.FORWARD_NOT_BEFORE_MS + 10),
        _original_book(study.FORWARD_NOT_BEFORE_MS + 11),
    )


def test_new_long_only_candidate_distinct_and_embargo_immutable() -> None:
    freeze = study.fresh_long_trend_freeze()
    previous = both_side_trend_matched_shadow_v2_freeze()
    assert freeze.candidate_id != previous.candidate_id
    assert freeze.loss_context_candidate_id != previous.loss_context_candidate_id
    assert freeze.source_composition_digest != previous.source_composition_digest
    assert freeze.dimensions == ("lead_strategy", "direction")
    assert freeze.values == ("trend", "long")
    assert freeze.source_paper_run_id == 38737278661
    assert freeze.source_paper_run_attempt == 1
    assert freeze.source_paper_head_sha == (
        "bcfd0eab058cda4ba9270dcd449a8cdf67b9199c"
    )
    assert freeze.source_max_timestamp_ms == 1_792_074_581_000
    assert freeze.source_max_timestamp_ms < freeze.frozen_at_ms
    assert freeze.frozen_at_ms == 1_792_108_800_000
    assert freeze.prospective_not_before_ms == study.FORWARD_NOT_BEFORE_MS
    assert freeze.prospective_not_before_ms - freeze.frozen_at_ms == 6 * 3_600_000
    assert study.PRECOMMITMENT["minimum_forward_ms"] == 72 * 3_600_000
    assert study.PRECOMMITMENT["previous_v1_v2_accounts_and_signed_records_admissible"] is False
    assert freeze.paper_only and freeze.research_only
    assert not freeze.promotion_authority and not freeze.execution_authority


def test_only_original_long_trend_entries_are_blocked() -> None:
    freeze = study.fresh_long_trend_freeze()
    baseline = LossContextPortfolioShadowEntryFilter(
        freeze, block_matching_context=False,
    )
    candidate = LossContextPortfolioShadowEntryFilter(
        freeze, block_matching_context=True,
    )
    open_at = study.FORWARD_NOT_BEFORE_MS + 60_001
    long_trend = _evaluation(direction=Direction.LONG, lead="trend")
    assert candidate.block_reason(
        long_trend, attempt_timestamp_ms=open_at - 100_000,
    ) == PRE_BOUNDARY_REASON
    assert baseline.block_reason(
        long_trend, attempt_timestamp_ms=open_at,
    ) is None
    assert candidate.block_reason(
        long_trend, attempt_timestamp_ms=open_at,
    ) == CONTEXT_BLOCK_REASON
    for direction, strategy in (
        (Direction.SHORT, "trend"),
        (Direction.LONG, "breakout"),
        (Direction.SHORT, "breakout"),
        (Direction.LONG, "mean_reversion"),
    ):
        assert candidate.block_reason(
            _evaluation(direction=direction, lead=strategy),
            attempt_timestamp_ms=open_at,
        ) is None
    assert candidate.matching_context_blocked == 1
    assert candidate.matching_context_blocked_by_market == {"TEST": 1}
    assert candidate.admitted_after_boundary == 4


def test_fresh_source_replay_constructs_new_independent_account_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "new-long-study"
    _Source.deny = False
    _Source.loaded = _original_source_rows()
    monkeypatch.setattr(study, "PinnedShortRankReplaySource", _Source)
    # Separate test fixtures exercise the real sealed-order restoration.
    monkeypatch.setattr(
        study, "restore_original_v3_received_order",
        lambda _root, _manifest, rows: rows,
    )
    response = study.run_digest_pinned_long_trend_matched_paper(
        source_root=tmp_path / "untrusted-replay-placeholder",
        manifest=_manifest(),
        expected_manifest_id="0123456789abcdef01234567",
        config=BaselineReplayConfig(execution=PaperExecutionConfig()),
        selected_markets=(MARKET,),
        account_root=root,
    )
    assert _Source.last_forward == study.FORWARD_NOT_BEFORE_MS
    assert response["source_records_replayed"] == 2
    source_receipt = response["locally_checked_market_gap_and_l2_receipt"]
    assert isinstance(source_receipt, dict)
    assert source_receipt["recorded_source_gap_count"] == 0
    assert source_receipt["selected_market_post_embargo_l2_counts"] == {"TEST": 1}
    assert source_receipt["common_l2_forward_elapsed_ms"] == 11
    assert source_receipt["original_exchange_feed_independently_authenticated"] is False
    assert response["minimum_forward_elapsed"] is False
    assert response["record_observed_forward_elapsed_ms"] == 11
    assert response["last_original_forward_record_at_ms"] == (
        study.FORWARD_NOT_BEFORE_MS + 11
    )
    assert response["after_cost_72h_profitability_verified"] is False
    assert response["full_account_study_admissible"] is False
    receipt = response["locally_reconciled_original_paired_sqlite_accounts"]
    assert isinstance(receipt, dict)
    assert receipt["local_checkpoint_self_digest_and_exact_accounts_reconciled"] is True
    assert receipt["baseline"]["starting_cash_usd"] == "10000"
    assert receipt["candidate"]["starting_cash_usd"] == "10000"
    assert receipt["baseline"]["fill_fees_usd"] == "0"
    assert receipt["candidate"]["funding_cash_usd"] == "0"
    assert receipt["candidate_minus_baseline_marked_after_cost_usd"] == "0"
    assert receipt["72h_forward_profitability_certified"] is False
    assert receipt["promotion_authority"] is False
    assert response["promotion_authority"] is False
    assert response["execution_authority"] is False
    summary = response["paired_account_original_runtime_summary"]
    assert isinstance(summary, dict)
    baseline = summary["baseline"]
    candidate = summary["candidate"]
    assert isinstance(baseline, dict) and isinstance(candidate, dict)
    assert baseline["equity"] == candidate["equity"]
    assert baseline["closed_trade_count"] == candidate["closed_trade_count"]
    assert summary["candidate_difference_is_opening_admission_only"] is True
    assert (root / "baseline-execution.sqlite3").is_file()
    assert (root / "candidate-execution.sqlite3").is_file()
    with pytest.raises(study.LongTrendForwardTrialError, match="empty root"):
        study.run_digest_pinned_long_trend_matched_paper(
            source_root=tmp_path,
            manifest=_manifest(),
            expected_manifest_id="0123456789abcdef01234567",
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MARKET,),
            account_root=root,
        )


def _completed_v3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> (
    tuple[Path, dict[str, object], dict[str, object]]
):
    _Source.deny = False
    _Source.loaded = _original_source_rows()
    monkeypatch.setattr(study, "PinnedShortRankReplaySource", _Source)
    # Separate test fixtures exercise the real sealed-order restoration.
    monkeypatch.setattr(
        study, "restore_original_v3_received_order",
        lambda _root, _manifest, rows: rows,
    )
    root = tmp_path / "v3-cash-audit"
    report = study.run_digest_pinned_long_trend_matched_paper(
        source_root=tmp_path / "original-untrusted-source",
        manifest=_manifest(),
        expected_manifest_id="0123456789abcdef01234567",
        config=BaselineReplayConfig(execution=PaperExecutionConfig()),
        selected_markets=(MARKET,),
        account_root=root,
    )
    summary = report["paired_account_original_runtime_summary"]
    assert isinstance(summary, dict)
    checkpoint = json.loads((root / "paired-shadow-state.json").read_text())
    return root, checkpoint, summary


@pytest.mark.parametrize("mutate", [
    "account_id", "account_equity", "fill_fee", "funding_cash",
    "checkpoint", "summary_relative",
])
def test_independent_v3_audit_refuses_torn_or_invented_cash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate: str,
) -> None:
    root, checkpoint, summary = _completed_v3(tmp_path, monkeypatch)
    original_other = (root / "baseline-execution.sqlite3").read_bytes()
    candidate_db = root / "candidate-execution.sqlite3"

    if mutate in ("account_id", "account_equity", "fill_fee", "funding_cash"):
        with sqlite3.connect(candidate_db) as conn:
            if mutate == "account_id":
                conn.execute(
                    "UPDATE paper_account_state SET state_id=? WHERE singleton_id=1",
                    ("f" * 64,),
                )
            elif mutate == "account_equity":
                row = conn.execute(
                    "SELECT payload_json FROM paper_account_state "
                    "WHERE singleton_id=1"
                ).fetchone()
                assert row is not None
                payload = json.loads(row[0])
                payload["equity"] = "10099"
                conn.execute(
                    "UPDATE paper_account_state SET payload_json=? WHERE singleton_id=1",
                    (json.dumps(payload),),
                )
            elif mutate == "fill_fee":
                conn.execute(
                    "INSERT INTO paper_fills(fill_id, attempt_id, plan_id, payload_json) "
                    "VALUES (?,?,?,?)",
                    ("forged", "forged", "forged", '{"taker_fee":"1.50"}'),
                )
            else:
                conn.execute(
                    "INSERT INTO paper_funding_events("
                    "accrual_id,market,boundary_ms,position_id,payload_json) "
                    "VALUES (?,?,?,?,?)",
                    ("forged", "TEST", study.FORWARD_NOT_BEFORE_MS, "fake",
                     '{"cash_delta":"7"}'),
                )
    elif mutate == "checkpoint":
        checkpoint["record_count"] = 5
    else:
        summary["candidate_minus_baseline_total_account_pnl"] = "999"

    with pytest.raises(V3AccountAuditError):
        audit_fresh_v3_paired_accounts(
            root, checkpoint=checkpoint, summary=summary,
            starting_cash=Decimal("10000"),
            expected_candidate_id=study.fresh_long_trend_freeze().candidate_id,
            expected_record_count=2,
        )
    assert (root / "baseline-execution.sqlite3").read_bytes() == original_other


def test_independent_account_audit_refuses_nonempty_prior_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, checkpoint, summary = _completed_v3(tmp_path, monkeypatch)
    with pytest.raises(V3AccountAuditError):
        audit_fresh_v3_paired_accounts(
            root, checkpoint=checkpoint, summary=summary,
            starting_cash=Decimal("0"),
            expected_candidate_id=study.fresh_long_trend_freeze().candidate_id,
            expected_record_count=2,
        )


def test_manifest_calendar_end_cannot_fabricate_72h_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Source.deny = False
    _Source.loaded = _original_source_rows()
    monkeypatch.setattr(study, "PinnedShortRankReplaySource", _Source)
    # Separate test fixtures exercise the real sealed-order restoration.
    monkeypatch.setattr(
        study, "restore_original_v3_received_order",
        lambda _root, _manifest, rows: rows,
    )
    report = study.run_digest_pinned_long_trend_matched_paper(
        source_root=tmp_path / "original-source-placeholder",
        manifest=_manifest(end_offset=study.MINIMUM_FORWARD_MS + 20_000),
        expected_manifest_id="0123456789abcdef01234567",
        config=BaselineReplayConfig(execution=PaperExecutionConfig()),
        selected_markets=(MARKET,),
        account_root=tmp_path / "fresh-source-age",
    )
    assert report["record_observed_forward_elapsed_ms"] == 11
    assert report["minimum_forward_elapsed"] is False
    assert report["after_cost_72h_profitability_verified"] is False


@pytest.mark.parametrize("rootname", [
    "both-side-trend-paired-shadow-v1",
    "both-side-trend-paired-shadow-v2",
    "loss-context-paired-v5",
])
def test_prior_trial_roots_are_forbidden_before_account_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rootname: str,
) -> None:
    _Source.deny = False
    _Source.loaded = _original_source_rows()
    monkeypatch.setattr(study, "PinnedShortRankReplaySource", _Source)
    # Separate test fixtures exercise the real sealed-order restoration.
    monkeypatch.setattr(
        study, "restore_original_v3_received_order",
        lambda _root, _manifest, rows: rows,
    )
    root = tmp_path / rootname
    with pytest.raises(study.LongTrendForwardTrialError, match="prior shadow root"):
        study.run_digest_pinned_long_trend_matched_paper(
            source_root=tmp_path,
            manifest=_manifest(),
            expected_manifest_id="0123456789abcdef01234567",
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MARKET,),
            account_root=root,
        )
    assert not root.exists()


def test_invalid_source_fails_before_creating_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(study, "PinnedShortRankReplaySource", _Source)
    # Separate test fixtures exercise the real sealed-order restoration.
    monkeypatch.setattr(
        study, "restore_original_v3_received_order",
        lambda _root, _manifest, rows: rows,
    )
    _Source.deny = True
    root = tmp_path / "fresh-only"
    try:
        with pytest.raises(ValueError, match="source manifest incomplete"):
            study.run_digest_pinned_long_trend_matched_paper(
                source_root=tmp_path,
                manifest=_manifest(),
                expected_manifest_id="0123456789abcdef01234567",
                config=BaselineReplayConfig(execution=PaperExecutionConfig()),
                selected_markets=(MARKET,),
                account_root=root,
            )
        assert not root.exists()
    finally:
        _Source.deny = False



@pytest.mark.parametrize("change", [
    "taker_fee_rate", "slippage", "risk_budget", "fee_schedule_id",
])
def test_replay_cannot_use_alternate_fee_or_risk_settings_from_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    from dataclasses import replace

    monkeypatch.setattr(study, "PinnedShortRankReplaySource", _Source)
    # Separate test fixtures exercise the real sealed-order restoration.
    monkeypatch.setattr(
        study, "restore_original_v3_received_order",
        lambda _root, _manifest, rows: rows,
    )
    _Source.deny = False
    _Source.last_forward = None
    normal = BaselineReplayConfig(execution=PaperExecutionConfig())
    if change == "taker_fee_rate":
        replay = replace(
            normal,
            execution=replace(
                normal.execution,
                taker_fee_rate=Decimal("0.00001"),
            ),
        )
    elif change == "slippage":
        replay = replace(
            normal,
            execution=replace(
                normal.execution,
                max_ioc_slippage_bps=Decimal("8"),
            ),
        )
    elif change == "risk_budget":
        replay = replace(
            normal, starting_cash=Decimal("11000"),
        )
    else:
        replay = replace(
            normal,
            execution=replace(
                normal.execution,
                fee_schedule_id="invented-cheaper-fee-schedule",
            ),
        )
    root = tmp_path / "never-authorized-paper-accounts"
    with pytest.raises(
        study.LongTrendForwardTrialError,
        match="original PAPER risk/fee/strategy configuration differs",
    ):
        study.run_digest_pinned_long_trend_matched_paper(
            source_root=tmp_path / "original-source",
            manifest=_manifest(),
            expected_manifest_id="0123456789abcdef01234567",
            config=replay,
            selected_markets=(MARKET,),
            account_root=root,
        )
    assert _Source.last_forward is None
    assert not root.exists()


def test_manifest_left_censored_starts_late_without_account_side_effects(
    tmp_path: Path,
) -> None:
    root = tmp_path / "never-created"
    with pytest.raises(study.LongTrendForwardTrialError, match="left-censored"):
        study.run_digest_pinned_long_trend_matched_paper(
            source_root=tmp_path,
            manifest=_manifest(start_offset=1),
            expected_manifest_id="0123456789abcdef01234567",
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MARKET,),
            account_root=root,
        )
    assert not root.exists()
