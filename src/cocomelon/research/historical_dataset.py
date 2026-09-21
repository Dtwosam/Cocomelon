from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast
from urllib.parse import quote

from cocomelon.domain.market import Candle, FundingRate, MarketId
from cocomelon.replay.compaction import _load_pyarrow
from cocomelon.research.historical_backfill import (
    HistoricalCandleManifest,
    HistoricalFundingManifest,
)
from cocomelon.research.historical_features import (
    HistoricalFeatureRow,
    HistoricalTrainingRow,
    build_historical_feature_rows,
    enrich_historical_market_context,
    join_features_to_outcomes,
)
from cocomelon.research.historical_learning import (
    DirectionalOutcome,
    build_directional_outcomes,
)

DATASET_SCHEMA_VERSION = 2
DATASET_CONVERTER_VERSION = "historical-directional-training-v2-market-context"
OUTPUT_FILENAME = "training.parquet"

TRAINING_COLUMNS = (
    "training_row_id",
    "feature_id",
    "outcome_id",
    "market",
    "anchor_end_ms",
    "target_end_ms",
    "horizon_ms",
    "anchor_close_px",
    "return_5m",
    "return_15m",
    "return_1h",
    "return_4h",
    "realized_vol_15m",
    "range_expansion_15m",
    "relative_volume_15m",
    "funding_rate",
    "funding_change",
    "funding_premium",
    "funding_premium_change",
    "funding_age_ms",
    "candle_15m_age_ms",
    "btc_return_5m",
    "btc_return_1h",
    "btc_return_4h",
    "eth_return_5m",
    "eth_return_1h",
    "eth_return_4h",
    "market_median_return_5m",
    "market_median_return_1h",
    "market_breadth_positive_5m",
    "market_breadth_positive_1h",
    "market_relative_return_5m",
    "market_relative_return_1h",
    "trend_regime",
    "availability_basis",
    "source_retrieved_at_ms",
    "retrieved_after_anchor",
    "available_features_json",
    "unavailable_features_json",
    "provenance_json",
    "source_manifest_ids_json",
    "entry_px",
    "exit_px",
    "long_gross_return",
    "short_gross_return",
    "feature_schema_version",
    "outcome_schema_version",
    "training_schema_version",
)


