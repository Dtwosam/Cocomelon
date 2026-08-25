# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing the Cocomelon build across ChatGPT chats. The live GitHub repository and authoritative repo docs are stronger authority than this summary.

**Repository:** `Dtwosam/Cocomelon`  
**Primary language:** Python 3.12  
**Venue:** Hyperliquid HyperCore perpetual markets  
**Observation:** genuine public Hyperliquid mainnet  
**Execution mode:** paper/shadow only  
**Live trading:** **DISABLED**  
**Hyperliquid testnet:** **NEVER USE**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

---

## 1. Mission and authority

Cocomelon is an autonomous intraday Hyperliquid perpetual-futures research/trading system. It discovers the real perp universe, applies mechanical eligibility, ranks opportunities, computes deterministic microstructure features, chooses LONG/SHORT/NO_TRADE, passes directional proposals through an independent risk engine, paper-executes approved trades against genuine mainnet observations, manages positions, journals/replays outcomes without lookahead, and evaluates the baseline through a locked one-shot Phase 9 OOS protocol before any learning or real-capital phase.

Economic objective: positive net risk-adjusted expectancy after fees, funding, slippage, and realistic execution costs while preserving capital. Profit is never assumed or guaranteed.

Authority order for a fresh conversation:

1. current explicit user instruction;
2. `AGENTS.md`;
3. `docs/MASTER_SPEC.md`;
4. `docs/DECISIONS.md`;
5. `docs/BUILD_ORDER.md`;
6. active phase plan/spec if present;
7. `docs/STATUS.md`;
8. this portable bootstrap.

Routine architecture, implementation, testing, CI, PR, review, and guarded merge decisions are handled autonomously. Real-money activation is the permanent exception: no live exchange order placement without later promotion gates and explicit user authorization.

---

## 2. Locked safety/product invariants

- Hyperliquid testnet is forbidden.
- Public market observation is Hyperliquid mainnet only.
- REST market-data base: `https://api.hyperliquid.xyz`.
- WebSocket market-data base: `wss://api.hyperliquid.xyz/ws`.
- Default/current execution is paper/shadow; no live exchange adapter is authorized.
- No wallet/private-key signing, transfer, withdrawal, or private-account execution path belongs in the evidence campaign.
- Strategy cannot size positions or send orders; independent risk has final veto.
- No averaging down, martingale/loss-recovery sizing, or stopless positions.
- Scanner rank is attention priority, not directional evidence.
- Whole-market discovery remains dynamic; eligibility is mechanically separate from ranking.
- Historical L2/order flow may never be fabricated from candles.
- Replay/evaluation must preserve evidence class, availability time, provenance, and realistic costs.
- Phase 10 and any learning/champion-challenger promotion remain blocked until genuine Phase 9 evidence passes the locked protocol.

Locked V1 risk includes 0.25% planned account risk per trade, 0.75% aggregate planned open risk, 1% daily realized-loss lockout, 3% rolling weekly drawdown lockout, a 60-minute cooldown after three consecutive losing trades, 0.50% correlation-bucket risk cap, and a 3x-or-lower gross leverage ceiling. Leverage is subordinate to dollar risk.

---

## 3. Current immutable research revisions

The three revisions that matter for the current evidence program are:

- **Campaign V2 strategy/risk/execution/evidence runtime:** `6de9d86aa7c36fce4f459e0bcc4e004de9215f25`;
- **Campaign retry-selection ledger tooling:** `e87a575a755074e36e22729c63c4831b474cf339`;
- **Frozen one-shot Phase 9 evaluator:** `629db6294822c97690c006591802f8a47e08652e`.

The campaign runtime contains the qualified redundant-mainnet transport stack:

- two independent public-mainnet WebSocket lanes;
- lane-wide readiness only after live subscribed data proves the session;
- readiness revocation on lane disconnect;
- 15-second connection-start phasing;
- application heartbeat during active traffic;
- connection spacing that does not hold the lock across a WebSocket handshake;
- synchronous REST context/funding polling offloaded from the asyncio WebSocket loop and serialized behind an async lock;
- merged-feed failover/backfill and cross-lane duplicate suppression;
- durable fail-fast termination on a real merged data gap.

Genuine heartbeat run `32878425117` qualified that runtime over roughly 98 seconds with 2,972 real mainnet events, 0 merged gaps, 0 duplicates, 0 anomalies, 0 reconnects, two healthy lanes, `network_access=true`, and `live_orders=false`. That was transport qualification only, not an economic claim.

