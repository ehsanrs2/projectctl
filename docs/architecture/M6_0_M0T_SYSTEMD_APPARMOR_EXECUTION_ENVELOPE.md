# M6.0 M0t — systemd / AppArmor execution envelope, before privileged enforcement

**State: DRAFT DESIGN, NO INSTALL AUTHORITY.** This PR creates two intentionally unresolved, **noninstallable** systemd/AppArmor templates, a strictly offline source-template review script, and unprivileged tests. It does not execute an installer, start a service, load an AppArmor profile, change credentials or any ProjectCTL project file. Production v2→v3, W1 Seal, R1 WAL Reader and Collector/CLI all remain **NO-GO**.

**Baseline:** merged #91 on main f4ca66d1bf3591b99bf47516b1907364ccdd255b; M0o candidate closed-world profile; M0r service-only GID design; owner-reported M0s root fixture 9/9 expected negative witnesses. M0s demonstrated **identical old synthetic code can write with BOTH candidate UID and private service writer GID**, producing NO_GO_OLD_CODE_WITH_SERVICE_GID_CAN_WRITE. The guest stdout is operator-provided evidence, not an independent VM attestation. A post-run M0s fixture cleanup check has not yet been provided.

## 1. Crucial gap: confinement of a service is not a global old-client execution embargo

