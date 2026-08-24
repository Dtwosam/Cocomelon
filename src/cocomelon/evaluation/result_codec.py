from __future__ import annotations

from decimal import Decimal, InvalidOperation

from cocomelon.domain.evaluation import (
    ConfidenceInterval,
    EdgeEvidenceStatus,
    EvaluationResult,
    OOSStatus,
    PerformanceMetrics,
    PromotionGatePreview,
    SliceMetrics,
    WalkForwardWindowResult,
)


class EvaluationResultCodecError(ValueError):
    pass


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise EvaluationResultCodecError(f"{field} must be an object")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationResultCodecError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvaluationResultCodecError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationResultCodecError(f"{field} must be a boolean")
    return value


def _optional_boolean(value: object, field: str) -> bool | None:
    if value is None:
        return None
    return _boolean(value, field)


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise EvaluationResultCodecError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise EvaluationResultCodecError(f"{field} must be a decimal string") from exc
    if not result.is_finite():
        raise EvaluationResultCodecError(f"{field} must be finite")
    return result


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EvaluationResultCodecError(f"{field} must be a string array")
    return tuple(value)


def performance_metrics_payload(metrics: PerformanceMetrics) -> dict[str, object]:
    return {
        "trade_count": metrics.trade_count,
        "covered_days": metrics.covered_days,
        "gross_pnl": str(metrics.gross_pnl),
        "total_fees": str(metrics.total_fees),
        "funding_cash_pnl": str(metrics.funding_cash_pnl),
        "signed_slippage_amount": str(metrics.signed_slippage_amount),
        "net_pnl": str(metrics.net_pnl),
        "total_net_r": str(metrics.total_net_r),
        "mean_net_r": str(metrics.mean_net_r),
        "median_net_r": str(metrics.median_net_r),
        "win_rate": str(metrics.win_rate),
        "average_winner_r": (
            None if metrics.average_winner_r is None else str(metrics.average_winner_r)
        ),
        "average_loser_r": (
            None if metrics.average_loser_r is None else str(metrics.average_loser_r)
        ),
        "profit_factor": None if metrics.profit_factor is None else str(metrics.profit_factor),
        "profit_factor_unavailable_reason": metrics.profit_factor_unavailable_reason,
        "largest_winner_r": (
            None if metrics.largest_winner_r is None else str(metrics.largest_winner_r)
        ),
        "largest_loser_r": (
            None if metrics.largest_loser_r is None else str(metrics.largest_loser_r)
        ),
        "p05_net_r": None if metrics.p05_net_r is None else str(metrics.p05_net_r),
        "expected_shortfall_5pct": (
            None
            if metrics.expected_shortfall_5pct is None
            else str(metrics.expected_shortfall_5pct)
        ),
        "median_holding_duration_ms": metrics.median_holding_duration_ms,
        "p95_holding_duration_ms": metrics.p95_holding_duration_ms,
        "realized_closed_trade_max_drawdown_fraction": (
            None
            if metrics.realized_closed_trade_max_drawdown_fraction is None
            else str(metrics.realized_closed_trade_max_drawdown_fraction)
        ),
        "account_equity_max_drawdown_fraction": (
            None
            if metrics.account_equity_max_drawdown_fraction is None
            else str(metrics.account_equity_max_drawdown_fraction)
        ),
        "account_drawdown_unavailable_reason": metrics.account_drawdown_unavailable_reason,
        "max_market_positive_pnl_share": (
            None
            if metrics.max_market_positive_pnl_share is None
            else str(metrics.max_market_positive_pnl_share)
        ),
        "max_strategy_positive_pnl_share": (
            None
            if metrics.max_strategy_positive_pnl_share is None
            else str(metrics.max_strategy_positive_pnl_share)
        ),
        "max_seven_day_positive_pnl_share": (
            None
            if metrics.max_seven_day_positive_pnl_share is None
            else str(metrics.max_seven_day_positive_pnl_share)
        ),
        "schema_version": metrics.schema_version,
    }


