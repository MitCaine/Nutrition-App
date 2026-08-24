from __future__ import annotations

import re
from collections.abc import Iterable

PROFILE_TOKEN_PATTERN = re.compile(r"^profile:([a-z][a-z0-9-]*)$")

PROFILE_CHECKS: dict[str, tuple[str, ...]] = {
    "repository": ("Repository validation",),
    "backend": ("Backend baseline",),
    "mobile": ("Mobile baseline",),
    "postgresql": ("Backend PostgreSQL 16 contracts",),
}


class QualificationProfileError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_profile_tokens(entries: Iterable[str]) -> list[str]:
    profiles: list[str] = []
    seen: set[str] = set()

    for entry in entries:
        if not entry.startswith("profile:"):
            continue

        match = PROFILE_TOKEN_PATTERN.fullmatch(entry)
        if match is None:
            raise QualificationProfileError(
                "QUALIFICATION_PROFILE_INVALID",
                (
                    "Qualification profile tokens must use "
                    "profile:lowercase-name syntax: "
                    f"{entry}"
                ),
            )

        profile = match.group(1)

        if profile in seen:
            raise QualificationProfileError(
                "QUALIFICATION_PROFILE_DUPLICATE",
                f"Qualification profile is declared more than once: {profile}",
            )

        seen.add(profile)
        profiles.append(profile)

    return profiles


def required_checks_for_profiles(profiles: Iterable[str]) -> dict[str, tuple[str, ...]]:
    requested = list(profiles)
    unknown = sorted(set(requested) - set(PROFILE_CHECKS))

    if unknown:
        raise QualificationProfileError(
            "QUALIFICATION_PROFILE_UNAVAILABLE",
            (
                "Qualification profile is not implemented by this repository: "
                + ", ".join(unknown)
            ),
        )

    return {
        profile: PROFILE_CHECKS[profile]
        for profile in requested
    }