Systemd User=, Group=, SupplementaryGroups= and AppArmorProfile= apply to the launched unit's process tree. They do **not** constrain a different unconfined old interpreter that obtains both writable credentials. An unattached named AppArmor policy has no automatic executable attachment. AppArmorProfile must refer to an already-loaded profile; it is ineffective when AppArmor is disabled; execution prefixes '+' bypass some unit options and '-' on the profile tells systemd to ignore failure. The profile's exec rules must exclude unconfined transitions ux/Ux and fallback pux/Pux. These details are documented by [systemd.exec](https://www.freedesktop.org/software/systemd/man/257/systemd.exec.html), [AppArmor profile types](https://apparmor-documentation-c38b15.gitlab.io/documentation/getting-started/profiles-basics/), and [AppArmor exec modes](https://www.apparmor.net/man/4.0/apparmor.d/).

**Two separate threat models:**

- **A — trusted-root restricted credential distribution.** Only a trusted guest root controller can issue the private GID, and a pinned/immutable candidate service is the only approved root-controlled launch route. All untrusted direct candidate-UID processes lack the group and fail DAC. Even here, root can intentionally grant old code the group, as M0s showed; to claim this topology is bounded, an independent reviewer must prove no **untrusted** actor can gain both credentials, substitute code inside the trusted service or inherit a writable FD. This is a **trust assumption plus externally evidenced limited scope**, not a global mandatory execution ban.
- **B — mandatory prohibition even with both UID and GID.** This requires a completely independent OS kernel mediation boundary covering every relevant execution and file-access route. A unit-local AppArmor profile **does not implement B**. Do not load a broad attachment to shared /usr/bin/python3 on an existing guest. If untrusted actors with both credentials are in scope, Model A fails and M0t cannot authorize B.

## 2. Exactly what this PR provides

- docs/architecture/m0t/m0t-review-only.service.template: deliberately unresolved, not a usable unit; shows fixed M0s *synthetic* UID 63072, primary GID 63072 and supplementary GID 63073; reviewed entrypoint marker, private fixture-only ReadWritePaths, explicit non-optional AppArmorProfile, no ambient/bounding capabilities and service-local hardening. **No reviewed v3/W1 executable exists**, hence the entrypoint marker cannot honestly be replaced in M0t.
- docs/architecture/m0t/m0t-review-only.apparmor.template: deliberately non-loadable named policy specification with unresolved reviewed exact interpreter+library closure, actor/import closure, database/WAL/SHM and JSON stage/rename rules, and no unconfined exec fallback. It has no executable attachment to global system Python.
- scripts/m0t_enforcement_envelope_review.py: only reads two fixed checked-in text files and emits nonauthorizing JSON, checking strict unit keys and reviewed profile placeholders. It is **not** a systemd parser, AppArmor syntax validation, disk provenance audit, unit process inspector or attestation.
- tests/test_m60m0t_enforcement_envelope_contract.py: nonroot validation of strict fails-closed conditions, systemd modifier and capability drift, direct credential bypass outcome, unsafe profile changes, and refusal of any root/install CLI.

Even with all hypothetical human claims true, the only admission result is NO_GO_MANDATORY_ENFORCEMENT_NOT_INDEPENDENTLY_ATTESTED. All other results also remain NO_GO, authorizes_root_trial=false, authorizes_policy_install=false and authorizes_migration=false.

**Unit hardening is defense-in-depth, not universal write denial.** ProtectSystem=strict, NoNewPrivileges=yes, RestrictNamespaces=yes and AppArmorProfile= apply only to the unit and its children; a separate same-credential writer remains a necessary adversarial test.

## 3. Proposed acceptance matrix T0–T12 for a different, reviewed disposable-guest pilot

Every gate starts **UNVERIFIED**.

| ID | Required externally checked guest evidence | NO-GO condition |
| --- | --- | --- |
| T0 | Disposable KVM guest, local ext4, no host/production/shared mounts or foreign root-capable actors, pinned VM and source identity | Unknown trust boundary |
| T1 | Collision-free, root-owned new unit/profile/fixture with durable operation/rollback log, safe reboot and crash cleanup before starting anything | Global changes cannot be safely restored |
| T2 | Root-owned fixed actor/interpreter and complete Python import/native extension/library/config closure, immutable at launch, no check/exec/symlink path swap | Unreviewed code obtains group |
| T3 | Real start/credential authority: service, unit drop-ins, timers/sockets, sudo/polkit/systemd-run, group delegation and CLI/provider paths | Any untrusted both-credential route |
| T4 | Independently read exact installed unit, ExecStart bytes/args, UID/GID and named profile; reject '+' exec, '-' profile errors, shell and writable environments | Unit or code source drift |
| T5 | Kernel shows loaded **enforcing** policy and correct live service process label; exact WAL/SHM/JSON stage and import scope, no ux/pux fallback | Only AppArmor Y, a caller label, or unit-reported success |
| T6 | Direct independent old program under candidate UID **without** writer GID fails DB/WAL/SHM and JSON create/replace | Any mutation |
| T7 | Deliberate old code as candidate UID **with** writer GID: document exact label and any write, then verify no *untrusted* launch route to both | Untrusted actor can obtain both |
| T8 | Reviewed immutable **synthetic** actor launched by one root-owned fixture unit with private GID, actual enforcing process label and scoped writes | Wrong process/credential/label |
| T9 | Old legacy v2 UID remains denied after simulated fixture release, including late restart | Any old UID write |
| T10 | All declared DB/JSON/WAL/SHM aliases, open FDs, SCM_RIGHTS recipients, descendants and independent restart writers drained under continuous embargo | Unknown actor/FD/race => quarantine |
| T11 | Restart, crash, disk-full, SIGKILL, power-loss and reboot tested with **independently verified** no residual global unit/profile or credential/FD effects | Incomplete rollback / quarantine |
| T12 | W1 and v3 migration/backup/commit recovery, R1 reader and Collector separately evaluated | Even pilot success cannot grant GO |

A policy that only confines one systemd service cannot substitute for T7. Root authority is explicitly trusted under Model A; it is not a credential-level assertion that an intentional root-run old-code test will fail.

## 4. Global policy lifecycle requires a separate security and rollback design

A later installer PR, if ever proposed, must first establish safe use of new unique guest-global unit/profile names, atomic no-follow root-owned file publication, collision detection, independently verified cleanup/rollback across unexpected exits/reboots, bounded lifecycle of all fixture actors, immutable executable+dependency hashes anchored at **actual execution**, and exact observation of real kernel enforcing profile/credentials. Refuse if the installed Debian kernel/service manager cannot provide those witnesses.

**Never silently install** the template under /etc/systemd/system or /etc/apparmor.d, update sudoers, change global system Python, use a real project state path, or run the M0s root pilot again to claim an AppArmor proof. A successful systemd-analyze syntax check or apparmor_parser non-loading parse check will still not certify actual enforcement.

## 5. Safe next operator action (only after review and merge)

These commands are **nonprivileged and read-only**:

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60m0t_enforcement_envelope_contract.py
    python -B -m scripts.m0t_enforcement_envelope_review --inspect
    find /var/tmp -maxdepth 1 -type d -name 'projectctl-m0s-*' -print

The final command may reveal a leftover test fixture (not automatically safe to delete), and no output does not attest all namespaces or guest crash-safety. Stop and inspect any residue rather than deleting it.

**Disposition: review-only M0t prerequisite complete if static contract CI succeeds.** Independent mandatory launch/path enforcement is not yet proven, all M0o P0–P9 and M0r R0–R9 deployment gates remain UNVERIFIED. An actual privileged guest policy pilot requires a different Draft PR and explicit operator authorization. Operational migration and W1/R1/Collector are NO-GO.
