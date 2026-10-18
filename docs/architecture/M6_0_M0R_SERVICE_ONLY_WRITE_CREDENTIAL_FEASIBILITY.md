# M6.0 M0r — Mandatory Writer-Launch Feasibility and Service-Only Credential Gate

**Status:** Architecture proposal + nonroot, read-only Debian guest preflight. **NO operational authority.** No profiles, systemd units, users, groups, mounts, migrations or actual security policy are installed, loaded, replaced or executed.

**Baseline:** merged M0q PR #87, main 2388bb8bc52e21aac808e8eb9b7cfbc279980a1f. Governing M0o dual-UID deployment candidate; M0p's operator-reported KVM 10/10 negative credential counterexample; M0q's ordinary-user Debian test (22 passed) and AppArmor module reported enabled while **current caller** was unconfined.

## 1. Security feasibility finding, not an enforcement claim

Systemd's AppArmorProfile setting confines the launched **unit process tree**, not an unrelated interpreter started independently with the same UID. AppArmor checks access using the process profile **in addition to** DAC; it cannot reduce the permissions of an unrelated **unconfined** actor that already has ordinary writable filesystem credentials. Masking a named service, setting NoNewPrivileges for that service, or successfully loading a single AppArmor unit profile **does not satisfy M0q Q4** (deny direct old code run as candidate UID).

Therefore do not create a supposed global solution by attaching a new default policy to the guest's shared system Python interpreter. This could affect system and administrative tools and still leave bypasses through alternative interpreters, imported code, executable aliases and detached processes. M0r refuses to implement a system-wide profile in an existing Debian guest.