def performance_metrics_from_payload(value: object) -> PerformanceMetrics:
    raw = _mapping(value, "performance_metrics")
    return PerformanceMetrics(
        trade_count=_integer(raw.get("trade_count"), "trade_count"),
        covered_days=_integer(raw.get("covered_days"), "covered_days"),
        gross_pnl=_decimal(raw.get("gross_pnl"), "gross_pnl"),
        total_fees=_decimal(raw.get("total_fees"), "total_fees"),
        funding_cash_pnl=_decimal(raw.get("funding_cash_pnl"), "funding_cash_pnl"),
        signed_slippage_amount=_decimal(
            raw.get("signed_slippage_amount"), "signed_slippage_amount"
        ),
        net_pnl=_decimal(raw.get("net_pnl"), "net_pnl"),
        total_net_r=_decimal(raw.get("total_net_r"), "total_net_r"),
        mean_net_r=_decimal(raw.get("mean_net_r"), "mean_net_r"),
        median_net_r=_decimal(raw.get("median_net_r"), "median_net_r"),
        win_rate=_decimal(raw.get("win_rate"), "win_rate"),
        average_winner_r=_optional_decimal(raw.get("average_winner_r"), "average_winner_r"),
        average_loser_r=_optional_decimal(raw.get("average_loser_r"), "average_loser_r"),
        profit_factor=_optional_decimal(raw.get("profit_factor"), "profit_factor"),
        profit_factor_unavailable_reason=_optional_string(
            raw.get("profit_factor_unavailable_reason"),
            "profit_factor_unavailable_reason",
        ),
        largest_winner_r=_optional_decimal(raw.get("largest_winner_r"), "largest_winner_r"),
        largest_loser_r=_optional_decimal(raw.get("largest_loser_r"), "largest_loser_r"),
        p05_net_r=_optional_decimal(raw.get("p05_net_r"), "p05_net_r"),
        expected_shortfall_5pct=_optional_decimal(
            raw.get("expected_shortfall_5pct"), "expected_shortfall_5pct"
        ),
        median_holding_duration_ms=(
            None
            if raw.get("median_holding_duration_ms") is None
            else _integer(raw.get("median_holding_duration_ms"), "median_holding_duration_ms")
        ),
        p95_holding_duration_ms=(
            None
            if raw.get("p95_holding_duration_ms") is None
            else _integer(raw.get("p95_holding_duration_ms"), "p95_holding_duration_ms")
        ),
        realized_closed_trade_max_drawdown_fraction=_optional_decimal(
            raw.get("realized_closed_trade_max_drawdown_fraction"),
            "realized_closed_trade_max_drawdown_fraction",
        ),
        account_equity_max_drawdown_fraction=_optional_decimal(
            raw.get("account_equity_max_drawdown_fraction"),
            "account_equity_max_drawdown_fraction",
        ),
        account_drawdown_unavailable_reason=_optional_string(
            raw.get("account_drawdown_unavailable_reason"),
            "account_drawdown_unavailable_reason",
        ),
        max_market_positive_pnl_share=_optional_decimal(
            raw.get("max_market_positive_pnl_share"), "max_market_positive_pnl_share"
        ),
        max_strategy_positive_pnl_share=_optional_decimal(
            raw.get("max_strategy_positive_pnl_share"), "max_strategy_positive_pnl_share"
        ),
        max_seven_day_positive_pnl_share=_optional_decimal(
            raw.get("max_seven_day_positive_pnl_share"),
            "max_seven_day_positive_pnl_share",
        ),
        schema_version=_integer(raw.get("schema_version"), "schema_version"),
    )


def _confidence_payload(value: ConfidenceInterval | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "metric": value.metric,
        "lower": str(value.lower),
        "upper": str(value.upper),
        "confidence": str(value.confidence),
        "resamples": value.resamples,
        "block_days": value.block_days,
        "schema_version": value.schema_version,
    }


def _confidence_from_payload(value: object) -> ConfidenceInterval | None:
    if value is None:
        return None
    raw = _mapping(value, "confidence_interval")
    return ConfidenceInterval(
        metric=_string(raw.get("metric"), "metric"),
        lower=_decimal(raw.get("lower"), "lower"),
        upper=_decimal(raw.get("upper"), "upper"),
        confidence=_decimal(raw.get("confidence"), "confidence"),
        resamples=_integer(raw.get("resamples"), "resamples"),
        block_days=_integer(raw.get("block_days"), "block_days"),
        schema_version=_integer(raw.get("schema_version"), "schema_version"),
    )


