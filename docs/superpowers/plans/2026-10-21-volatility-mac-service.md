# Minimal Mac service for the frozen volatility trial

Current explicit owner authorization supersedes the prior no-integration restriction. No ordinary runtime, PR1392, strategy parameter, LIVE adapter or historical result changes.

The service is specific to VolatilityPaperTrial: native mainnet receipts and existing normalization, serialized clock/data/funding callbacks, the existing PAPER engine, local fsync source custody and a bounded independent Git CAS checkpoint/owner fence. A user LaunchAgent may restart this exact command; power/logout/network gaps remain failures, never guaranteed fills. All admission checks precede network access or account genesis.

1. Preserve the original policy SHA and refresh real ordinary state/main/mandate. Create isolated branch/worktree.
2. Source tests then adapter: raw receipt before normalization, first closed native8h availability, real clocks, conflicts/gaps, exact settled funding. No historical book reconstruction.
3. Custody tests then component: three consistent SQLite backups, fixed trial identity, independent CAS head and expiring owner generation, strict restore, no genesis over existing history, bounded remote storage/write rate. Real local bare Git tests model transport, not production custody.
4. Service tests then integration: deny unknown NAT before any network/account creation; serialize input and original arrival order; real wall clock after waits; exact daily boundary or UNKNOWN; nonblocking charged REST budget and reconnect cap; continue protective management with entries denied; funding after close; fsync originals and independent checkpoints. Default PAPER-only.
5. Interruptions: exact clean restore, unclean pending tail, open/partial/failed exits, irreversible suspension and late funding. Unacknowledged source is never manufactured. Missing/rolled-back roots cannot create new$10k; unclean custody disables entries/qualification while preserved known local obligations continue protective-only.
6. Independent code/lifecycle review; configured compile/Ruff/mypy, full and research exact-head CI. Merge only reviewed bytes after both pass.
7. Activation is separate: actual authorized runtime/power/failure service, independently verified current source/account custody, aggregate IP governance and resource budget, immutable exact-SHA receipt, distinct$10k ledgers and future daily boundary>=6h after release. The user's shared/unknown NAT answer currently prohibits Hyperliquid connections and entries. No real source/account activity is claimed from synthetic tests.

Files: volatility_source.py, volatility_transport.py, volatility_custody.py, volatility_owner.py, volatility_service.py and focused tests; the specific Python module command and narrow research-CI selection. No framework, collector platform, paid dependency or ordinary workflow change.