---

## 4. Scheduled genuine-mainnet Campaign V2

`.github/workflows/evidence-campaign-scheduled.yml` is the sole production evidence-acquisition path. It runs on cron `37 1,7,13,19 * * *` UTC and supports manual workflow dispatch. Ordinary repository pushes do not launch the expensive campaign.

Each scheduled run:

1. checks the durable Phase 9 terminal/final state and stops if the one-shot protocol is already terminal;
2. checks out the immutable Campaign V2 runtime revision;
3. records up to two bounded 45-minute genuine-mainnet attempts in paper mode;
4. fail-fast aborts any attempt on the first durable merged data gap;
5. normalizes transport health and requires zero merged gaps, duplicates, and anomalies with two redundant lanes;
6. performs an offline eligibility probe before selecting an attempt;
7. only admits an attempt whose replay/dataset are complete and whose paper exposure is flat at the replay horizon;
8. records all attempted cohorts and rejection reasons in a deterministic attempt ledger;
9. performs the final canonical offline replay/dataset freeze and paper-only economic-semantics assertions;
10. uploads a 90-day immutable artifact.

### Right-censor retry semantics

Run `32880737422` was the first full 45-minute transport-clean Campaign V2 corpus:

- 46,408 genuine mainnet events;
- 0 merged gaps;
- 0 duplicates;
- 0 anomalies;
- 0 reconnects;
- complete replay and evaluation dataset;
- paper-only execution;
- one opened PUMP paper position and zero closed positions at the replay horizon.

The cohort was **correctly excluded from economics** for `open_exposure`. It made no edge claim and did not mutate the attested corpus.

PR #74 changed only bounded acquisition selection semantics: if attempt 1 is transport-clean but replay/dataset-incomplete or right-censored by open paper exposure, the already-budgeted attempt 2 is used. Attempt selection is allowed to inspect only:

- replay completeness;
- evaluation-dataset completeness/gap references;
- opened vs closed position counts / flat exposure.

It may **not** inspect final equity, PnL, net R, profitability, bootstrap results, win rate, profit factor, or edge status. Rejected clean attempts are preserved in the deterministic attempt ledger with explicit admission rejection reasons such as `admission_open_exposure`.

Immutable retry-ledger tooling revision: `e87a575a755074e36e22729c63c4831b474cf339`.

The qualified strategy/risk/execution runtime remains pinned to `6de9d86aa7c36fce4f459e0bcc4e004de9215f25`; the right-censor retry change does not alter strategy logic, risk limits, position management, or paper execution.

---

## 5. Automatic verified corpus curator

`.github/workflows/evidence-corpus-curator.yml` listens for completed Campaign V2 runs and serializes corpus mutation.

Before any successful source artifact can mutate the corpus, the curator independently verifies:

- source repository identity;
- `main` source branch;
- production Campaign V2 workflow ID/path;
- exact source workflow-run ID;
- trigger/workflow head lineage;
- source workflow conclusion;
- immutable artifact identity from that exact source run;
- cohort transport/replay/economic admission requirements;
- retry-selection audit / attempt-ledger lineage.

PRs #71 and #72 hardened this provenance chain so a valid-looking artifact cannot be rebound to a non-authoritative workflow/branch/run.

PR #76 repaired the curator staging lifecycle after the checkout step was proven to remove the pre-created `intake/` directory before trusted-artifact selector preparation. The fix keeps that directory present across checkout without changing admission semantics. A rerun of previously failing curator workflow run `32885277066` then passed selector preparation, independent source intake, and intake-audit upload; because source campaign `32880737422` concluded failure, selection-audit, corpus aggregation, and Phase 9 lifecycle steps remained skipped. The persisted intake report recorded `corpus_mutated=false`, `economic_claim=none`, `source_verified=false`, and `source_conclusion=failure`. The tracked hidden directory marker was not included in the uploaded artifact.

Eligible cohorts are aggregated idempotently into the attested V2 mainnet corpus. Existing aggregates are re-verified when read for append/progress/freeze. Ineligible/diagnostic/right-censored evidence is preserved for diagnosis but does not mutate the economic corpus.

The curator exposes **counts-only readiness**, not early PnL. It must not reveal or optimize on untouched-test performance before the deterministic one-shot cutoff.

