# M6.0 M0k — Debian 13 SQLite WAL CANTOPEN and Read-only VFS Proof

**Status:** test-only correction and evidence revision; **NO-GO** for any operational v2→v3 migration.
**Base:** merged M0j at `main@1bb2e2fcb4c3c5793bb70ddef4ead8c334f3c6b6`.
**M0h corrected test-source pin:** `bcc488f523bec10e952b22dd2fedcdf12ffb850f`. This exact commit has the M0k classifier, its synthetic tests and the M0h namespace test correction. Pinning it makes clean lab evidence reproducible **independently of future main merges**.
**Previous M0h test-source SHA:** `4c0b28ebe3b05a3c550b8ccd10b419ab4d3dd6fe`; old evidence is immutable history and does not meet the corrected pin.

## Actual evidence from operator-owned disposable Debian guest

- Debian GNU/Linux **13.7** (Trixie), kernel **6.12.113+deb13-amd64**, Python **3.13.5**, pytest **9.1.1**.
- KVM guest detected via `systemd-detect-virt --vm`; user/mount namespace trial `unshare --user --map-root-user --mount --fork -- true` exited zero without sudo.
- `/tmp` was `tmpfs`, so owner selected `TMPDIR=$HOME/m0k-ext4-tmp` on guest-local `/dev/vda1` **ext4**. No virtiofs/9p/NFS/CIFS mounts reported by the requested guest checks; this remains **operator-reported**, not cryptographic VM attestation.
- The original `m0j_collect_vm_evidence` run recorded **6 passed / 1 failed / 0 skipped**, `NO_GO_PYTEST_NONZERO_EXIT`. The exact failing case was `test_kernel_readonly_bind_view_blocks_new_legacy_writes[view_db]`. The child returned `OperationalError`, SQLite primary code **14 / SQLITE_CANTOPEN**, rather than code 8 / SQLITE_READONLY or raw OS `EROFS`.
- Separately running the unchanged M0i verifier over that historical JUnit gave `NO_GO_TEST_FAILURE_OR_ERROR`. **Both refusals are correct. Do not rewrite historical JUnit, invent a missing pass, or classify code 14 itself as a successful kernel restriction.**

SQLite WAL depends on the database, WAL and SHM paths. A connection can return CANTOPEN when it cannot create/access supporting WAL-mode files. This is consistent with but **not conclusive proof of** a read-only mount. Official reference: https://www.sqlite.org/wal.html and https://www.sqlite.org/walformat.html .

## Bounded correction; no weakened acceptance

The corrected M0h child now performs **two disposable O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW probes**, immediately removing successfully created probe files:

1. **Source control:** create a new dummy file inside the source alias' `.projectctl` directory, require success (errno 0). This confirms that the original source remains writable, i.e. global all-writer fencing is absent.
2. **View control:** attempt the same new dummy filename through the read-only bind view's `.projectctl`; require Linux `EROFS` (errno 30). This directly confirms the per-view VFS write boundary.

A new *separate* diagnostic classifier maps a SQLite CANTOPEN failure to the distinct result `vfs_ro_confirmed_sqlite_cantopen` **only** when source creation succeeded and view creation independently yielded EROFS. The parent test checks both errno values and the SQLite base code explicitly. This status says only that (a) a WAL-mode SQLite operation failed with code 14 and (b) independent VFS probes proved the mount view read-only. It **does not attribute code 14's internal cause with certainty** or assert that SQLite wrote. Code 14 without either proof remains `unexpected_error` and fails the test.

Unambiguous `EROFS` and base `SQLITE_READONLY` remain `kernel_denied` as before. An unrelated failure remains `unexpected_error`. The legacy JSON denial, alias DB/JSON bypass, preopened-fd ambiguity, outside-namespace independent v2 writer and all-external-gates NO-GO tests are **unchanged in meaning**. The seven original test IDs remain exact, so M0i structural checks apply.

The M0i verifier **re-pins its expected test-source SHA** to this corrected revision and explicitly quarantines an old-pin manifest. The M0j collector inherits the pin from M0i. This is a test-protocol version update, not an alteration of old evidence or a migration policy change.

## Re-run after owner-approved PR merge — disposable VM ONLY

On the **existing Debian VM**, keeping the historical `$HOME/m0h-pinned-pilot` worktree and evidence untouched:

```bash
cd "$HOME/projectctl-m0k-lab"
git fetch origin
git status --porcelain --untracked-files=all
# If clean and PR is merged, update controller checkout:
git switch --detach origin/main
source .venv/bin/activate

# A NEW detached worktree at corrected, exact pinned test SHA.
git worktree add --detach "$HOME/m0k-pinned-pilot" \
  bcc488f523bec10e952b22dd2fedcdf12ffb850f

python -B -m scripts.m0j_collect_vm_evidence \
  --checkout "$HOME/m0k-pinned-pilot" --inspect

mkdir -p -m 700 "$HOME/m0j-private-evidence" "$HOME/m0k-ext4-tmp"
export TMPDIR="$HOME/m0k-ext4-tmp"
findmnt -T "$TMPDIR" -no SOURCE,FSTYPE,TARGET
```

Before collecting, independently review that the guest is still disposable, the original host's production mounts remain inaccessible, `TMPDIR` is guest-local ext4, and the non-root user retains appropriate namespace capabilities. Only after this owner check:

```bash
python -B -m scripts.m0j_collect_vm_evidence \
  --checkout "$HOME/m0k-pinned-pilot" \
  --collect \
  --output-parent "$HOME/m0j-private-evidence" \
  --acknowledge DISPOSABLE_VM_REVIEWED_NO_PRODUCTION_MOUNTS \
  --scope-id debian13-kvm-m0k-02 \
  --filesystem "$(findmnt -T "$TMPDIR" -no FSTYPE)" \
  --userns-policy unshare-map-root-passed-lsm-not-verified
```

Every new collection creates its **own** evidence directory and manifest. Old evidence still returns `NO_GO` (or is quarantined for an outdated pin) and is **never retagged**. A new `LAB_REVIEW_ONLY` would mean only seven bounded cases passed in an asserted disposable guest; independent source/legacy bypasses deliberately remain open.

## CI / security governance

Exact-HEAD CI must pass full pytest, compile, public schema/export policies and pinned SDK. GitHub runner may still skip **five** real namespace tests: those skips never establish guest success. New classifier unit tests use no privileged tools and expressly reject plain CANTOPEN 14, view EROFS with source probe failure, and unrelated errors.

No production `projectctl/` code, DB format/version, schema v3 migration, cgroup, AppArmor, installed VM, systemd policy or operator service is modified by this PR. All-writer external startup embargo, authoritative DB/WAL/SHM+JSON path closure, durable backup/recovery and W1/R1 remain **NO-GO**.

**Keep PR Draft until full CI and owner review. Do not merge automatically.**
