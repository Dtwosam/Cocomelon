"""Original GitHub source and account-handoff evidence never imply trading authority."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from cocomelon.research.prospective_both_side_trend_paired_freeze import (
    TRIAL_ID,
    both_side_trend_matched_shadow_freeze,
)
from cocomelon.research.trend_paired_shadow_sidecar import (
    TREND_PAIR_FREEZE_FILE,
    TREND_PAIR_STATE_ROOT,
    TREND_PAIR_SUMMARY_FILE,
)
from scripts import audit_both_side_trend_paired_handoff as audit

REPO = "Dtwosam/Cocomelon"
RUN = 456789
ATTEMPT = 1


def _source() -> tuple[dict[str, object], dict[str, object]]:
    run: dict[str, object] = {
        "id": RUN,
        "run_attempt": ATTEMPT,
        "name": "Continuous Paper · 38247356164",
        "path": ".github/workflows/continuous-paper.yml",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": REPO},
    }
    jobs: dict[str, object] = {
        "jobs": [{
            "run_id": RUN, "run_attempt": ATTEMPT,
            "name": "paper",
            "steps": [
                {"name": "Run continuous paper trader", "conclusion": "success"},
                {
                    "name": "Upload isolated both-side trend paired-paper evidence",
                    "conclusion": "success",
                },
            ],
        }],
    }
    return run, jobs


def _artifact(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("unrelated.txt", "source")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    artifacts: dict[str, object] = {
        "artifacts": [{
            "name": f"continuous-paper-both-side-trend-paired-shadow-{RUN}-{ATTEMPT}",
            "id": 5678,
            "digest": f"sha256:{digest}",
            "expired": False,
        }],
    }
    return archive, artifacts


def _audit(tmp_path: Path) -> dict[str, object]:
    run, jobs = _source()
    archive, artifacts = _artifact(tmp_path)
    return audit.audit_trend_handoff(
        run=run, jobs=jobs, artifacts=artifacts,
        archive=archive, repository=REPO,
        source_run_id=RUN, source_attempt=ATTEMPT,
    )


def test_genuine_completed_worker_must_match_one_exact_attempt() -> None:
    run, jobs = _source()
    assert audit._source_class(
        run=run, jobs=jobs, repository=REPO,
        run_id=RUN, attempt=ATTEMPT,
    ) == "completed_successful_worker"
    run["conclusion"] = "failure"
    assert audit._source_class(
        run=run, jobs=jobs, repository=REPO,
        run_id=RUN, attempt=ATTEMPT,
    ) == "completed_non_success_worker"

    run["conclusion"] = "success"
    altered_jobs = json.loads(json.dumps(jobs))
    altered_jobs["jobs"][0]["run_attempt"] = ATTEMPT + 1
    with pytest.raises(
        audit.TrendPairHandoffAuditError, match="exact attempt",
    ):
        audit._source_class(
            run=run, jobs=altered_jobs, repository=REPO,
            run_id=RUN, attempt=ATTEMPT,
        )
    altered_jobs["jobs"][0]["run_attempt"] = ATTEMPT
    altered_jobs["jobs"][0]["steps"][1]["conclusion"] = "failure"
    with pytest.raises(
        audit.TrendPairHandoffAuditError, match="not both proven",
    ):
        audit._source_class(
            run=run, jobs=altered_jobs, repository=REPO,
            run_id=RUN, attempt=ATTEMPT,
        )


def test_custom_github_run_name_allowed_but_workflow_path_fixed() -> None:
    run, jobs = _source()
    assert audit._source_class(
        run=run, jobs=jobs, repository=REPO,
        run_id=RUN, attempt=ATTEMPT,
    ) == "completed_successful_worker"
    run["name"] = "A harmless different run name"
    assert audit._source_class(
        run=run, jobs=jobs, repository=REPO,
        run_id=RUN, attempt=ATTEMPT,
    ) == "completed_successful_worker"
    run["path"] = ".github/workflows/other.yml"
    with pytest.raises(
        audit.TrendPairHandoffAuditError, match="source worker identity",
    ):
        audit._source_class(
            run=run, jobs=jobs, repository=REPO,
            run_id=RUN, attempt=ATTEMPT,
        )
    run["path"] = ".github/workflows/continuous-paper.yml"
    run["event"] = "pull_request"
    with pytest.raises(
        audit.TrendPairHandoffAuditError, match="not a recognized",
    ):
        audit._source_class(
            run=run, jobs=jobs, repository=REPO,
            run_id=RUN, attempt=ATTEMPT,
        )


def test_exact_outer_zip_sha256_is_mandatory(tmp_path: Path) -> None:
    archive, metadata = _artifact(tmp_path)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert audit._validate_artifact(
        metadata, archive, run_id=RUN, attempt=ATTEMPT,
    ) == actual
    archive.write_bytes(archive.read_bytes() + b"tampering")
    with pytest.raises(audit.TrendPairHandoffAuditError, match="SHA256"):
        audit._validate_artifact(
            metadata, archive, run_id=RUN, attempt=ATTEMPT,
        )


def test_missing_trend_zip_is_explicitly_unverified(tmp_path: Path) -> None:
    receipt = _audit(tmp_path)
    assert receipt["status"] == "unverified"
    assert receipt["archived_execution_sqlite_integrity_verified"] is False
    assert receipt["archived_execution_economics_reconciled"] is False
    assert "paired" in str(receipt["reasons"])
    assert receipt["source_class"] == "completed_successful_worker"
    assert receipt["archive_sha256"] is not None
    assert receipt["execution_authority"] is False
    assert receipt["promotion_authority"] is False
    assert receipt["durable_execution_sqlite_replay_verified"] is False
    assert receipt["full_forward_after_cost_profit_verified"] is False


def test_archive_reader_requires_explicit_exact_paths_and_both_stores(
    tmp_path: Path,
) -> None:
    freeze = both_side_trend_matched_shadow_freeze()
    baseline_path = tmp_path / "valid-baseline.sqlite3"
    _make_paper_sqlite(baseline_path)
    zip_path = tmp_path / "trend.zip"
    with zipfile.ZipFile(zip_path, "w") as zipped:
        zipped.writestr(
            f"continuous-paper-state/{TREND_PAIR_FREEZE_FILE}",
            json.dumps(freeze.to_dict()),
        )
        zipped.writestr(
            f"continuous-paper-state/{TREND_PAIR_SUMMARY_FILE}",
            json.dumps({"checkpoint_published": False}),
        )
        zipped.writestr(
            f"continuous-paper-state/{TREND_PAIR_STATE_ROOT}/paired-shadow-state.json",
            json.dumps({"schema_version": 2}),
        )
        zipped.writestr(
            f"continuous-paper-state/{TREND_PAIR_STATE_ROOT}/review-ledger.jsonl",
            "{}\n",
        )
        zipped.write(
            baseline_path,
            f"continuous-paper-state/{TREND_PAIR_STATE_ROOT}/baseline-execution.sqlite3",
        )
    with pytest.raises(
        audit.TrendPairHandoffAuditError, match="candidate execution store",
    ):
        audit._extract_receipts(zip_path, tmp_path)



def _make_paper_sqlite(path: Path, *, version: str = "1") -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE paper_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE paper_order_plans (plan_id TEXT PRIMARY KEY, payload_json TEXT);
            CREATE TABLE paper_execution_attempts (attempt_id TEXT PRIMARY KEY, payload_json TEXT);
            CREATE TABLE paper_fills (fill_id TEXT PRIMARY KEY, payload_json TEXT);
            CREATE TABLE paper_positions (market TEXT PRIMARY KEY, payload_json TEXT);
            CREATE TABLE paper_position_events (event_id TEXT PRIMARY KEY, payload_json TEXT);
            CREATE TABLE paper_funding_events (accrual_id TEXT PRIMARY KEY, payload_json TEXT);
            CREATE TABLE paper_account_state (singleton_id INTEGER PRIMARY KEY, payload_json TEXT);
            CREATE TABLE paper_rolling_peak_candidates (ordinal INTEGER PRIMARY KEY, equity TEXT);
            """
        )
        conn.execute(
            "INSERT INTO paper_meta (key, value) VALUES ('schema_version', ?)",
            (version,),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("lane", ["baseline", "candidate"])
def test_archived_execution_store_sqlite_integrity_is_read_only(
    tmp_path: Path, lane: str,
) -> None:
    source = tmp_path / "paper.sqlite3"
    _make_paper_sqlite(source)
    zip_path = tmp_path / "store.zip"
    with zipfile.ZipFile(zip_path, "w") as zipped:
        zipped.write(
            source,
            f"continuous-paper-state/{TREND_PAIR_STATE_ROOT}/{lane}-execution.sqlite3",
        )
    with zipfile.ZipFile(zip_path) as zipped:
        audit._verify_archived_execution_store(zipped, tmp_path, lane=lane)
    extracted = tmp_path / f"{lane}-execution.sqlite3"
    assert extracted.read_bytes() == source.read_bytes()
    assert not (tmp_path / f"{lane}-execution.sqlite3-wal").exists()


@pytest.mark.parametrize(
    ("store_bytes", "version", "error"),
    [
        (b"not an SQLite database", None, "unreadable"),
        (None, "9", "schema version mismatch"),
    ],
)
def test_archived_execution_store_rejects_corruption_or_schema_drift(
    tmp_path: Path, store_bytes: bytes | None, version: str | None, error: str,
) -> None:
    source = tmp_path / "paper.sqlite3"
    if store_bytes is not None:
        source.write_bytes(store_bytes)
    else:
        _make_paper_sqlite(source, version=version or "1")
    zip_path = tmp_path / "store.zip"
    with zipfile.ZipFile(zip_path, "w") as zipped:
        zipped.write(
            source,
            f"{TREND_PAIR_STATE_ROOT}/baseline-execution.sqlite3",
        )
    with zipfile.ZipFile(zip_path) as zipped:
        with pytest.raises(audit.TrendPairHandoffAuditError, match=error):
            audit._verify_archived_execution_store(zipped, tmp_path, lane="baseline")


def test_archived_execution_store_rejects_duplicate_members(
    tmp_path: Path,
) -> None:
    import warnings

    source = tmp_path / "paper.sqlite3"
    _make_paper_sqlite(source)
    member = f"{TREND_PAIR_STATE_ROOT}/candidate-execution.sqlite3"
    zip_path = tmp_path / "duplicate-stores.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(zip_path, "w") as zipped:
            zipped.write(source, member)
            zipped.write(source, member)
    with zipfile.ZipFile(zip_path) as zipped:
        with pytest.raises(audit.TrendPairHandoffAuditError, match="ambiguous"):
            audit._verify_archived_execution_store(zipped, tmp_path, lane="candidate")


def test_duplicate_zip_member_cannot_override_signed_freeze(tmp_path: Path) -> None:
    import warnings

    archive_path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive_path, "w") as zipped:
        zipped.writestr(TREND_PAIR_FREEZE_FILE, b"one")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            zipped.writestr(TREND_PAIR_FREEZE_FILE, b"two")
    with zipfile.ZipFile(archive_path) as zipped:
        with pytest.raises(
            audit.TrendPairHandoffAuditError, match="ambiguous",
        ):
            audit._member(zipped, TREND_PAIR_FREEZE_FILE)


