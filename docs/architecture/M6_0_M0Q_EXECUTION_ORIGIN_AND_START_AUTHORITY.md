# M6.0 M0q — Python Entry-Point Provenance and Independent Launch-Authority Gate

**Status: executable-origin counterexample + read-only guest capability discovery only. Operational M0, W1, R1 and public Collector/CLI are NO-GO.**
**Base:** merged M0p PR #86 at `main@d565f0e6aa716d7545b2243a161254a93afe0666`; governing M0o profile `D13-KVM-EXT4-DUAL-UID-CUTOVER-ROOT-GATE-v2`, P0–P9 still **UNVERIFIED**.
**Scope:** exactly three **new** files: one nonprivileged read-only context probe, one executable-origin-focused CI test module and this architecture/next-pilot specification. No root operations, systemd/AppArmor configurations installed or modified, no users/groups/ACLs/cgroups/mounts/services changed, no production `projectctl/`, v3 migration, W1 or R1 code touched.

## 1. Why the previous boundary is not enough

M0p's operator-reported disposable Debian KVM trial completed 10/10 intended **negative** observations: the old UID was denied after simulated access handoff, the candidate UID could write and the **same synthetic old-style code** could also write if given the candidate UID. This excludes **credential separation alone** as an authenticator of *program version or approved entry point*. M0p did not execute the genuine deployed v3 writer; source DB stayed v2.

M0q tests the **next independent failure mode** with real unprivileged Python subprocesses, without another root/DAC test:

- Hashing and pinning `/usr/bin/python3` says nothing about which `-m module`, `-c` string, import dependency, `sitecustomize`, `PYTHONPATH`, mutable wheel, provider hook or copied script will run. The same interpreter runs a trusted-looking *and* an attacker-controlled `-m` entry point when a private fixture's `PYTHONPATH` is changed.
- Before executing `-c`, normal Python site initialization can execute a writable `sitecustomize.py` supplied through `PYTHONPATH`. `python -I` mitigates that **specific** environment injection, but is **not** a version attestation or policy that all direct interpreter starts are barred.
- A pathname content hash sampled **before** a later `exec` can differ from the pathname bytes used at launch following a private `os.replace`. Root-owned immutable ancestry, import/content closure, non-writable release distribution and a verified executable launch path must be evaluated together. A prelaunch hash alone is not a descriptor-anchored execution attestation.
- The generic synthetic program from M0p still admits old code as the candidate UID. **No success label in M0q (including AppArmor enabled) can authorize migration.**

A genuine v3-compatible, trusted writer executable and W1 checks **do not yet exist**. M0q intentionally does not create a pseudo-authoritative program or choose a production executable digest.

## 2. Only candidate enforcement topology, not installed controls

Future supported **disposable-guest pilot** uses M0o's *two static, distinct unprivileged identities*, conceptual `legacy_v2_uid` and `candidate_v3_uid`, plus an independent root-owned service/maintenance controller. This is a **closed-world trust assumption**, *not a fact established about the existing* `ehsan` + sudo lab user. The operator must separately verify no privileged actors, untrusted namespaces/remote clients or other ways to assume v3 credentials.

To establish *both* code provenance and externally enforced start scope, a future guest-only implementation must provide:

