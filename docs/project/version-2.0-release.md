# Version 2.0 release

> **Document role: Release Record.** This document defines the Version 2.0
> source/GitHub release content and release boundary. Exact integration, tag,
> GitHub Release, and issue-state identities remain external Git/GitHub
> evidence rather than claims established merely by this document.

## Release identity

Version 2.0 uses the repository-root `VERSION` file as the canonical release
identity. Its exact release value is `2.0.0`.

The selected release mirrors are:

- `apps/mobile/package.json` version `2.0.0`;
- the root package identity in `apps/mobile/package-lock.json` version `2.0.0`;
- Expo marketing version `2.0.0` in `apps/mobile/app.json`;
- backend project version `2.0.0` in `apps/backend/pyproject.toml`; and
- FastAPI application version `2.0.0`.

This is a source/GitHub release. It does not add an iOS `buildNumber`, Android
`versionCode`, new bundle identifier, new Android application identifier, or
store-distribution binary. Native application identifiers remain unchanged.

## What Version 2.0 represents

Version 2.0 records the current application after completion of the local-first
SQLite program and the subsequent nutrition-model, Targets, OCR, local backup,
mobile UX, and Nutrition History work now represented by the current guides.

Ordinary application use remains local-first. On-device SQLite is authoritative
for the selected local application runtime. The preserved FastAPI/PostgreSQL
implementation remains an explicit alternate remote/reference authority rather
than a synchronized copy.

Version 2.0 does not weaken the repository's historical-data guarantees.
Immutable Daily Log nutrition snapshots, immutable Recipe publication
revisions, explicit runtime authority, nutrition/serving identity, and bounded
OCR correction provenance remain governed by the current
[Project Invariants](invariants.md).

Historical Version 1.0, Version 1.1, and Version 1.2 planning and qualification
records remain provenance. They are not rewritten as if Version 2.0 had been
their original release context.

## Supported release toolchains

The supported mobile JavaScript toolchain is Node 24. Release metadata excludes
Node 25 from the supported range.

The supported backend Python toolchain is Python 3.12. Backend release metadata
excludes Python 3.13 from the supported range, and Ruff targets `py312`.

The committed `.nvmrc` and `.python-version` pins remain unchanged. Dependency
locks remain reproducibility authorities for their respective environments.

See the [Development Guide](development-guide.md) and
[Testing Guide](../operations/testing.md) for current setup and qualification
entry points.

## Runtime and remote-startup boundary

The normal current-product development path is the local SQLite runtime.

For the preserved remote application runtime:

- `0033_complete_runtime_authority` is the current application migration head;
- schema 0020 is retained only as a limited preactivation/operations sandbox
  boundary, not the current feature-complete remote application startup state;
- `0021_target_activation_execution` remains a separately authorized
  operations-only activation boundary; and
- current remote application startup assumes an already provisioned and
  qualified database at the current remote head.

Current development guidance uses revision inspection to establish remote schema
state. Version 2.0 does not introduce an unqualified `alembic upgrade head`
convenience path and does not bypass the 0021 operational boundary.

The [Current State](current-state.md) owns the current migration-head summary,
and the [Operations Index](../operations/README.md) owns preserved remote
operational procedures.

## Upgrade and backup guidance

Local SQLite schema evolution continues through the mobile application's
schema-version migration engine rather than by replaying the remote Alembic
history.

For user-controlled local protection, use the validated local SQLite
backup/restore workflow before changes where a recoverable local application
snapshot is appropriate. A local backup is a replacement artifact, not a
second live authority or synchronization mechanism. Credentials and other
secrets outside the application SQLite database are not included in that
artifact.

Remote PostgreSQL backup, restore, activation, and recovery remain bounded
operator/provider responsibilities. Operators must use the applicable
operations guidance and authorization boundaries rather than treating a
convenience development command as a production migration procedure.

Version 2.0 adds no automatic cloud backup, cross-device synchronization,
local/remote synchronization, dual-write, or failover behavior.

## Known limitations and maintenance boundary

Public multi-user production deployment remains unsupported without a
production identity provider and multi-tenant trust model.

Native Apple Vision OCR and native image-quality inspection still require an
iOS native development or release build; Expo Go cannot provide those native
modules.

The accepted pre-release dependency-security disposition includes three open
Dependabot alerts: two high-severity `image-size` alerts inherited through the
Expo/Metro toolchain and one moderate `uuid` alert inherited through
Expo-related tooling. The corresponding accepted snapshot has zero open
code-scanning alerts and zero open secret-scanning alerts.

These dependency findings are not remediated by forcing an incompatible Expo
or toolchain major upgrade. Final publication requires a fresh dependency and
security recheck; a material change in that disposition stops publication
until it is reviewed.

Other current product limitations remain documented in
[Current State](current-state.md).

## Qualification and publication

Version 2.0 source qualification requires the complete mobile Node 24 and
backend Python 3.12 baselines, repository documentation and capsule validation,
repository audit, PostgreSQL 16 qualification, whitespace validation, and the
standard review bundle defined by the release task.

Publication occurs only after independent review of the exact qualified source
checkpoint.

The required publication order is:

1. integrate the exact independently reviewed tree through the human
   integration boundary;
2. prove the integration tree is byte-identical to the reviewed task tree;
3. qualify the exact integration commit;
4. recheck dependency/security state;
5. qualify the required GitHub checks for that integration commit;
6. create one annotated `v2.0.0` tag targeting that exact qualified integration
   commit;
7. create one corresponding GitHub Release;
8. verify the remote tag and GitHub Release identities;
9. archive the release task as MERGED; and
10. close the governing release-coherence issue only after archive
    qualification.

This source document defines that release procedure. Its presence does not by
itself assert that integration, tag publication, GitHub Release publication,
archive, or issue closure has already occurred.