References: [systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html), [AppArmor file rules and DAC](https://apparmor-documentation-c38b15.gitlab.io/documentation/getting-started/rules-basics/), [AppArmor parser](https://sources.debian.org/src/apparmor/4.1.0-1/parser/apparmor_parser.8), [Linux open file descriptions](https://man7.org/linux/man-pages/man2/open.2.html). The AppArmor parser's no-kernel-load option is useful for a *future* profile syntax check, not a policy-enforcement or attestation test.

## 2. Concrete candidate: dedicated service-only writer group

**Design hypothesis — not deployed:** Preserve two distinct static unprivileged legacy-v2 and candidate-v3 UIDs from M0o. Add a **third, private write GID** held **only by the root-controlled reviewed system unit**, not automatically by either UID's direct-shell, cron, user-unit, interpreter or login process. During a simulated offline maintenance hold no writer identity has access. After a simulated handoff a root-owned service would receive candidate UID plus the private GID; direct old code as candidate UID **without the service GID** must still be denied by ordinary filesystem permissions. Old v2 UID always remains denied.

The private group is an additional capability and **not binary identity**: old code run with the candidate UID **and** private GID might still write. Root could grant both credentials; an improperly delegated systemd-run/sudo/setgid operation or inherited group/FD also bypasses isolation. These are mandatory negative tests; they cannot be dismissed as harmless simply because a root reviewer deliberately created the counterexample. The closed-world operator contract must explicitly exclude untrusted actors that can acquire both credentials, or the design is NO-GO and needs stronger kernel policy or an independently enforced broker boundary.

For real SQLite, the future protocol must cover state.sqlite, journal/WAL/SHM files (including not-yet-created sidecars), JSON staging/rename and parent directories, unexpected symlink/hardlink/bind mounts, default ACL and umask, owner-vs-group permissions, inode check/replace races, inherited open FDs and remote/namespace clients. Merely assigning a group on one database file is insufficient.

The service must be started by an independently trusted root-held, reviewed unit with verified immutable executable, Python script, imports/wheels/native extensions and config: no writer-writable PYTHONPATH, sitecustomize, script path, drop-in, environment file or service ExecStart expansion. An enforced AppArmor domain of the actual service process is defense-in-depth, not a substitute for the dedicated-GID/credential distribution boundary.

## 3. Adversarial acceptance matrix for a **later, separately approved disposable VM pilot**

All gates start **UNVERIFIED**. The future owner-controlled proof must show:

| Gate | Verification requirement | Required stop condition |
| --- | --- | --- |
| R0: deployment | Isolated disposable Debian KVM, guest-local ext4, no host/prod mounts, exact program/VM identity, no shared/foreign writer | Unknown guest, mount, credential or root actor => NO_GO |
| R1: credential scope | Static v2/v3 UIDs plus private service-only GID; no outside service credential/group assignment or delegated root/sudo/start | Independent actor acquires write group => NO_GO |
| R2: code provenance | Root-owned fixed reviewed interpreter+module+native/import/config closure; no PYTHONPATH, sitecustomize, writable package, script-swap or code injection | Unexpected code can run with trusted writer authority => NO_GO |
| R3: service + MAC | Root-owned verified unit starts service with exact credentials; loaded AppArmor profile in enforce mode is observed for actual child, no loose exec/ux fallback | Only unit MAC observed with unconfined outsiders still writable => NO_GO |
| R4: **Q4/no-group** | Direct old Python -m, -c, script and imports as candidate UID without private GID cannot modify DB+WAL+SHM or JSON stage+replace | Any independent write => NO_GO |
| R5: **Q4/with-group** | Deliberately test same old code as candidate UID **with** private GID on a new disposable fixture and record whether access succeeds | If untrusted actor can get both credentials => NO_GO / redesign |
| R6: old release denial | Old v2 UID remains denied on all ordinary inode/alias paths after service release | Old client write => NO_GO |
| R7: FD and continuous hold | Complete supported FD/descendant/SCM_RIGHTS, restart/trigger, mount alias and WAL/JSON inventory; barrier never lapses during maintenance | Untracked holder, race, timeout or uncertain hold => QUARANTINE |
| R8: safe global-policy lifecycle | Script-owned uniquely named unit and AppArmor profile, refuse collisions, independent unload/cleanup verification; no existing profile or unit replaced | Unexpected host effect or incomplete teardown => NO_GO |
| R9: separate product admission | No real migration, W1 trusted Seal, R1 WAL reader or Collector until independent design and fault proofs | Even passing pilot => REVIEW ONLY, never production GO |

**R4 is necessary but R5 is the architectural stress test.** A direct old program with both candidate credentials might succeed regardless of the AppArmor domain attached to an unrelated unit. If that route can exist in deployment, M0r must not call the policy an independently enforced start boundary.

No privileged installation script or AppArmor profile template is shipped in M0r. Such a pilot must first demonstrate a crash-safe, collision-safe policy/units rollback in a *new, separately reviewed disposable guest*. If safe cleanup cannot be guaranteed, reject the installer idea rather than risk modifying global AppArmor and systemd state in the user's existing VM.

## 4. Nonprivileged deliverables and exact commands

scripts/m0r_guest_launch_authority_preflight.py performs only fixed read-only checks: Linux/nonroot process, systemd-detect-virt --vm, findmnt filesystem type for /var/tmp, AppArmor module enabled flag, the current caller's label, PID1 comm, and **two separate Parser hints**: discovery on the invoking user's PATH and no-follow file metadata for the fixed Debian path `/usr/sbin/apparmor_parser` (root-owned regular executable; no group/world write). Neither verifies package provenance or active kernel confinement. **It never calls apparmor_parser**, does not install an OS policy and cannot attest the profile of any writer. All decisions are NO_GO, with authorizes_migration=false and authorizes_policy_install=false. A successful inspect command can exit 0 while retaining the explicit NO_GO decision.

The BoundaryClaims model records twelve purely *untrusted* review claims; an affirmative direct old-program/same-UID bypass takes precedence over missing fields. Even twelve true values never produce permission to run a kernel installer. Nonroot CI tests exercise these stop decisions but are **not an independent kernel test**.

After owner review and merge, in the existing Debian VM without sudo:

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60m0r_mandatory_launch_feasibility_contract.py
    python -B -m scripts.m0r_guest_launch_authority_preflight --inspect
    command -v apparmor_parser || true

A nonroot `PATH` may exclude `/usr/sbin`. In that case, if the **fixed standard-path file** is a root-owned regular executable with no group/world write, M0r reports `parser_on_path=false`, `parser_standard_path_status=root_owned_executable`, and the **diagnostic** decision `NO_GO_POLICY_PARSER_PRESENT_OUTSIDE_PATH` rather than the misleading old `NO_GO_POLICY_PARSER_NOT_PRESENT`. Missing/unreadable/nonregular/symlink/unsafe-permission standard-path hints have their own NO-GO results. A reported file does **not** establish that any profile is loaded, enforcing, attached to the proposed service or globally covers independent candidate-UID processes. Do not invoke or install it as part of preflight.

Absent parser at the fixed path, the normal caller being unconfined, or positive KVM/ext4 hints are not requests to change host settings.

## 5. Required separate PR after owner security sign-off

If owner accepts the **service-only write GID** model and the boundaries in R0–R9, a separate Draft PR may construct **an opt-in root guest-only** systemd/AppArmor/credential experiment using a random private fixture, new names without collision, exact acknowledgment, and no production project. Its first objective must be the actual R4/R5 negative challenge, not a celebratory test of a positive confined service. It must separately prove no residual global profile, unit, group, process or FD state remains; never overwrite an existing host profile or rely on broad unit restarts.

M0r explicitly does **not** authorize that later root run, a global Python profile, real systemd mutation, source migration, W1/R1, or enabling public Trace. Current operational v2→v3 remains **NO-GO**.


## 6. M0r follow-up — nonroot PATH discovery correction (2026-10-18)

The operator reported a real disposable Debian KVM observation on merged PR #88:
- User `PATH`: `$HOME/projectctl-m0k-lab/.venv/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/games:/usr/games` (no `/usr/sbin`).
- `ls -l /usr/sbin/apparmor_parser`: executable owned by root with mode 0755.
- `dpkg-query -W apparmor`: `apparmor 4.1.0-1`; `dpkg-query -S /usr/sbin/apparmor_parser` identified the AppArmor package.
- `command -v apparmor_parser` produced no path. The initial `shutil.which` observation reported `parser_available=false` and yielded `NO_GO_POLICY_PARSER_NOT_PRESENT`.

**Resolved interpretation:** the executable exists at its standard Debian location, but was not found using the ordinary caller's `PATH`. This correction adds the two separate hints and keeps every decision `NO_GO_*`. The standalone fixed-path file check is an **inode/permission hint only** and does not replace dpkg package verification, current running-process LSM labels, provenance attestation or independent policy enforcement. No root operation or system file modification is introduced.
