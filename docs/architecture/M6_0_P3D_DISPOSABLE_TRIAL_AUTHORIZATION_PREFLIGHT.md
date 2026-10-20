# M6.0 P3d — Disposable Trial Authorization and Environment Preflight

**Date:** 2026-10-20

**Baseline:** merged P3c PR #109 and post-merge hygiene PR #110, `main@44ca610409a781608fc1843dca8333701bc7e5d5`.

**Classification:** DESIGN / OFFLINE DOSSIER REVIEW ONLY; **NO PRIVILEGED TRIAL AUTHORIZATION**.

**Decision:** `P3D_NO_GO_TRIAL_NOT_AUTHORIZED`.

This stage converts the P3c T1 conditional VM topology into an explicit, machine-checkable **request checklist**. It does **not** provision or inspect a VM, check real filesystems, execute the 28 P3-F scenarios, grant authority, sign an approval, deploy a Custodian or change the operator's Debian machine. P3/P3a/P3b/P3c conclusions remain intact.

## 1. Scope and inputs

Chosen conditional architecture: P3-C2 / P3c T1, an independently administered **disposable Debian VM**, one untrusted static writer identity, a separately controlled static Custodian identity and an independently controlled observer. A future target must use a dedicated nonvolatile storage candidate (the prior observed `/tmp` rw tmpfs is rejected), synthetic data and an explicitly scoped root/hypervisor trusted computing base. Root or the VM host rolling the whole guest back is **not** defeated by ordinary local DAC. If it must be in adversarial scope, refuse T1 without a separately approved external monotonic authority.

Files introduced:

- `scripts/p3d_disposable_preflight.py` — offline fixed-schema stdin parser; strictly bounded to 24 KiB; duplicate-key, forged permission, unexpected field, missing/duplicate/claimed-passed test and noncanonical declaration refusal. Prints only fixed field names, statuses and numbers in JSON; one fixed refusal if input invalid. Checks current non-root UID/GID only to avoid elevated invocation; does not attest a host or grant permissions.
- `docs/architecture/p3/p3d-disposable-trial-request.template.json` — checked-in **unfilled**, sanitized request with ten `MISSING` evidence claims, five false scope claims, nine false operational permission claims, 28 `NOT_RUN` cases, no owner or reviewer approval.
- `docs/architecture/p3/p3d-authorization-preflight-decision.json` — pinned repository decision and unchanged operational restrictions.
- `tests/test_m60_p3d_disposable_preflight.py` — synthetic positive-shape and adversarial denial tests.

A requested evidence value can later be set only to `CLAIMED_UNVERIFIED` in a **separately reviewed** copy. That states merely that a human asserts supporting material exists. It does NOT attach a real artifact or prove its trustworthiness. An actual guest identifier, directory path, principal ID, ACL dump, privilege-bearing command list, private key or reviewer signature MUST NOT be submitted in this JSON or committed to this repository. Sensitive specifics belong in an independently controlled, limited-access approval record, linked/reconciled only after manual review by an actual owner and independent administrator. The script deliberately rejects arbitrary string/path/command fields.

## 2. Hard barriers and machine-readable semantics

`P3D_NO_GO_TRIAL_NOT_AUTHORIZED` is **unconditional**. The only difference between the result categories is the completeness of **untrusted declarations**:

| Result field | Meaning | Authorization |
| --- | --- | --- |
| `DOSSIER_INCOMPLETE` | One or more of 10 evidence keys is missing or one of 5 scope booleans is false | Never |
| `HUMAN_CLAIMS_PRESENT_UNVERIFIED` | All ten fields merely claim supporting material and all five scope flags are asserted | Never |
| `missing_evidence_keys`, `unmet_scope_keys` | Which claims a human must independently review | Never |
| `authorizations` | Nine fixed permission denials, all false | Never |
| `actual_trial_cases_executed` | Always zero; all P3-F01 to P3-F28 remain NOT_RUN | Never |

