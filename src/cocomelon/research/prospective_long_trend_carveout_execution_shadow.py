from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from typing import Final, cast

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.risk import RiskRequest
from cocomelon.evidence.openings import conservative_cost_estimate
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.planner import PlanningRejection, plan_opening_order
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    OpeningOpportunityExitBookEvidence,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ReplacementFundingBoundaryEvidence,
)
from cocomelon.research.prospective_capacity_reflow_exit_fill import (
    prospective_capacity_reflow_exit_fill_summary,
)
from cocomelon.research.prospective_capacity_reflow_realized_pnl import (
    prospective_capacity_reflow_realized_pnl_summary,
)
from cocomelon.research.prospective_full_stack_forward_markout import (
    LONG_TREND_CARVEOUT_CANDIDATE_ID,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    LEGACY_CONFIG_SOURCE_KIND,
    LEGACY_SOURCE_KIND,
    SOURCE_KIND,
    WEEKLY_DRAWDOWN_REASON,
    execution_config_payload,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    SCHEMA_VERSION as SOURCE_SCHEMA_VERSION,
)
from cocomelon.risk.engine import evaluate_risk

FORWARD_HORIZONS_MS: Final = (
    5 * 60 * 1_000,
    15 * 60 * 1_000,
    60 * 60 * 1_000,
)
MAX_MARK_LAG_MS: Final = 120_000
ZERO: Final = Decimal("0")


class ProspectiveLongTrendExecutionShadowError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _execution_config_from_payload(
    raw: object,
) -> PaperExecutionConfig:
    if not isinstance(raw, dict):
        raise ProspectiveLongTrendExecutionShadowError(
            "captured execution config must be an object"
        )

    def required_int(key: str) -> int:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProspectiveLongTrendExecutionShadowError(
                f"captured execution config {key} is invalid"
            )
        return value

    def required_string(key: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise ProspectiveLongTrendExecutionShadowError(
                f"captured execution config {key} is invalid"
            )
        return value

    raw_max_position_age_ms = raw.get("max_position_age_ms")
    max_position_age_ms: int | None
    if raw_max_position_age_ms is None:
        max_position_age_ms = None
    elif (
        isinstance(raw_max_position_age_ms, bool)
        or not isinstance(raw_max_position_age_ms, int)
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "captured execution config max_position_age_ms is invalid"
        )
    else:
        max_position_age_ms = raw_max_position_age_ms
    try:
        return PaperExecutionConfig(
            config_version=required_string("config_version"),
            latency_ms=required_int("latency_ms"),
            max_book_age_ms=required_int("max_book_age_ms"),
            max_asset_ctx_age_ms=required_int(
                "max_asset_ctx_age_ms"
            ),
            max_position_age_ms=max_position_age_ms,
            funding_reconciliation_grace_ms=required_int(
                "funding_reconciliation_grace_ms"
            ),
            max_ioc_slippage_bps=Decimal(
                required_string("max_ioc_slippage_bps")
            ),
            taker_fee_rate=Decimal(
                required_string("taker_fee_rate")
            ),
            fee_schedule_id=required_string("fee_schedule_id"),
            native_perp_min_notional=Decimal(
                required_string("native_perp_min_notional")
            ),
            paper_max_gross_leverage=Decimal(
                required_string("paper_max_gross_leverage")
            ),
        )
    except (ValueError, ArithmeticError) as exc:
        raise ProspectiveLongTrendExecutionShadowError(
            "captured execution config is invalid"
        ) from exc


def _validate_source(
    raw: object,
    *,
    legacy_config: PaperExecutionConfig | None,
) -> tuple[
    tuple[dict[str, object], ...],
    PaperExecutionConfig,
    str,
    int,
]:
    if not isinstance(raw, dict):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source must be an object"
        )
    schema_version = raw.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source schema is unsupported"
        )
    if schema_version in {SOURCE_SCHEMA_VERSION, 2}:
        expected_kind = (
            SOURCE_KIND
            if schema_version == SOURCE_SCHEMA_VERSION
            else LEGACY_CONFIG_SOURCE_KIND
        )
        if raw.get("kind") != expected_kind:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow source kind is unsupported"
            )
        config_payload = raw.get("execution_config")
        config_sha256 = raw.get("execution_config_sha256")
        if (
            not isinstance(config_sha256, str)
            or len(config_sha256) != 64
            or _sha256(config_payload) != config_sha256
        ):
            raise ProspectiveLongTrendExecutionShadowError(
                "captured execution config digest mismatch"
            )
        config = _execution_config_from_payload(config_payload)
        config_source = f"captured_source_v{schema_version}"
    elif schema_version == 1:
        if raw.get("kind") != LEGACY_SOURCE_KIND:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow source kind is unsupported"
            )
        if legacy_config is None:
            raise ProspectiveLongTrendExecutionShadowError(
                "legacy execution-shadow source requires fallback config"
            )
        config = legacy_config
        config_source = "legacy_evaluator_fallback_v1"
    else:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source schema is unsupported"
        )

    if raw.get("candidate_id") != LONG_TREND_CARVEOUT_CANDIDATE_ID:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow candidate drift"
        )
    if raw.get("baseline_risk_reason") != WEEKLY_DRAWDOWN_REASON:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow baseline risk reason drift"
        )
    for key, expected in (
        ("research_only", True),
        ("execution_authority", False),
        ("promotion_authority", False),
        ("changes_execution", False),
        ("changes_risk_limits", False),
        ("changes_candidate_readiness", False),
        ("durable_gate_required", True),
    ):
        if raw.get(key) is not expected:
            raise ProspectiveLongTrendExecutionShadowError(
                f"execution-shadow source authority drift: {key}"
            )

    source_sha256 = raw.get("source_sha256")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source digest is invalid"
        )
    digest_payload = {
        key: value
        for key, value in raw.items()
        if key != "source_sha256"
    }
    if _sha256(digest_payload) != source_sha256:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source digest mismatch"
        )

    opportunities = raw.get("opportunities")
    if not isinstance(opportunities, list):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow opportunities must be a list"
        )
    if raw.get("source_opportunity_count") != len(opportunities):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source opportunity count mismatch"
        )
    if raw.get("missing_opportunity_evidence") != 0:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source has missing opening evidence"
        )
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in opportunities:
        if not isinstance(item, dict):
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opportunity row must be an object"
            )
        opportunity_id = item.get("opportunity_id")
        if not isinstance(opportunity_id, str) or not opportunity_id:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opportunity id is invalid"
            )
        if opportunity_id in seen:
            raise ProspectiveLongTrendExecutionShadowError(
                "duplicate execution-shadow opportunity id"
            )
        seen.add(opportunity_id)
        rows.append(item)
    return tuple(rows), config, config_source, schema_version

