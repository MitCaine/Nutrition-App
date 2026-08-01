# Current state

> **Document role: Current Guide.** This is the single authoritative starting point for Version
> 1.1 development. Update it when the active release line, roadmap status, migration heads,
> operational availability, or supported deployment boundary changes.

## Release and roadmap status

Version 1.0 is complete and is the maintained baseline for Version 1.x. Version 1.1 is the active
development line.

No Version 1.1 feature roadmap is currently committed in repository documentation. New product
scope should be recorded deliberately rather than inferred from historical stage or release
documents. The [Historical Knowledge Index](../historical/README.md) preserves the Version 1.0
roadmap, release-candidate evidence, and release gate.

## Current architecture

The application is a mobile client backed by an API and an authoritative application database,
with a separate optional operations architecture for high-risk migration, promotion, evidence,
qualification, activation, and recovery work. The
[Architecture Overview](../architecture/overview.md) owns the current system and layer model; the
[Architecture Decision Index](../architecture/decisions.md) owns accepted structural choices.

| Authority | Current head |
| --- | --- |
| Application migration | `0021_target_activation_execution` |
| Control migration | `ops_0011_phase5c4_recovery_audit` |

Revision 0021 is an authorized target-activation migration, not an ordinary development upgrade.
Use the active runbooks rather than advancing to it through a convenience startup path.

## Active operational state

Target activation and emergency close, purpose-specific preactivation cutback, evidence-driven
recovery, cumulative recovery qualification, role separation, and disposable infrastructure
qualification are implemented. The [Operations Index](../operations/README.md) is the canonical
entry point for their exact authority, commands, validation, and limitations.

The [Version 1.0 release gate](../historical/releases/production-hardening-phase5c4.9.md) is retained
as release evidence, not current planning guidance.

## Current documentation entry points

| Need | Canonical document |
| --- | --- |
| Enduring purpose, scope, and priorities | [Project Constitution](constitution.md) |
| Technical truths that changes must preserve | [Project Invariants](invariants.md) |
| Minimum implementation or review context | [Project Onboarding](onboarding.md) |
| Current system boundaries | [Architecture Overview](../architecture/overview.md) |
| Accepted structural choices | [Architecture Decision Index](../architecture/decisions.md) |
| Code ownership and change checklist | [Development Guide](development-guide.md) |
| Testing, qualification, release, and recovery | [Operations Index](../operations/README.md) |
| Historical provenance and learning | [Historical Knowledge Index](../historical/README.md) |

The [Documentation Index](../README.md) remains the authoritative navigation map for the full
knowledge system.

## Known limitations for developers

- Public multi-user production deployment is intentionally unsupported. No production identity
  provider or multi-tenant trust model is installed; private-single-user authentication is not a
  scalable account system. See the [Constitution](constitution.md#intended-deployment-model) and
  [Architecture Overview](../architecture/overview.md#configuration-and-authentication).
- Mobile behavior is online-first. There is no durable offline mutation queue or synchronization
  engine. See [Project Invariants](invariants.md#why-an-online-first-design).
- Native label recognition requires an iOS development build; Expo Go cannot load the project
  module. See [OCR, Search, and Offline Behavior](../features/ocr-search-and-offline.md).
- The independent control gate is not consumed by ordinary application requests. Provider routing,
  backup, restore, and readback remain bounded operator/provider responsibilities. See the
  [Control Plane Guide](../operations/control-plane.md#current-runtime-boundary).
- Local infrastructure qualification proves only its disposable topology and provider stand-in;
  it is not production-vendor certification. See the [Operations Index](../operations/README.md).

## Authority and maintenance

When sources disagree, use this order:

1. implementation and migrations;
2. this Current State document and current architecture, feature, and operations guides;
3. accepted architecture decisions and technical invariants; and
4. historical and evidence records for provenance only.

Report drift instead of silently reconciling contradictory documents in working memory. Keep this
page concise by linking to canonical detail rather than copying feature inventories, rationale, or
runbook instructions.