def _economic_store_fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    """A one-trade LONG account with independently recomputable cashflow."""
    path = tmp_path / "paired-economic.sqlite3"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE paper_order_plans (
                plan_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL
            );
            CREATE TABLE paper_execution_attempts (
                attempt_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE paper_fills (
                fill_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL,
                plan_id TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE paper_funding_events (
                accrual_id TEXT PRIMARY KEY, market TEXT NOT NULL,
                boundary_ms INTEGER NOT NULL, position_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE paper_account_state (
                singleton_id INTEGER PRIMARY KEY,
                state_id TEXT, payload_json TEXT NOT NULL
            );
            CREATE TABLE paper_positions (
                market TEXT PRIMARY KEY, payload_json TEXT NOT NULL
            );
            """
        )
        for plan_id, reduce_only, side in (
            ("open", False, "buy"), ("close", True, "sell")
        ):
            conn.execute(
                "INSERT INTO paper_order_plans VALUES (?, ?)",
                (
                    plan_id,
                    json.dumps({
                        "market": "TEST", "side": side,
                        "reduce_only": reduce_only,
                    }),
                ),
            )
        for index, (plan_id, price) in enumerate(
            (("open", "10"), ("close", "11"))
        ):
            attempt_id = f"attempt-{index}"
            conn.execute(
                "INSERT INTO paper_execution_attempts VALUES (?,?,?)",
                (
                    attempt_id, plan_id,
                    json.dumps({
                        "plan_id": plan_id, "filled_quantity": "2",
                        "requested_quantity": "2", "unfilled_quantity": "0",
                        "gross_fill_notional": str(2 * int(price)),
                        "average_fill_price": price,
                        "fee": "0.01",
                        "attempt_timestamp_ms": 1000 + 2000 * index,
                    }),
                ),
            )
            conn.execute(
                "INSERT INTO paper_fills VALUES (?,?,?,?)",
                (
                    f"fill-{index}", attempt_id, plan_id,
                    json.dumps({
                        "attempt_id": attempt_id, "plan_id": plan_id,
                        "price": price, "quantity": "2",
                        "notional": str(2 * int(price)),
                        "taker_fee": "0.01",
                    }),
                ),
            )
        conn.execute(
            "INSERT INTO paper_account_state VALUES (1,?,?)",
            (
                "signed-account-1",
                json.dumps({
                    "starting_cash": "1000", "cash": "1001.98",
                    "equity": "1001.98", "unrealized_pnl": "0",
                    "realized_gross_pnl": "2",
                    "cumulative_fees": "0.02", "cumulative_funding": "0",
                    "positions": [],
                }),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    ledger: dict[str, object] = {
        "equity": "1001.98", "realized_net_pnl": "1.98",
        "total_account_pnl": "1.98",
        "closed_trade_count": 1, "open_position_count": 0,
        "opening_fills": 1, "opening_execution_attempts": 1,
        "long_closed_trade_count": 1, "short_closed_trade_count": 0,
        "long_closed_net_pnl": "1.98", "short_closed_net_pnl": "0",
    }
    return path, ledger


def test_independent_replay_reconciles_realized_fill_cashflows(
    tmp_path: Path,
) -> None:
    path, ledger = _economic_store_fixture(tmp_path)
    replay = audit._reconcile_archived_lane_economics(
        path, account_state_id="signed-account-1", ledger_lane=ledger,
    )
    assert replay["closed_trades_from_fills"] == 1
    assert replay["realized_gross_from_fills"] == "2"
    assert replay["fees_from_fills"] == "0.02"
    assert replay["realized_net_from_fills"] == "1.98"


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        ("fill_fee", "fill fee sum"),
        ("ledger_equity", "signed ledger equity"),
        ("ledger_closed_profit", "signed long closed net PnL"),
        ("account_id", "account state identity"),
        ("opening_price", "weighted average fill price"),
    ],
)
def test_independent_replay_fails_closed_on_mismatched_economics(
    tmp_path: Path, tamper: str, expected: str,
) -> None:
    path, ledger = _economic_store_fixture(tmp_path)
    account_id = "signed-account-1"
    if tamper == "fill_fee":
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM paper_fills WHERE fill_id='fill-0'"
            ).fetchone()
            payload = json.loads(row[0])
            payload["taker_fee"] = "0.11"
            conn.execute(
                "UPDATE paper_fills SET payload_json=? WHERE fill_id='fill-0'",
                (json.dumps(payload),),
            )
    elif tamper == "ledger_equity":
        ledger["equity"] = "1011.98"
    elif tamper == "ledger_closed_profit":
        ledger["long_closed_net_pnl"] = "10.98"
    elif tamper == "account_id":
        account_id = "forged-account"
    elif tamper == "opening_price":
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM paper_execution_attempts "
                "WHERE attempt_id='attempt-0'"
            ).fetchone()
            payload = json.loads(row[0])
            payload["average_fill_price"] = "11"
            conn.execute(
                "UPDATE paper_execution_attempts SET payload_json=? "
                "WHERE attempt_id='attempt-0'",
                (json.dumps(payload),),
            )
    with pytest.raises(audit.TrendPairHandoffAuditError, match=expected):
        audit._reconcile_archived_lane_economics(
            path, account_state_id=account_id, ledger_lane=ledger,
        )


def test_consistent_receipts_only_verify_archive_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, jobs = _source()
    archive, artifacts = _artifact(tmp_path)
    freeze = both_side_trend_matched_shadow_freeze()
    state: dict[str, object] = {
        "portfolio_shadow_candidate_id": freeze.candidate_id,
        "review_ledger_row_count": 1,
        "review_ledger_latest_row_digest": "f" * 64,
        "promotion_authority": False,
        "execution_authority": False,
        "research_only": True,
        "paper_only": True,
        "shadow_only": True,
    }
    state["state_digest"] = audit._signed_digest(state)
    summary: dict[str, object] = {
        "trial_id": TRIAL_ID,
        "frozen_forward_not_before_ms": freeze.prospective_not_before_ms,
        "checkpoint_published": True,
        "checkpoint_error": None,
        "checkpoint": state,
        "research_only": True,
        "paper_only": True,
        "shadow_only": True,
        "promotion_authority": False,
        "execution_authority": False,
        "forward_profitable_signed_account_edge_proven": False,
        "original_mainnet_source_and_gaps_independently_authenticated": False,
    }
    monkeypatch.setattr(
        audit, "_extract_receipts",
        lambda _zip, _tmp: (
            freeze.to_dict(), summary, state, tmp_path / "ledger.jsonl",
        ),
    )
    monkeypatch.setattr(
        audit, "review_ledger_receipt",
        lambda *_args, **_kwargs: {
            "row_count": 1, "latest_row_digest": "f" * 64,
        },
    )
    monkeypatch.setattr(
        audit, "_reconcile_archived_lane_economics",
        lambda *_args, **_kwargs: {"closed_trades_from_fills": 0},
    )
    monkeypatch.setattr(
        audit, "build_paired_shadow_review",
        lambda *_args: {"ready_for_review": False},
    )
    receipt = audit.audit_trend_handoff(
        run=run, jobs=jobs, artifacts=artifacts,
        archive=archive, repository=REPO,
        source_run_id=RUN, source_attempt=ATTEMPT,
    )
    assert receipt["status"] == "archive_checkpoint_lineage_verified"
    assert receipt["archived_execution_sqlite_integrity_verified"] is True
    assert receipt["archived_execution_economics_reconciled"] is True
    assert receipt["verified_checkpoint_count"] == 1
    assert receipt["reasons"] == ["economic_review_not_ready"]
    assert receipt["durable_execution_sqlite_replay_verified"] is False
    assert receipt["full_forward_after_cost_profit_verified"] is False
    assert receipt["independent_mainnet_market_source_authenticated"] is False
    assert receipt["promotion_authority"] is False
    assert receipt["execution_authority"] is False

    state["state_digest"] = "0" * 64
    corrupted = audit.audit_trend_handoff(
        run=run, jobs=jobs, artifacts=artifacts,
        archive=archive, repository=REPO,
        source_run_id=RUN, source_attempt=ATTEMPT,
    )
    assert corrupted["status"] == "unverified"
    assert "digest mismatch" in str(corrupted["reasons"])


def test_independent_audit_workflow_can_never_place_orders() -> None:
    workflow = Path(
        ".github/workflows/independent-both-side-trend-handoff-audit.yml"
    ).read_text()
    assert "workflow_run:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "Continuous Mainnet Paper Trader" in workflow
    assert "head_branch == 'main'" in workflow
    assert "  actions: read" in workflow
    assert "  contents: read" in workflow
    assert "actions: write" not in workflow
    assert "issues: write" not in workflow
    assert "gh workflow run" not in workflow
    assert "gh_api_bounded_retry" in workflow
    assert "--artifact-zip /tmp/trend-paper-audit/source.zip" in workflow
    assert "audit_both_side_trend_paired_handoff.py" in workflow
    assert "original market feed gaps independently authenticated: FALSE" in workflow
    assert "live execution / promotion authority: FALSE / FALSE" in workflow


def test_trend_audit_bootstraps_first_real_zip_without_workflow_chain() -> None:
    """A push of the audit itself rechecks real worker 38261652982."""
    workflow = Path(
        ".github/workflows/independent-both-side-trend-handoff-audit.yml"
    ).read_text(encoding="utf-8")
    assert "  push:\n    branches:\n      - main\n    paths:" in workflow
    assert (
        '      - ".github/workflows/independent-both-side-trend-handoff-audit.yml"'
        in workflow
    )
    assert "github.event_name == 'push' && '38261652982'" in workflow
    assert "github.event_name == 'push' && '1'" in workflow
    assert '--source-run-id "$SOURCE_RUN_ID"' in workflow
    assert '--source-attempt "$SOURCE_ATTEMPT"' in workflow
    assert "permissions:\n  actions: read\n  contents: read" in workflow
    assert "gh workflow run" not in workflow


def test_trend_audit_scheduled_fallback_targets_real_archived_source() -> None:
    """Scheduled runner must ignore bootstrap runs and absent artifact ZIPs."""
    workflow = Path(
        ".github/workflows/independent-both-side-trend-handoff-audit.yml"
    ).read_text(encoding="utf-8")
    assert "  schedule:" in workflow
    assert 'cron: "17 */3 * * *"' in workflow
    assert "github.event_name == 'schedule'" in workflow
    assert "runs?status=completed&branch=main&per_page=50" in workflow
    assert '.event == "workflow_dispatch"' in workflow
    assert '.head_branch == "main"' in workflow
    assert '.path == ".github/workflows/continuous-paper.yml"' in workflow
    assert "continuous-paper-both-side-trend-paired-shadow-$run_id-$run_attempt" in workflow
    assert '.name == $name and .expired == false' in workflow
    assert '| length == 1' in workflow
    # Must interpolate an actual jq source run ID, not literal syntax.
    assert r'| "\(.id) \(.run_attempt)"' in workflow
    assert r'| "\\(.id) \\(.run_attempt)"' not in workflow
    # Must write two real environment lines for separate audit steps.
    assert r"printf 'SOURCE_RUN_ID=%s\nSOURCE_ATTEMPT=%s\n'" in workflow
    assert ">> \"$GITHUB_ENV\"" in workflow
    assert "No completed original worker with exact trend archive" in workflow
    assert "source scripts/gh_api_bounded_retry.sh" in workflow
    assert "actions: write" not in workflow
    assert "issues: write" not in workflow
