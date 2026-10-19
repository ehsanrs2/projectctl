# M6.0 M0x — nonroot anchored-journal replay at real recovery crash windows

**Scope: experimental private files only; no root, systemd, AppArmor, project DB, W1/R1, Collector, CLI migration or production policy changes.** M0w PR #95 was merged on `main@cd99013dc034fe25794258a711babcc612fcf81d`; the owner reported a successful nonroot Debian KVM SIGKILL/fresh-process replay with no visible M0w residue. M0w still had one specific unsafe window: after unlink of its **only** journal but before unlink of the enclosing directory, a second interruption left an unrecognized empty directory with no durable provenance.

This change **separates the durable anchor from the disposable inner work directory**, so that the *inner recovery* can be restarted from a fresh interpreter even after its inner journal is gone. It does **not** claim globally crash-safe teardown: the stable anchor is retired in a **distinct post-test cleanup** phase that itself has a residual empty-outer-directory failure window.

## 1. New two-tier transaction (strictly nonprivileged)

A single random `/var/tmp/projectctl-m0x-*` test root (0700, current user, local observed filesystem) contains:

- `m0x-anchor.json` (0600): **external to** the disposable `work/` directory, created and fsynced before `work/` exists. It names the exact root, hashes the fixed journal/effect contents and contains literal `authorizes_root_trial=false`, `authorizes_policy_install=false`, `authorizes_migration=false`.
- `work/` (0700): one `m0x-journal.json` (0600) and one disposable `m0x-effect.bin` (0600), all fsynced with their enclosing directory.

**Permitted private recovery sequence:** verify anchor and all existing inner inodes/content; unlink fixed effect, fsync `work/`; unlink fixed inner journal, fsync `work/`; remove now-empty `work/`, fsync outer root; **retain the anchor**. A fresh recovery process can repeat from any intermediate state because the outer anchor stays intact, including an empty `work/` after journal unlink and an absent `work/` after its removal. Unknown leaf, missing/tampered anchor, effect present without inner journal, symlink/hardlink, unsafe mode/ownership or out-of-scope path => **quarantine and preserve evidence**. This is a deliberately fixed two-file and one-subdirectory protocol, not a general rollback engine.

The optional nonroot exercise actually tests **four independently created private fixtures** with a child process killed by `SIGKILL` at each corresponding interruption point:

| Phase | Killed child has reached | Fresh recovery must demonstrate |
| --- | --- | --- |
| X0 | Before unlinking the effect | Original journal and effect verified |
| X1 | After effect unlink and directory fsync | Journal-only replay |
| X2 | **After inner journal unlink and directory fsync** | Empty work directory replay using the **outer** durable anchor |
| X3 | After work directory removal and outer directory fsync | Anchor-only idempotent replay |

For each case, the surviving ordinary-user harness kills **only its direct test child**, observes `-SIGKILL`, and launches a **new Python process** with a fixed code path and only the private fixture path. It validates the result, then separately retires that fixture's outer anchor. It never searches/kills arbitrary guest PIDs or uses root, alternate actor files or selectable filesystem locations in the operator CLI.

## 2. Precise evidence ceiling and unresolved teardown window

- **Proved only in its bounded conditions:** new nonroot interpreter can use the fsynced outer anchor to reconcile the *inner* work directory across these four controlled SIGKILL windows. The harness remains alive and supervises the test. It is not a daemon, boot agent, true power-loss/reboot test, durable root-owned recovery record, independent trust authority or a real unit/profile lifecycle.
- **Still unresolved:** final `retire_fixture()` unlinks the last outer anchor, fsyncs its containing directory, then removes the empty outer root. A crash in this post-test cleanup may leave an empty, anchorless root requiring **manual quarantine**. We have **not** closed this outermost unlink/remove window; extending trust to a root-owned independent journal or retained tombstone demands a separately reviewed design. A future implementation must not simply label this two-tier construction universally crash-safe.
- **Same-UID trust:** all owner/mode/inode checks and name/nonce verification are local to a private ordinary-user test, **not cryptographic provenance**, immunity to concurrent same-UID code, fd-pinned race-free cleanup, foreign mount namespaces or hostile/root writers.
- **fsync semantics:** file and directory fsync calls are present, but no actual VM reboot, power cut, storage hardware flush or external read-after-restart witness occurred.
- If the recovery or surviving harness dies before its post-test cleanup, a residue may remain; this code offers **no general recursive/glob deletion**. Stop and review it manually.
- AppArmorProfile in a service does not automatically constrain a separately launched unconfined old Python client which acquires the same UID and supplementary GID. The M0s negative observation remains: old code with candidate UID+private write GID **writes**. M0x does not improve code/import provenance or group delegation.

## 3. Safe operator runbook (only after human review and merge)

Use the same independently reviewed, isolated Debian KVM disposable guest checkout. First run only ordinary-user tests and inert inspection:

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60m0x_anchored_crash_window_lab.py
    python -B -m scripts.m0x_anchored_crash_window_lab --inspect

Then an optional **strictly nonroot** four-phase private-fixture exercise, after checking the reviewed HEAD. It creates random direct children **only beneath /var/tmp**, sends SIGKILL **only to its own test subprocesses**, and verifies absence after bounded post-test cleanup:

    python -B -m scripts.m0x_anchored_crash_window_lab \
      --exercise \
      --acknowledge NONROOT_M0X_ANCHORED_CRASH_WINDOW_LAB

Finally, read-only residue search:

    find /var/tmp -maxdepth 1 -type d -name 'projectctl-m0x-*' -print

Expected output is `NO_GO_PRIVATE_CRASH_WINDOWS_REPLAYED`, four named verified phases, `fresh_recovery_processes=4`, and all authorization flags false. **Do not use sudo**, do not run on a machine with shared/production mounts, do not choose a custom path, and do not manually delete a residue until independently checking owner/inode/leaf content. If any phase fails or reports QUARANTINE, **stop and do not automatically retry**.

## 4. Gates still missing before any global policy test

| Gate | Required external evidence | M0x result |
| --- | --- | --- |
| X4 | Outer anchor retirement safe under crash/reboot or retained independent transaction receipt | UNVERIFIED |
| X5 | Surviving **boot-time** recovery owner independent of harness/service | UNVERIFIED |
| X6 | Actual disposable VM reboot/power-cut and post-restart verification | UNVERIFIED |
| X7 | Root-controlled unique AppArmor profile/systemd unit lifecycle with crash-safe cleanup | UNVERIFIED |
| X8 | Actual enforcing process label, immutable code/import closure, old-UID+GID adversarial test | UNVERIFIED |
| X9 | Complete DB/WAL/SHM+JSON aliases, preopened FDs, namespaces, late writers and privilege delegation | UNVERIFIED |

This PR closes **only M0w's inner journal-unlink replay gap under controlled process death**. It leaves outer retirement and every guest-global enforcement gate open. No production v2→v3 migration, trusted W1 Seal, R1 WAL reader or Collector/CLI work is authorized. **M0/W1/R1 and public CLI remain NO-GO.**
