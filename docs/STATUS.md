# Cocomelon Project Status

**Last updated:** 2026-08-24  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Live trading:** **DISABLED**

## Current state

**Latest merged engineering milestone:** Phase 9 genuine-mainnet evidence campaign controls and fail-fast acquisition support  
**Phase 9 evaluator:** MERGED  
**Phase 9 evidence aggregation:** PR #23 — MERGED at `d404fa8c077c2721de55eda7f7fb2854d590ce4f`  
**Phase 9 genuine-mainnet attestation:** PR #25 — MERGED at `ef3c728e310be6a5b1ed94934a77453fba9c63cd`  
**Phase 9 offline cohort verification:** PR #27 — MERGED at `7be48ed59aa073015042881cbfbe75caa7e08f08`  
**Phase 9 evidence-progress precheck:** PR #28 — MERGED at `ae31c1f7445fb8622a393e5e6223157a6c0cf54b`  
**Phase 9 fail-fast gap watcher:** PR #29 — MERGED at `390d4ba39abe4fe3f476af68587f13f2371d9cba`  
**Pinned trading/evidence revision under test:** `571c13bfe0bab0312940617540ec973ee3eee3c5`  
**Pinned operational gap-watcher revision:** `390d4ba39abe4fe3f476af68587f13f2371d9cba`  
**Current evidence-runner head:** `7f577c6cf19d6c001183247c3736037fe95bffee` on intentionally unmerged PR #22  
**Real baseline evidence status:** **UNMEASURED**  
**Phase 9 economic/research exit gate:** PENDING sufficient clean attested genuine-mainnet evidence  
**Phase 10:** BLOCKED pending a genuine Phase 9 baseline evaluation that satisfies the locked evidence policy

`main` was verified at `390d4ba39abe4fe3f476af68587f13f2371d9cba` after merging PR #29.

## Phase 9 evaluator

The merged Phase 9 evaluator provides deterministic, fail-closed research gates around trusted Phase 8 replay/journal outputs. It includes immutable evaluation facts and datasets, time-based train/validation/test partitions, six-hour purge/embargo, untouched-OOS consumption tracking, deterministic cost-aware metrics and bootstrap confidence intervals, walk-forward evaluation, market/regime/strategy/direction/time/score-bucket diagnostics, fixed predeclared fee/slippage/funding stress profiles, sampled `NO_TRADE` diagnostics, and five explicit evidence states:

- `INVALID_EVIDENCE`
- `OOS_CONTAMINATED`
- `INSUFFICIENT_EVIDENCE`
- `NO_EDGE_DEMONSTRATED`
- `CANDIDATE_EDGE`

Its versioned V1 research policy remains:

- minimum untouched OOS trades: 100;
- minimum OOS covered days: 30;
- minimum eligible walk-forward windows: 3;
- minimum trades per walk-forward window: 20;
- minimum score-bucket trades: 20;
- minimum positive walk-forward-window fraction: 60%;
- bootstrap confidence: 95%;
- day-block bootstrap size: 5 days;
- bootstrap resamples: 2,000;
- split embargo: 6 hours;
- sampled `NO_TRADE` horizons: 1 hour and 4 hours.

`CANDIDATE_EDGE` additionally requires positive untouched-test mean net R, bootstrap lower bound > 0, positive/stable eligible walk-forward behavior, market positive-PnL concentration <=35%, and seven-day concentration <=50%.

## Genuine-mainnet evidence pipeline

The Phase 9 evidence path supports genuine public Hyperliquid mainnet recordings through deterministic paper replay and evaluation without enabling live trading.

Merged capability includes:

- public Hyperliquid mainnet-only recording with immutable recording-session identity;
- pinned source-code revision binding for the strategy/risk/execution code under test;
- offline frozen replay bundles and deterministic baseline replay;
- canonical replay/journal/fact aggregation across separate cohort artifacts sharing one fixed code revision;
- idempotent evidence-store merging with rollback-safe pair replacement;
- genuine-mainnet attestation that binds cohort metadata to canonical replay results, bundle/session identity, code revision, and source-file digests;
- rejection of non-mainnet endpoints, live-order semantics, gaps, duplicates, anomalies, incomplete replays, metadata/replay mismatches, reused recording sessions, and overlapping cohort time windows;
- exact-attested-run-set dataset freezing to prevent post-hoc favorable-run selection;
- a dedicated offline-only `cocomelon-mainnet-evidence` command surface with `verify`, `aggregate`, `progress`, and `freeze-dataset`;
- a counts-only `progress` precheck that reports attested run count, closed trades, closed-trade days, and shortfalls versus the locked 100-trade/30-day minimum without computing PnL or edge;
- canonical closed-trade cross-checking before progress counts are reported, preventing post-attestation journal additions from inflating campaign progress;
- no testnet, live-order, wallet, signing, transfer, withdrawal, private-account, optimizer/search, or Phase 10 activation path in the evidence tool.

