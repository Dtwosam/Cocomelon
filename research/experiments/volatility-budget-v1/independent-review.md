# Independent volatility-budget PAPER binding review

**Verdict: no remaining actionable code defect found in the reviewed inactive binding. Operational activation remains BLOCKED.** Full/research exact-head CI, final change review and post-merge verification remain the parent's release work; this review does not assert they have completed.

Scope: read-only source review of the pure volatility policy, dedicated lifecycle, associated tests and existing PAPER/risk/funding mechanics in `/Users/Dtwo1/.codex/worktrees/flow-exhaustion-paper/Cocomelon`. Synthetic temporary accounts were created only under `/private/tmp`. This reviewer made no repository edits, commits, GitHub messages, operational accounts, entry boundary, launcher, network market requests or LIVE action.

## Reviewed bytes and independent verification

SHA256:

- Frozen policy: `eca2816e42a1a0409737e179b45761a8a4ad0ebb2149ee7ad956b6867caffdaa` (unchanged).
- `src/cocomelon/research/volatility_budget.py`: `378d04b6bdc55b0e5271821f69d04306c3e0b2f17cc93eb11fe41fc55f4b83fe`.
- `src/cocomelon/research/volatility_budget_paper.py`: `b60001c5afa5143ee987e79f753c94f699d9173b49fcaf2b589805b6b1d248f4`.
- `tests/test_volatility_budget.py`: `9f50325d837d2072d0a5de467b97576b6ff6d97066ab1099fbaabc8798c10531`.
- `tests/test_volatility_budget_paper.py`: `fb87b38a892f26fa236b5488d12e38fd35fabdfea812c7f0b16227afa67b434b`.

Independent final local regression run: **245 tests passed**, using Python3.12 and `-p no:cacheprovider`, covering both new volatility suites, existing flow policy/lifecycle, risk engine/invariants, PAPER funding, funding accounting and general accounting. Collection count independently verified. This is synthetic behavior verification, not economic or operational-source validation.

## Findings and corrections verified

1. **Canonical selection after eligibility:** original code conflated eligibility with later cost/funding veto and could substitute another market. Current pure plan exposes `current_eligible`; lifecycle selects the first eligible cooldown-admitted canonical crossing, then consumes the selected batch if later execution/cost/risk/instrument vetoes. Both valid unselected and ineligible crossings still consume the any-side72h signal cooldown; suppressed crossings do not move expiry.
2. **Fresh mark/oracle at opening:** current lifecycle requires genuine positive fresh mark/oracle context at actual opening attempt instead of asserting fresh health unconditionally. Missing/invalid context cannot open.
3. **Durable mark stop:** a mark-only stop crossing now latches a permanent reduction obligation before later mark recovery. The obligation survives restart and continues through fresh post-latency original execution books.
4. **Local checkpoint rollback:** independently reproduced trial-only checkpoint rollback originally lost consumed daily batch/cooldowns and accepted replay. Current lifecycle mirrors revision/digest witnesses in both account databases after the trial commit; account witness ahead of trial rejects checkpoint rollback. Account-only rollback/history loss also rejects. Normal trial-first interrupted saves may leave account witnesses behind and remain recoverable. This is not proof against coherent whole-directory rollback.
5. **Opening expiry without a book:** `tick`/advance now expires staged opening at2s, preserving the consumed day and permitting a future independent eligible batch rather than stranding capacity.
6. **Actual execution book integrity:** shared strict helper now rejects wrong schema, duplicate prices, malformed/nonpositive levels and stale/future clocks for actual opening and reductions, matching the relevant predecision source protections.

Additional inspected behavior: current28=`returns[-28:]`, prior28=`returns[:-1]`, current7=`returns[-7:]`, prior7=`returns[-8:-1]`; sample variance uses ddof1. Squared thresholds use integer-ratio cross multiplication with strict prior and inclusive current comparisons. Native inclusive close remains canonical T+1ms; bar retrieval receipt at the cutoff is too late. Source/protocol provenance, unsupported margin metadata, positive geometry, stop/target immutability, risk/fee envelopes, partial/missed fills, durable reduction retries,24h from actual first fill, exact boundary residual exposure and delayed funding after flat are covered by source inspection and regressions. Default restart restores neither entry authorization nor source admission. No LIVE execution path was found.

## IOC interpretation and risk limit

Frozen wording specifies reuse of the existing depth-aware IOC and a25bp cap without explicitly anchoring that cap to decision reference E. Existing IOC semantics anchor its depth limit to the actual attempt executable quote. Current top-quote admission also rejects adverse movement beyond E25bp; deepest IOC levels can consequently be approximately50bp adverse to E. The frozen E-based stop/target never reanchors. Risk is re-sized against the actual top quote and fixed stop with the stricter59bp reserve, and each actual fill is independently clipped to approved notional and planned-risk ceilings. This does not bypass the0.10% planned-risk limit; gaps/slippage/future funding can still exceed planned realized loss. Silently tightening the whole IOC to E25bp would add a policy admission rule not explicitly stated in the freeze; the reviewed interpretation preserves the existing adapter semantics.

## Operational and evidentiary limits

`/private/tmp/volatility-resource-verdict.md` does not establish an independently owned existing24h runtime, aggregate shared-IP budget or durable restart/source custody. Those facts remain prerequisites, independently of passing code tests. A source-admission boolean cannot certify them. Local mirrored witnesses cannot detect rollback/cloning of the entire directory and both witnesses together; independent custody remains required.

Lifecycle runtime ingress records contain mark/book payloads and clocks, while daily decision records bind supplied bar inputs through the evidence digest. A future operational owner must separately preserve and authenticate original candle responses, receipt clocks and gaps, and bind them to these inputs. This inactive library does not prove that original source archive exists or that a held-position service can meet freshness/resource requirements for24h.

No operational activation receipt, account genesis, T0 or first-entry boundary is approved by this review. No profitable edge or prospective economic progress is verified. Preserve ordinary worker state, historical losses, exact policy bytes and LIVE-off.