1. **Root-owned versioned distribution and full code closure:** fixed, read-only, symlink/hardlink/device-anchored interpreter or independently shipped executable, service binary/module, imports/wheels/native extensions, configuration, `sitecustomize` exposure, search paths and env; verify actual provenance and digest over an immutable release root outside state directories writable by either v2/v3 UID. Explicit integrity verification must resist check/exec races and writable aliases. A hash printed by the application itself is not independent authority.
2. **Exact root-owned start entry point:** a reviewed systemd system unit with a static **candidate_v3_uid** and group, an exact trusted `ExecStart` and fixed workdir and environment; no `DynamicUser=`, `ExecStart` shell/inline Python/eval, arbitrary `PYTHONPATH`, environment sourced from a writer-writable file, `ExecStartPre` privilege exception or operator-writable drop-in ambiguity. Treat `NoNewPrivileges=yes`, capability bounding and other hardening as **defense-in-depth of *unit children***, not restrictions on processes outside the unit.
3. **Independent MAC path as a *candidate*, not assumed:** evaluate loaded/enforced AppArmor (or a separately reviewed equivalently mandatory OS-wide access control) against actual fixed program and **all writable file operations**. A `systemd.exec AppArmorProfile=` constrains only processes in that unit, and has no effect if AppArmor is disabled; `-profile` ignores failures. The **unconfined** actor with the same UID is the deliberate mandatory adversarial case. Unconfined tasks may execute an alternative interpreter, embedded bytecode, a writable script or use unmediated credentials unless a separately proven OS policy forbids it. A per-service profile, `aa-exec -p` invoked voluntarily, executable-path attachments and unit masking **do not on their own** prove every v3-credential process is confined.
4. **Mandatory credential/launcher exclusion:** demonstrate that *no actor outside the approved root-owned entry point* can obtain `candidate_v3_uid` (including `sudo`/setuid/user sessions, delegated service control, namespaces and inherited credentials) **or** write via an unconfined equivalent path. If that claim cannot be bounded, the topology is **NO_GO_UNCONFINED_CANDIDATE_CREDENTIAL**. Controlling the user's shell is not a substitute for MAC enforcement.
5. **Preserve old-v2 denial across release:** all `legacy_v2_uid` opens and writes to DB/WAL/SHM, JSON and staging directories remain denied after the candidate service becomes writable. Unknown existing FDs, aliases, daemon restarts, root-capable writers and remote clients must be excluded *before* cutover; old UID must never regain its prior ACL.
6. **Version/migration guard:** even a proven candidate executable cannot operate as a v3 writer until independently reviewed v3 migration/recovery and W1 token/Seal contracts have passed. Do not enable the candidate service on a real v2 project or declare any R1 live-WAL reader trusted via this exercise.

### Technical caveats from upstream behavior