## Evidence acquisition controls

PR #29 added a small stdlib-only operational watcher that observes the durable recorder `gaps/` partition and sends `SIGTERM` to the known recorder child process on the first non-empty fsynced gap segment. The helper does not import market-data, strategy, risk, execution, wallet, or network capability.

The intentionally unmerged evidence-runner PR #22 is now at `7f577c6cf19d6c001183247c3736037fe95bffee` and has been hardened to:

- keep trading/replay code pinned independently at `571c13bfe0bab0312940617540ec973ee3eee3c5`;
- pin the operational gap watcher independently at `390d4ba39abe4fe3f476af68587f13f2371d9cba`;
- terminate a dirty 45-minute acquisition attempt after the first durable gap instead of knowingly spending the rest of the attempt on inadmissible evidence;
- preserve per-attempt recorder/watcher exit statuses, timestamps, recording-session metadata, recorder manifest, watcher output, and gap rows as diagnostics before retrying;
- still require final recorder-reported zero gaps, zero duplicates, zero anomalies, public-network recording, and `live_orders=false` before accepting a cohort;
- serialize future PR #22 workflow runs with a per-PR concurrency group and `cancel-in-progress=false`, preserving the active cohort while preventing overlapping successors.

The runner-control integration was staged and CI-checked on PR #30 against the runner branch. PR #22 was temporarily retargeted away from `main` while that staging PR was merged into its head, then restored to `main`; verification showed only normal CI was launched for the new runner head, not another evidence cohort. This avoided overlapping the still-running cohort.

## First genuine 30-minute mainnet cohort

GitHub Actions run `32770800218` produced immutable artifact `genuine-mainnet-evidence-cohort-32770800218-attempt-1` from the pinned trading revision `571c13bfe0bab0312940617540ec973ee3eee3c5`.

The artifact is genuine public Hyperliquid mainnet evidence and paper-only:

- workflow checkout revision: `571c13bfe0bab0312940617540ec973ee3eee3c5`;
- runner trigger head: `6ea9915738dd80930a36a749b5f5a5e0343e8fe2`;
- recording network access: `true`;
- replay network access: `false`;
- live orders: `false` throughout;
- duration: 1,800 seconds;
- selected markets: `AERO`, `CASHCAT`, `ENA`, `PUMP`, `PURR`;
- recorded market events: 360,404;
- duplicate events: 0;
- anomalies: 0;
- reconnects: 1;
- recorded gaps: 60;
- validated rows including gap records: 360,464 across 980 segments;
- strategy decisions: 10;
- risk approvals: 2;
- risk rejections: 0;
- execution attempts: 1;
- fills: 3;
- opened positions: 1;
- closed positions: 0;
- closed trades: 0;
- final paper equity: `9992.897173445500000000000000` while an ENA short remained open;
- replay `data_complete`: `false`;
- frozen evaluation dataset trades: 0.

The 60 gaps came from one websocket disconnect/recovery episode across subscribed channels. Because the cohort is incomplete and has no closed trades, it is **not admissible economic evidence** and the merged attestation path rejects it before it can enter the real Phase 9 aggregate.

The final equity value above is not a realized profitability result because the cohort ended with an open paper position and incomplete market-data coverage.

Therefore:

**REAL BASELINE EDGE: UNMEASURED**

This result is not `NO_EDGE_DEMONSTRATED`; it is insufficient/inadmissible evidence for an economic conclusion.

## Evidence campaign status

GitHub Actions run `32781582212` is the second non-overlapping genuine-mainnet paper cohort under the same pinned trading revision. It was triggered at runner head `164d58c343afde64d422aa472442d39b46b3041b`, before the fail-fast watcher and concurrency hardening were promoted to PR #22, so those controls do not retroactively change this in-flight run. Its result must be inspected and attested before any inclusion in the economic corpus.

Future PR #22 cohorts use the hardened runner head `7f577c6cf19d6c001183247c3736037fe95bffee` and therefore inherit fail-fast gap handling plus serialized execution.

The 30-day untouched-OOS coverage requirement cannot be accelerated by overlapping captures. Evidence collection must therefore favor temporally distinct, non-overlapping cohorts while preserving the same fixed trading revision for the evaluation campaign.

## Completed engineering phases

