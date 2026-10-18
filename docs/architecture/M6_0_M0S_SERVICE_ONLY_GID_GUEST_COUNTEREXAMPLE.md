# M6.0 M0s — Disposable KVM Service-Only GID Credential Counterexample

**Status:** REVIEW-GATED, OPTIONAL ROOT-IN-DISPOSABLE-GUEST TEST ONLY. No systemd unit or AppArmor profile is installed/changed. No actual migration, W1, R1, Collector or production writer authorization.

**Base:** merged M0r follow-up PR #89, main 3734a3a212ea20440f428546e242e377b9ff2c8b. M0o proposed two separate static writer UIDs; M0p showed old code writes if given the v3 UID; M0q exposed Python entrypoint/import origin; M0r proposed an additional private service-only write GID. The operator-reported Debian M0r Parser observation was a PATH false negative, not kernel confinement.

## 1. Objective — isolate M0r R4/R5, not general writer quiescence

This pilot deliberately probes *one* credential fact in actual guest Linux DAC:
- An independent candidate-UID Python process **without** the private writer group must not create DB/WAL/SHM writes or publish JSON.
- Giving a child the dedicated writer group allows a synthetic SQLite probe-table update and dummy JSON stage+replace, on a freshly initialized **real ProjectCTL v2 state.sqlite**.
- The *exact same synthetic program* acting as old code **also writes** with both candidate UID and private writer GID. That is the expected **security counterexample**, not an accepted trusted executable.
- The legacy UID remains denied after the fixture's synthetic release; denied operations must leave the DB probe count and published JSON unchanged.

M0s does not test or create an actual systemd unit, an enforced AppArmor profile, a true v3 writer, a globally held new-start embargo, an all-writer FD drain, complete alias inventory or live WAL-export safety. Neither a read-only KVM observation nor matching self-reported booleans is independent VM attestation.

## 2. Privilege boundary and file scope

**Fixed numeric synthetic credentials only**, never caller-selected:
- Legacy UID and primary GID: 63071.
- Candidate UID and primary GID: 63072.
- Private *supplementary* writer GID: 63073, granted only inside individual test-owned children in the pilot.

The script creates **no users or system groups**. Linux child credentials change via setgroups, setresgid and setresuid, after a root-only opt-in preflight. NSS IDs 63071–63073 must be unused, but that alone does not prove absence of active clients, namespaces, host mounts or privilege delegation. A future supported operator must separately attest guest isolation and ID scope. Never use the identifiers for a production service.

The only mutation allowed is a newly and randomly created script-owned directory under **/var/tmp/projectctl-m0s-*** on the independently confirmed disposable Debian KVM/QEMU guest, with guest-local ext4 /var/tmp. It contains an initialized ProjectCTL v2 database, **one disposable test-only SQLite table**, dummy JSON, and any SQLite WAL/SHM or JSON stage leaves produced by the fixture. The test root is not selectable by the caller. Before any group/permission change, the script checks expected direct leaves for owner, device, type and single-link identity, and rejects unexpected files. It sets only fixture leaves to root:63073, 0660, and the private .projectctl directory to root:63073, 02770 so newly created WAL/JSON stages can inherit that group. This is not a secure recursive production ownership procedure.

Every child runs embedded stdlib Python code via a resolved guest-system Python, isolated mode -I, fixed label, fixed operation and minimal environment, with all three operations bounded by subprocess timeouts: O_RDWR DB probe, disposable SQLite test-table INSERT, and staged dummy JSON replacement. It cannot select a production source path, UID, GID, binary or action. No service, root-owned shared profile, sudoers, cgroup, mount or host PID is modified.

Cleanup is limited to the exact fresh temp root and attempted in a finally handler. Kill, power loss or unexpected cleanup failure **may leave a private root-owned fixture**; do not glob-delete or claim durable cleanup. Review exact leftover inode/scope manually if interruption occurs. No backup/restore or migration command exists in this PR.