def _lifecycle_evidence(
    raw: object,
    *,
    schema_version: int,
    opportunity_ids: frozenset[str],
) -> tuple[
    tuple[OpeningOpportunityExitBookEvidence, ...],
    tuple[ReplacementFundingBoundaryEvidence, ...],
]:
    if schema_version < 3:
        return (), ()
    if not isinstance(raw, dict):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow lifecycle source must be an object"
        )
    if raw.get("fixed_exit_horizons_ms") != list(FORWARD_HORIZONS_MS):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow fixed exit horizons drift"
        )
    if raw.get("max_exit_book_capture_lag_ms") != MAX_MARK_LAG_MS:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow exit-book lag drift"
        )

    raw_exit_books = raw.get("exit_books")
    if not isinstance(raw_exit_books, list):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow exit books must be a list"
        )
    if raw.get("exit_book_count") != len(raw_exit_books):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow exit-book count mismatch"
        )
    if raw.get("exit_books_sha256") != _sha256(raw_exit_books):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow exit-book digest mismatch"
        )
    exit_books: list[OpeningOpportunityExitBookEvidence] = []
    seen_exit_books: set[tuple[str, int]] = set()
    for item in raw_exit_books:
        try:
            evidence = OpeningOpportunityExitBookEvidence.from_dict(item)
        except Exception as exc:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow exit-book evidence is invalid"
            ) from exc
        if evidence.opportunity_id not in opportunity_ids:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow exit book references unknown opportunity"
            )
        if evidence.horizon_ms not in FORWARD_HORIZONS_MS:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow exit-book horizon is unsupported"
            )
        key = (evidence.opportunity_id, evidence.horizon_ms)
        if key in seen_exit_books:
            raise ProspectiveLongTrendExecutionShadowError(
                "duplicate execution-shadow exit book"
            )
        seen_exit_books.add(key)
        exit_books.append(evidence)

    raw_funding = raw.get("funding_records")
    if not isinstance(raw_funding, list):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow funding records must be a list"
        )
    if raw.get("funding_record_count") != len(raw_funding):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow funding-record count mismatch"
        )
    if raw.get("funding_records_sha256") != _sha256(raw_funding):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow funding-record digest mismatch"
        )
    funding: list[ReplacementFundingBoundaryEvidence] = []
    seen_funding: set[tuple[str, int]] = set()
    for item in raw_funding:
        try:
            evidence = ReplacementFundingBoundaryEvidence.from_dict(item)
        except Exception as exc:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow funding evidence is invalid"
            ) from exc
        key = (evidence.market, evidence.boundary_ms)
        if key in seen_funding:
            raise ProspectiveLongTrendExecutionShadowError(
                "duplicate execution-shadow funding record"
            )
        seen_funding.add(key)
        funding.append(evidence)

    return tuple(exit_books), tuple(funding)