---

## 6. Locked one-shot Phase 9 policy

The V2 Phase 9 protocol is deterministic from the first attested V2 source timestamp:

- 1 calendar day train bookkeeping;
- 1 calendar day validation bookkeeping;
- 45 calendar days untouched test;
- 7-day expanding walk-forward windows stepped every 7 days;
- 6-hour embargo.

Locked minimum evidence requirements include:

- at least 100 untouched OOS closed trades;
- at least 30 OOS covered days;
- at least 3 eligible walk-forward windows;
- at least 20 trades per eligible walk-forward window;
- at least 20 trades per score bucket;
- at least 60% positive eligible walk-forward windows;
- 95% bootstrap confidence;
- 5-day day-block bootstrap;
- 2,000 bootstrap resamples;
- sampled `NO_TRADE` horizons of 1 hour and 4 hours.

`CANDIDATE_EDGE` additionally requires positive untouched-test mean net R, bootstrap lower confidence bound above zero, stable positive walk-forward behavior, market positive-PnL concentration <=35%, and seven-day concentration <=50%.

Possible authoritative Phase 9 states are:

- `INVALID_EVIDENCE`;
- `OOS_CONTAMINATED`;
- `INSUFFICIENT_EVIDENCE`;
- `NO_EDGE_DEMONSTRATED`;
- `CANDIDATE_EDGE`.

If the fixed test window completes without enough evidence, the protocol persists a readiness-only terminal insufficient-evidence state rather than repeatedly peeking at OOS results.

---

## 7. Fresh-chat continuation instructions

When asked to continue Cocomelon:

1. inspect live `main` and treat it as authoritative over this file;
2. read `AGENTS.md` and `docs/STATUS.md` before changing code;
3. check open PRs, review threads, exact-head CI, and recent Campaign/curator workflow runs;
4. do not rebuild or repatch work already merged;
5. preserve the immutable Campaign V2 strategy/risk/execution runtime unless a genuine defect requires a separately qualified replacement;
6. use RED -> GREEN TDD for behavior changes and require compileall, Ruff, mypy, full pytest, research tests, independent PR-context CI, and guarded merge where applicable;
7. preserve paper-only/live-disabled boundaries and never weaken evidence/admission gates merely to obtain more data;
8. do not inspect or optimize on locked OOS PnL before the one-shot protocol allows it;
9. update `docs/STATUS.md` and this portable bootstrap at meaningful integration boundaries;
10. verify current Hyperliquid documentation before relying on venue behavior that could have changed.

---

## 8. Exact handoff now

Current engineering focus is **evidence accumulation**, not transport repair or manual replay orchestration.

The transport-qualified runtime is deployed to the scheduled Campaign V2. The first full 45-minute clean corpus, run `32880737422`, was excluded only because one paper position remained open at the replay horizon. PR #74 now spends the pre-existing second bounded acquisition attempt when a clean attempt is non-performance-ineligible for completeness or right-censoring, with every rejection recorded and selection explicitly forbidden from using PnL/equity/edge. PR #76 has also operationally restored the curator's post-checkout staging path, so the next successful source campaign can reach independent verification and aggregation without the earlier `intake/` lifecycle failure.

Continue in this order:

1. keep Phase 10 and live trading blocked;
2. let scheduled Campaign V2 collect temporally distinct genuine-mainnet paper cohorts from immutable runtime `6de9d86aa7c36fce4f459e0bcc4e004de9215f25` using retry-ledger revision `e87a575a755074e36e22729c63c4831b474cf339`;
3. admit only source-workflow-successful, independently verified, non-overlapping, complete, merged-gap-free, flat-exposure cohorts with valid retry-selection lineage;
4. let the automatic curator accumulate the attested corpus and expose counts-only readiness;
5. at the deterministic V2 cutoff, persist either the frozen ready one-shot snapshot followed by the genuine Phase 9 evaluation, or the readiness-only terminal `INSUFFICIENT_EVIDENCE` state;
6. only if the genuine one-shot result is `CANDIDATE_EDGE` and every locked promotion criterion passes may work advance toward Phase 10;
7. real-money execution remains forbidden until later explicit authorization even if Phase 9 eventually demonstrates candidate edge.

**REAL BASELINE EDGE: UNMEASURED.**  
**LIVE TRADING: DISABLED.**