def _walkforward_payload(value: WalkForwardWindowResult) -> dict[str, object]:
    return {
        "split_manifest_id": value.split_manifest_id,
        "evaluation_start_ms": value.evaluation_start_ms,
        "evaluation_end_ms": value.evaluation_end_ms,
        "included_trade_ids": value.included_trade_ids,
        "excluded_trade_ids": value.excluded_trade_ids,
        "metrics": performance_metrics_payload(value.metrics),
        "eligible": value.eligible,
        "reason_codes": value.reason_codes,
        "schema_version": value.schema_version,
    }


def _walkforward_from_payload(value: object) -> WalkForwardWindowResult:
    raw = _mapping(value, "walkforward_result")
    return WalkForwardWindowResult(
        split_manifest_id=_string(raw.get("split_manifest_id"), "split_manifest_id"),
        evaluation_start_ms=_integer(raw.get("evaluation_start_ms"), "evaluation_start_ms"),
        evaluation_end_ms=_integer(raw.get("evaluation_end_ms"), "evaluation_end_ms"),
        included_trade_ids=_strings(raw.get("included_trade_ids"), "included_trade_ids"),
        excluded_trade_ids=_strings(raw.get("excluded_trade_ids"), "excluded_trade_ids"),
        metrics=performance_metrics_from_payload(raw.get("metrics")),
        eligible=_boolean(raw.get("eligible"), "eligible"),
        reason_codes=_strings(raw.get("reason_codes"), "reason_codes"),
        schema_version=_integer(raw.get("schema_version"), "schema_version"),
    )


def _slice_payload(value: SliceMetrics) -> dict[str, object]:
    return {
        "slice_kind": value.slice_kind,
        "slice_key": value.slice_key,
        "sample_size": value.sample_size,
        "research_ready": value.research_ready,
        "metrics": performance_metrics_payload(value.metrics),
        "reason_codes": value.reason_codes,
        "schema_version": value.schema_version,
    }


def _slice_from_payload(value: object) -> SliceMetrics:
    raw = _mapping(value, "slice_metrics")
    return SliceMetrics(
        slice_kind=_string(raw.get("slice_kind"), "slice_kind"),
        slice_key=_string(raw.get("slice_key"), "slice_key"),
        sample_size=_integer(raw.get("sample_size"), "sample_size"),
        research_ready=_boolean(raw.get("research_ready"), "research_ready"),
        metrics=performance_metrics_from_payload(raw.get("metrics")),
        reason_codes=_strings(raw.get("reason_codes"), "reason_codes"),
        schema_version=_integer(raw.get("schema_version"), "schema_version"),
    )


def _preview_payload(value: PromotionGatePreview) -> dict[str, object]:
    return {
        "profit_factor_pass": value.profit_factor_pass,
        "max_drawdown_pass": value.max_drawdown_pass,
        "market_concentration_pass": value.market_concentration_pass,
        "seven_day_concentration_pass": value.seven_day_concentration_pass,
        "closed_trade_count_pass": value.closed_trade_count_pass,
        "covered_days_pass": value.covered_days_pass,
        "invariant_health_pass": value.invariant_health_pass,
        "reason_codes": value.reason_codes,
        "schema_version": value.schema_version,
    }


def _preview_from_payload(value: object) -> PromotionGatePreview:
    raw = _mapping(value, "promotion_preview")
    return PromotionGatePreview(
        profit_factor_pass=_optional_boolean(raw.get("profit_factor_pass"), "profit_factor_pass"),
        max_drawdown_pass=_optional_boolean(raw.get("max_drawdown_pass"), "max_drawdown_pass"),
        market_concentration_pass=_optional_boolean(
            raw.get("market_concentration_pass"), "market_concentration_pass"
        ),
        seven_day_concentration_pass=_optional_boolean(
            raw.get("seven_day_concentration_pass"), "seven_day_concentration_pass"
        ),
        closed_trade_count_pass=_optional_boolean(
            raw.get("closed_trade_count_pass"), "closed_trade_count_pass"
        ),
        covered_days_pass=_optional_boolean(raw.get("covered_days_pass"), "covered_days_pass"),
        invariant_health_pass=_optional_boolean(
            raw.get("invariant_health_pass"), "invariant_health_pass"
        ),
        reason_codes=_strings(raw.get("reason_codes"), "reason_codes"),
        schema_version=_integer(raw.get("schema_version"), "schema_version"),
    )


