# M6.0 P3k — Synthetic lost-ACK reconciliation and bounded restart

**Classification:** isolated, disposable Linux/KVM **engineering trial**, not production custody admission. Depends on merged P3i (#114) and P3j (#115), without editing their code or the real ProjectCTL DB/WAL.

## The unresolved ambiguity

A durable SQLite transaction can succeed and the Unix socket ACK can subsequently be lost. An automatic replay of the same write is not a reliable way to determine the outcome and is explicitly excluded.

P3k adds a distinct foreground **lab server** and a strict two-operation IPC schema:

- `{"v":1,"op":"issue","sequence":N}`: reuses P3i `commit()`, updating the synthetic receipt and high-water in one SQLite transaction.
- `{"v":1,"op":"lookup","sequence":N}`: opens the **existing** Custodian SQLite authority, starts `BEGIN IMMEDIATE`, validates the entire synthetic history with P3i `_verify()`, and returns `COMMITTED` plus stored SHA-256, or `ABSENT` at that snapshot. Never creates a ledger or issues a receipt.

Each request is ASCII, newline-terminated, at most 128 bytes, contains only exactly these three typed fields, and is processed under Linux kernel `SO_PEERCRED` UID admission. The Writer CLI checks the server UID against the local `p3-custodian` account. An independent trusted launcher and root-owned code/import chain remain assumptions, not implementation guarantees.

### Intentionally dropped ACK

A **trusted lab-only** server argument `--drop-ack-sequence N` suppresses the success response **after** SQLite commit for that one `issue` sequence. The Writer client prints `P3K_ISSUE_OUTCOME_UNKNOWN` and returns exit code **4**, rather than claiming success or automatically retrying. A later explicit `lookup N` can return the committed digest after verifying the ledger. A valid generic `REFUSED` response yields exit code **3**, and does not prove whether an earlier attempt committed. A successful response/lookup yields exit code **0**.

The `ABSENT` result is a **point-in-time observation**, not irrevocable evidence: another in-flight publication might commit afterwards, or the whole VM/database might have been rolled back. A caller must **not** automatically reissue solely on `ABSENT`; stronger source identity, exclusive publication/ordering, and rollback-resistant authority are out of scope.

### Bounded lifecycle / fail-closed behavior

The server handles at most 16 requests per launch, one at a time. On normal exit it unlinks only the still-matching socket inode. It can be freshly launched against the **same existing** ledger and will read its committed state. It refuses an existing symlink or bound/stale socket instead of deleting it automatically. This is **not** a persistent managed service, a stale-socket repair routine, crash-safe supervisor, or evidence of successful restart following arbitrary SIGKILL. An unbounded wait for the next connection is still possible until the configured count is reached; a trusted operator must control lifecycle.

P3k's socket directory must be an existing Custodian-owned `0711` direct child `/var/tmp/projectctl-p3k-*`; socket is mode `0666` for cross-UID connect, with credential admission enforced in code. The prior P3i directory must be Custodian-owned `0700` under `/var/tmp/projectctl-p3i-*`. The same ledger must not be replaced or reinitialized to retry. The script is intentionally nonroot and requires `--acknowledge SYNTHETIC_DISPOSABLE_LAB`. It must be installed alongside root-owned P3i and P3j scripts by the trusted VM administrator before a real two-UID guest run.

## Verification

Development tests, executed on Linux:

```bash
python -m pytest -q -rs tests/test_m60p3k_synthetic_ack_recovery_lab.py tests/test_m60p3j_synthetic_unix_intake_lab.py tests/test_m60p3i_synthetic_sqlite_custody_lab.py
git diff --check origin/main...HEAD
```

P3k focused unit tests cover dropped ACK with committed readback/no duplicate, positive and absent readback after normal server restart, denied peer UID, corrupted authority, missing authority, invalid and duplicated JSON fields, fake server UID, and stale UNIX socket/symlink refusal. Tests use local same-UID threads to exercise protocol and database; they are **not** a substitute for an actual `p3-writer` → `p3-custodian` guest trial. No CI status or guest PASS is presumed by this design document.

## Evidence ceiling

The prior P3j trial operator-reported direct two-UID IPC and a retained *synthetic* P3i high-water of **4**, not live ProjectCTL records. P3k does not change that result or any real source. No genuine producer identity, authenticated epoch, crypto receipt, signed package, external high-water/anti-rollback anchor, power cut, guest restart/SIGKILL recovery, source coherence or formal P3 acceptance is demonstrated. Production P0–P4 are not admitted by this experiment.