- The systemd `AppArmorProfile=` directive switches a *unit process* to an existing profile; it has **no effect when AppArmor is disabled**, and a leading `-` asks systemd to ignore errors: [systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).
- `NoNewPrivileges=` and other service sandbox options only apply to the unit's processes and descendants, not independently started processes: [systemd.exec NoNewPrivileges](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).
- AppArmor execution mode `ux/Ux` explicitly goes **unconfined**; transitions and fallback modes such as `pux` risk losing enforcement; `Px/px` require an appropriate loaded profile: [AppArmor executable rules](https://www.apparmor.net/man/4.0/apparmor.d/) and [rules basics](https://apparmor-documentation-c38b15.gitlab.io/documentation/getting-started/rules-basics/).
- `aa-exec` is a means of *requesting* confinement; invocation by the test is not proof another same-UID entry point will be confined: [aa-exec](https://www.apparmor.net/man/5.0/aa-exec/). Upstream [AppArmor policy guidance](https://gitlab.com/apparmor/apparmor/-/wikis/aparmor_policy_development_guide) warns about executable attachments overlapping writable locations and unconfined execution avenues.
- Neither an LSM module flag `Y` nor a label for **the caller** is a source of truth for the security policy attached to the future v3 writer, the exact guest unit, or foreign credential access.

## 3. Read-only Debian guest inspection: no sudo

After independently reviewing this PR, on the existing Debian KVM guest **only as the normal user** (no privileged mutation; can be run from the PR branch before merge only if the operator chooses):

```bash
cd "$HOME/projectctl-m0k-lab"
git fetch origin
git switch --detach origin/main   # AFTER the owner merges this PR
source .venv/bin/activate
python -m pytest -q -rs tests/test_m60m0q_executable_origin_scope.py
python -B -m scripts.m0q_execution_context_inspect --inspect
```

`--inspect` reads **only** these fixed paths: `/sys/module/apparmor/parameters/enabled`, `/proc/self/attr/current`, and `/proc/1/comm`. It never calls `systemctl`, `apparmor_parser`, `aa-exec`, `sudo`, or changes service/profile/UID/source files. It reads the **current caller**'s AppArmor label, not the writer's, and does not inspect a selected system unit.

Possible decisions are only `NO_GO_UNSUPPORTED_OS`, `NO_GO_APPARMOR_NOT_VERIFIED_ENABLED`, `NO_GO_CALLER_CONFINEMENT_NOT_OBSERVED`, `NO_GO_SYSTEMD_PID1_NOT_OBSERVED`, `NO_GO_WRITER_ENTRYPOINT_SCOPE_UNPROVEN`, or `NO_GO_INVALID_EXECUTION_SNAPSHOT`. **All** include `authorizes_migration=false`. The probe returns success exit status for successful *inspection*, **not authorization**. Non-Linux CI may run the Python entrypoint counterexamples even though the kernel context reports NO-GO.

The focused tests write/replace **only fixture scripts in pytest `tmp_path`** and invoke standard Python subprocesses with controlled `PYTHONPATH`. They perform neither UID switches nor privileged/AppArmor operations. A passing negative Python test is **not evidence that the guest is actually susceptible through a protected v3 identity**; it illustrates the classes of injection a future policy must rule out.

## 4. Exact adversarial acceptance matrix for a distinct guest-only mandatory enforcement PR

**The next implementation must be a separately reviewed, operator-opt-in disposable guest design — never implicit access to the user's host or current project.** It must answer these named cases in a bounded isolated topology:

| Case | Required negative or positive witness | If unverified |
| --- | --- | --- |
| Q0 guest and policy version | Independent KVM, ext4, LSM/profile and installed-unit provenance; live policy **enforce**, not `complain`, disabled or unit-only self-report | NO_GO_UNVERIFIED_GUEST_POLICY |
| Q1 release artifact closure | Root-owned immutable executable/interpreter, pinned script+dependencies, no writable link/path/import/env alias or check/exec swap | NO_GO_UNTRUSTED_ARTIFACT |
| Q2 positive approved launch | Exactly selected root-owned unit launches script-owned harmless fixture **with observed AppArmor domain**, static v3 test UID and narrow filesystem access; don't simulate v3 W1 | NO_GO_TRUSTED_LAUNCH_UNVERIFIED |
| Q3 direct old program as *old UID* | Same fixture DB+WAL+SHM/JSON staged writes denied **after** the simulated release | NO_GO_LEGACY_UID_REGRESSION |
| Q4 independently launched old Python as *new UID* | Direct interpreter `-c`, `-m`, `PYTHONPATH`, import hook, alternative exec path and writable script cannot write the released fixture unless independently proven trusted | NO_GO_UNCONFINED_CANDIDATE_CREDENTIAL |
| Q5 unconfined/sandbox escape | `aa-exec` opt-out, attachment bypass, `ux/Ux`, unset profile, `ExecStart=+`, unreviewed drop-in, credential delegation, root/capability route either impossible **within closed trust model** or causes hard NO-GO | NO_GO_LSM_OR_LAUNCH_BYPASS |
| Q6 preopen and independent descendants | Complete declared inherited/duplicated FD scope drained; old FD cannot outlive the gate; unknown actors are stop conditions | NO_GO_UNDRAINED_WRITER |
| Q7 continuous hold | Service restarts, timers, sockets, direct old v2 CLI and simulated maintenance/release faults are rejected throughout hold; no data write is allowed outside approved fixture | NO_GO_BARRIER_NOT_CONTINUOUS |
| Q8 cleanup and evidence | Unique guest-only fixture, exact profile/unit identifiers, private audit record of real kernel decisions, no undrained sandbox processes or residual profile/mount/service modifications | NO_GO_CLEANUP_UNVERIFIED |

A test harness that merely starts a confined service and watches it succeed is **insufficient**. In particular **Q4 is the hard gate**: if a direct old/interpreted program can still write using the new UID, changing the label or reporting its SHA does not solve the problem. Stop and revise architecture rather than add more self-validating Boolean checks.

The next privileged pilot must explicitly account for the **host-global nature of loading/changing AppArmor profiles** and systemd units; make its test resources uniquely script-owned, refuse unsafe collisions, record exact identities, avoid changes to existing global profiles/units, have crash-safe containment, and require a separately approved guest runbook with root acknowledgment. **No such installer, loader, policy, unit or root action exists in M0q.**

## 5. Admission disposition and scope discipline

For M0q the strongest possible conclusion is **`M0Q_EXECUTION_ORIGIN_RISKS_DOCUMENTED`**, not an assertion that direct v2 launch is blocked. The previous M0o P0–P9 remain unverified; no OCI/container/remote/privileged topology is certified and no trusted W1 or R1 exists. If an LSM cannot constrain the full **credential and entrypoint** threat scope, the design must declare **`NO_GO_UNSUPPORTED_DEPLOYMENT`** or revisit the phased v2-compatible option from ADR-040.

**No operational state changed by this PR. Keep Draft until exact-head CI and owner security review; do not auto-merge.**