def _exit_execution_config_payload(
    config: PaperExecutionConfig,
) -> dict[str, object]:
    return {
        "config_version": config.config_version,
        "latency_ms": config.latency_ms,
        "max_book_age_ms": config.max_book_age_ms,
        "max_ioc_slippage_bps": str(config.max_ioc_slippage_bps),
        "taker_fee_rate": str(config.taker_fee_rate),
        "fee_schedule_id": config.fee_schedule_id,
    }


def _exact_realized_horizon_summary(
    realized: dict[str, object],
    *,
    horizon_ms: int,
) -> dict[str, object]:
    raw_options = realized.get("option_results")
    if not isinstance(raw_options, list):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow realized option results are invalid"
        )
    key = str(horizon_ms)
    exact: list[tuple[str, Decimal, Decimal]] = []
    statuses: Counter[str] = Counter()
    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow realized option is invalid"
            )
        market = raw_option.get("opportunity_market")
        exits = raw_option.get("exits")
        if not isinstance(market, str) or not isinstance(exits, dict):
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow realized option lineage is invalid"
            )
        raw_exit = exits.get(key)
        if not isinstance(raw_exit, dict):
            statuses["missing_exit_result"] += 1
            continue
        raw_pnl = raw_exit.get("exact_realized_pnl")
        raw_return = raw_exit.get("exact_realized_return_fraction")
        if isinstance(raw_pnl, str) and isinstance(raw_return, str):
            pnl = Decimal(raw_pnl)
            return_fraction = Decimal(raw_return)
            exact.append((market, pnl, return_fraction))
            statuses["exact"] += 1
        else:
            reason = raw_exit.get("incomplete_reason")
            statuses[
                reason if isinstance(reason, str) and reason else "incomplete"
            ] += 1

    pnl_values = tuple(item[1] for item in exact)
    return_values = tuple(item[2] for item in exact)
    positive = tuple(value for value in pnl_values if value > ZERO)
    negative = tuple(value for value in pnl_values if value < ZERO)
    markets = sorted({item[0] for item in exact})
    leave_one_option = [
        sum(
            (
                candidate[1]
                for candidate_index, candidate in enumerate(exact)
                if candidate_index != index
            ),
            ZERO,
        )
        for index in range(len(exact))
    ]
    leave_one_market = [
        sum(
            (candidate[1] for candidate in exact if candidate[0] != market),
            ZERO,
        )
        for market in markets
    ]
    gross_profit = sum(positive, ZERO)
    gross_loss = -sum(negative, ZERO)
    count = len(exact)
    return {
        "horizon_ms": horizon_ms,
        "status_counts": dict(sorted(statuses.items())),
        "exact_options": count,
        "positive": len(positive),
        "negative": len(negative),
        "flat": sum(value == ZERO for value in pnl_values),
        "total_exact_realized_pnl": str(sum(pnl_values, ZERO)),
        "mean_exact_realized_pnl": (
            None
            if count == 0
            else str(sum(pnl_values, ZERO) / Decimal(count))
        ),
        "mean_exact_realized_return_fraction": (
            None
            if count == 0
            else str(sum(return_values, ZERO) / Decimal(count))
        ),
        "gross_profit": str(gross_profit),
        "gross_loss": str(gross_loss),
        "profit_factor": (
            None
            if gross_loss == ZERO
            else str(gross_profit / gross_loss)
        ),
        "market_count": len(markets),
        "leave_one_option_out_min_total_pnl": (
            None
            if not leave_one_option
            else str(min(leave_one_option))
        ),
        "leave_one_market_out_min_total_pnl": (
            None
            if not leave_one_market
            else str(min(leave_one_market))
        ),
    }


