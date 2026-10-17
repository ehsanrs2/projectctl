# M6.0 M0i — Offline VM Kernel Evidence and M0h Host-NO-GO Review Contract

**Status:** test-only/owner-side **read-only evidence verifier**, no service changes, no operational migration.
**Baseline:** `main@5be3ddf87fe9191c593a3744dc6cfd44bf0453a9` (M0g merged).
**Dependency:** M0h **PR #78 is still Draft and unmerged**. Pin its reviewed **exact HEAD** `4c0b28ebe3b05a3c550b8ccd10b419ab4d3dd6fe` for the contract only. This M0i branch is created independently from `main`; it does not import or bundle M0h code.
**Scope:** `scripts/m0i_verify_vm_evidence.py`, `tests/test_m60m0i_vm_evidence_contract.py`, and this document. No changes under `projectctl/`, migration registry or system configuration.

## Why M0i exists

The owner-host M0h run on 2026-10-17 at exact HEAD showed **2 passing / 5 skipped** cases. Both Linuxbrew and `/usr/bin/unshare --user --map-root-user --mount --fork -- true` failed writing `/proc/self/uid_map`: `Operation not permitted`. The observed host kernel was `6.11.0-29-generic`; unprivileged userns enabled generally; AppArmor unprivileged-userns restriction enabled. Kernel audit recorded a transition from `unconfined` to `unprivileged_userns` and at least one `apparmor="DENIED" operation="capable" ... capname="sys_admin"`. That DENIED event was **not proven to belong to the last failing invocation**. Nevertheless the current host cannot provide *positive* M0h mount-namespace evidence. Do **not** disable AppArmor, elevate permissions, or reclassify skipped tests as success.

M0h also deliberately demonstrates that a child-specific readonly bind view leaves the original source alias writable, that preopened handles are unresolved, and that an independent v2 interpreter can still publish. Passing all seven M0h cases would **not** prove all-writer exclusion; it would prove the experimental view plus its documented bypass cases.

**M0i creates one small offline verifier for these observations. It never claims to attest to kernel state.** JSON, JUnit XML, and the claimed git SHA are locally supplied and can all be forged by their writer. A SHA-256 check guards against accidental post-bundle changes, **not** adversarial provenance forgery. A separately trusted, reviewed owner chain would be required before using any evidence in real maintenance.

## Exact evidence format and reviewer semantics

The tool is `scripts/m0i_verify_vm_evidence.py` and uses only the Python 3.12+ standard library. It accepts two explicitly supplied local files, each capped at 1 MiB:

- `--manifest`: UTF-8 JSON with **exactly** `protocol`, `m0h_commit`, `test_module`, `junit_sha256`, and `environment`. All duplicate/missing/unknown keys are refused. `protocol` must equal `projectctl-m0i-v1`; the test commit and test path must match the pinned PR #78 source. The environment has exactly `kind` (`owner_host` or `disposable_vm`), `kernel_release`, `filesystem`, `scope_id`, and `userns_policy`. These environment fields are **self-reported descriptive claims**; they are not authenticated.
- `--junit`: exact bytes of `pytest --junitxml=...` for **only** `tests/test_m60m0h_mount_namespace_access_pilot.py`. The tool recomputes SHA-256, rejects DTD/ENTITY, malformed XML, duplicated/unexpected/missing cases or wrong class; then requires the **exact seven test IDs** at PR #78's pinned HEAD.

Expected seven cases: 2 readonly-view kernel-denial checks; 2 original-source alias-write bypass checks; 1 preopened-fd ambiguity case; 1 outside-namespace legacy-v2 write; 1 fail-closed policy test. The **first five** require namespace support on a real host. There is no automatic fallback and no skip-as-pass conversion.

| Evidence outcome | Reviewer decision | What it proves |
| --- | --- | --- |
| Exact owner-host JUnit: 2 passed, 5 kernel skips | `NO_GO_KERNEL_CASES_SKIPPED` | Missing kernel proof, as observed in the owner's Ubuntu/AppArmor host |
| Any single kernel skip, even on claimed VM | `NO_GO_KERNEL_CASES_SKIPPED` | The specific positive/negative Linux case did not run |
| Any failed/error case | `NO_GO_TEST_FAILURE_OR_ERROR` | Test result unusable for acceptance |
| Wrong SHA, wrong class/case set, duplicate/malformed records | `QUARANTINE_...` | Provenance consistency or structural evidence invalid |
| All 7 passed on an environment described as `owner_host` | `NO_GO_HOST_NOT_ISOLATED_VM` | Not a separately selected disposable VM |
| All 7 passed on a *claimed* `disposable_vm` | **`LAB_REVIEW_ONLY`** | Locally well-formed laboratory summary; **NOT authenticated host/kernel or all-writer evidence** |
| Missing actual external writer/restart/fd/mount/backup/recovery proof | Operational migration remains **NO-GO** | JUnit of M0h never covers these authority requirements |

