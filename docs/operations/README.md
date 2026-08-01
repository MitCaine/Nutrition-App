# Operations index

> **Document role: Operational Reference.** This is the authoritative navigation page for
> validation, qualification, release, recovery, and control-plane work.

## Routine repository operation

- [Repository Session Contract](session-contract.md#repository-session-contract): mandatory start
  and end workflow for every implementation session.
- [Testing Guide](testing.md): baseline, focused, PostgreSQL, MinIO, performance, and final checks.

## Control and recovery

- [Control Plane Guide](control-plane.md): current authority boundaries, role topology, evidence
  flow, migration safety, and runtime limitations.
- [Resource Membership Runbook](runbooks/resource-membership.md): revision 0019 preflight,
  migration, qualification, and recovery.
- [Immutable Provenance Runbook](runbooks/immutable-provenance.md): revision 0020 enforcement,
  qualification, and deployment boundary.
- [Target Activation Runbook](runbooks/target-activation.md): authorized revision 0021 migration,
  activation, reconciliation, and emergency close.
- [Recovery and Cutback Runbook](runbooks/recovery-and-cutback.md): preactivation cutback,
  cumulative recovery qualification, and disposable PITR boundary.

## Release reproducibility

- [Version 1.0 PostgreSQL Release Qualification](version-1.0-release-qualification.md): canonical
  fail-closed PostgreSQL 16 suite and retained infrastructure-evidence command.
- [Version 1.0 Release Gate Record](../historical/releases/production-hardening-phase5c4.9.md):
  point-in-time release criteria and evidence contract.

Version-specific release records remain historical after the release. Reusable commands and active
runbooks remain here until their supported operational boundary changes.

## Operational authority rule

Scripts are interfaces; the owning SQL routine, role grant, migration, and authoritative
observation define authority. Provider command acknowledgement alone is never proof of an external
effect. If current operational guidance conflicts with a historical phase record, follow current
state and the active runbook, then preserve the historical record unchanged.