def _execution_config_compatible(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    config: PaperExecutionConfig,
) -> None:
    request = evidence.risk_request_object
    instrument = evidence.instrument_object
    if request.cost_estimate != conservative_cost_estimate(config):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow cost estimate drift"
        )
    if (
        instrument.minimum_order_notional
        != config.native_perp_min_notional
        or request.limits.max_gross_leverage
        != config.paper_max_gross_leverage
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow execution envelope drift"
        )
    received_at_ms = int(
        evidence.book_event.receive_time.timestamp() * 1000
    )
    earliest_ms = (
        request.strategy_decision.timestamp_ms + config.latency_ms
    )
    if (
        request.timestamp_ms < earliest_ms
        or received_at_ms < earliest_ms
        or received_at_ms > request.timestamp_ms
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow captured timing violates execution latency"
        )


def _neutralize_weekly_drawdown(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> RiskRequest:
    request = evidence.risk_request_object
    baseline = evaluate_risk(request)
    if (
        baseline.approved
        or baseline.reason_codes != (WEEKLY_DRAWDOWN_REASON,)
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow baseline request is not weekly-drawdown-only"
        )
    account = request.account_state
    peak = account.rolling_7d_peak_equity
    if peak <= ZERO or account.equity <= ZERO or peak < account.equity:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow weekly drawdown state is invalid"
        )
    adjusted_account = replace(
        account,
        rolling_7d_peak_equity=account.equity,
    )
    return replace(request, account_state=adjusted_account)


def _markout(
    *,
    path: ContinuousPaperOpeningOpportunityPath | None,
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    horizon_ms: int,
    entry_price: Decimal,
    quantity: Decimal,
    entry_fee: Decimal,
) -> dict[str, object]:
    target_at_ms = evidence.opportunity_timestamp_ms + horizon_ms
    base: dict[str, object] = {
        "horizon_ms": horizon_ms,
        "target_at_ms": target_at_ms,
        "observed_at_ms": None,
        "observation_lag_ms": None,
        "mark_px": None,
        "directional_return_fraction": None,
        "gross_mark_to_market_pnl": None,
        "entry_fee_adjusted_mark_to_market_pnl": None,
    }
    if path is None:
        return {**base, "status": "missing_path"}
    if (
        path.opportunity_id != evidence.opportunity_id
        or path.market != evidence.market
        or path.direction != evidence.direction
        or path.opportunity_timestamp_ms
        != evidence.opportunity_timestamp_ms
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow forward path lineage mismatch"
        )
    if horizon_ms > path.max_path_age_ms:
        return {**base, "status": "unsupported_horizon"}

    mark = next(
        (
            item
            for item in path.marks
            if item.observed_at_ms >= target_at_ms
        ),
        None,
    )
    if mark is None:
        return {**base, "status": "pending"}
    lag_ms = mark.observed_at_ms - target_at_ms
    observed = {
        **base,
        "observed_at_ms": mark.observed_at_ms,
        "observation_lag_ms": lag_ms,
        "mark_px": str(mark.mark_px),
    }
    if lag_ms > MAX_MARK_LAG_MS:
        return {**observed, "status": "stale"}

    signed_move = mark.mark_px - entry_price
    gross = signed_move * quantity
    fee_adjusted = gross - entry_fee
    return {
        **observed,
        "status": "settled",
        "directional_return_fraction": str(
            signed_move / entry_price
        ),
        "gross_mark_to_market_pnl": str(gross),
        "entry_fee_adjusted_mark_to_market_pnl": str(
            fee_adjusted
        ),
    }


