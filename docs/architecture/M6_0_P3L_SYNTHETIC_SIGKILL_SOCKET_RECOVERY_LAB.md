# M6.0 P3l — Custodian SIGKILL / stale Unix socket recovery lab

**Scope:** synthetic, disposable Linux/KVM engineering trial only. Adds a **separate** P3l entrypoint; P3i/P3j/P3k and all real ProjectCTL storage/interfaces remain unchanged. No systemd unit or privileged service is installed.

## Failure windows and fixed authority

The P3l foreground Custodian process listens on `intake.sock` and calls the previously reviewed P3i `commit()` for every admitted synthetic `issue`. A trusted laboratory flag selects exactly one crash window:

- `--crash-before-sequence N`: after inserting synthetic receipt N and updating high-water in the still-open SQLite transaction, kill **the Custodian server process itself** with `SIGKILL`. The expected verified state after SQLite recovery is N absent; do **not** infer this solely from the missing ACK.
- `--crash-after-sequence N`: after SQLite commit returns, kill the server before sending ACK. A new process can verify N as `COMMITTED` through `lookup`, with no duplicate `issue`.

These flags require `--max-requests 1`. An unexpected client/sequence does **not** trigger crash. The Writer receives `P3L_ISSUE_OUTCOME_UNKNOWN` (exit 4) on a lost response; it must **not retry issuing the ambiguous sequence automatically**. Even `lookup ABSENT` is only a point-in-time observation and may reflect an in-flight writer or snapshot rollback.

## Stale Unix socket recovery: opt-in only

After `SIGKILL`, the kernel releases the listener and process file lock, but the filesystem may retain `intake.sock`. A new server **fails closed** when this socket exists without `--recover-stale-socket`. With that explicit option, it holds a persistent `flock(LOCK_EX|LOCK_NB)` on Custodian-owned `0600` `.custodian-owner.lock` and:

1. Verifies the existing P3i SQLite authority using `inspect()` before modifying any socket pathname (SQLite may recover a hot rollback journal here).
2. Requires the existing pathname be a Custodian-owned `0666` Unix socket with link count 1; symlink or regular-file aliases are rejected.
3. Probes the socket; **only** a Linux `ECONNREFUSED` response is treated as disconnected. A connected listener or uncertain result refuses recovery.
4. Re-checks the socket's device/inode/owner/mode before unlinking **only this pathname** and binding the new socket.

The file lock persists across successful runs and must **never be unlinked**: it prevents cooperating Custodian processes from creating two independent lock inodes. Linux releases the **held flock** when the process is killed; it does not delete the lock file. Normal server exit unlinks only the matching socket inode, not the lock file. This is a restricted cooperating-server contract, **not protection against malicious Custodian/Root/mount namespace or arbitrary same-UID code**.

The socket folder must be a Custodian-owned `0711` direct child `/var/tmp/projectctl-p3l-*`. Writer can traverse it and connect to mode `0666` socket, but cannot modify directory entries. Clients and server check kernel `SO_PEERCRED` UID; this is **not producer-code, DB epoch, or origin authentication**. P3l imports P3i and P3k from an externally verified root-owned adjacent program directory in the VM.

## Testing and expected guest sequence

Repository Linux tests cover true child-process `SIGKILL` before and after transaction commit, surviving kernel lock release, opt-in socket recovery, absence versus committed reconciliation, idle server SIGKILL, denial of concurrent owner, symlink/regular path refusal, lock symlink and unapproved UID. Tests use same-UID development processes for positive protocol operations and are **not a replacement for the separate p3-writer/p3-custodian VM acceptance**.

In a later **bounded guest** trial, preserve the existing synthetic P3i high-water **6** (operator-reported P3k result), then:

- Start Custodian as static `p3-custodian` with crash **before** commit of sequence 7; Writer gets ambiguous result. Recover stale socket **explicitly** under verified custodian code and ledger, then look up 7: expect ABSENT. The next `issue 7` must be a separate, deliberate action after confirming no concurrent publisher.
- Start Custodian with crash **after** commit of sequence 8; Writer gets ambiguous result. Recover the stale socket and look up 8: expect COMMITTED. Do not issue 8 again.
- Keep ledger and owner-lock file for subsequent evidence inspection. Unexpected intermediate status requires investigation, not a blind replay.

The exact launch procedure must ensure the code is verified against the GitHub blob, the prior guest ledger state is verified, the directory starts absent, and each crash leaves the *server* stopped before starting the next. The trusted administrator (not Writer) must create and own the prescribed socket directory.

## Validation

```bash
python -m pytest -q -rs \
  tests/test_m60p3l_synthetic_sigkill_socket_recovery_lab.py \
  tests/test_m60p3k_synthetic_ack_recovery_lab.py \
  tests/test_m60p3j_synthetic_unix_intake_lab.py \
  tests/test_m60p3i_synthetic_sqlite_custody_lab.py
git diff --check origin/main...HEAD
```

**Not proven by P3l:** authentic ProjectCTL source receipt, code or issuer identity, root compromise, snapshot/whole-VM rollback, power-loss durability, power-cycle recovery, service supervision, safe multi-producer policy, side-channel or arbitrary FD passing protection, cross-file DB/WAL coherence, signed release chain or formal operational P3 approval. Production P0–P4 remains outside this trial.