The machine output **always** contains `"authorizes_migration": false`. CLI exit code `0` means only that the JSON/JUnit files received `LAB_REVIEW_ONLY`; all other outcomes return `2`. Do not connect this result to an operational admittance switch.

## Creating a disposable evidence bundle (future selected VM ONLY)

**Do not run elevated commands or change host AppArmor settings to force passing tests.** Choose, document and separately approve a disposable VM with its own local filesystem, exact guest kernel, namespaces/AppArmor policy and no production project mounts. Test only on its temporary project directory.

In a *clean M0h checkout at the pinned SHA*, with `pytest` installed:

```bash
# The following creates only local evidence files and disposable pytest fixtures.
git rev-parse HEAD  # MUST print 4c0b28ebe3b05a3c550b8ccd10b419ab4d3dd6fe
EVIDENCE_DIR="$(mktemp -d)"
python -m pytest -q -rs \
  --junitxml="$EVIDENCE_DIR/m0h-junit.xml" \
  tests/test_m60m0h_mount_namespace_access_pilot.py
```

The reviewer lives in a **different M0i checkout** because M0h remains unmerged. Populate `manifest.json` in the evidence directory using the actual JUnit digest and **reviewed** selected-VM environment values. This sample records format only, not a trustworthy attestation:

```json
{
  "protocol": "projectctl-m0i-v1",
  "m0h_commit": "4c0b28ebe3b05a3c550b8ccd10b419ab4d3dd6fe",
  "test_module": "tests/test_m60m0h_mount_namespace_access_pilot.py",
  "junit_sha256": "REPLACE_WITH_SHA256_OF_M0H_JUNIT_BYTES",
  "environment": {
    "kind": "disposable_vm",
    "kernel_release": "REPLACE_WITH_VERIFIED_GUEST_KERNEL",
    "filesystem": "REPLACE_WITH_VERIFIED_LOCAL_FILESYSTEM",
    "scope_id": "REPLACE_WITH_NON_SECRET_VM_IDENTIFICATION",
    "userns_policy": "REPLACE_WITH_REVIEWED_GUEST_POLICY"
  }
}
```

Derive the JUnit SHA-256 locally via `sha256sum "$EVIDENCE_DIR/m0h-junit.xml"`; use the 64-character lowercase hex digest (no prefix). For tests on the owner's original machine, use `"kind": "owner_host"`, **not** `disposable_vm`.

Then, from the independent M0i checkout, run:

```bash
python -B scripts/m0i_verify_vm_evidence.py \
  --manifest "$EVIDENCE_DIR/manifest.json" \
  --junit "$EVIDENCE_DIR/m0h-junit.xml"
```

The script does not execute pytest itself, invoke `unshare`, inspect the production source tree, access external services, or write a report. Do not upload an evidence bundle that contains host secrets, identifiers, paths or private credentials; preserve original artifacts privately for owner review if needed. Never use synthetic M0i unit-test JUnit as actual kernel acceptance.

## Production gates explicitly outside M0i

Even a VM with seven passing M0h tests has no proved **global** barrier. Production M0 still requires an owner-selected supported host/deployment, a complete verified inventory of every preexisting and future v2 writer (including independent JSON and open SQLite/WAL/SHM descriptors), an externally enforced startup embargo across all entrypoints, trustworthy containment of provider process trees and other users/namespaces/mount aliases, and independently audited durable backup/recovery held across migration commit and reconciliation. Unsupported or unobservable clients mean **NO-GO**. W1 trusted leases/Seal publication and R1 live-WAL source reading remain separate no-go tracks.

## CI and governance

Require the exact PR HEAD's full Python pytest/compile, schema-policy/export and Codex SDK. The M0i unit tests validate **synthetic evidence** and the offline CLI only; CI green does not produce an actual VM, host access barrier, kernel privilege, backup protocol or production go/no-go admission.

```bash
git fetch origin
git switch --track origin/experiment/m6.0-m0i-vm-evidence-verifier
source .venv/bin/activate
python -m pytest -q tests/test_m60m0i_vm_evidence_contract.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Keep M0i Draft pending exact-head CI, independent security review and owner approval. Do not merge M0h implicitly, automatically merge M0i, enable schema v3 or modify the active Ubuntu/AppArmor host.**
