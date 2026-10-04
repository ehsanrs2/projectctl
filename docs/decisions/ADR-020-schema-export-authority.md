# ADR-020: Public JSON Schema Export Authority and Drift Policy

Status: Accepted

## Context

ProjectCTL exposes versioned public Pydantic contracts through
`projectctl.schema_export.PUBLIC_SCHEMAS` and the `projectctl schema export` command.

Historically, the repository also checked in a partial `schemas/generated/` directory. That
directory stopped matching the exporter as new contracts and schema versions were added.

This created two conflicting representations of the same derived artifacts:

1. the exporter registry and model definitions;
2. a manually refreshed checked-in generated mirror.

The Blueprint's architecture review recorded this as Finding H and required one explicit policy:

- either CI must prove that every checked-in generated schema exactly matches the exporter; or
- generated schema copies must no longer be versioned.

Generated JSON Schema files are derived artifacts. Maintaining a second Git copy provides little
value unless those files are an independently supported distribution surface.

## Decision

`projectctl.schema_export.PUBLIC_SCHEMAS` plus the referenced versioned model classes are the
implementation authority for public JSON Schema export.

The repository will **not version `schemas/generated/`**.

### Export behavior

`export_json_schemas(destination)` remains the supported implementation path and now writes
schemas in deterministic filename order.

The default CLI remains:

```bash
projectctl schema export
```

which may create `schemas/generated/` in a local working tree. That directory is ignored by Git
and is a disposable build/export artifact.

### CI policy

CI enforces both parts of the contract:

1. `schemas/generated/` must not be present in the checked-out repository;
2. exporting to a clean temporary directory must produce exactly the filenames registered in
   `PUBLIC_SCHEMAS`, in deterministic order, and each output must parse as a JSON Schema object.

This means CI validates the generator itself rather than comparing against another derived copy.

### Repository policy

- `schemas/generated/` is listed in `.gitignore`.
- agent instructions explicitly prohibit versioning a generated schema mirror.
- the legacy partial generated directory is removed.
- public contract history continues to live in the versioned model classes and additive
  `PUBLIC_SCHEMAS` registry entries.
- when a schema contract version is superseded, the old model/export entry remains if audit
  compatibility requires it.

### External distribution

This decision does not prevent generated schemas from being published later as release artifacts,
package data, documentation assets, or another derived distribution surface.

If such a distribution surface becomes part of the compatibility contract, it must be generated
from `PUBLIC_SCHEMAS` in release automation rather than maintained manually in Git.

## Consequences

Positive:

- there is one implementation authority for public schema generation;
- partial or stale checked-in schema mirrors cannot mislead reviewers or consumers;
- adding a public contract requires changing the registry/model, not a second manually maintained
  artifact set;
- local `projectctl schema export` no longer dirties the Git working tree by default;
- CI still verifies that every registered schema is exportable and valid JSON;
- schema export order is deterministic.

Tradeoffs:

- generated schemas are no longer browsable directly as committed repository files;
- consumers that need files must run the export command or consume future release artifacts;
- Git history no longer records formatting-only changes in generated JSON.

## Rejected alternatives

### Keep the mirror and compare every file byte-for-byte in CI

Rejected for the current project stage. It would duplicate a fully derived representation in Git
without an established consumer requiring committed files, increase review noise, and require
large generated diffs whenever Pydantic schema formatting changes.

### Keep a partial curated subset of generated schemas

Rejected because a partial directory is ambiguous: it looks authoritative while omitting newer
contracts.

### Treat checked-in files as authoritative instead of the exporter

Rejected because ProjectCTL runtime/CLI behavior is generated from the model registry, so making a
separate JSON copy authoritative would invert the implementation boundary.

## Follow-up

With Finding H resolved, the architecture roadmap may proceed to M3.2 task-authority expansion.

If ProjectCTL later publishes JSON Schemas as formal release artifacts, add a release-level
verification step that regenerates them from `PUBLIC_SCHEMAS` and attests the produced artifact
set.
