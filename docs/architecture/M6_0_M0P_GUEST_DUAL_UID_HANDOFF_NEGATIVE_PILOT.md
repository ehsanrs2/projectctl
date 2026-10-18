# M6.0 M0p — Disposable KVM Dual-UID Cutover and Old-Program Credential Bypass Pilot

**Status:** DRAFT, operator-reviewed guest-only **negative** proof proposal, **not a production cutover**; no systemd start authority or binary authenticity proof. **Production v2→v3 remains NO-GO.**
**Base:** merged PR #85 at main `e8a26f43660ef4ffb95e3fa36f5742bd7faf7afa`; M0o profile `D13-KVM-EXT4-DUAL-UID-CUTOVER-ROOT-GATE-v2`.
**Scope:** two test-only scripts, one nonroot CI test file and this doc. No changes in `projectctl/`, migration history, registered v2 DB schema, `systemd` services, system users/groups, ACLs, cgroups, mounts, host PIDs, public CLI, W1 or R1.

## 1. Precise decision and why this is useful after M0o

M0m positively demonstrated on a disposable KVM/ext4 v2 fixture that root-owned DAC can deny fresh old-writer opens while **preopened FDs remain writable**. M0n showed exact known-process FD identity and pidfd exit while unmanaged writers still bypassed a voluntary process launcher. M0o selected a **proposed** dual-UID version boundary; it did not prove that environment exists.

**M0p isolates the next missing transition invariant:** even if root DAC denies the *old UID* both during maintenance and **after** new credentials are permitted, **identical old-style code given the new UID can still write**. Therefore filesystem credentials alone do **not** authenticate the installed new binary or a root-owned fixed executable/launch policy. This is a negative result that constrains the next independent systemd+executable-identity pilot.

M0p runs a root-controlled, newly created disposable *real ProjectCTL v2* database with **one synthetic SQLite probe table**, dummy JSON and dummy FD leaf under one randomly named, script-owned `/var/tmp/projectctl-m0p-*` tree. Synthetic separate-interpreter actors use the Python standard library `sqlite3`, **not an unmodified v2 RunStore binary and not a candidate v3 runtime**. This is an intentional test limitation; source version stays 2 and **no migration occurs**.

### Fixed roles

- Operator: already verified `sudo` from an independently authenticated **nonroot** guest user; actual root authority for the *disposable fixture only*.
- `legacy_fixture_uid = 63071`, `candidate_fixture_uid = 63072`: ephemeral **numeric credentials only** used by test-owned child processes. The test rejects existing passwd/group entries with these numbers; it does **not** create system users or groups. A lack of NSS entries is **not** proof those UIDs cannot exist in another namespace or access the filesystem via an undeclared path. Do not use them for real service identities or reuse them for production.
- `/var/tmp` must be guest-local `ext4` and systemd must identify the guest as `kvm` or `qemu`. The operator must additionally confirm that the guest is disposable, has no production host mounts, and that the chosen synthetic IDs are unused within the true trust boundary. Tool-reported virtualization/filesystem/UID checks are **not attestation**.
- The Linux actors execute a resolved **guest system Python** and only the embedded, version-neutral disposable probe. They need no access to the operator's private project checkout. They inherit no supplemental groups and cannot sudo.

### Ordered acceptance observations (ten strict booleans)

1. Synthetic old UID can initially update a test probe table in initialized ProjectCTL v2 SQLite and stage/replace dummy JSON.
2. The root-controlled owner takes back only the private test `.projectctl` tree. Fresh old-UID **and** new-UID direct writable opens are denied with `EACCES/EPERM`; synthetic SQLite and dummy JSON publisher attempts from both UIDs fail; DB probe count and JSON bytes remain unchanged.
3. A test-owned preopened old-UID dummy JSON FD survives the permission change and still writes. Its exact **owned child exits**, verified through Linux `pidfd`, *before any credential handoff*. **This cannot prove global FD drainage** or preclude shared/inherited file descriptions in other processes.
4. Only then, root transfers ownership of the private dummy fixture `.projectctl` to the *new* synthetic UID. New UID can update disposable SQLite+JSON, old UID continues to be denied direct opens and attempts at both file families.
5. **Critically, the same embedded old-style probe code**, when executed with *the new UID*, can also write. This is a deliberately successful negative counterexample: **`NO_GO_UNTRUSTED_CANDIDATE_EXECUTION_IDENTITY`**, not a false v3 authorization.
6. The file remains an *initialized v2 ProjectCTL database*, with `APPLICATION_ID` unchanged and `PROJECT_STATE_DB_VERSION=2`; no W1 Seal producer, v3 SQL, WAL backup or migration is involved.

