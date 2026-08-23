# Cocomelon Build Order

This is the approved construction sequence. Do not skip ahead merely because later phases are more exciting.

Each phase must leave the repository in a working, testable state. `docs/STATUS.md` records the active phase and evidence that the prior phase passed.

## Phase 0 — Governance and source-of-truth anchor

**Goal:** Make the project portable across chats and contributors before code begins.

Deliverables:

- `README.md`;
- `AGENTS.md`;
- `docs/MASTER_SPEC.md`;
- `docs/DECISIONS.md`;
- `docs/BUILD_ORDER.md`;
- `docs/STATUS.md`;
- `docs/CHATGPT_PROJECT_SOURCE.md`;
- first detailed implementation plan.

Exit criteria:

- documents agree on mainnet-only/paper-first architecture;
- risk limits are consistent;
- no unresolved placeholder decisions block Phase 1;
- repo source hierarchy is explicit.

## Phase 1 — Python foundation and domain contracts

**Goal:** Establish a small typed codebase whose interfaces can survive later strategy changes.

Deliverables:

- Python project configuration;
- package layout;
- environment/config loader;
- explicit mainnet URL validation and testnet rejection;
- typed market, signal, risk, order, fill, position, and journal domain models;
- time/ID utilities;
- structured logging with secret redaction;
- pytest + lint/type checks;
- CI workflow.

Exit criteria:

- clean install from scratch;
- tests pass;
- known testnet hosts fail configuration tests;
- paper is the only default execution mode;
- no secret values can be committed through example config.

## Phase 2 — Hyperliquid mainnet discovery and REST snapshots

**Goal:** Reliably discover the real perp universe and normalize low-frequency market context.

Deliverables:

- mainnet HTTP client with retry/backoff/rate-budget awareness;
- perp DEX discovery;
- metadata/universe normalization;
- `metaAndAssetCtxs` normalization;
- candle snapshot fetcher;
- funding-history fetcher where useful;
- canonical `MarketId` / market registry;
- raw response fixtures captured from mainnet with sensitive user data excluded;
- contract tests against fixtures;
- small live smoke command that reads mainnet only and performs no trading.

Exit criteria:

- dynamic market list, no favorite-token hard-coding;
- delisted/invalid markets identified;
- timestamps and schema versions persisted;
- client stays within documented rate limits.

## Phase 3 — WebSocket collector and durable market recording

**Goal:** Build reliable live mainnet event capture and reconnect behavior.

Deliverables:

- WebSocket supervisor;
- subscriptions for all mids, candles, L2 book, and trades as needed;
- reconnect/resubscribe handling;
- freshness/heartbeat tracking;
- duplicate/out-of-order handling;
- raw/normalized event schemas;
- rotating Parquet writer;
- data-gap records;
- dynamic deep-watchlist subscription manager.

Exit criteria:

- collector survives disconnect/reconnect tests;
- stale streams are detected;
- events preserve exchange and receive timestamps;
- raw market recording runs for an extended smoke period without corruption.

## Phase 4 — Feature engine, eligibility, and market scanner

**Goal:** Turn trustworthy observations into a broad-to-deep opportunity funnel.

Deliverables:

- liquidity/spread/depth quality features;
- multi-timeframe returns/trend features;
- realized volatility and range features;
- relative-volume features;
- funding/OI context;
- market regime baseline;
- eligibility gate;
- opportunity score/ranker;
- dynamic shortlist manager;
- feature snapshot versioning.

Exit criteria:

- bad-quality markets cannot rank into tradable state;
- scanner operates across discovered markets;
- feature calculations are deterministic and lookahead-safe;
- shortlist changes are explainable from recorded features.

## Phase 5 — Baseline strategy engines

**Goal:** Produce explainable trade ideas without ML dependence.

Deliverables:

- trend engine;
- breakout engine;
- mean-reversion engine;
- funding/OI context engine;
- order-flow engine for recorded microstructure data;
- shared `StrategySignal` contract;
- regime-aware deterministic decision combiner;
- LONG/SHORT/NO_TRADE output;
- reason codes and feature references.

Exit criteria:

- each engine has unit tests and deterministic fixture examples;
- strategy signals cannot bypass eligibility;
- NO_TRADE is common/valid rather than treated as failure;
- order-flow tests use actual recorded/fixture book/trade structures, not fabricated candle approximations.

## Phase 6 — Independent risk engine

**Goal:** Turn a strategy decision into a bounded, vetoable order plan.

Deliverables:

- 0.25% risk-budget calculation;
- stop-distance sizing;
- liquidity/notional caps;
- 0.75% aggregate open-risk guard;
- 1% daily loss lockout;
- 3% rolling weekly drawdown lockout;
- three-loss cooldown;
- correlation buckets;
- stale-data/execution-health vetoes;
- immutable risk-decision journal.

Exit criteria:

- tests prove strategies cannot override risk;
- adverse edge cases fail closed;
- sizing accounts for estimated execution costs;
- averaging-down and martingale behaviors are impossible through public interfaces.