def evaluation_result_payload(result: EvaluationResult) -> dict[str, object]:
    return {
        "dataset_manifest_id": result.dataset_manifest_id,
        "split_manifest_id": result.split_manifest_id,
        "candidate_set_id": result.candidate_set_id,
        "policy_id": result.policy_id,
        "oos_status": result.oos_status.value,
        "train_metrics": performance_metrics_payload(result.train_metrics),
        "validation_metrics": performance_metrics_payload(result.validation_metrics),
        "test_metrics": performance_metrics_payload(result.test_metrics),
        "mean_net_r_confidence_interval": _confidence_payload(
            result.mean_net_r_confidence_interval
        ),
        "walkforward_results": tuple(
            _walkforward_payload(item) for item in result.walkforward_results
        ),
        "slice_reports": tuple(_slice_payload(item) for item in result.slice_reports),
        "sensitivity_report_ids": result.sensitivity_report_ids,
        "no_trade_report_ids": result.no_trade_report_ids,
        "edge_status": result.edge_status.value,
        "promotion_preview": _preview_payload(result.promotion_preview),
        "included_sample_count": result.included_sample_count,
        "excluded_sample_count": result.excluded_sample_count,
        "reason_codes": result.reason_codes,
        "schema_version": result.schema_version,
    }


def evaluation_result_from_payload(value: object) -> EvaluationResult:
    raw = _mapping(value, "evaluation_result")
    walkforward_raw = raw.get("walkforward_results")
    slice_raw = raw.get("slice_reports")
    if not isinstance(walkforward_raw, list):
        raise EvaluationResultCodecError("walkforward_results must be an array")
    if not isinstance(slice_raw, list):
        raise EvaluationResultCodecError("slice_reports must be an array")
    return EvaluationResult(
        dataset_manifest_id=_string(raw.get("dataset_manifest_id"), "dataset_manifest_id"),
        split_manifest_id=_string(raw.get("split_manifest_id"), "split_manifest_id"),
        candidate_set_id=_string(raw.get("candidate_set_id"), "candidate_set_id"),
        policy_id=_string(raw.get("policy_id"), "policy_id"),
        oos_status=OOSStatus(_string(raw.get("oos_status"), "oos_status")),
        train_metrics=performance_metrics_from_payload(raw.get("train_metrics")),
        validation_metrics=performance_metrics_from_payload(raw.get("validation_metrics")),
        test_metrics=performance_metrics_from_payload(raw.get("test_metrics")),
        mean_net_r_confidence_interval=_confidence_from_payload(
            raw.get("mean_net_r_confidence_interval")
        ),
        walkforward_results=tuple(_walkforward_from_payload(item) for item in walkforward_raw),
        slice_reports=tuple(_slice_from_payload(item) for item in slice_raw),
        sensitivity_report_ids=_strings(
            raw.get("sensitivity_report_ids"), "sensitivity_report_ids"
        ),
        no_trade_report_ids=_strings(raw.get("no_trade_report_ids"), "no_trade_report_ids"),
        edge_status=EdgeEvidenceStatus(_string(raw.get("edge_status"), "edge_status")),
        promotion_preview=_preview_from_payload(raw.get("promotion_preview")),
        included_sample_count=_integer(raw.get("included_sample_count"), "included_sample_count"),
        excluded_sample_count=_integer(raw.get("excluded_sample_count"), "excluded_sample_count"),
        reason_codes=_strings(raw.get("reason_codes"), "reason_codes"),
        schema_version=_integer(raw.get("schema_version"), "schema_version"),
    )
