# M6.0 M0c — Strict Offline Cutover and Recovery Admission Contract

**Status:** TEST-ONLY decision model and operator-facing design; **NO-GO** for an operational v2→v3 migration.
**Baseline:** `main@ae68eead658dab4cce182aa6e04068d83c85c7b9` (PR #72 M0b merged).
**Governing architecture:** ADR-039/040 Path A; M0a unified disposable v3 SQL candidate, M0b legacy-writer bypass proof, B3a4 WAL-inclusive backup experiment.
**Files:** `tests/test_m60m0c_offline_cutover_contract.py` and this document.

## Decision and trust boundary

Proceed with **Option A: explicit offline-only cutover** as the *design default*, not a runnable migration. A process still running an unmodified ProjectCTL v2 binary can evade any newly introduced maintenance `flock`, `execution_authority_gate`, NULL `lease_owner` test, or SQLite transaction and can replace JSON outside SQLite. M0b demonstrates these cases with real spawned RunStore processes.

**No test of a sampled v2 database can establish the absence of all independent writers.** A verified external exclusion mechanism, specific to deployment/OS/filesystem, must prevent already-running legacy writers, detached provider processes, background workers, remote clients and new startups from accessing this project's SQLite database **or its authoritative external artifacts**. The operator must hold this exclusion across source inspection, backup, transaction, outcome reconciliation and handoff. This is not a portable Python process-list or an advisory lock invented by v3.

M0c does NOT implement a service supervisor, a process scanner, an operator attestation format, a privileged lock, new runtime writer cooperation, a recovery command or an automatic admission. It cannot authenticate the input claims to its test-only policy; every all-true claim ends at **OPERATOR_REVIEW_ONLY**, never GO. Production admission remains disallowed until an OS-specific exclusion protocol has been reviewed and independently proven.

## Proposed cutover protocol: ordered gates

### Gate 0 — Operator identity and blast-radius approval

1. Explicitly select the project root, source `.projectctl/state.sqlite` and separate private backup-retention location. Bind to canonical, descriptor-anchored filesystem identities; do not trust string paths or a symlink check alone. Never act on an implicit current directory or migrate multiple projects implicitly.
2. Inventory and identify every writer: CLI, RunStore, Execution, Verification, heartbeat thread, scheduler, worker/provider subprocess, Recovery, rebind, integration, any independent JSON publisher and any process with the database previously opened. Include other users, containers, namespaces, network filesystems and unrelated programmatic API clients where applicable.
3. Operator authorizes a downtime window and accepts impact. Unsupported or uninspectable environments produce **NO-GO** rather than an optimistic best effort.

### Gate 1 — Enforced offline exclusion (UNIMPLEMENTED)

1. Stop all relevant services and subprocesses, drain active writes and prevent all new starts **before** sampling leases or opening the database. Explicitly resolve legacy v2 owner strings; do not mint an apparently valid v3 generation/token from v2 state.
2. Use a site-specific OS/supervisor/filesystem barrier with evidence that covers **nonparticipants**, not merely cooperating v3 clients. The barrier must stay valid when a worker has an already-open database handle or can reopen it after an empty lease-owner observation.
3. Verify that no external artifact writer can replace the protected manifest leaves while the barrier is held. Account for mount aliases, other namespaces, other machines and restart managers. Unknown writers, unsupported filesystem semantics, inability to stop/start-block or a lost barrier imply **NO-GO**.
4. Maintain an operator-owned admission record binding the project/DB identities, approved exclusion method, participating/legacy binaries, startup barrier, start time, requested v2→v3 target and responsible operator. **A record is not proof** without independent enforcement.

### Gate 2 — Preflight and WAL-inclusive durable backup

1. Revalidate the *anchored* source as the exact intended project: strict ProjectCTL application ID, original v2 `user_version`, migration history `[1,2]`, schema/integrity and foreign keys; reject unresolved non-NULL legacy leases. No future-scheduled writer is excluded merely by these checks.
2. While exclusion is held, take a SQLite-consistent backup **including committed WAL frames** using a reviewed maintenance-only backup path. A raw copy of just `state.sqlite` is insufficient. A backup API may interact with WAL/SHM and **must not be used by the read-only Trace exporter**.
3. Publish a new private no-clobber backup using descriptor-anchored ancestry, proven file and directory `fsync`, durable retention, controlled ownership/permissions and integrity verification on an independently opened copy. Record stable project identity, backup identity and recovery metadata (including actual source version and an unambiguous backup epoch).
4. Do not place sensitive backup content, manifest bytes or secret credentials in public logs. Separate retention/restore policy, encryption/access control and backup authenticity require owner decision.
5. Recheck source identity and expected version/history while exclusion continues. Two equal samples or matching event counts are **not a proof** of epoch consistency: undetected writers, DB ABA, changes in artifact JSON and checkpoint timing remain possible. Exclusion supplies the missing guarantee, not the sample comparison.

### Gate 3 — Candidate migration (NOT implemented by M0c)

Only after Gates 0–2 are *externally proved* and approved, a separate reviewed production M0 could run the corrected unified M0a v3 DDL within **one caller-owned SQLite transaction**, without `executescript`. It must preserve prior rows, maintain exact migration history, fail on all preflight discrepancies, and never let a v2 writer resume. Required future policies include fresh-project v3 initialization, v1→v2→v3 upgrades, old-version refusal without mutation, legacy owner epoch reset, and v3 RunStore/Verifier compatibility.

Neither B3a4's lab backup nor M0a's disposable DDL may be copied into an authority-bearing migrator without independent path/lock, durability, compatibility and fault audits.

### Gate 4 — Commit uncertainty and recovery (NO automatic rollback)

Keep startup barred and evidence/backup retained through exact outcome reconciliation. Classify any crash, fsync-after-publication failure, interrupted SQLite COMMIT, permission loss or inconsistent schema/history as **quarantined/unknown**. Do not assume an exception means rollback; do not assume a `user_version=3` row alone means the schema, Seal or runtime is trustworthy. Do **not** blindly retry migration, drop WAL/SHM, overwrite `state.sqlite` or restore from backup.

A trusted recovery flow must independently verify original DB identity, v2 backup and source state, schema/version/history/index/trigger constraints, application integrity, owner-controlled restore destination and precise v3 completion. Restore is a **separate, explicit operator-approved maintenance action**, preferably to a fresh isolated target first. A known intact v2 or apparently complete v3 state still requires operator review before any release.

### Gate 5 — Controlled release (NOT implemented)

Resume only after all earlier gate outcomes are unambiguous and a newly compatible v3 runtime has passed its own W1 lease-token fencing, same-run writer mutex, atomic status/event/Seal and file/directory durability acceptance. Reject reopening the project with unmodified v2 clients. R1 safe source-WAL reader remains independent, unproven and disabled; no Collector, assessment or public Trace command becomes valid by passing M0c.

## Executable decision model (disposable tests only)

The test module uses freshly initialized **real ProjectCTL project-state v2** fixtures under `tmp_path`, including a WAL-committed observation, and the already isolated B3a4 backup lab. No production source, migration registry or `projectctl/` module changes occur.

The model has two deliberately **non-authorizing** interfaces:

- `_admission_review(exclusion, before, after, backup, backup_durable_and_retained, paths_anchored)` requires ALL seven external operator/supervisor claims, an explicitly durable/retained backup and anchored-path claim, exact v2 identity/history/integrity, no unresolved legacy owner, and equal limited observations. Incomplete claims, stale observations or missing backup refuse. **Its strongest result is OPERATOR_REVIEW_ONLY.** The claims themselves are not authenticated or enforced.
- `_recovery_review(backup, source, outcome_known, exclusion_continuous)` quarantines absent evidence, untrusted backup, ambiguous COMMIT, mixed version/history or broken exclusion. Even recognized v2 and *synthetically modeled* v3 version/history combinations produce only an operator-review result; it neither validates full v3 DDL nor restores a database.

Covered cases:

| Case | Expected model result |
| --- | --- |
| Any single stop/drain/restart-block/exclusion claim missing | BLOCK_MISSING_EXTERNAL_EXCLUSION |
| No backup, unspecified durability/retention or unanchored paths | BLOCK_MISSING_TRUSTED_BACKUP |
| Wrong application ID | QUARANTINE_SOURCE_IDENTITY |
| Unsupported version/history/integrity or legacy owner present | QUARANTINE_SOURCE_VERSION_OR_INTEGRITY / BLOCK_LEGACY_LEASE |
| Test writer appends an event **after** WAL-inclusive backup | BLOCK_OBSERVED_EPOCH_DRIFT |
| B3a4 injected prepublication failures at four points | No named backup; BLOCK_MISSING_TRUSTED_BACKUP |
| V2 source + valid backup + recognized outcome | OPERATOR_REVIEW_V2_RETAIN_BACKUP |
| Ambiguous COMMIT / missing exclusion / untrusted backup | Quarantine |
| Hypothetical matching v3/version-history fields | OPERATOR_REVIEW_V3_NOT_VALIDATED |
| All claims set and observations equal | OPERATOR_REVIEW_ONLY, **never migration approval** |

A passing policy test is **not** a test of actual external exclusion, secure filesystem paths, WAL crash durability, schema-v3 correctness, backup retention policy or power-failure resistance. The event-count comparison illustrates that an observed drift can be detected; it does not detect arbitrary JSON mutation or establish a cryptographic cross-store snapshot.

## Remaining blockers before production M0 / W1 / R1

- [ ] Select **one supported deployment** (OS, process supervisor, filesystem, namespace/network boundary), enumerate *all* writers, and demonstrate reliable stop + prevent-start exclusion against a live pre-existing v2 RunStore and an external JSON publisher. Prove the barrier survives concurrency and is maintained across the cutover; show refusal for unsupported mounts and unknown clients.
- [ ] Specify testable stop/timeout/cancellation behavior, structured operator approval, project/source identity, independent barrier evidence and crash-safe maintenance ownership without treating untrusted user-supplied booleans as attestation.
- [ ] Design descriptor-anchored, symlink/hardlink/path-swap-safe no-clobber WAL-inclusive backup and file+parent durability, disk-full and fsync-after-link ambiguity handling; validate a separate backup/restore plan without rewriting live DB/WAL/SHM.
- [ ] Require fault/kill-process/power-loss acceptance of the exact source schema, history and retained backup; durable recovery decisions and no auto-retry on uncertain COMMIT.
- [ ] Approve actual M0a schema and v1/v2/v3 client/new-project transition, full all-writer W1 token fencing and single-transaction trusted Seal publication.
- [ ] Separately prove R1 read-only live-WAL source non-mutation and phase-aligned as-of Seal consumption; keep `snapshot_proven=False`, `assessments=[]`, exporter disabled until then.

## Acceptance and governance

On the exact PR HEAD require the full GitHub Actions pytest, compile, public schema policy/export and pinned Codex SDK jobs. Because the backup lab requires POSIX semantics, operator-local focused smoke is useful on the eventual supported host:

```bash
git fetch origin
git switch --track origin/experiment/m6.0-m0c-offline-cutover-contract
source .venv/bin/activate
python -m pytest -q tests/test_m60m0c_offline_cutover_contract.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Keep Draft until exact-head CI, threat review and owner approval. Do not merge without instruction.** This is a bounded decision/test milestone; merging it must **not** authorize an operational migration, new writer rights, old-client cutover or read-only WAL export.
