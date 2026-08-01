"""Canonical meal and note contracts shared by Daily Log workflows.

The database intentionally keeps these fields nullable text columns.  This
module defines the application boundary rules without rewriting historical
rows, so legacy values remain readable while all new or explicitly edited
values are canonical.
"""

from __future__ import annotations

from typing import Literal

SUPPORTED_MEALS = ("breakfast", "lunch", "dinner", "snack")
MealType = Literal["breakfast", "lunch", "dinner", "snack"]
MAX_NOTE_CODE_POINTS = 1_000


class LogContractError(ValueError):
    """A stable, field-specific Daily Log contract validation failure."""

    def __init__(self, code: str, message: str, field: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def detail(self) -> dict[str, object]:
        """Return the stable API detail shape for this validation failure."""

        return {
            "code": self.code,
            "message": self.message,
            "field_errors": [
                {"field": self.field, "code": self.code, "message": self.message}
            ],
        }


def normalize_meal(value: object) -> str | None:
    """Validate an explicit meal assignment and return its canonical value.

    ``None`` is the sole representation of an unassigned meal.  Historical
    unsupported values are not passed through this function; callers reading
    persisted rows should use :func:`project_meal` instead.
    """

    if value is None:
        return None
    if isinstance(value, str) and value in SUPPORTED_MEALS:
        return value
    raise LogContractError(
        "meal_invalid",
        "Meal must be breakfast, lunch, dinner, snack, or absent.",
        "meal_type",
    )


def project_meal(value: object) -> str | None:
    """Project a persisted meal into the supported display domain.

    Legacy unsupported values are intentionally mapped to the canonical
    unassigned state for grouping and presentation.  The raw value remains
    untouched in persistence and can be surfaced as a compatibility notice by
    a later presentation workflow.
    """

    return value if isinstance(value, str) and value in SUPPORTED_MEALS else None


def is_legacy_meal(value: object) -> bool:
    """Return whether a persisted value is a non-canonical legacy meal."""

    return value is not None and project_meal(value) is None


def normalize_note(value: object) -> str | None:
    """Trim and validate one explicitly supplied plain-text note.

    Python's ``len`` counts Unicode code points, which is the contract's
    length unit.  Internal whitespace and line breaks are preserved.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise LogContractError("note_invalid", "Note must be plain text.", "notes")
    normalized = value.strip()
    if len(normalized) > MAX_NOTE_CODE_POINTS:
        raise LogContractError(
            "note_too_long",
            "Note must be 1,000 Unicode code points or fewer.",
            "notes",
        )
    return normalized or None