def _robustness(
    results: tuple[dict[str, object], ...],
    *,
    horizon_key: str,
) -> dict[str, object]:
    settled: list[tuple[str, Decimal]] = []
    for result in results:
        markouts = result.get("markouts")
        if not isinstance(markouts, dict):
            continue
        markout = markouts.get(horizon_key)
        if not isinstance(markout, dict):
            continue
        if markout.get("status") != "settled":
            continue
        raw_pnl = markout.get(
            "entry_fee_adjusted_mark_to_market_pnl"
        )
        market = result.get("market")
        if not isinstance(raw_pnl, str) or not isinstance(market, str):
            continue
        settled.append((market, Decimal(raw_pnl)))

    total = sum((pnl for _market, pnl in settled), ZERO)
    leave_option = tuple(total - pnl for _market, pnl in settled)
    by_market: dict[str, Decimal] = {}
    for market, pnl in settled:
        by_market[market] = by_market.get(market, ZERO) + pnl
    leave_market = tuple(
        total - pnl for pnl in by_market.values()
    )
    return {
        "settled_fills": len(settled),
        "market_count": len(by_market),
        "total_entry_fee_adjusted_pnl": str(total),
        "leave_one_option_out_min_pnl": str(
            min(leave_option, default=ZERO)
        ),
        "positive_after_removing_any_one_option": (
            len(settled) >= 2
            and min(leave_option, default=ZERO) > ZERO
        ),
        "leave_one_market_out_min_pnl": str(
            min(leave_market, default=ZERO)
        ),
        "positive_after_removing_any_one_market": (
            len(by_market) >= 2
            and min(leave_market, default=ZERO) > ZERO
        ),
    }


def _horizon_summary(
    results: tuple[dict[str, object], ...],
    horizon_ms: int,
) -> dict[str, object]:
    key = str(horizon_ms)
    status_counts: Counter[str] = Counter()
    settled_pnl: list[Decimal] = []
    settled_returns: list[Decimal] = []
    for result in results:
        markouts = result.get("markouts")
        if not isinstance(markouts, dict):
            continue
        markout = markouts.get(key)
        if not isinstance(markout, dict):
            continue
        status = markout.get("status")
        if isinstance(status, str):
            status_counts[status] += 1
        if status != "settled":
            continue
        raw_pnl = markout.get(
            "entry_fee_adjusted_mark_to_market_pnl"
        )
        raw_return = markout.get("directional_return_fraction")
        if not isinstance(raw_pnl, str) or not isinstance(
            raw_return, str
        ):
            raise ProspectiveLongTrendExecutionShadowError(
                "settled execution-shadow markout is incomplete"
            )
        settled_pnl.append(Decimal(raw_pnl))
        settled_returns.append(Decimal(raw_return))

    positive = tuple(value for value in settled_pnl if value > ZERO)
    negative = tuple(value for value in settled_pnl if value < ZERO)
    flat = sum(value == ZERO for value in settled_pnl)
    gross_profit = sum(positive, ZERO)
    gross_loss = -sum(negative, ZERO)
    settled_count = len(settled_pnl)
    return {
        "horizon_ms": horizon_ms,
        "status_counts": dict(sorted(status_counts.items())),
        "settled": settled_count,
        "positive": len(positive),
        "negative": len(negative),
        "flat": flat,
        "positive_fraction": (
            None
            if settled_count == 0
            else str(Decimal(len(positive)) / Decimal(settled_count))
        ),
        "total_entry_fee_adjusted_mark_to_market_pnl": str(
            sum(settled_pnl, ZERO)
        ),
        "mean_entry_fee_adjusted_mark_to_market_pnl": (
            None
            if settled_count == 0
            else str(sum(settled_pnl, ZERO) / Decimal(settled_count))
        ),
        "mean_directional_return_fraction": (
            None
            if settled_count == 0
            else str(
                sum(settled_returns, ZERO)
                / Decimal(settled_count)
            )
        ),
        "gross_profit": str(gross_profit),
        "gross_loss": str(gross_loss),
        "profit_factor": (
            None
            if gross_loss == ZERO
            else str(gross_profit / gross_loss)
        ),
        "robustness": _robustness(
            results,
            horizon_key=key,
        ),
    }


