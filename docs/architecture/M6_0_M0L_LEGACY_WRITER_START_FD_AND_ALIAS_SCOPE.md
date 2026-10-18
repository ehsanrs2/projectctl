# M6.0 M0l — All-Legacy-Writer Startup, FD, Inode and Sidecar Scope Pilot

**Status:** NEGATIVE LAB CHARACTERIZATION + explicit fail-closed observation contract. No operational all-writer embargo. **Production v2→v3 migration remains NO-GO.**

**Baseline:** `main@ee3356d124732aee1ddb66a63c6a716306126abc` after merged PR #81.
**Prior lab evidence:** On an independently operator-reviewed Debian 13.7 KVM guest, the M0k corrected M0h trial returned `LAB_REVIEW_ONLY` with **7 passed, 0 failed, 0 skipped**. A standalone M0i verifier returned exactly the same counts and `authorizes_migration: false`. This **only confirms read-only mount-view behavior and intentionally successful bypasses on that disposable guest**; manifest hashes/self-reported VM origin are not remote attestations. Earlier 6-pass/1-fail historical evidence stays NO-GO.
**Scope:** exactly one new pure script, one new test module, and this document; no production module `projectctl/` changed.

## M0l experiment and what can actually be decided

Path A/ADR-039/040 requires stopping **every** old uncooperative v2 writer before a private, WAL-inclusive backup and v3 cutover. M0h/M0k have shown that a mount view controls only that view, and the writable original path and independent process remain usable. M0l asks which *additional* same-host escape surfaces invalidate a mere process census or permission change.

These real integration tests run entirely on **new ProjectCTL v2 state and dummy JSON under pytest `tmp_path`**, with only test-owned processes and file descriptors:

| M0l test | Deterministic observation | Consequence |
| --- | --- | --- |
| New independent interpreter **after** a static no-worker observation | Uses real unchanged v2 `RunStore.append_event` and dummy JSON staging/replace | A sampled process list and voluntary stop flag are **not** an independently enforced *future start* embargo |
| Writable descriptor opened *before* owner-owned fixture JSON is changed to read-only mode | Already-open `O_WRONLY` descriptor writes after `chmod 0400` | Post-open mode bits cannot prove all inherited/previously-open write descriptions are drained |
| Dummy JSON inode reachable by *both* hardlink and symlink alternate names | Writes through each alias are visible at original inode | Canonical-looking names and path-only rules are insufficient to account for aliases, mount namespaces or hardlinks |
| Real v2 SQLite connection with write transaction in WAL mode | `state.sqlite`, `state.sqlite-wal` and `state.sqlite-shm` coexist while separately staged JSON is published | Filesystem authority includes **DB+WAL+SHM and independent JSON**; protecting DB filename or holding a SQLite transaction alone does not fence sidecars |

These examples prove **specific bypasses**, not that all possible bypasses have been enumerated. They do not shut down systemd, kill processes, mutate host AppArmor, create privileged mounts, alter a project belonging to a user, or issue migration commands. A passing negative experiment is **not** approval to migrate.

## Formal, unauthenticated scope review

`scripts/m0l_all_writer_embargo_contract.py` declares 10 external obligations, each requiring **literal Boolean True**, not truthy strings or integers:

1. Source identity and ancestors anchored.
2. Database, WAL, SHM and JSON all covered.
3. Symlink, hardlink and mount aliases closed.
4. Every legacy process and descendant drained.
5. Every inherited/preopened writable descriptor closed.
6. New independent same-UID starts externally blocked.
7. systemd units, timers, sockets and restart sources blocked.
8. Other UIDs, namespaces and remote writers excluded.
9. The embargo holds across private WAL-inclusive backup, ambiguous commit reconciliation, and controlled release.
10. An *external*, independently enforced authority actually verifies that scope.

A separate `BypassObservations` structure names late independent writers, preopened FDs, inode aliases and JSON writes outside SQLite. `None`/incomplete/malformed observations are NO-GO; any affirmative bypass is NO-GO; any missing external obligation is NO-GO. **Even if all obligations are marked True and all four bypass fields are False, `review()` returns only `LAB_REVIEW_ONLY`, always with `authorizes_migration=False`.** Operator claims and snapshot observations cannot authenticate a continuous absence of old writers.

The test file exercises every required flag, falsy and nonliteral-true values, unknown bypass observations, each affirmative bypass, plus actual disposable v2 writes. This deliberately **does not** add a new CLI authorizer or implement a system policy.

## Boundaries requiring a future, separately approved operator contract

The existing VM has *laboratory evidence*; it does not have a credible closed-world production topology. Before implementing an actual externally privileged embargo in a later phase, the owner must choose and document:

- A **concrete supported deployment** (VM or dedicated host, service manager, dedicated authority UID, controlled local filesystem, whether other users/containers/remote clients are present).
- A complete outside-the-process supervisor/systemd start gate covering CLI launchers, imports, timers, sockets, restart-on-failure processes, provider descendants, and same-UID independent interpreters. Sampling `systemctl` state or PID/cgroup membership is not enforcement.
- A credential/UID and filesystem isolation boundary covering the real `.projectctl/state.sqlite`, `-wal`, `-shm`, Evidence/Verification JSON leaves, their parent directories, symlink/hardlink/mount aliases, already-open writer FDs, and any backup authority. Bare chmod does not drain FDs.
- An owner-approved fail-closed barrier that cannot be bypassed by *old unmodified v2* clients. If privileged controls or unavailable topology prevent demonstration, stop with NO-GO and revisit ADR-039/040 Option B's *cooperative* rollout. A new voluntary lock cannot retrofit the existing clients.
- Continuous enforcement and auditable reconciliation over quiescence, WAL-inclusive durable backup, v3 transaction, ambiguous commit/rollback, recheck, and staged release. No auto-retry or unsafe restore.

**It is not yet safe to automate a real v2→v3 migration, assume a userns view is a global block, or state that M0l has achieved all-writer exclusion.**

## Reproduce, verify and keep independent

After separate owner review and merge, on the Debian lab guest (or ordinary Linux CI) from a clean `main` checkout:

```bash
cd "$HOME/projectctl-m0k-lab"
git fetch origin
git status --short
git switch --detach origin/main
source .venv/bin/activate
export TMPDIR="$HOME/m0k-ext4-tmp"
python -m pytest -q -rs tests/test_m60m0l_writer_fd_startup_surface.py
```

This test needs no sudo or `unshare`: the test-owned fixture files and children suffice. The existing M0k JUnit and M0i manifests remain untouched. New M0l CI is **not kernel proof of a production containment policy**, only of the characterization cases. Require exact-head full GitHub Actions pytest, Python compile, schema-source/export guard and pinned SDK. **Keep the PR Draft until owner review; do not merge automatically.**
