# M6.0 P3a — Nonprivileged Debian deployment inventory

**Status:** RESEARCH_ONLY / NONAUTHORITATIVE / P3A_INVENTORY_ONLY_NO_GO.

**Baseline:** merged P3 PR #106, main commit 5fbf1decc4b469cf28fcd98074b19b011a13928f. ADR-039 read-only Trace, ADR-040 Path A design, R0b active-WAL refusal C, and the P3 deployment NO-GO remain unchanged.

## Scope and operator procedure

The standalone script scripts/p3a_nonprivileged_inventory.py only examines metadata of an explicitly selected **existing absolute disposable directory** and its ancestors. It uses lstat, listxattr (ACL presence only), and bounded reads of /proc/self/status and /proc/self/mountinfo. It does not list the target directory contents, follow symbolic links, open project databases or JSON, create reports on disk, execute subprocesses, switch credentials, run sudo, provision services or change configuration.

As an ordinary non-root user, after checking the diff, from an existing clone:

    python scripts/p3a_nonprivileged_inventory.py --candidate-dir /tmp

The /tmp example is **not** a recommended Custodian deployment location: it is only a nonprivileged metadata sampling target that already exists. Never point the tool at the project workspace, .projectctl state, real data, secrets or private homes. The script rejects root, setuid/setgid context, relative/root/ambiguous paths, known ProjectCTL state components, and symlink ancestors. This is not comprehensive protection against naming an unsafe arbitrary path; operator selection remains necessary.

The tool prints compact JSON to stdout and does not save anything. Refusals use a fixed diagnostic without echoing paths. Review JSON privately before publishing. Paths, mount devices and hostnames are not emitted, but numeric UID/GID and kernel release may still be environment-sensitive.

## Observation schema

- candidate: undisclosed-path marker, depth, directory-observed flag.
- ancestry: for each ancestor and candidate, effective-owner/group-match flags, write/sticky permission bits and ACL xattr presence/unknown. No names, paths or ACL bodies. ACL_XATTR_NOT_SEEN is not a proof of absence of other security policy.
- process: effective UID/GID, supplementary group count and CapEff category. Does not attest the identity or privileges of a legacy writer.
- platform: operating system and kernel release (informational only).
- mount: most-specific parsed mountinfo filesystem type and read-only mount-option observation. Neither implies durable fsync nor proves mount namespace, aliases or bind mounts.
- unknowns: unresolved credential, source epoch, signer, durability, rollback, FD, namespace and reboot witnesses.
- authorization: every flag false; decision unconditionally P3A_INVENTORY_ONLY_NO_GO.

This is self-observation, NOT attestation. It remains vulnerable to namespace differences, proc spoofing, race/TOCTOU, simultaneous mutation and privileged rollback. Success does not prove same-UID exclusion, independent Custodian existence, no-clobber behavior, durable commits, High-Water monotonicity, trusted source epoch or authenticated producer.

## Mapping to P3 falsification matrix

| P3 witness | P3a contributes | Still missing |
| --- | --- | --- |
| CRED F01–F08 | Local process, ACL/mode metadata | Independently provisioned identity and adversarial old-writer FD/GID/start-path denial |
| BLOB F09–F11 | FS family observation | Alias, no-follow, TOCTOU, no-clobber hostile tests |
| SEQ F12–F14 | None | Protected sequence/high-water and independently authorized policy |
| DUR F15–F25 | Mount options only | Real target-FS fsync, crash/reboot, lost ACK and retirement tests |
| AUTH F07/F14/F27 | None | Independently authenticated issuer and P0/P1 source epoch |
| EXP F26–F28 | Sanitized metadata only | All P0–P3 proofs and explicit P4 approval |

**Next step:** privately review redacted Debian observation, define the threat scope, disposable topology and independent administrator. A later separately reviewed and explicitly approved trial is required for actual dual-principal experiments. No positive P3a JSON result can authorize a privileged trial.

## Verification

    python -m pytest -q tests/test_m60_p3a_nonprivileged_inventory.py
    git diff --check 5fbf1decc4b469cf28fcd98074b19b011a13928f..HEAD

These are synthetic tests, not Debian attestation. Operational P0–P4, v3 migration, W1, R1, Collector/CLI, keys, services, root and Worker/Task authority remain NO-GO.
