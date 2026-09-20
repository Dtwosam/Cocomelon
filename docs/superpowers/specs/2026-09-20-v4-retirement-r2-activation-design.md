# V4 Retirement and R2 Activation Design

**Date:** 2026-09-20  
**Status:** Approved by explicit user direction to reveal V4 economics, retire the failed baseline, and continue building for profitability.

## Purpose

Turn the deliberately revealed V4 baseline into permanent touched development evidence, stop spending future scheduled acquisition on that failed candidate, and activate the immutable R2 short-trend quality challenger in the existing paper-only research lane.

The transition must preserve every risk and live-trading invariant. It must also prevent the revealed V4 tuning window from ever being mistaken for untouched validation data.

## Evidence basis

The user explicitly authorized revealing V4 economics before the original 30-day finalization gate. The authenticated 100-trade development snapshot was produced by V4 corpus artifact `10497424756`, whose latest accepted source run was `35190636004`.

The revealed 100-trade baseline was economically weak: approximately `-$629.91` net PnL, `-0.298 R/trade`, profit factor `0.44`, and `7.80%` realized closed-trade drawdown. The R2 hypothesis was frozen from that touched sample: retain only baseline decisions that are SHORT, trend-led, and scored from 72 through 81 inclusive. On the same touched sample the retained subset was approximately `+$57.39` net with profit factor around `1.30`; this is hypothesis generation only, not evidence of edge.

The development cutoff is the end of source run `35190636004`'s fixed 5h15m capture:
`1789645942986` ms.

## Design

### 1. Permanent touched lineage

Candidate spec registration may declare an optional `v4_touched_through_ms`.

Registration fails closed unless the authoritative V4 registry is complete through that timestamp. It then copies every recorded V4 acquisition interval ending at or before the cutoff into the candidate's local touched intervals, using deterministic provenance IDs derived from the V4 run IDs.

This import is conservative: accepted, rejected, failed, and diagnostic V4 acquisition intervals all count as touched if they fall in the development window. Candidate renaming or code/config changes cannot erase them.

Exact repeat registration is idempotent. A pre-existing candidate is accepted only when its immutable family, parent/ancestor chain, code revision, config digest, execution config, and inherited risk config exactly match the spec. Any mismatch fails closed.

### 2. R2 immutable candidate

Create `docs/research-r2-short-trend-quality-v1.json` with:

- candidate: `research-r2-short-trend-quality-v1`
- parent: `scheduled-research-root`
- strategy code revision: `2ce088d69df01f044b0650b811b51015a5edda51`
- max position age: 20 minutes
- starting cash: unchanged at 10000
- risk config: inherited unchanged from the parent
- V4 touched cutoff: `1789645942986`

The strategy filter itself remains the #205 implementation: SHORT + trend + score 72–81. This transition does not add profit-protection logic yet; that is a separate challenger hypothesis after R2 has enough forward touched evidence.

### 3. Automatic registration and activation

The research candidate-registration workflow gains a narrow main-branch push trigger for the R2 spec/registration workflow. It restores only trusted research authority, registers R2, imports the declared V4 touched history, and republishes the authoritative registry.

Trust consumers accept registration artifacts from either the existing explicit workflow-dispatch path or the new main-branch push path, always with exact artifact/run head-SHA matching.

The research campaign uses the source-controlled R2 candidate ID instead of a stale repository variable. Root remains `scheduled-research-root`; fanout remains exactly root plus one optional challenger.

Both pre-publication and final rollout verifier gates explicitly verify R2 through a CLI challenger-ID argument.

### 4. Retire future V4 acquisition

Remove the V4 cron schedule. Do not cancel, retry, extend, or otherwise intervene in any acquisition already running when the change lands.

Historical V4 artifacts/corpus remain available for audit and touched development analysis. V4 no longer has promotion status and cannot regain untouched status.

Scheduler-health reporting detects that the V4 workflow has no schedule and reports retirement rather than a permanent stale alarm.

### 5. Validation semantics

R2 remains TOUCHED / NON-PROMOTIONAL research.

At 20 closed research trades, apply only the existing futility rule. Positive results cannot promote R2. `RESEARCH_PROMISING` still requires at least 40 closed research trades, at least 7 closed-trade UTC days, `P(mu > 0) >= 0.80`, complete costs, and clean integrity/risk state.

Any future clean validation must use data after candidate freeze and after the existing six-hour embargo following the latest inherited touched interval. Live trading and Phase 10 remain blocked.
