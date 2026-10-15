# V2 actor-received DATA_GAP witness order forensics

The current v2 paired-paper lane is failed, with a strict source-gap ordering
exception. The original verifier intentionally uses one fail-closed exception
for multiple reasons: reversed/duplicate record ordinal, invalid received
clock, received-clock regression, or witness record ordinal beyond the signed
market-record count.

The independent offline command below distinguishes those cases by reading
the **original extracted file** without modifying it. Run it only after an
independent GitHub artifact ID, SHA-256 and original signed checkpoint have
been verified. Never run against a mutable live worker checkpoint:

    python -m scripts.diagnose_v2_source_gap_order \
      --witness ORIGINAL/source-gap-record-witness.jsonl \
      --signed-processed-records EXACT_SIGNED_CHECKPOINT_RECORD_COUNT

The command reports the first invalid row, its preceding original ordinal
and receive time (where available), and the full original JSONL SHA-256.
It rechecks all row digests and previous-record links before trusting any
row's ordering fields. It reads the entire file even after detecting a
failure to record its exact original byte hash. No markets, account IDs,
payloads, API keys or HTTP response bodies are printed. Its diagnostic
snapshot does not rewrite, prune, checkpoint, or append original evidence.

A hash-consistent witness tail whose ordinal exceeds the supplied signed
checkpoint count is explicitly labeled "uncheckpointed_witness_tail",
not silently trimmed or admitted. A hash-consistent witness inside the
supplied count is labeled "self_consistent_unverified": this does not verify
that the count came from an authenticated signed state or that original
exchange events were complete. Broken hashes, received timestamps moving
backwards, and repeated ordinals remain invalid. The CLI **always exits 2**
even if its local checks find no ordering failure; it cannot make an
unverified research lane green through shell exit status.

To remediate, first establish the exact original actor-received row and
its signed-state predecessor from independently archived bytes. Any future
forward-only repair requires a separate proof of account/ledger/source
continuity; never retroactively change the witness or permit v2 profitability,
paper source promotion, or LIVE trades because a diagnostic succeeded.

No changes to current paper strategy, accounts, risk, worker source, signed
gap history, observation thresholds, or real orders.

## Immutable original ZIP three-way split audit

The separate `scripts/audit_v2_checkpoint_split_archive.py` reads **only**
an exact original v2 ZIP, matches its SHA-256 against a separately obtained
GitHub artifact digest, verifies the v2 signed JSON state's self-digest,
recomputes the signed original witness prefix SHA-256 and row/digest counts,
checks the full witness's original chain/order with the offline diagnostic,
and compares **both** original SQLite paper-account state IDs against their
signed state IDs using read-only temporary SQLite copies.

It detects a valid older signed prefix followed by a newer intact witness
and unsynchronized baseline/candidate execution stores as a **three-way
checkpoint split**. That is exactly the structure independently found in
real 2026-10-15 archived worker artifacts 11974152140 and 11979576395.
The original ZIP and all of its members are never modified, truncated,
rewritten or extracted using archive-controlled filesystem paths.

    python -m scripts.audit_v2_checkpoint_split_archive \\
      --zip ORIGINAL-V2-GITHUB-ARTIFACT.zip \\
      --expected-zip-sha256 VERIFIED_GITHUB_SHA256

The digest argument must be verified against original GitHub metadata by an
independent operator/auditor; supplying a matching value is not identity
proof. Even if every local component matches, the status is
`locally_consistent_unverified`, **not** positive after-cost evidence,
verified venue completeness, a valid external signed terminal attestation,
permission to restart from a mismatched account, or authorization to trade.
The CLI returns exit code **2** for all successful diagnostics.