The ten-field `LabObservations` contract requires exact literal `True`. Missing, incorrect or untested observations become `NO_GO_UNVERIFIED_*`. **Even all ten positive bounded observations result in `NO_GO_UNTRUSTED_CANDIDATE_EXECUTION_IDENTITY` with `authorizes_migration=false`.** Unexpected exceptions/unsupported platforms return `NO_GO_LAB_REFUSED` and nonzero exit.

## 2. Restrictions and preflight before running *any* root operation

This is an **optional, explicitly reviewed guest-only** experiment. The ordinary user may run read-only inspect and CI contract tests. **Do not run root `--run` before PR review/merge and independent VM-isolation/UID validation.** Do not run privileged mode on Ubuntu host, production servers, or the current ProjectCTL source/database.

After owner-reviewed merge, run **without sudo** first, from the existing Debian KVM guest:

```bash
cd "$HOME/projectctl-m0k-lab"
git fetch origin
git status --short
git switch --detach origin/main
source .venv/bin/activate
export TMPDIR="$HOME/m0k-ext4-tmp"
python -m pytest -q -rs tests/test_m60m0p_guest_handoff_contract.py
python -B -m scripts.m0p_guest_dual_uid_handoff_lab --inspect
findmnt -T /var/tmp -no SOURCE,FSTYPE,TARGET
systemd-detect-virt --vm
getent passwd 63071; getent passwd 63072
getent group 63071; getent group 63072
```

`getent` should find **no entries** for either reserved numeric test UID/GID; the expected `getent` return code is nonzero, which is not a script failure. Use exact separate review of other processes/containers/host sharing before considering these numeric UIDs unused. No privileged user/group provisioning is included in the PR.

**Only after** the operator separately confirms an isolated, disposable guest, root identity, test UID/GID exclusivity, exact script SHA and acceptance of the intentionally negative result, the optional VM-only run would be:

```bash
cd "$HOME/projectctl-m0k-lab"
source .venv/bin/activate
sudo "$PWD/.venv/bin/python" -B -m \
  scripts.m0p_guest_dual_uid_handoff_lab \
  --run \
  --acknowledge DISPOSABLE_KVM_GUEST_M0P_DUAL_UID_NEGATIVE_LAB
```

The program has **no caller-supplied path, UID, service name or command to affect an existing project**. It gates root execution behind Linux/KVM/ext4/ack/nonroot-`sudo` identity verification, fixed unused NSS IDs and a resolved guest `/usr/bin` Python. It uses only freshly created random temporary fixtures and one script-owned preopen child; normal cleanup handles only that child and that exact tree. Do **not** assume crash/kill/power-loss cleanup: inspect exact leftover fixture identity manually, never glob-delete. It never invokes `systemctl`, sets up service units, creates OS users, changes host data, authorizes backup, calls `projectctl migrate` or writes a v3 database.

## 3. What M0p absolutely does NOT prove

- The test actors are generic SQLite+dummy JSON clients, not actual deployed trusted `RunStore`/Verification/v3 application binaries. A synthetic SQLite table does not validate W1 lease fencing, release-version compatibility, authenticated binary identity or seal publication.
- This does not create/stop/mask a real systemd service or guarantee all CLI, socket, timer, restart or direct Python routes are denied. **New processes still execute; DAC only restricts ordinary new file opens to the fixture.**
- A single owned FD holder and its pidfd exit does not prove global FD absence, inherited FD/SCM_RIGHTS drainage, mount-alias closure, credential revocation, or concurrent unknown-root writers.
- Strict immutable Python result booleans, systemd KVM detection, and CI/owner console output cannot remotely attest privilege, independent enforcement or topology.
- There is deliberately **no successful real v2→v3 cutover** or verified post-release v3 executable. File access transfers to a *test* candidate credential while the **source remains v2**, for proof of credential insufficiency only.

## 4. Required next architecture action (do not launch another generic negative lab)

The subsequent pilot, in a **separate PR and separately approved disposable guest**, must resolve **root-owned executable/entrypoint integrity** and a **real externally enforced start/barrier** without relying solely on DAC or `systemctl mask`. Only after proving **all declared writer/FD holders drained under continuous exclusion** can a future migration-maintenance design be reconsidered. The two static writer identities, root-controlled trusted service entrypoint and strictly one active writable credential are **candidate** requirements, not accepted real deployment facts. Unsupported/unverifiable deployment => `NO_GO_UNSUPPORTED_DEPLOYMENT` or consider staged v2-compatible rollout.

**Never change `docs/PROJECT_STATE.yaml`, production DB version, W1 trusted Seal or R1 Reader admission on the basis of M0p. PR remains Draft until exact-head CI and explicit owner review.**