## Phase 7 — Real-mainnet paper execution and position management

**Goal:** Autonomously trade fake capital against real Hyperliquid mainnet observations.

Deliverables:

- paper execution adapter;
- L2-aware marketable fill simulation;
- configurable latency;
- fees and funding accounting;
- partial-fill model where evidence permits;
- stop/trigger behavior;
- position lifecycle/account equity ledger;
- partial exits and trailing/thesis exits;
- emergency close behavior;
- restart recovery for simulated positions.

Exit criteria:

- end-to-end scanner -> decision -> risk -> paper order -> fill -> position -> exit works unattended;
- accounting invariants reconcile to the cent/tolerance defined by tests;
- simulator never awards unsupported passive maker fills;
- failure injection does not create duplicate positions.

## Phase 8 — Journal, replay, and deterministic backtester

**Goal:** Make every decision reproducible and every strategy measurable.

Deliverables:

- complete decision/trade journal;
- deterministic event replay;
- candle/context backtester;
- microstructure replay for real recorded data;
- MFE/MAE calculations;
- net-R calculations;
- fees/funding/slippage attribution;
- reproducibility manifest including config/data/strategy versions.

Exit criteria:

- same dataset + config + code version reproduces results;
- lookahead tests pass;
- candle and microstructure evidence classes remain clearly separated.

## Phase 9 — Evaluation and research gates

**Goal:** Determine whether any baseline actually has an edge.

Deliverables:

- time-based train/validation/test splits;
- out-of-sample reports;
- walk-forward evaluation;
- performance by market/regime/strategy/direction/time;
- score-bucket calibration analysis;
- drawdown/tail-loss analysis;
- sensitivity analysis for fees/slippage/funding;
- rejection/missed-opportunity sampling.

Exit criteria:

- at least one baseline candidate either shows repeatable net expectancy or the project honestly records that no edge has been demonstrated;
- no strategy is promoted because of one lucky market/window.

## Phase 10 — Learning engine and champion/challenger

**Goal:** Let data improve ranking/decision quality without uncontrolled self-modification.

Deliverables:

- versioned training datasets;
- feature registry;
- first supervised challenger models;
- time-aware model training;
- expected-net-R/ranking target experiments;
- model registry/metadata;
- deterministic evaluation pipeline;
- champion/challenger comparison and promotion rules.

Exit criteria:

- challenger beats champion on required out-of-sample/walk-forward criteria;
- promotion is reproducible;
- training cannot alter live hard risk limits;
- model cannot directly call execution APIs.

## Phase 11 — Long-running mainnet shadow operation

**Goal:** Prove the complete autonomous system can operate continuously on real market data.

Deliverables:

- service supervisor/CLI;
- startup reconciliation;
- health metrics;
- stale-data alerts/logging;
- daily performance report;
- crash/restart recovery tests;
- paper account snapshots;
- locked champion version during evaluation window.

Minimum live-promotion evidence begins accumulating here:

- 500 closed paper trades;
- 45 calendar days shadow operation;
- positive net expectancy after costs;
- positive untouched out-of-sample results;
- walk-forward stability;
- profit factor >= 1.20;
- maximum paper drawdown <= 8%;
- diversification/concentration gates from `MASTER_SPEC.md`;
- zero unresolved safety invariant failures.

## Phase 12 — Mainnet live execution adapter (disabled)

**Goal:** Implement and test the real-order pathway without enabling autonomous capital risk yet.

Deliverables:

- dedicated Hyperliquid API/agent-wallet integration;
- order/cancel/query/reconciliation methods only;
- client-order-id/idempotency handling;
- nonce discipline;
- startup account/position reconciliation;
- duplicate-order prevention;
- dual live-mode activation guard;
- secret handling/redaction tests;
- live adapter disabled by default.

Testing must use deterministic mocks/fixtures and read-only mainnet queries where safe. **Do not use Hyperliquid testnet.**

Exit criteria:

- adapter behavior is fully covered without risking funds;
- no withdrawal/transfer capability is exposed through the execution interface;
- accidental configuration cannot activate live trading.

## Phase 13 — Explicit live promotion

**Goal:** Begin autonomous real-money execution only after the user explicitly authorizes it and all promotion gates pass.

Required actions:

- freeze and archive the promoted champion/config;
- verify gate report;
- user chooses funding amount;
- user authorizes live mode explicitly;
- start at the locked 0.25% per-trade risk model;
- monitor reconciliation and drawdown continuously;
- preserve automatic daily/weekly lockouts.

Failure to meet a gate means remain in paper mode.

## Phase 14 — Evidence-based optimization

Only after stable live evidence exists:

- consider risk changes gradually;
- expand additional perp DEX/HIP-3 execution support;
- improve exits;
- improve correlation/risk models;
- test additional strategies/features;
- consider dashboard/notifications;
- consider infrastructure upgrades if free limits become a demonstrated bottleneck.

No scaling decision is automatic. Every risk increase requires evidence and a documented decision.