def prospective_long_trend_execution_shadow_summary(
    source: object,
    config: PaperExecutionConfig | None = None,
) -> dict[str, object]:
    rows, active_config, config_source, source_schema_version = (
        _validate_source(
            source,
            legacy_config=config,
        )
    )
    opportunity_ids = frozenset(
        cast(str, row["opportunity_id"]) for row in rows
    )
    exit_books, funding_records = _lifecycle_evidence(
        source,
        schema_version=source_schema_version,
        opportunity_ids=opportunity_ids,
    )
    results: list[dict[str, object]] = []
    lifecycle_entry_options: list[dict[str, object]] = []
    risk_rejections: Counter[str] = Counter()
    planning_rejections: Counter[str] = Counter()
    execution_results: Counter[str] = Counter()

    for row in rows:
        opportunity_id = cast(str, row["opportunity_id"])
        raw_opportunity = row.get("opportunity")
        try:
            evidence = ContinuousPaperOpeningOpportunityEvidence.from_dict(
                raw_opportunity
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opening evidence is invalid"
            ) from exc
        if evidence.opportunity_id != opportunity_id:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opening evidence id mismatch"
            )
        if (
            evidence.direction != "long"
            or evidence.lead_strategy != "trend"
            or evidence.baseline_risk_approved
            or evidence.baseline_risk_reason_codes
            != (WEEKLY_DRAWDOWN_REASON,)
        ):
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opening evidence lineage mismatch"
            )

        raw_path = row.get("path")
        path: ContinuousPaperOpeningOpportunityPath | None
        if raw_path is None:
            path = None
        else:
            try:
                path = ContinuousPaperOpeningOpportunityPath.from_dict(
                    raw_path
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProspectiveLongTrendExecutionShadowError(
                    "execution-shadow forward path is invalid"
                ) from exc

        _execution_config_compatible(evidence, active_config)
        adjusted_request = _neutralize_weekly_drawdown(evidence)
        risk = evaluate_risk(adjusted_request)

        result: dict[str, object] = {
            "opportunity_id": opportunity_id,
            "timestamp_ms": evidence.opportunity_timestamp_ms,
            "market": evidence.market,
            "direction": evidence.direction,
            "lead_strategy": evidence.lead_strategy,
            "counterfactual_risk_approved": risk.approved,
            "counterfactual_risk_reason_codes": list(
                risk.reason_codes
            ),
            "planning_approved": False,
            "planning_rejection": None,
            "execution_result": None,
            "filled_quantity": None,
            "average_fill_price": None,
            "entry_fee": None,
            "markouts": {},
        }
        if not risk.approved:
            reason = (
                risk.reason_codes[0]
                if risk.reason_codes
                else "unknown"
            )
            risk_rejections[reason] += 1
            results.append(result)
            continue

        plan = plan_opening_order(
            risk,
            evidence.instrument_object,
            active_config,
            adjusted_request.entry_reference_price,
            adjusted_request.strategy_decision.timestamp_ms,
        )
        if isinstance(plan, PlanningRejection):
            result["planning_rejection"] = plan.reason
            planning_rejections[plan.reason] += 1
            results.append(result)
            continue
        result["planning_approved"] = True

        simulation = simulate_ioc(
            plan,
            evidence.book_event,
            evidence.instrument_object,
            active_config,
            attempt_timestamp_ms=adjusted_request.timestamp_ms,
        )
        attempt = simulation.attempt
        result["execution_result"] = attempt.result.value
        execution_results[attempt.result.value] += 1
        if not simulation.fills:
            results.append(result)
            continue
        if attempt.average_fill_price is None:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow fill is missing average price"
            )

        quantity = attempt.filled_quantity
        entry_price = attempt.average_fill_price
        entry_fee = attempt.fee
        result["filled_quantity"] = str(quantity)
        result["average_fill_price"] = str(entry_price)
        result["entry_fee"] = str(entry_fee)
        result["markouts"] = {
            str(horizon_ms): _markout(
                path=path,
                evidence=evidence,
                horizon_ms=horizon_ms,
                entry_price=entry_price,
                quantity=quantity,
                entry_fee=entry_fee,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        }
        if plan.stop_price is None:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opening plan is missing stop"
            )
        lifecycle_entry_options.append(
            {
                "option_id": opportunity_id,
                "opportunity_id": opportunity_id,
                "opportunity_timestamp_ms": (
                    evidence.opportunity_timestamp_ms
                ),
                "opportunity_market": evidence.market,
                "opportunity_direction": evidence.direction,
                "risk_approved": True,
                "risk_reason_codes": list(risk.reason_codes),
                "planning_approved": True,
                "planning_rejection": None,
                "execution_result": attempt.result.value,
                "attempt_id": attempt.attempt_id,
                "entry_attempt_timestamp_ms": (
                    attempt.attempt_timestamp_ms
                ),
                "opening_plan_id": plan.plan_id,
                "opening_risk_decision_id": plan.risk_decision_id,
                "opening_strategy_decision_id": (
                    plan.strategy_decision_id
                ),
                "opening_stop_price": str(plan.stop_price),
                "correlation_bucket": (
                    adjusted_request.correlation_bucket
                ),
                "venue_max_leverage": str(
                    evidence.instrument_object.venue_max_leverage
                ),
                "requested_quantity": str(
                    attempt.requested_quantity
                ),
                "filled_quantity": str(attempt.filled_quantity),
                "average_fill_price": str(entry_price),
                "gross_fill_notional": str(
                    attempt.gross_fill_notional
                ),
                "taker_fee": str(entry_fee),
                "unfilled_quantity": str(
                    attempt.unfilled_quantity
                ),
            }
        )
        results.append(result)

    result_tuple = tuple(
        sorted(
            results,
            key=lambda item: (
                cast(int, item["timestamp_ms"]),
                cast(str, item["market"]),
                cast(str, item["opportunity_id"]),
            ),
        )
    )
    fillable = sum(
        item["filled_quantity"] is not None
        for item in result_tuple
    )

    lifecycle_modeled = source_schema_version >= 3
    exit_fill: dict[str, object] | None = None
    realized_pnl: dict[str, object] | None = None
    exact_by_horizon: dict[str, object] = {}
    if lifecycle_modeled:
        fill_feasibility: dict[str, object] = {
            "replacement_entry_fills_modeled": True,
            "execution_config": _exit_execution_config_payload(
                active_config
            ),
            "fillable_option_ids": [
                cast(str, item["option_id"])
                for item in lifecycle_entry_options
            ],
            "option_results": lifecycle_entry_options,
        }
        exit_fill = prospective_capacity_reflow_exit_fill_summary(
            fill_feasibility,
            exit_books,
            active_config,
            horizons_ms=FORWARD_HORIZONS_MS,
        )
        realized_pnl = prospective_capacity_reflow_realized_pnl_summary(
            exit_fill,
            funding_records,
        )
        exact_by_horizon = {
            str(horizon_ms): _exact_realized_horizon_summary(
                realized_pnl,
                horizon_ms=horizon_ms,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "candidate_id": LONG_TREND_CARVEOUT_CANDIDATE_ID,
        "baseline_risk_reason": WEEKLY_DRAWDOWN_REASON,
        "source_schema_version": source_schema_version,
        "execution_config_source": config_source,
        "execution_config": execution_config_payload(
            active_config
        ),
        "execution_config_sha256": _sha256(
            execution_config_payload(active_config)
        ),
        "execution_model": (
            "captured_request_plus_decision_time_visible_book_ioc"
        ),
        "outcome_scope": (
            "entry_markout_plus_real_l2_fixed_horizon_realized_when_complete"
            if lifecycle_modeled
            else "entry_fee_adjusted_forward_mark_to_market_only"
        ),
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "source_opportunities": len(rows),
        "counterfactual_risk_approvals": sum(
            item["counterfactual_risk_approved"] is True
            for item in result_tuple
        ),
        "counterfactual_risk_rejections": dict(
            sorted(risk_rejections.items())
        ),
        "planning_approvals": sum(
            item["planning_approved"] is True
            for item in result_tuple
        ),
        "planning_rejections": dict(
            sorted(planning_rejections.items())
        ),
        "execution_results": dict(
            sorted(execution_results.items())
        ),
        "fillable_opportunities": fillable,
        "by_horizon": {
            str(horizon_ms): _horizon_summary(
                result_tuple,
                horizon_ms,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        },
        "option_results": list(result_tuple),
        "exit_book_records": len(exit_books),
        "funding_evidence_records": len(funding_records),
        "fixed_horizon_exit_execution": exit_fill,
        "fixed_horizon_realized_pnl": realized_pnl,
        "exact_realized_by_horizon": exact_by_horizon,
        "exact_realized_pnl_available": (
            False
            if realized_pnl is None
            else realized_pnl["exact_realized_pnl_available"]
        ),
        "exact_realized_pnl_option_horizons": (
            0
            if realized_pnl is None
            else realized_pnl["exact_realized_pnl_option_horizons"]
        ),
        "replacement_exits_modeled": lifecycle_modeled,
        "exit_fees_modeled": lifecycle_modeled,
        "funding_modeled": lifecycle_modeled,
        "realized_pnl_modeled": lifecycle_modeled,
    }
