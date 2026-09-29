"""Versioned repository path-pattern semantics for task authorization."""
from __future__ import annotations

import fnmatch
from functools import lru_cache


V1 = 1
V2 = 2
SUPPORTED_VERSIONS = frozenset({V1, V2})


class PathPatternError(ValueError):
    """A path or pattern is outside the selected authorization grammar."""


def _components(value: str, *, label: str, reject_nul: bool) -> tuple[str, ...]:
    if (not isinstance(value, str) or not value or value.startswith("/")
            or "\\" in value or (reject_nul and "\0" in value)):
        raise PathPatternError(f"{label} must be a nonempty repository-relative POSIX path")
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise PathPatternError(f"{label} contains an empty, '.' or '..' component")
    return parts


def validate_pattern(pattern: str, version: int) -> tuple[str, ...]:
    """Validate a pattern and return its path components.

    V1 keeps its historical fnmatch syntax, including slash-crossing ``*``.
    V2 accepts only complete ``*`` and ``**`` components.
    """
    if type(version) is not int or version not in SUPPORTED_VERSIONS:
        raise PathPatternError(f"unsupported path-pattern version: {version!r}")
    parts = _components(pattern, label="pattern", reject_nul=version == V2)
    if version == V2:
        for part in parts:
            if part in {"*", "**"}:
                continue
            if any(token in part for token in "*?[]"):
                raise PathPatternError(f"unsupported v2 glob component: {part}")
    return parts


def validate_path(path: str, version: int) -> tuple[str, ...]:
    """Validate a repository-relative path under an authenticated version."""
    if type(version) is not int or version not in SUPPORTED_VERSIONS:
        raise PathPatternError(f"unsupported path-pattern version: {version!r}")
    if version == V1:
        # V1 applied fnmatchcase directly to observed Git path strings. Keep
        # that exact behavior, including legal POSIX filenames containing '\\'.
        if not isinstance(path, str):
            raise PathPatternError("path must be a string")
        return tuple(path.split("/"))
    return _components(path, label="path", reject_nul=version == V2)


def has_glob(pattern: str, version: int) -> bool:
    """Return whether a validated pattern contains wildcard syntax."""
    parts = validate_pattern(pattern, version)
    if version == V1:
        # Keep the capsule-containment rule's historic glob detection.
        return any(token in pattern for token in "*?[")
    return any(part in {"*", "**"} for part in parts)


def matches(path: str, pattern: str, version: int) -> bool:
    """Match one real Git path using the selected authorization grammar."""
    validate_path(path, version)
    parts = validate_pattern(pattern, version)
    if version == V1:
        return path == pattern or fnmatch.fnmatchcase(path, pattern)

    path_parts = tuple(path.split("/"))

    @lru_cache(maxsize=None)
    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(parts):
            return path_index == len(path_parts)
        component = parts[pattern_index]
        if component == "**":
            return (match(path_index, pattern_index + 1)
                    or (path_index < len(path_parts)
                        and match(path_index + 1, pattern_index)))
        if path_index == len(path_parts):
            return False
        if component == "*" or component == path_parts[path_index]:
            return match(path_index + 1, pattern_index + 1)
        return False

    return match(0, 0)


def permitted(path: str, allowed: list[str] | tuple[str, ...],
              forbidden: list[str] | tuple[str, ...], version: int) -> bool:
    """Apply allowed and forbidden patterns, with forbidden always winning."""
    validate_path(path, version)
    allowed_match = any(matches(path, pattern, version) for pattern in allowed)
    forbidden_match = any(matches(path, pattern, version) for pattern in forbidden)
    return allowed_match and not forbidden_match
