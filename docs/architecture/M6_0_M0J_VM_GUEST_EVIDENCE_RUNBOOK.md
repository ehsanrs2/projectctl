# M6.0 M0j — Owner-Reviewed Disposable VM Evidence Collection Runbook

**Status:** A runnable, **owner-invoked guest-only pilot** with synthetic test coverage. This is NOT VM creation, cryptographic VM attestation, a production security control, an operational cutover, a backup tool or v2→v3 migration authorization.
**Baseline:** `main@7d5d17f7320237c0892942a521d0ea388b57e54e` (PRs #78 M0h and #79 M0i both merged).
**Pinned test source:** corrected M0k test-only M0h revision `bcc488f523bec10e952b22dd2fedcdf12ffb850f`, not the original M0h PR head. The old M0h HEAD 4c0b28ebe3b05a3c550b8ccd10b419ab4d3dd6fe evidence remains a historical **NO-GO** and cannot be relabelled.
**Files:** `scripts/m0j_collect_vm_evidence.py`, `tests/test_m60m0j_vm_collector_contract.py` and this document only. No `projectctl/` code changes.

## Concrete deployment decision

The operator's current Ubuntu machine is **not** the accepted kernel-test environment. On the prior owner's Linux 6.11 host, the M0h focused suite produced **2 passed / 5 skipped** because `unshare --user --map-root-user --mount --fork -- true` could not set `/proc/self/uid_map` (EPERM); AppArmor audit records a `unprivileged_userns` profile transition and one `CAP_SYS_ADMIN` denial. The kernel-denial log has not been proven to correlate with every failed invocation. Host-level security settings must **not** be changed to bypass the problem.

**Candidate supported guest profile, subject to owner review before running:**

| Field | Required value / boundary |
| --- | --- |
| Guest | Disposable Linux VM, single-purpose for M0h, no unrelated services/projects |
| Owner | Explicit human approval and user-controlled VM lifecycle; not an automatically provisioned system |
| Source | Fresh checkout at the **exact M0h commit**, clean tracked and untracked worktree |
| Filesystem | Dedicated guest-local filesystem, record actual type; no mounted production project, shared host worktree, network mount or secrets |
| Security | Guest's kernel/LSM/userns settings reviewed; no host AppArmor changes, no blanket AppArmor disable, no forced sudo |
| Identity | Nonsecret guest label; metadata is **asserted by the operator**, not independently attested |
| Python | Compatible Python >=3.12, installed project dev dependencies, `pytest` and `unshare` present |
| Operation | Run only M0h's seven disposable `tmp_path` tests; bounded by 180-second timeout |
| Authority | No root, migration, service restart, external writer isolation or production release authority |

A suggested guest family is a disposable Ubuntu Linux VM with a local ext4 filesystem. **No specific Ubuntu release, kernel or AppArmor exception is asserted to work until the guest actually passes the optional kernel checks.** The owner must choose a VM backend and review isolation/provenance separately. A container with host mounts or `systemd-nspawn` shell should not be labeled a separate VM without external verification.

## Executable operator workflow

These commands are intended **only inside that selected VM**, in a new project checkout that already has the M0j script and M0i reviewer. They do not provision a VM or change host settings. The VM owner must ensure no real ProjectCTL project is mounted or reachable from the guest.

Create a second, detached source tree for the *exact* M0h tests. The parent repository is not modified:

```bash
git fetch origin
git cat-file -t bcc488f523bec10e952b22dd2fedcdf12ffb850f  # commit
git worktree add --detach "$HOME/m0k-pinned-pilot" \
  bcc488f523bec10e952b22dd2fedcdf12ffb850f
git -C "$HOME/m0k-pinned-pilot" rev-parse HEAD
git -C "$HOME/m0k-pinned-pilot" status --porcelain --untracked-files=all
```

The last command must print **nothing**; the rev-parse output must match the 40-character pinned SHA. Prefer a dedicated VM with a clean local repository; do not reuse a production directory. From the M0j checkout, activate the prepared virtual environment (the script itself does not install dependencies):

```bash
source .venv/bin/activate
python -B -m scripts.m0j_collect_vm_evidence \
  --checkout "$HOME/m0k-pinned-pilot" --inspect
```

This checks the exact commit and worktree; it **does not** claim the system is a VM, run namespaces or produce evidence. Its result is `CHECKOUT_PINNED_REVIEW_VM_SEPARATELY`.

If and only if the owner has independently inspected the guest, kernel/LSM policy and lack of host project mounts, create a private existing evidence parent, then invoke the collector:

```bash
mkdir -p -m 700 "$HOME/m0j-private-evidence"
chmod 700 "$HOME/m0j-private-evidence"
python -B -m scripts.m0j_collect_vm_evidence \
  --checkout "$HOME/m0k-pinned-pilot" \
  --collect \
  --output-parent "$HOME/m0j-private-evidence" \
  --acknowledge DISPOSABLE_VM_REVIEWED_NO_PRODUCTION_MOUNTS \
  --scope-id disposable-m0h-guest-01 \
  --filesystem ext4 \
  --userns-policy owner-reviewed-guest-policy
```

The `--filesystem` and `--userns-policy` arguments **must be replaced with the actual guest observations**, not copied as factual attestations. The explicit acknowledgement is a user claim, not an OS-authenticated gate.

After collection, the script prints machine JSON with a newly created `evidence_dir` containing `m0h-junit.xml` and `manifest.json`. The directory is mode 0700; files are 0600; the script uses no-clobber publication, fsync for the manifest and directory, and computes SHA-256 of the actual JUnit bytes. The output is **not an authenticated artifact**, crash-consistent backup or safe production evidence. Do not auto-upload it or store secrets in a repo.

The collector runs `python -B -m pytest` only on the pinned M0h test module and invokes the *same* M0i evidence reviewer. The printed result is **always** `authorizes_migration: false`.

**Outcome interpretation:**

- `NO_GO_KERNEL_CASES_SKIPPED`: guest still cannot execute M0h's kernel probes; do not disable the guest security policy merely to obtain a pass.
- `NO_GO_TEST_FAILURE_OR_ERROR`, `NO_GO_PYTEST_NONZERO_EXIT`, `NO_GO_TEST_TIMEOUT` or any `QUARANTINE_...`: retain artifacts privately, review; never retry or reclassify automatically.
- `LAB_REVIEW_ONLY`: all seven test cases completed successfully in the *operator-claimed* disposable VM. These include the **intended bypass successes** through the original writable alias and independent legacy writer. **This is NOT an all-writer exclusion success** and does not permit migration.

The verifier may be invoked independently, from the same M0j checkout, using the exact new evidence directory:

```bash
python -B scripts/m0i_verify_vm_evidence.py \
  --manifest "$EVIDENCE_DIR/manifest.json" \
  --junit "$EVIDENCE_DIR/m0h-junit.xml"
```

Set `EVIDENCE_DIR` manually from the collector's printed result; do not substitute an old directory. Do not publish paths/logs identifying private hosts or share private credentials.

## Proof missing after M0j

Even seven M0h passes prove **only** per-mount readonly behavior and **deliberately successful** source-alias/independent-process bypasses. To ever authorize production offline migration a *different*, audited OS/supervisor and filesystem deployment must fully exclude all unmodified v2 writers (including extant writable SQLite/WAL/SHM descriptors, worker descendants, unrelated CLI, JSON publishers, other UIDs, containers and remote mounts) and enforce an independent start embargo while a durable anchored WAL-inclusive backup, transactional v3 migration, outcome reconciliation and controlled release run. No sampled PID or read-only mount view substitutes for that.

The M0j evidence CLI is intentionally neither cryptographically signed nor bound to a trustworthy remote VM attestation or source-tree hash outside the git SHA. No runtime migration/repair path, service shutdown, project writer authority, Seal or R1 WAL Trace exporter is introduced.

## CI and owner governance

GitHub Actions exact-PR-HEAD CI must pass full pytest, compile, source-schema and public export policies, pinned Codex SDK. M0j CI runs **synthetic tests with a mocked subprocess**, not actual guest mounts, systemd units or AppArmor changes.

```bash
git fetch origin
git switch --track origin/experiment/m6.0-m0j-vm-evidence-collector
source .venv/bin/activate
python -m pytest -q tests/test_m60m0j_vm_collector_contract.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Keep Draft, do not merge without owner instruction, and do not treat any VM evidence outcome as a production GO.** Owner-host remains NO-GO; M0j records a bounded path to *laboratory* VM kernel testing only.
