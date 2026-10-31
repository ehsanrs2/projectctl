# M6.0 P3m — Synthetic no-clobber blob + SQLite record binding

**Classification: isolated, disposable Linux/POSIX engineering laboratory only — not an operational custody or production authorization.** P3m adds a **separate** Python file and focused tests on top of merged P3l (#117). It does **not** alter P3i/P3j/P3k/P3l, their retained synthetic ledger, source ProjectCTL data/DB/WAL, real issuer receipts, or any public CLI.

## Gap addressed: P3-F10/15/16/19/20/21 (partial, synthetic)

P3l demonstrated lost ACK and Custodian SIGKILL against a transactionally updated **receipt ledger**. It did not materialize a separately published package file or prove that the bytes at an accepted identity match the row that says they are accepted. The new P3m experiment models **one private, finite set of synthetic object bytes**, immutable *by cooperative protocol* and bound to SQLite in controlled order.

P3m uses a new and **independent** store. The existing P3i guest ledger has operator-reported `P3I_HIGH_WATER=8` and MUST remain unchanged; P3m starts at high-water **0 in its own tree**. Never use the P3i ledger directory as the P3m workdir.

## Publication order

An already independently created, Custodian-owned `0700` direct child `/var/tmp/projectctl-p3m-<ID>` holds only:
- `.owner.lock` (Custodian-owned `0600` regular file). A kernel `flock(LOCK_EX | LOCK_NB)` guards cooperating publishers; the file/inode persists and is **never unlinked**.
- `objects/` (Custodian-owned `0700`), holding a fixed maximum of **16** `000000NN.obj` files (`0400`). Payload is the exact synthetic UTF-8 line `{"sequence":N,"data":"SYNTHETIC"}\n`.
- `authority.sqlite3` (`0600`, DELETE rollback-journal mode, synchronous FULL) holding `state.high_water` and `receipt(sequence,name,sha256,size)` in one SQLite transaction.

`init` **refuses an existing populated root**. It never initializes a missing store opportunistically during inspection or publication. Only the admin/custodian-approved private tree is allowed.

`publish N` obtains the process lock and verifies *all* prior SQLite/object bytes before starting, then:
1. Requires exactly `N = high_water + 1` with `1 <= N <= 16`. Rejects duplicate, skipped or reverted sequences.
2. Creates a fixed staging inode with `O_EXCL | O_NOFOLLOW` in `objects/`, writes canonical bytes, changes to `0400` and fsyncs the file **and containing directory**.
3. Uses an atomic hard-link creation `os.link(stage, final)` as the **no-replacement** publication primitive. An existing final name makes the operation fail; no overwrite/rename fallback. Fsyncs the `objects/` directory. Unlinks the staging alias and fsyncs the directory again. At this point the final blob exists but is not yet an accepted object.
4. Starts `BEGIN IMMEDIATE`, rechecks old high-water, writes the full object name/digest/size row and updates high-water with a conditional update, then performs exactly one SQLite `COMMIT`. SQLite remains the **only accepted-record authority**.
5. Returns `COMMITTED` and digest only after the commit call returns; **no** automatic retry on missing ACK.

An object name on disk without an authoritative matching row is a **refused/quarantined orphan**, never a valid accepted package. A row with missing, replaced, linked, mode-changed or content-corrupted bytes is also refused; the inspector never reconstructs authority from loose files or automatically deletes suspicious entries.

The fixed maximum and tight object schema are deliberate limitations, not production serialization. The SHA-256 is a **self-checked integrity value**, *not* independently authenticated source origin or an anti-rollback anchor.

## Process crash windows

The trusted test-only flags `--kill-after-object` and `--kill-after-commit` cause the P3m process to SIGKILL **itself**, not an arbitrary PID:

| Window | Expected child result | Fresh-process readback | Meaning |
| --- | --- | --- | --- |
| After final object fsync, **before** SQLite record commit | `-SIGKILL` | **REFUSED/QUARANTINE**: orphan final object, SQLite high-water still 0 | Do not promote orphan based on file or hash alone |
| After SQLite record commit, **before** acknowledgement | `-SIGKILL` | `CONSISTENT`, high-water 1, correct object bytes and digest | Lost ACK does not warrant replay |

Tests also cover duplicate/skipped sequence denial, symlink and hardlink aliases, permission changes, missing object, tampered content, stray stage, unsafe owner/root and unknown files. These are unit and Linux child-process tests on a same-UID temporary fixture, **not** proof of two-UID separation; do not claim a real power failure was injected.

## Explicit nonclaims and hard stop conditions

- **Not** the full P3-C2 production candidate: P3m is a test-only standalone Custodian-run CLI. It has no AF_UNIX Writer handoff, P2 authentic issuer/registry, W1 as-of source epoch, real package/manifest, collector/reader integration, service unit, key material or release policy.
- An adversary with Custodian/root/host power can alter the same store and recompute self-hashes; a complete SQLite+object rollback would pass this local consistency check. **No independent monotonic anchor** or VM snapshot-rollback detection exists.
- File/dir fsync and SQLite synchronous FULL are ordering mechanisms only; no actual guest power-cut, drive-cache verification or reboot was executed. A host/VM interruption requires its own separately approved runbook and observer.
- A crash earlier than the two injected windows may leave a stage and/or mismatched objects. This lab intentionally **refuses** such a tree. It has **no automatic cleanup, repair or orphan adoption**.
- The root store must be private and on a separately checked filesystem; do not operate on real ProjectCTL, symlinks, production mounts, unreviewed paths or any P3i/P3j/P3k/P3l ledger.
- P0–P4 remain **NO_GO for operational use**. No credential elevation, container/VM policy edit, root-run Python, systemd, AppArmor, network, or privileged service install is authorized by this experiment.

## Developer validation before any guest work

Use the ordinary-user Debian development checkout at the PR head, and do **not** run the CLI in a real or shared project:

```bash
python -m pytest -q -rs \
  tests/test_m60p3m_synthetic_blob_binding_lab.py \
  tests/test_m60p3l_synthetic_sigkill_socket_recovery_lab.py \
  tests/test_m60p3k_synthetic_ack_recovery_lab.py \
  tests/test_m60p3j_synthetic_unix_intake_lab.py \
  tests/test_m60p3i_synthetic_sqlite_custody_lab.py

git diff --check origin/main...HEAD
```

Only after code review, green CI and the user's focused tests should a **separate** bounded two-UID guest plan be proposed for a fresh P3m private directory. Preserve the existing retained P3i high-water **8** and do not reissue P3i sequences 7 or 8.
