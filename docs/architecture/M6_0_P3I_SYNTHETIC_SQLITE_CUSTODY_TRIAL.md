# M6.0 P3i — Synthetic single-authority SQLite custody lab

**Scope:** engineering-only disposable lab. This is **not** an operational P3 gate, trusted producer, signer, service or production migration. No real ProjectCTL database, WAL, manifest, key, run, Worker/Task process or public CLI is read or modified. Source export/epoch admission P0/P1/P2/P4 remains NO-GO.

## P3h guest observations (operator-reported, 2026-10-21)

The operator reported the following from a separate Debian 13.7 KVM disposable VM with ext4 `/dev/vda1` (not an independently attested host):

- `p3-writer` UID 999/GID 989 and `p3-custodian` UID 997/GID 987, both non-sudo service identities. Custodian's example directory was `0700` and receipt `0600`.
- Five preliminary Writer negative attempts (read, append, unlink, create, chmod) returned nonzero; **two later kernel-specific checks** established `EACCES (13)` on direct read and open-for-append, with Custodian positive readback.
- Writer symlink-follow read and protected-file hardlink creation both returned `EACCES (13)`; original synthetic receipt still read `{"sequence":1,"data":"SYNTHETIC"}`.
- A deliberately inherited open FD remained readable following `fork` and a UID drop; across `exec`, `FD_CLOEXEC` suppressed inheritance, whereas an intentionally inheritable FD remained readable. This is evidence of a **risk**, not safe closure of every FD transfer (notably `SCM_RIGHTS`).
- The operator's two synthetic file-publication `SIGKILL` episodes produced `RECEIPT_ABSENT` before publish and `RECEIPT_PRESENT_VALID` after link/unlink plus directory `fsync`, with shell exit status 0. A precommit `.pending` staging file was not asserted absent. That example is **not** a ledger/high-water commit and did not simulate VM reboot or power loss.

These are console outputs provided by the operator, not independently captured, signed or checked P3-F01–F28 acceptance artifacts. The existing formal P3 deployment NO-GO is unchanged.

## Why this next experiment exists

P3h confirmed elementary filesystem boundaries and process-kill readback, but a final JSON filename is not a single transaction for receipt identity **and** anti-replay high-water. P3i deliberately stores the synthetic receipt bytes, SHA-256 and monotonically increasing sequence in **one SQLite rollback-journal transaction**. Its verification program reads actual rows from the same file instead of accepting a caller-supplied checkpoint. Tests kill only their own short-lived child process before commit and after commit; a fresh interpreter checks the resulting state. They also race two independent processes for one sequence.

`PRAGMA synchronous=FULL` and SQLite rollback journal (`journal_mode=DELETE`) are explicit. The **code's protocol** commits receipt and high-water atomically from SQLite's point of view; the tests exercise process death only, not underlying media flush guarantees, live-v2 WAL, disk corruption, hardware rollback, VM snapshots or cross-resource publication. No second file/object is published. Never equate this with a finished custody package protocol.

### State model

- `state(id=1, high_water)` starts at 0 **only after an explicit bootstrap in an empty private directory**. Runtime `inspect` or `commit` opens the existing database with `mode=rw`, refusing a missing file instead of silently reinitializing it.
- `receipts(sequence PRIMARY KEY, sha256 UNIQUE, payload)` retains **only internally generated** ASCII synthetic records of the form `{"sequence":N,"data":"SYNTHETIC"}\n`. Caller cannot upload receipt bytes or claim an issuer.
- `BEGIN IMMEDIATE` serializes candidate publication against the database; the transaction checks existing receipt history/digests and admits only `high_water+1`. Both `INSERT` and `UPDATE high_water` are committed together. Replayed/stale/gapped inputs are refused.
- After a commit, an intentionally killed caller has **no ACK**; a fresh process sees the persisted receipt and a duplicate sequence is refused. The caller must not interpret a missing ACK as permission to blindly retry.
- Private directory `0700`, current owner, and ledger file `0600`, non-symlink regular inode with link count 1 are checked; no change to the guest's existing P3h receipt. These checks are **not race-free protection** against a malicious same-UID process, privileged host, FDs pre-opened elsewhere, SQLite VFS attacks or directory substitution by its owner.

## Local code validation

Run without Root in a disposable repository checkout:

```bash
python -m pytest -q -rs tests/test_m60p3i_synthetic_sqlite_custody_lab.py
python -m compileall -q scripts/p3i_synthetic_sqlite_custody_lab.py
```

The explicit operator CLI is **not** wired into ProjectCTL. Its fixed database filename, `/var/tmp/projectctl-p3i-*` private immediate directory requirement and `--acknowledge SYNTHETIC_DISPOSABLE_LAB` guard prevent accidental use with normal project directories. Do not run destructive experiments in an active project checkout; prepare any future guest trial with reviewed code provenance and a dedicated lab identity.

## Evidence ceiling and next implementation need

The local test run prepared during this change observed **8 passing unit/process tests** (including subprocess `SIGKILL` and competing publishers). No CI or Debian guest execution of the new P3i implementation is claimed at authorship. The existing P3h console data are **operator-reported**, not equivalent to P3i execution evidence.

Remaining: independent trusted code/admin ownership vs old actual Writer, separately authenticated producer admission, cross-store source-epoch truth, real published blob and protected metadata binding, no-clobber immutable package finalization, issuer/key policy, precise dirty-dir/rollback/power-failure cutpoints, actual reboot readback, restoration/anti-rollback witness, and P3-F acceptance evidence. **No production deployment GO, real v2 schema migration, live WAL reader, export or new Worker/Task authority.**
