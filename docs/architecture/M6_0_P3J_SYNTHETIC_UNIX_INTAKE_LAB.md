# M6.0 P3j — Bounded Unix peer-credential synthetic custody intake

**Classification: disposable engineering experiment only.** No real ProjectCTL DB/WAL, manifests, Verification Seal, signer, authentic source producer, service/systemd, public CLI or Worker/Task authority. Production P0–P4 remains **NO-GO**.

**Input boundary:** A client may send only one newline-terminated ASCII JSON object `{"v":1,"op":"issue","sequence":N}` of at most 128 bytes. No file path, blob, claimed issuer, arbitrary payload, executable, key, SQL, project data, or external output destination is accepted. Duplicate JSON keys, extra fields, float/bool sequences, invalid range and oversized requests are refused. The ledger payload remains generated internally from the existing **P3i** synthetic format.

**Credential boundary:** The Unix stream server obtains `SO_PEERCRED` from the accepted socket and compares its kernel-supplied UID to the explicitly configured *lab Writer* UID. The client separately checks the server's kernel UID against the `p3-custodian` account. Linux UID does **not** authenticate source code, W1, issuer or DB epoch; inherited/misdelegated UID or capabilities, root, actual Writer launch paths and socket-FD passing remain outside this demo. The server must be started under static `p3-custodian` and its executable and P3i import dependencies must be root-controlled on the dedicated VM. No service unit is created by this PR.

**Socket boundary:** `intake.sock` is created in a Custodian-owned `0711` directory under `/var/tmp/projectctl-p3j-*`, with socket mode `0666` solely to enable different UIDs to connect; unapproved peers are rejected using `SO_PEERCRED`. The directory is deliberately *not writable by Writer*, preventing pathname replacement by Writer under normal DAC. The program refuses an existing socket or symlink, and checks the socket inode before deleting the socket on normal exit. This is not a mount-namespace/administrator-proof guarantee. A socket-file mode of `0666` is **not** authority by itself; the peer-credential check is mandatory. Server processes at most 16 connections per explicit run, one at a time; malformed/unauthorized attempts consume a connection slot.

**Durable ledger boundary:** Server reuses the previously initialized P3i SQLite database in a Custodian-owned `0700` directory under `/var/tmp/projectctl-p3i-*`. It refuses an absent database rather than bootstrapping. `commit()` performs the receipt/high-water update inside one SQLite transaction. Success response is sent only after `commit()` returns; transport failure can mean *commit happened but ACK was lost*. Clients must not auto-reissue after ambiguous responses. Replayed sequences return a generic `REFUSED`.

**CLI limits:** The standalone `scripts/p3j_synthetic_unix_intake_lab.py` CLI requires `--acknowledge SYNTHETIC_DISPOSABLE_LAB`, ordinary nonroot equal real/effective UID, root-independent Linux peer credentials, the static `p3-custodian` account in the guest, exact prefix/parent checks for socket and ledger directories, and a distinct allowed writer UID for the server. The server's socket directory must already exist with `0711` and be Custodian-owned. The **client** does not need write/read access to the Custodian ledger or socket directory: traverse-only `0711` suffices. `serve` is foreground and bounded by request count, not a daemon or service. If a client never arrives it can still wait indefinitely; stop explicitly rather than launching unsupervised. No cleanup of retained P3i SQLite evidence is attempted.

## Focused repository validation

From an ordinary-user development checkout:

```bash
python -m pytest -q -rs tests/test_m60p3j_synthetic_unix_intake_lab.py
python -m pytest -q -rs tests/test_m60p3i_synthetic_sqlite_custody_lab.py
git diff --check origin/main...HEAD
```

Tests exercise real Unix sockets/peer credentials between local same-UID test threads (for positive frames), mismatch rejections, malformed input, replay rejection and missing-ledger refusal. **They cannot substitute for the actual two-UID Debian guest acceptance**, where the server must run as `p3-custodian` and clients as `p3-writer`. Explicit root-owned installation, kernel credential readback, precise guest launch commands and crash/ACK tests are a separate, bounded operator action after review. Do not copy or serve code from a Writer-writable directory in the guest.

## Observed baseline, untested here

P3i PR #114 was merged into main (2026-10-25). Its operator-reported guest test passed synthetic initialize, sequence 1 commit, pre/post-commit `SIGKILL` readbacks, replay rejection and direct Writer `EACCES (13)`. The operator retained `/var/tmp/projectctl-p3i-6saOQ8Oa` with high-water 2. P3j does **not** alter or assume this state in repository tests; a future guest trial could use the existing ledger with sequence 3 after confirming its contents and code hashes.

**Not proved:** issuer/source authenticity, producer admission beyond exact kernel UID, independent administrative management, stable daemon lifecycle, code import closure, arbitrary FD passing, rollback resistance, VM reboot/power-loss storage permanence, real cross-file source coherence, signed package publication, and P3 formal acceptance. This branch remains a nonproduction lab.