## 3. Expected readout and nonauthorizing decision

| Phase | Actor | Mandatory observation |
| --- | --- | --- |
| Embargo-before-release | Both old and candidate UIDs *without* writer GID | All direct DB opens, SQLite inserts and dummy JSON publications denied |
| Group-gated synthetic release | Old UID without GID | Still denied |
| Group-gated synthetic release | Candidate UID without writer GID | Still denied; DB/JSON unchanged |
| Group-gated synthetic release | Candidate UID **with private writer GID** | Synthetic DB/JSON writes succeed |
| **Credential bypass** | **Same old-style synthetic code with candidate UID plus writer GID** | **Writes succeed — failure of binary provenance** |
| Final check | Real initialized v2 source | Application version stays v2, no migration |

Nine exact-True fixture observations are checked by the test-only contract. Missing, malformed or negative evidence yields a named NO_GO_UNVERIFIED result. When every bounded expected observation is true, the decision is:

    NO_GO_OLD_CODE_WITH_SERVICE_GID_CAN_WRITE
    authorizes_migration=false
    authorizes_policy_install=false

This is diagnostic confirmation of an **unsafe privilege-reuse path**, not permission to change AppArmor, install a service, migrate SQLite or accept a trusted writer.

## 4. Runbook and hard preconditions

**Before any guest root execution**: explicitly review the PR, confirm exact git head, merge only with owner approval, then run the **ordinary-user** checks:

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    export TMPDIR="$HOME/m0k-ext4-tmp"
    python -m pytest -q -rs tests/test_m60m0s_guest_service_gid_contract.py
    python -B -m scripts.m0s_guest_service_gid_pilot --inspect
    findmnt -T /var/tmp -no SOURCE,FSTYPE,TARGET
    systemd-detect-virt --vm
    for n in 63071 63072 63073; do
      getent passwd "$n" || true
      getent group "$n" || true
    done

The root-only portion requires **a separate explicit operator authorization** after independent confirmation of a truly disposable KVM guest with no host/production/shared mounts, no other actors owning the fixed identifiers and a safe cleanup window. **Do not run this merely because the PR was merged.** Only then might the operator choose to run:

    cd "$HOME/projectctl-m0k-lab"
    source .venv/bin/activate
    sudo "$PWD/.venv/bin/python" -B -m scripts.m0s_guest_service_gid_pilot \
      --run --acknowledge DISPOSABLE_KVM_GUEST_M0S_SERVICE_ONLY_GID_NEGATIVE_LAB

Never run root mode on a production machine, shared workstation or host. Unexpected error, denied-positive case, cleanup failure or missing scope evidence => stop, do not retry automatically. Guest stdout is **operator-reported evidence**, not a cryptographically independently attested kernel proof.

## 5. Next mandatory boundary remains separate

A future PR may explore collision-free, privately named systemd units and AppArmor profiles **only on a separately approved disposable guest**, with exact teardown and no host-wide Python profile. The real question is whether any untrusted actor can obtain *both* candidate UID and writer GID outside the reviewed immutable entrypoint. Linux credentials and supplementary groups are privileges, **not binary identity**. Unit-level AppArmor confinement does not automatically constrain external same-credential processes.

A genuine mandatory-enforcement pilot requires exact program/module provenance, root-owned service config, confinement observed on real unit descendants, negative old-code tests **both without and with group**, no escaping/inherited file descriptors, private WAL/SHM+JSON scope, restart/start-barrier and independently audited cleanup. R4/R5 are only a subset of M0r R0–R9. <https://man7.org/linux/man-pages/man7/credentials.7.html> and <https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html> describe credential and unit group semantics.

**Strongest M0s possible status: M0S_GID_COUNTEREXAMPLE_REVIEW_ONLY.** The M0o P0–P9 and M0r R0–R9 real-world conditions remain **UNVERIFIED**. v2→v3 production migration and W1/R1/Collector/CLI remain **NO-GO**.