class HistoricalDatasetIntegrityError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalDatasetIntegrityError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise HistoricalDatasetIntegrityError(f"{field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalDatasetIntegrityError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalDatasetIntegrityError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalDatasetIntegrityError(f"{field} must be a boolean")
    return value


def _decimal_value(value: object, field: str) -> Decimal:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise HistoricalDatasetIntegrityError(f"{field} must be numeric")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise HistoricalDatasetIntegrityError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise HistoricalDatasetIntegrityError(f"{field} must be finite")
    return result


def _market(value: str) -> MarketId:
    if ":" not in value:
        return MarketId(dex="", coin=value)
    dex, coin = value.split(":", 1)
    if not dex or not coin or ":" in coin:
        raise HistoricalDatasetIntegrityError(f"invalid canonical market: {value!r}")
    return MarketId(dex=dex, coin=coin)


def _pairs(value: object, field: str) -> tuple[tuple[int, int], ...]:
    result: list[tuple[int, int]] = []
    for index, item in enumerate(_array(value, field)):
        values = _array(item, f"{field}[{index}]")
        if len(values) != 2:
            raise HistoricalDatasetIntegrityError(f"{field}[{index}] must contain two integers")
        result.append(
            (
                _integer(values[0], f"{field}[{index}][0]"),
                _integer(values[1], f"{field}[{index}][1]"),
            )
        )
    return tuple(result)


def _strings(value: object, field: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{field}[{index}]")
        for index, item in enumerate(_array(value, field))
    )


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalDatasetIntegrityError(f"unable to read manifest: {path}") from exc
    return _mapping(payload, "manifest")


def _verify_normalized(path: Path, expected_sha256: str) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HistoricalDatasetIntegrityError(f"unable to read normalized source: {path}") from exc
    actual = _sha256_bytes(data)
    if actual != expected_sha256:
        raise HistoricalDatasetIntegrityError(
            "normalized source sha256 mismatch for "
            f"{path}: expected {expected_sha256}, got {actual}"
        )
    return data


def _jsonl_rows(data: bytes, field: str) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HistoricalDatasetIntegrityError(f"{field} must be UTF-8") from exc
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HistoricalDatasetIntegrityError(
                f"{field} contains invalid JSON at line {line_number}"
            ) from exc
        rows.append(_mapping(value, f"{field}[{line_number}]"))
    return tuple(rows)


def _candle_manifest(payload: Mapping[str, object]) -> HistoricalCandleManifest:
    manifest = HistoricalCandleManifest(
        market=_string(payload.get("market"), "market"),
        interval=_string(payload.get("interval"), "interval"),
        requested_start_ms=_integer(payload.get("requested_start_ms"), "requested_start_ms"),
        requested_end_ms=_integer(payload.get("requested_end_ms"), "requested_end_ms"),
        page_count=_integer(payload.get("page_count"), "page_count"),
        candle_count=_integer(payload.get("candle_count"), "candle_count"),
        gap_ranges=_pairs(payload.get("gap_ranges"), "gap_ranges"),
        complete_requested_grid=_boolean(
            payload.get("complete_requested_grid"),
            "complete_requested_grid",
        ),
        raw_page_digests=_strings(payload.get("raw_page_digests"), "raw_page_digests"),
        normalized_sha256=_string(payload.get("normalized_sha256"), "normalized_sha256"),
        schema_version=_integer(payload.get("schema_version"), "schema_version"),
    )
    if _string(payload.get("manifest_id"), "manifest_id") != manifest.manifest_id:
        raise HistoricalDatasetIntegrityError("candle manifest_id mismatch")
    return manifest


def _funding_manifest(payload: Mapping[str, object]) -> HistoricalFundingManifest:
    manifest = HistoricalFundingManifest(
        market=_string(payload.get("market"), "market"),
        requested_start_ms=_integer(payload.get("requested_start_ms"), "requested_start_ms"),
        requested_end_ms=_integer(payload.get("requested_end_ms"), "requested_end_ms"),
        expected_interval_ms=_integer(payload.get("expected_interval_ms"), "expected_interval_ms"),
        page_count=_integer(payload.get("page_count"), "page_count"),
        funding_count=_integer(payload.get("funding_count"), "funding_count"),
        observed_start_ms=_optional_integer(payload.get("observed_start_ms"), "observed_start_ms"),
        observed_end_ms=_optional_integer(payload.get("observed_end_ms"), "observed_end_ms"),
        gap_ranges=_pairs(payload.get("gap_ranges"), "gap_ranges"),
        continuous_observed_grid=_boolean(
            payload.get("continuous_observed_grid"),
            "continuous_observed_grid",
        ),
        raw_page_digests=_strings(payload.get("raw_page_digests"), "raw_page_digests"),
        normalized_sha256=_string(payload.get("normalized_sha256"), "normalized_sha256"),
        schema_version=_integer(payload.get("schema_version"), "schema_version"),
    )
    if _string(payload.get("manifest_id"), "manifest_id") != manifest.manifest_id:
        raise HistoricalDatasetIntegrityError("funding manifest_id mismatch")
    return manifest


def load_candle_source(root: Path) -> tuple[HistoricalCandleManifest, tuple[Candle, ...]]:
    manifest = _candle_manifest(_read_manifest(root / "manifest.json"))
    data = _verify_normalized(root / "candles.jsonl", manifest.normalized_sha256)
    expected_market = _market(manifest.market)
    candles: list[Candle] = []
    for row in _jsonl_rows(data, "candles"):
        market = _market(_string(row.get("market"), "market"))
        if market != expected_market:
            raise HistoricalDatasetIntegrityError("candle market does not match manifest")
        interval = _string(row.get("interval"), "interval")
        if interval != manifest.interval:
            raise HistoricalDatasetIntegrityError("candle interval does not match manifest")
        candles.append(
            Candle(
                market=market,
                interval=interval,
                start_ms=_integer(row.get("start_ms"), "start_ms"),
                end_ms=_integer(row.get("end_ms"), "end_ms"),
                open_px=_decimal_value(row.get("open_px"), "open_px"),
                high_px=_decimal_value(row.get("high_px"), "high_px"),
                low_px=_decimal_value(row.get("low_px"), "low_px"),
                close_px=_decimal_value(row.get("close_px"), "close_px"),
                volume=_decimal_value(row.get("volume"), "volume"),
                trade_count=_integer(row.get("trade_count"), "trade_count"),
                source=_string(row.get("source"), "source"),
                received_at_ms=_integer(row.get("received_at_ms"), "received_at_ms"),
                schema_version=_integer(row.get("schema_version"), "schema_version"),
            )
        )
    if len(candles) != manifest.candle_count:
        raise HistoricalDatasetIntegrityError("candle row count does not match manifest")
    return manifest, tuple(candles)


def load_funding_source(
    root: Path,
) -> tuple[HistoricalFundingManifest, tuple[FundingRate, ...]]:
    manifest = _funding_manifest(_read_manifest(root / "manifest.json"))
    data = _verify_normalized(root / "funding.jsonl", manifest.normalized_sha256)
    expected_market = _market(manifest.market)
    rates: list[FundingRate] = []
    for row in _jsonl_rows(data, "funding"):
        market = _market(_string(row.get("market"), "market"))
        if market != expected_market:
            raise HistoricalDatasetIntegrityError("funding market does not match manifest")
        rates.append(
            FundingRate(
                market=market,
                time_ms=_integer(row.get("time_ms"), "time_ms"),
                funding_rate=_decimal_value(row.get("funding_rate"), "funding_rate"),
                premium=_decimal_value(row.get("premium"), "premium"),
                source=_string(row.get("source"), "source"),
                received_at_ms=_integer(row.get("received_at_ms"), "received_at_ms"),
                schema_version=_integer(row.get("schema_version"), "schema_version"),
            )
        )
    if len(rates) != manifest.funding_count:
        raise HistoricalDatasetIntegrityError("funding row count does not match manifest")
    return manifest, tuple(rates)


def _market_root(source_root: Path, market: MarketId) -> Path:
    return source_root / quote(market.canonical, safe="")


def build_training_rows_from_source_root(
    source_root: Path,
    *,
    markets: Sequence[MarketId],
    horizons_ms: Sequence[int],
) -> tuple[HistoricalTrainingRow, ...]:
    unique_markets = tuple(sorted(set(markets), key=lambda item: item.canonical))
    if not unique_markets:
        raise ValueError("at least one market is required")
    if not horizons_ms:
        raise ValueError("at least one horizon is required")
    base_interval_ms = 300_000
    if any(value <= 0 or value % base_interval_ms != 0 for value in horizons_ms):
        raise ValueError("horizons must be positive multiples of the 5m base interval")

    all_features: list[HistoricalFeatureRow] = []
    all_outcomes: list[DirectionalOutcome] = []
    for market in unique_markets:
        root = _market_root(source_root, market)
        candle_5m_manifest, candles_5m = load_candle_source(root / "candles" / "5m")
        if candle_5m_manifest.market != market.canonical:
            raise HistoricalDatasetIntegrityError("5m source market mismatch")

        candle_15m_path = root / "candles" / "15m"
        candles_15m: tuple[Candle, ...] = ()
        source_manifest_ids = [candle_5m_manifest.manifest_id]
        if (candle_15m_path / "manifest.json").is_file():
            candle_15m_manifest, candles_15m = load_candle_source(candle_15m_path)
            if candle_15m_manifest.market != market.canonical:
                raise HistoricalDatasetIntegrityError("15m source market mismatch")
            source_manifest_ids.append(candle_15m_manifest.manifest_id)

        funding_path = root / "funding"
        funding_rates: tuple[FundingRate, ...] = ()
        if (funding_path / "manifest.json").is_file():
            funding_manifest, funding_rates = load_funding_source(funding_path)
            if funding_manifest.market != market.canonical:
                raise HistoricalDatasetIntegrityError("funding source market mismatch")
            source_manifest_ids.append(funding_manifest.manifest_id)

        features = build_historical_feature_rows(
            candles_5m=candles_5m,
            candles_15m=candles_15m,
            funding_rates=funding_rates,
            source_manifest_ids=source_manifest_ids,
        )
        outcomes = build_directional_outcomes(
            candles_5m,
            horizons_ms=horizons_ms,
        )
        all_features.extend(features)
        all_outcomes.extend(outcomes)

    enriched_features = enrich_historical_market_context(all_features)
    combined = join_features_to_outcomes(enriched_features, all_outcomes)
    seen_training_ids: set[str] = set()
    for row in combined:
        if row.training_row_id in seen_training_ids:
            raise HistoricalDatasetIntegrityError("duplicate training row identity")
        seen_training_ids.add(row.training_row_id)

    return tuple(
        sorted(
            combined,
            key=lambda item: (
                item.market.canonical,
                item.anchor_end_ms,
                item.horizon_ms,
                item.training_row_id,
            ),
        )
    )


def _row_payload(row: HistoricalTrainingRow) -> dict[str, object]:
    feature = row.feature
    outcome = row.outcome
    return {
        "training_row_id": row.training_row_id,
        "feature_id": row.feature_id,
        "outcome_id": row.outcome_id,
        "market": row.market.canonical,
        "anchor_end_ms": row.anchor_end_ms,
        "target_end_ms": outcome.target_end_ms,
        "horizon_ms": row.horizon_ms,
        "anchor_close_px": str(feature.anchor_close_px),
        "return_5m": None if feature.return_5m is None else str(feature.return_5m),
        "return_15m": None if feature.return_15m is None else str(feature.return_15m),
        "return_1h": None if feature.return_1h is None else str(feature.return_1h),
        "return_4h": None if feature.return_4h is None else str(feature.return_4h),
        "realized_vol_15m": (
            None if feature.realized_vol_15m is None else str(feature.realized_vol_15m)
        ),
        "range_expansion_15m": (
            None if feature.range_expansion_15m is None else str(feature.range_expansion_15m)
        ),
        "relative_volume_15m": (
            None if feature.relative_volume_15m is None else str(feature.relative_volume_15m)
        ),
        "funding_rate": None if feature.funding_rate is None else str(feature.funding_rate),
        "funding_change": (
            None if feature.funding_change is None else str(feature.funding_change)
        ),
        "funding_premium": (
            None if feature.funding_premium is None else str(feature.funding_premium)
        ),
        "funding_premium_change": (
            None
            if feature.funding_premium_change is None
            else str(feature.funding_premium_change)
        ),
        "funding_age_ms": feature.funding_age_ms,
        "candle_15m_age_ms": feature.candle_15m_age_ms,
        "btc_return_5m": (
            None if feature.btc_return_5m is None else str(feature.btc_return_5m)
        ),
        "btc_return_1h": (
            None if feature.btc_return_1h is None else str(feature.btc_return_1h)
        ),
        "btc_return_4h": (
            None if feature.btc_return_4h is None else str(feature.btc_return_4h)
        ),
        "eth_return_5m": (
            None if feature.eth_return_5m is None else str(feature.eth_return_5m)
        ),
        "eth_return_1h": (
            None if feature.eth_return_1h is None else str(feature.eth_return_1h)
        ),
        "eth_return_4h": (
            None if feature.eth_return_4h is None else str(feature.eth_return_4h)
        ),
        "market_median_return_5m": (
            None
            if feature.market_median_return_5m is None
            else str(feature.market_median_return_5m)
        ),
        "market_median_return_1h": (
            None
            if feature.market_median_return_1h is None
            else str(feature.market_median_return_1h)
        ),
        "market_breadth_positive_5m": (
            None
            if feature.market_breadth_positive_5m is None
            else str(feature.market_breadth_positive_5m)
        ),
        "market_breadth_positive_1h": (
            None
            if feature.market_breadth_positive_1h is None
            else str(feature.market_breadth_positive_1h)
        ),
        "market_relative_return_5m": (
            None
            if feature.market_relative_return_5m is None
            else str(feature.market_relative_return_5m)
        ),
        "market_relative_return_1h": (
            None
            if feature.market_relative_return_1h is None
            else str(feature.market_relative_return_1h)
        ),
        "trend_regime": feature.trend_regime.value,
        "availability_basis": feature.availability_basis,
        "source_retrieved_at_ms": feature.source_retrieved_at_ms,
        "retrieved_after_anchor": feature.retrieved_after_anchor,
        "available_features_json": _canonical_json(feature.available_features),
        "unavailable_features_json": _canonical_json(feature.unavailable_features),
        "provenance_json": _canonical_json(feature.provenance),
        "source_manifest_ids_json": _canonical_json(feature.source_manifest_ids),
        "entry_px": str(outcome.entry_px),
        "exit_px": str(outcome.exit_px),
        "long_gross_return": str(outcome.long_gross_return),
        "short_gross_return": str(outcome.short_gross_return),
        "feature_schema_version": feature.schema_version,
        "outcome_schema_version": outcome.schema_version,
        "training_schema_version": row.schema_version,
    }


def _logical_sha256(rows: Sequence[Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update((_canonical_json(dict(row)) + "\n").encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class HistoricalDatasetManifest:
    output_relative_path: str
    output_sha256: str
    output_byte_count: int
    row_count: int
    logical_sha256: str
    markets: tuple[str, ...]
    horizons_ms: tuple[int, ...]
    source_manifest_ids: tuple[str, ...]
    writer_library_version: str
    columns: tuple[str, ...] = TRAINING_COLUMNS
    converter_version: str = DATASET_CONVERTER_VERSION
    schema_version: int = DATASET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.output_relative_path != OUTPUT_FILENAME:
            raise ValueError(f"output_relative_path must be {OUTPUT_FILENAME}")
        for field, value in (
            ("output_sha256", self.output_sha256),
            ("logical_sha256", self.logical_sha256),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{field} must be a lowercase SHA-256 digest")
        if self.output_byte_count <= 0:
            raise ValueError("output_byte_count must be positive")
        if self.row_count <= 0:
            raise ValueError("row_count must be positive")
        if not self.markets or any(not item.strip() for item in self.markets):
            raise ValueError("markets must contain non-empty identities")
        if not self.horizons_ms or any(value <= 0 for value in self.horizons_ms):
            raise ValueError("horizons_ms must contain positive values")
        if not self.source_manifest_ids or any(
            not item.strip() for item in self.source_manifest_ids
        ):
            raise ValueError("source_manifest_ids must contain non-empty identities")
        if not self.writer_library_version.strip():
            raise ValueError("writer_library_version must not be empty")
        if tuple(self.columns) != TRAINING_COLUMNS:
            raise ValueError("columns must match the historical training schema")
        if not self.converter_version.strip():
            raise ValueError("converter_version must not be empty")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        object.__setattr__(self, "markets", tuple(sorted(set(self.markets))))
        object.__setattr__(self, "horizons_ms", tuple(sorted(set(self.horizons_ms))))
        object.__setattr__(
            self,
            "source_manifest_ids",
            tuple(sorted(set(self.source_manifest_ids))),
        )

    @property
    def dataset_id(self) -> str:
        payload = {
            "logical_sha256": self.logical_sha256,
            "row_count": self.row_count,
            "markets": self.markets,
            "horizons_ms": self.horizons_ms,
            "source_manifest_ids": self.source_manifest_ids,
            "columns": self.columns,
            "converter_version": self.converter_version,
            "schema_version": self.schema_version,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "output_relative_path": self.output_relative_path,
            "output_sha256": self.output_sha256,
            "output_byte_count": self.output_byte_count,
            "row_count": self.row_count,
            "logical_sha256": self.logical_sha256,
            "markets": self.markets,
            "horizons_ms": self.horizons_ms,
            "source_manifest_ids": self.source_manifest_ids,
            "writer_library_version": self.writer_library_version,
            "columns": self.columns,
            "converter_version": self.converter_version,
            "schema_version": self.schema_version,
        }


def export_training_dataset(
    rows: Sequence[HistoricalTrainingRow],
    output_root: Path,
) -> HistoricalDatasetManifest:
    ordered = tuple(
        sorted(
            rows,
            key=lambda item: (
                item.market.canonical,
                item.anchor_end_ms,
                item.horizon_ms,
                item.training_row_id,
            ),
        )
    )
    if not ordered:
        raise ValueError("training rows must not be empty")
    identities = tuple(row.training_row_id for row in ordered)
    if len(set(identities)) != len(identities):
        raise HistoricalDatasetIntegrityError("duplicate training row identity")

    payloads = tuple(_row_payload(row) for row in ordered)
    logical_sha256 = _logical_sha256(payloads)
    pyarrow, parquet = _load_pyarrow()
    table = pyarrow.Table.from_pylist(list(payloads))
    table = table.select(list(TRAINING_COLUMNS))

    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / OUTPUT_FILENAME
    temporary = output_root / f".{OUTPUT_FILENAME}.tmp"
    try:
        parquet.write_table(
            table,
            temporary,
            compression="zstd",
            version="2.6",
            use_dictionary=True,
        )
        with temporary.open("rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
        directory_fd = os.open(output_root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()

    raw = output_path.read_bytes()
    source_manifest_ids = tuple(
        sorted(
            {
                manifest_id
                for row in ordered
                for manifest_id in row.feature.source_manifest_ids
            }
        )
    )
    manifest = HistoricalDatasetManifest(
        output_relative_path=OUTPUT_FILENAME,
        output_sha256=_sha256_bytes(raw),
        output_byte_count=len(raw),
        row_count=len(ordered),
        logical_sha256=logical_sha256,
        markets=tuple(row.market.canonical for row in ordered),
        horizons_ms=tuple(row.horizon_ms for row in ordered),
        source_manifest_ids=source_manifest_ids,
        writer_library_version=_string(
            getattr(pyarrow, "__version__", None),
            "pyarrow.__version__",
        ),
    )
    _atomic_write(
        output_root / "manifest.json",
        (_canonical_json(manifest.to_dict()) + "\n").encode("utf-8"),
    )
    return manifest