A deliberately populated but forged manifest MUST NOT get a trial GO. The input is attacker-controllable; schema checks establish only structure, **not** the existence of an administrator, persistent disk, code ownership, independent ledger, protected high-water, issuer, coherent DB/JSON source epoch, fsync/no-clobber behavior, or reviewer assent. No field can carry an approval, a signature, exact privileged command, target pathname, or a passed scenario. Unknown keys, nonboolean booleans and mismatched scenario list cause fixed refusal. JSON key order is immaterial; scenario order is fixed P3-F01 through P3-F28.

## 3. What the separate owner-approved trial application must prove

A future human review (not completed by this PR) must cover these ten independent gates with externally held evidence:

1. **Disposable VM boundary:** owner-controlled guest/host/virtual disk identity, isolation from real ProjectCTL and secrets, snapshot and teardown boundaries, retention budget.
2. **Administrative independence:** real independent administrator and witness, no shared sudo/root, credential, capabilities or controlling code path with legacy writer.
3. **Static identities and groups:** concrete non-root filesystem UIDs/GIDs/groups and kernel-level credential denial, including old writer and supplemental private GID.
4. **Nonvolatile filesystem and protected ancestry:** independently verified guest/host backing, mount namespace, overlay/idmap, ACL/LSM and admin-owned parent chain; `/tmp` is not a storage target.
5. **Executable provenance:** protected Custodian executable, Python import dependencies, service launcher/config and every writable ancestor; deny old writer code injection.
6. **Legacy bypass controls:** uncooperative old binary, inherited FDs, sockets, service entry points, symlink/hardlink/bind alias adversarial plan and observer.
7. **Authoritative commit design:** no-clobber exact object, file+directory fsync, single transaction tying package+receipt+high-water to committed state, protected replay and no self-hashed trust surrogate.
8. **Crash and recovery plan:** phase-accurate SIGKILL/reboot/ACK-loss/ENOSPC/EIO/retirement cut points and independent fresh-process readbacks, no ambiguous-ACK retry.
9. **Synthetic privacy and abort:** no real DB/WAL/secrets, finite private evidence, owner-approved cleanup, immediate-stop criteria, exact future command manifest.
10. **Independent security/owner signoff:** reviewers examine the exact disposable target and every privilege-bearing step **outside this validator** before any action.

Each of P3-F01 to P3-F28 must have a separate observing principal, failure and negative control, before/after witness, precise cut point, rollback scope, privacy boundary and human disposition. All cases remain NOT_RUN. The source-authority claims P0/P1/P2 and output P4 are separate and still NO_GO even if a synthetic CRED/BLOB/SEQ/DUR trial eventually succeeds.

## 4. Safe ordinary-user verification

After reviewing the new script and fixed input, on the Debian development checkout:

```bash
python -m pytest -q -rs tests/test_m60_p3d_disposable_preflight.py
python -m json.tool docs/architecture/p3/p3d-disposable-trial-request.template.json > /dev/null
python -m json.tool docs/architecture/p3/p3d-authorization-preflight-decision.json > /dev/null
python scripts/p3d_disposable_preflight.py < docs/architecture/p3/p3d-disposable-trial-request.template.json
git diff --check 44ca610409a781608fc1843dca8333701bc7e5d5..HEAD
```

All commands are nonprivileged and do not create or modify guest/system/project database state; shell `> /dev/null` discards display output only. The intended result is `DOSSIER_INCOMPLETE` and `P3D_NO_GO_TRIAL_NOT_AUTHORIZED`, **not** a ready-to-run test plan.

## 5. Stop and follow-up decision

**NO-GO remains mandatory** if no isolated disposable VM, independent administrator, static Custodian trust boundary, viable persistent store, approved exact privileged-command plan, protected high-water, independently observed restart failure semantics or separate owner/security signoff exists. Do not substitute the current project user's Debian checkout or same-UID sidecar. If root/full-host rollback must be treated as adversarial, stop local T1 and separately reassess the trust architecture.

The next meaningful action is for a human owner to select a **real disposable VM and an actually independent administrator/observer**, with review details kept outside the repository. Only a later **separate, explicit, bounded human authorization** could allow a particular future trial. Neither this PR, a green CI nor fully claimed evidence changes any P0–P4 operational gate, W1, R1, migration, Collector/CLI or Worker/Task authority.