- Phase 0 — governance/source-of-truth anchor: COMPLETE.
- Phase 1 — Python foundation/domain/config/CI: MERGED at `3efd9e28b84eaa5dcd75f6949d8df02e2928d163`.
- Phase 2 — mainnet REST discovery/normalization: MERGED at `b95352e238d6a9eabd63e13c1f8300e654a7e636`.
- Phase 3 — WebSocket collector/durable recorder: MERGED at `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57`.
- Phase 4 — feature engine/scanner/ranking/shortlist: MERGED at `dae7cf6cf51af9def0a027529d2b0900a6a4d5f6`.
- Phase 5 — explainable baseline strategy engines: MERGED at `82c3db2f9ce39676e089eac79e63c5043b72e331`.
- Phase 6 — independent risk engine: MERGED at `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`.
- Phase 7 — real-mainnet paper execution + position manager: MERGED at `5cd4b3603cf05d2e5dc2cc3a165c026a01b2fcab`.
- Phase 8 — deterministic journal/replay/backtester + analytical compaction: MERGED at `f7f37044997e13b3ffe91edd312756862343782b`.
- Phase 9 — deterministic evaluation/OOS/walk-forward infrastructure: MERGED at `97218fdec7b8896ce63cf5889dbe41fb39f97bd7`.
- Phase 9 Evidence Bridge: MERGED at `dec15b53d00bf5e65ba4c017aba0159c98d0088d`.
- Phase 9 execution-activity replay accounting repair: PR #21 — MERGED at `ed3cae5af4a7b971babecec28448675c19d10bf6`.
- Phase 9 fixed-revision evidence-store aggregation: PR #23 — MERGED at `d404fa8c077c2721de55eda7f7fb2854d590ce4f`.
- Phase 9 genuine-mainnet attestation and economic-corpus boundary: PR #25 — MERGED at `ef3c728e310be6a5b1ed94934a77453fba9c63cd`.
- Phase 9 single-cohort offline verifier: PR #27 — MERGED at `7be48ed59aa073015042881cbfbe75caa7e08f08`.
- Phase 9 attested evidence progress precheck: PR #28 — MERGED at `ae31c1f7445fb8622a393e5e6223157a6c0cf54b`.
- Phase 9 fail-fast durable-gap watcher: PR #29 — MERGED at `390d4ba39abe4fe3f476af68587f13f2371d9cba`.

## Locked safety and product invariants

- Hyperliquid testnet is forbidden.
- Market observations are Hyperliquid mainnet only.
- Mainnet market-data endpoints remain `https://api.hyperliquid.xyz` and `wss://api.hyperliquid.xyz/ws`.
- Default execution is paper/shadow and places no real exchange orders.
- No live exchange adapter is enabled or authorized.
- No wallet/private-key signing, transfer, withdrawal, or private account/user subscription exists in the current evidence path.
- Whole-market discovery remains dynamic; eligibility is separate from ranking.
- Explainable deterministic baselines remain first-class before ML; `NO_TRADE` is valid.
- Strategy cannot size positions or send orders; independent risk has final veto.
- Locked risk remains 0.25% planned account risk per trade, 0.75% aggregate planned open risk, 1% daily realized-loss lockout, 3% rolling weekly drawdown, and cooldown after three consecutive losing trades.
- No averaging down, martingale, or stopless positions.
- No historical L2/order flow may be fabricated from candles.
- PyArrow remains optional research tooling only.
- Real-money activation always requires explicit user authorization after all later promotion gates pass.

## Exact next action

1. Keep Phase 10 blocked.
2. Complete and inspect GitHub Actions run `32781582212` without making an economic claim from workflow success alone.
3. Run the offline `cocomelon-mainnet-evidence verify` boundary against any complete artifact before aggregation.
4. Admit only cohorts that pass genuine-mainnet attestation: complete, gap-free, duplicate-free, anomaly-free, paper-only, fixed revision, unique recording session, and non-overlapping time window.
5. Aggregate admitted cohorts through `cocomelon-mainnet-evidence aggregate`, then use the counts-only `progress` precheck to track the raw corpus toward the locked 100-trade/30-day evidence floor without revealing edge metrics early.
6. Continue collecting temporally distinct cohorts under the same pinned trading revision; future runs use serialized fail-fast acquisition.
7. Freeze only the exact attested run set, then freeze time splits, candidate set, policy, and predeclared sensitivity profiles before revealing untouched-test metrics.
8. Run and persist the genuine Phase 9 baseline evaluation only when the evidence policy can be evaluated honestly.
9. Only after the real evidence result is known decide whether the approved build order permits Phase 10 or requires more baseline evidence.

## Live trading status

**DISABLED.**

Cocomelon can discover, analyze, decide, risk-gate, paper-execute/manage, journal, replay, verify, aggregate, attest, report counts-only evidence progress, and deterministically evaluate fake-capital outcomes against genuine public mainnet evidence. No genuine corpus has yet demonstrated economic edge, and no real-money order is authorized.
