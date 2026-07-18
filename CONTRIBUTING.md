# Contributing

Thank you for considering a contribution. Start with the
[Repository Tour](docs/repository-tour.md), then use the
[Development Guide](docs/development-guide.md) to find the owning code and tests for the change.

Before changing behavior, identify the invariant that owns it in the
[Architecture Decision Index](docs/architecture-decisions.md) or the relevant domain guide. Keep
changes bounded, run the focused tests first, and then run the fast baseline in the
[Testing Guide](docs/testing.md#baseline-validation).

Changes to migrations, PostgreSQL authority, control routines, performance evidence, MinIO
integration, or native OCR require the specialized qualification documented in the Testing Guide.
Read the optional [Control Plane Guide](docs/control-plane.md) before modifying Phase 5 code.

Do not commit credentials, local environment files, generated native projects, dependency trees,
or qualification output that has not been explicitly admitted as repository evidence.

