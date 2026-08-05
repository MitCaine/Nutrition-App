# Contributing

Thank you for considering a contribution. The
[Engineering Workflow](engineering/README.md) defines the branch, commit, validation, review,
merge, and release conventions for this repository. Use
[Project Onboarding](docs/project/onboarding.md) to load the minimum application context, then use
the [Development Guide](docs/project/development-guide.md) to find the owning code and tests.

Every implementation session must follow the single
[Repository Session Contract](docs/operations/session-contract.md#repository-session-contract). Run its
start command before editing and its end command before claiming completion.


The experimental
[Repository-owned Task Workflow](engineering/workflow/README.md) provides versioned capsules
for bounded execution. A capsule coordinates an approved task but never overrides product,
architecture, invariant, operations, backlog, or GitHub Issue authority.

Before changing behavior, identify the invariant that owns it in the
[Architecture Decision Index](docs/architecture/decisions.md) or the relevant domain guide. Keep
changes bounded, run focused tests first, and then run the affected baseline in the
[Testing Guide](docs/operations/testing.md#baseline-validation). The
[Script Index](scripts/README.md) explains the stable repository entry points.

Changes to migrations, PostgreSQL authority, control routines, performance evidence, MinIO
integration, or native OCR require the specialized qualification documented in the Testing Guide.
Read the optional [Control Plane Guide](docs/operations/control-plane.md) before modifying Phase 5 code.

Do not commit credentials, local environment files, generated native projects, dependency trees,
or qualification output that has not been explicitly admitted as repository evidence.

Open a focused pull request using the repository template. State exact validation results and mark
specialized infrastructure or native suites as passed, failed, or not run. Do not combine unrelated
cleanup with a behavioral change.
