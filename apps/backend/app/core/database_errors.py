from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum


class RuntimeDatabaseErrorCategory(str, Enum):
    WRITE_FENCE_CLOSED = "write_fence_closed"
    SERIALIZATION_FAILURE = "serialization_failure"
    DEADLOCK_DETECTED = "deadlock_detected"
    LOCK_NOT_AVAILABLE = "lock_not_available"
    CONNECTION_FAILURE = "connection_failure"
    UNRELATED = "unrelated"


@dataclass(frozen=True)
class RuntimeDatabaseError:
    category: RuntimeDatabaseErrorCategory
    sqlstate: str | None


def extract_sqlstate(exc: BaseException) -> str | None:
    """Extract SQLSTATE without depending on one SQLAlchemy/driver wrapper shape."""
    pending: deque[BaseException] = deque((exc,))
    seen: set[int] = set()
    while pending:
        current = pending.popleft()
        if id(current) in seen:
            continue
        seen.add(id(current))
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(current, attribute, None)
            if isinstance(value, str) and value:
                return value.upper()
        for nested in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
            *current.args,
        ):
            if isinstance(nested, BaseException) and id(nested) not in seen:
                pending.append(nested)
    return None


def classify_runtime_database_error(exc: BaseException) -> RuntimeDatabaseError:
    sqlstate = extract_sqlstate(exc)
    if sqlstate == "P5C01":
        category = RuntimeDatabaseErrorCategory.WRITE_FENCE_CLOSED
    elif sqlstate == "40001":
        category = RuntimeDatabaseErrorCategory.SERIALIZATION_FAILURE
    elif sqlstate == "40P01":
        category = RuntimeDatabaseErrorCategory.DEADLOCK_DETECTED
    elif sqlstate == "55P03":
        category = RuntimeDatabaseErrorCategory.LOCK_NOT_AVAILABLE
    elif sqlstate is not None and sqlstate.startswith("08"):
        category = RuntimeDatabaseErrorCategory.CONNECTION_FAILURE
    else:
        category = RuntimeDatabaseErrorCategory.UNRELATED
    return RuntimeDatabaseError(category=category, sqlstate=sqlstate)
