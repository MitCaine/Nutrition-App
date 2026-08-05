#!/usr/bin/env python3
"""Validate repository-owned task capsules and strict execution readiness."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _reexec_with_supported_python() -> None:
    if sys.version_info >= (3, 11):
        return

    repository_root = Path(__file__).resolve().parents[1]
    backend_python = repository_root / "apps/backend/.venv/bin/python"

    if backend_python.is_file():
        current = Path(sys.executable).resolve()
        target = backend_python.resolve()

        if current != target:
            os.execv(
                str(target),
                [str(target), str(Path(__file__).resolve()), *sys.argv[1:]],
            )

    raise SystemExit(
        "Python 3.11 or newer is required. "
        "The validator could not locate apps/backend/.venv/bin/python."
    )


_reexec_with_supported_python()

import argparse
import json
import re
import subprocess
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable

SCHEMA_VERSION = 1
ACTIVE_STATES = (
    "DRAFT",
    "GRILLED",
    "SPECIFIED",
    "DECOMPOSED",
    "READY",
    "IN_PROGRESS",
    "IMPLEMENTED",
    "VERIFIED",
    "REVIEWED",
)
COMPLETED_STATES = ("MERGED", "RETROSPECTED", "CANCELLED")
ALL_STATES = ACTIVE_STATES + COMPLETED_STATES
READY_OR_LATER = {
    "READY",
    "IN_PROGRESS",
    "IMPLEMENTED",
    "VERIFIED",
    "REVIEWED",
    "MERGED",
    "RETROSPECTED",
}
VERIFIED_OR_LATER = {"VERIFIED", "REVIEWED", "MERGED", "RETROSPECTED"}
TASK_TYPES = {
    "product",
    "architecture",
    "implementation",
    "correction",
    "audit",
    "documentation",
    "tooling",
    "operations",
    "release",
}
RISKS = {"low", "medium", "high", "critical"}
DELEGATION_MODES = {"none", "bounded"}

REQUIRED_METADATA = (
    "schema_version",
    "capsule_revision",
    "id",
    "title",
    "state",
    "task_type",
    "risk",
    "created",
    "updated",
    "source_issue",
    "base_commit",
    "branch",
    "controller",
    "executor",
    "reviewer",
    "delegation",
    "delegation_constraints",
    "blocked",
    "blocked_reason",
    "blocked_since",
    "dependencies",
    "planning_artifacts",
    "owned_paths",
    "allowed_paths",
    "forbidden_paths",
    "specialized_qualification",
)

REQUIRED_SECTIONS = (
    "Goal",
    "Outcome",
    "Non-goals",
    "Background",
    "Authority and precedence",
    "Dependencies and prerequisites",
    "Owned surface",
    "Allowed changes",
    "Forbidden changes",
    "Acceptance criteria",
    "Required verification",
    "Return evidence",
    "Escalation conditions",
    "Decisions and assumptions",
    "State history",
    "Completion record",
)
REQUIRED_VERIFICATION_SUBSECTIONS = (
    "Focused",
    "Baseline",
    "Specialized qualification",
)
COMPLETION_FIELDS = (
    "Reviewed commit",
    "Review disposition",
    "Verification summary",
    "Specialized qualification",
    "Known warnings",
    "Deferred work/follow-up IDs",
    "Retrospective required",
)

NORMAL_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"GRILLED", "CANCELLED"},
    "GRILLED": {"SPECIFIED", "CANCELLED"},
    "SPECIFIED": {"DECOMPOSED", "CANCELLED"},
    "DECOMPOSED": {"READY", "CANCELLED"},
    "READY": {"IN_PROGRESS", "DECOMPOSED", "CANCELLED"},
    "IN_PROGRESS": {"IMPLEMENTED", "CANCELLED"},
    "IMPLEMENTED": {"VERIFIED", "CANCELLED"},
    "VERIFIED": {"REVIEWED", "CANCELLED"},
    "REVIEWED": {"IN_PROGRESS", "MERGED", "CANCELLED"},
    "MERGED": {"RETROSPECTED"},
    "RETROSPECTED": set(),
    "CANCELLED": set(),
}

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
H2_PATTERN = re.compile(r"(?m)^##\s+(.+?)\s*$")
H3_PATTERN = re.compile(r"(?m)^###\s+(.+?)\s*$")
CHECKBOX_PATTERN = re.compile(r"(?m)^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
ACCEPTANCE_PATTERN = re.compile(r"^(AC-[1-9][0-9]*):\s+\S")
NOT_APPLICABLE_PATTERN = re.compile(
    r"^not applicable\s*(?:—|–|-|:)\s*\S.{4,}$",
    re.IGNORECASE | re.DOTALL,
)
PLACEHOLDER_PATTERNS = (
    re.compile(r"\bTASK-ID\b", re.IGNORECASE),
    re.compile(r"\bYYYY-MM-DD\b", re.IGNORECASE),
    re.compile(r"\b(?:TBD|TODO|FIXME)\b", re.IGNORECASE),
    re.compile(r"<[^>]+>"),
    re.compile(r"Outcome-oriented task title", re.IGNORECASE),
    re.compile(r"accountable-controller", re.IGNORECASE),
    re.compile(r"bounded-executor", re.IGNORECASE),
    re.compile(r"independent-reviewer", re.IGNORECASE),
    re.compile(r"State the problem this task resolves", re.IGNORECASE),
    re.compile(r"State the observable successful result", re.IGNORECASE),
    re.compile(r"Each criterion is observable", re.IGNORECASE),
)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    field: str | None = None


@dataclass
class CapsuleResult:
    path: str
    capsule_id: str | None = None
    state: str | None = None
    valid: bool = True
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    metadata: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None

    def error(self, code: str, message: str, field_name: str | None = None) -> None:
        self.valid = False
        self.errors.append(Finding(code, message, field_name))

    def warning(self, code: str, message: str, field_name: str | None = None) -> None:
        self.warnings.append(Finding(code, message, field_name))


class InvocationError(RuntimeError):
    """Repository inspection failed before capsule validation could run."""


def run_git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise InvocationError(f"git {' '.join(args)} failed: {detail}")
    return completed


def repository_context(repo: Path) -> dict[str, Any]:
    inside = run_git(repo, "rev-parse", "--is-inside-work-tree")
    if inside.returncode or inside.stdout.strip() != "true":
        raise InvocationError(f"Not a Git worktree: {repo}")
    head = run_git(repo, "rev-parse", "HEAD", check=True).stdout.strip()
    branch = run_git(repo, "branch", "--show-current", check=True).stdout.strip()
    status = run_git(repo, "status", "--porcelain=v1", "-uall", check=True).stdout
    return {
        "root": str(repo),
        "head": head,
        "branch": branch or "DETACHED",
        "clean": not bool(status.strip()),
    }


def relative_path(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def discover_capsules(repo: Path) -> list[Path]:
    found: list[Path] = []
    for directory in (
        repo / "engineering" / "capsules" / "active",
        repo / "engineering" / "capsules" / "completed",
    ):
        if directory.is_dir():
            found.extend(
                path
                for path in sorted(directory.glob("*.md"))
                if path.name not in {"README.md", "TEMPLATE.md"}
            )
    return found


def parse_document(path: Path, result: CapsuleResult) -> tuple[dict[str, Any], str] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        result.error("READ_FAILED", str(exc))
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "+++":
        result.error("FRONT_MATTER_MISSING", "The first line must be '+++'.")
        return None
    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "+++"
        )
    except StopIteration:
        result.error("FRONT_MATTER_UNTERMINATED", "TOML front matter must end with '+++'.")
        return None
    try:
        metadata = tomllib.loads("\n".join(lines[1:end]))
    except tomllib.TOMLDecodeError as exc:
        result.error("FRONT_MATTER_INVALID", str(exc))
        return None
    body = "\n".join(lines[end + 1 :]).strip() + "\n"
    return metadata, body


def split_sections(body: str, result: CapsuleResult) -> dict[str, str]:
    matches = list(H2_PATTERN.finditer(body))
    names = [match.group(1).strip() for match in matches]
    for name in sorted({name for name in names if names.count(name) > 1}):
        result.error("SECTION_DUPLICATE", f"Section appears more than once: {name}", name)
    for name in names:
        if name not in REQUIRED_SECTIONS:
            result.error("SECTION_UNKNOWN", f"Unknown schema-v1 section: {name}", name)
    for name in REQUIRED_SECTIONS:
        if name not in names:
            result.error("SECTION_MISSING", f"Required section is missing: {name}", name)
    known = [name for name in names if name in REQUIRED_SECTIONS]
    expected = [name for name in REQUIRED_SECTIONS if name in known]
    if known != expected:
        result.error("SECTION_ORDER", "Required sections must follow the schema-defined order.")
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[match.group(1).strip()] = body[start:end].strip()
    return sections


def split_verification(content: str, result: CapsuleResult) -> dict[str, str]:
    matches = list(H3_PATTERN.finditer(content))
    names = [match.group(1).strip() for match in matches]
    for name in sorted({name for name in names if names.count(name) > 1}):
        result.error(
            "VERIFICATION_SUBSECTION_DUPLICATE",
            f"Verification subsection appears more than once: {name}",
            "Required verification",
        )
    for name in names:
        if name not in REQUIRED_VERIFICATION_SUBSECTIONS:
            result.error(
                "VERIFICATION_SUBSECTION_UNKNOWN",
                f"Unknown verification subsection: {name}",
                "Required verification",
            )
    for name in REQUIRED_VERIFICATION_SUBSECTIONS:
        if name not in names:
            result.error(
                "VERIFICATION_SUBSECTION_MISSING",
                f"Required verification subsection is missing: {name}",
                "Required verification",
            )
    known = [name for name in names if name in REQUIRED_VERIFICATION_SUBSECTIONS]
    expected = [name for name in REQUIRED_VERIFICATION_SUBSECTIONS if name in known]
    if known != expected:
        result.error(
            "VERIFICATION_SUBSECTION_ORDER",
            "Verification subsections must follow Focused, Baseline, Specialized qualification.",
            "Required verification",
        )
    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        values[match.group(1).strip()] = content[start:end].strip()
    return values


def parse_iso_date(value: Any, field_name: str, result: CapsuleResult) -> date | None:
    if not isinstance(value, str):
        result.error("TYPE_INVALID", f"{field_name} must be a quoted YYYY-MM-DD string.", field_name)
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        result.error("DATE_INVALID", f"{field_name} must use YYYY-MM-DD.", field_name)
        return None


def meaningful(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if NOT_APPLICABLE_PATTERN.match(stripped):
        return True
    return not any(pattern.search(stripped) for pattern in PLACEHOLDER_PATTERNS)


def validate_string_list(
    metadata: dict[str, Any], key: str, result: CapsuleResult
) -> list[str]:
    value = metadata.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        result.error("TYPE_INVALID", f"{key} must be a list of non-empty strings.", key)
        return []
    return [item.strip() for item in value]


def validate_commit(repo: Path, value: str, field_name: str, result: CapsuleResult) -> bool:
    if not COMMIT_PATTERN.fullmatch(value):
        result.error(
            "COMMIT_INVALID",
            f"{field_name} must be an exact lowercase 40-character commit hash.",
            field_name,
        )
        return False
    resolved = run_git(repo, "rev-parse", f"{value}^{{commit}}")
    if resolved.returncode or resolved.stdout.strip() != value:
        result.error(
            "COMMIT_UNKNOWN",
            f"{field_name} does not resolve to an exact repository commit: {value}",
            field_name,
        )
        return False
    return True


def validate_scope_paths(entries: Iterable[str], field_name: str, result: CapsuleResult) -> None:
    seen: set[str] = set()
    for entry in entries:
        if entry in seen:
            result.error("SCOPE_PATH_DUPLICATE", f"Duplicate scope path: {entry}", field_name)
        seen.add(entry)
        candidate = Path(entry)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or "\\" in entry
            or "://" in entry
            or entry in {".", "./"}
        ):
            result.error(
                "SCOPE_PATH_INVALID",
                f"Scope path/pattern must use repository-relative POSIX syntax: {entry}",
                field_name,
            )


def validate_authority_paths(repo: Path, entries: Iterable[str], result: CapsuleResult) -> None:
    for entry in entries:
        raw = entry.split("#", 1)[0].strip()
        candidate = Path(raw)
        if not raw or candidate.is_absolute() or ".." in candidate.parts or "://" in raw:
            result.error(
                "AUTHORITY_PATH_INVALID",
                f"Authority path must be repository-relative: {entry}",
                "planning_artifacts",
            )
            continue
        resolved = (repo / candidate).resolve()
        try:
            resolved.relative_to(repo.resolve())
        except ValueError:
            result.error(
                "AUTHORITY_PATH_ESCAPE",
                f"Authority path escapes the repository: {entry}",
                "planning_artifacts",
            )
            continue
        if not resolved.is_file():
            result.error(
                "AUTHORITY_PATH_MISSING",
                f"Authority artifact does not exist as a file: {entry}",
                "planning_artifacts",
            )


def parse_state_history(
    content: str, current_state: str, updated: date | None, result: CapsuleResult
) -> None:
    rows: list[list[str]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        columns = [column.strip() for column in stripped.strip("|").split("|")]
        if len(columns) != 5:
            continue
        if columns[0].lower() == "date" or all(
            set(column) <= {"-", ":"} for column in columns
        ):
            continue
        rows.append(columns)
    if not rows:
        result.error(
            "STATE_HISTORY_MISSING",
            "State history must contain at least one five-column data row.",
            "State history",
        )
        return
    previous: str | None = None
    last_date: date | None = None
    for index, row in enumerate(rows):
        date_text, from_state, to_state, actor, reason = row
        try:
            row_date = date.fromisoformat(date_text)
        except ValueError:
            result.error(
                "STATE_HISTORY_DATE_INVALID",
                f"State history row {index + 1} has an invalid date: {date_text}",
                "State history",
            )
            continue
        if last_date and row_date < last_date:
            result.error(
                "STATE_HISTORY_DATE_ORDER",
                "State history dates must be nondecreasing.",
                "State history",
            )
        last_date = row_date
        if to_state not in ALL_STATES:
            result.error(
                "STATE_HISTORY_STATE_INVALID",
                f"Unknown destination state in history: {to_state}",
                "State history",
            )
        if not actor or not reason:
            result.error(
                "STATE_HISTORY_DETAIL_MISSING",
                f"State history row {index + 1} requires actor and reason/evidence.",
                "State history",
            )
        if index == 0:
            if from_state not in {"—", "–", "-"} or to_state != "DRAFT":
                result.error(
                    "STATE_HISTORY_INITIAL_INVALID",
                    "The first state history row must be — → DRAFT.",
                    "State history",
                )
        else:
            if from_state != previous:
                result.error(
                    "STATE_HISTORY_CHAIN_INVALID",
                    f"State history row {index + 1} starts from {from_state}, expected {previous}.",
                    "State history",
                )
            if previous in NORMAL_TRANSITIONS and to_state not in NORMAL_TRANSITIONS[previous]:
                result.error(
                    "STATE_TRANSITION_INVALID",
                    f"Transition is not allowed: {previous} → {to_state}",
                    "State history",
                )
        previous = to_state
    if previous != current_state:
        result.error(
            "STATE_HISTORY_CURRENT_MISMATCH",
            f"Last state-history destination is {previous}; metadata state is {current_state}.",
            "State history",
        )
    if updated and last_date and updated != last_date:
        result.error(
            "STATE_HISTORY_UPDATED_MISMATCH",
            f"updated ({updated.isoformat()}) must equal the latest state-history date ({last_date.isoformat()}).",
            "updated",
        )


def completion_values(content: str) -> dict[str, str]:
    pattern = re.compile(r"(?m)^\s*-\s+\*\*(.+?):\*\*\s*(.*)$")
    return {match.group(1).strip(): match.group(2).strip() for match in pattern.finditer(content)}


def validate_completion(repo: Path, state: str, content: str, result: CapsuleResult) -> None:
    if state not in COMPLETED_STATES:
        return
    values = completion_values(content)
    for field_name in COMPLETION_FIELDS:
        if field_name not in values:
            result.error(
                "COMPLETION_FIELD_MISSING",
                f"Completion field is missing: {field_name}",
                "Completion record",
            )
        elif not meaningful(values[field_name]):
            result.error(
                "COMPLETION_FIELD_INCOMPLETE",
                f"Completion field is incomplete: {field_name}",
                "Completion record",
            )
    if state in {"MERGED", "RETROSPECTED"}:
        reviewed = values.get("Reviewed commit", "")
        if reviewed:
            validate_commit(repo, reviewed, "Reviewed commit", result)
        disposition = values.get("Review disposition", "")
        if disposition and not disposition.lower().startswith("approved"):
            result.error(
                "COMPLETION_DISPOSITION_INVALID",
                "Merged or retrospected work must record an Approved disposition.",
                "Completion record",
            )
    if state == "RETROSPECTED":
        retrospective = values.get("Retrospective required", "")
        if retrospective and not retrospective.lower().startswith("yes"):
            result.error(
                "RETROSPECTIVE_RECORD_INVALID",
                "RETROSPECTED requires 'Retrospective required' to begin with yes.",
                "Completion record",
            )


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return str(value)


def validate_acceptance(content: str, state: str, result: CapsuleResult) -> None:
    matches = list(CHECKBOX_PATTERN.finditer(content))
    if not matches:
        result.error(
            "ACCEPTANCE_CHECKLIST_MISSING",
            "Acceptance criteria must contain at least one Markdown checkbox.",
            "Acceptance criteria",
        )
        return
    identifiers: list[str] = []
    for match in matches:
        checked, text = match.groups()
        identifier = ACCEPTANCE_PATTERN.match(text)
        if not identifier:
            result.error(
                "ACCEPTANCE_ID_MISSING",
                "Every acceptance checkbox must begin with a stable ID such as AC-1.",
                "Acceptance criteria",
            )
        else:
            identifiers.append(identifier.group(1))
        if state in VERIFIED_OR_LATER and checked.lower() != "x":
            result.error(
                "ACCEPTANCE_UNVERIFIED",
                f"{identifier.group(1) if identifier else 'Acceptance item'} is unchecked in state {state}.",
                "Acceptance criteria",
            )
    if len(identifiers) != len(set(identifiers)):
        result.error(
            "ACCEPTANCE_ID_DUPLICATE",
            "Acceptance criterion IDs must be unique.",
            "Acceptance criteria",
        )


def validate_capsule(
    repo: Path,
    path: Path,
    *,
    execution: bool,
    context: dict[str, Any],
) -> CapsuleResult:
    result = CapsuleResult(path=relative_path(repo, path))
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(repo.resolve())
    except ValueError:
        result.error("PATH_OUTSIDE_REPOSITORY", "Capsule path must be inside the repository.")
        return result
    allowed_parents = {
        Path("engineering/capsules/active"),
        Path("engineering/capsules/completed"),
    }
    if relative.parent not in allowed_parents:
        result.error(
            "CAPSULE_LOCATION_INVALID",
            "Capsules must be direct children of engineering/capsules/active or completed.",
        )
    parsed = parse_document(resolved, result)
    if parsed is None:
        return result
    metadata, body = parsed
    result.metadata = json_safe(metadata)
    for key in REQUIRED_METADATA:
        if key not in metadata:
            result.error("METADATA_MISSING", f"Required metadata is missing: {key}", key)
    for key in sorted(set(metadata) - set(REQUIRED_METADATA)):
        result.error("METADATA_UNKNOWN", f"Unknown schema-v1 metadata key: {key}", key)

    schema = metadata.get("schema_version")
    if type(schema) is not int or schema != SCHEMA_VERSION:
        result.error("SCHEMA_UNSUPPORTED", f"schema_version must be {SCHEMA_VERSION}.", "schema_version")
    revision = metadata.get("capsule_revision")
    if type(revision) is not int or revision < 1:
        result.error(
            "CAPSULE_REVISION_INVALID",
            "capsule_revision must be a positive integer.",
            "capsule_revision",
        )

    capsule_id = metadata.get("id")
    if isinstance(capsule_id, str):
        result.capsule_id = capsule_id
        if not ID_PATTERN.fullmatch(capsule_id):
            result.error(
                "ID_INVALID",
                "id may contain only letters, digits, periods, underscores, and hyphens.",
                "id",
            )
        if path.stem != capsule_id:
            result.error(
                "ID_FILENAME_MISMATCH",
                f"Filename stem '{path.stem}' must equal metadata id '{capsule_id}'.",
                "id",
            )
    else:
        result.error("TYPE_INVALID", "id must be a string.", "id")

    state = metadata.get("state")
    if isinstance(state, str):
        result.state = state
        if state not in ALL_STATES:
            result.error("STATE_INVALID", f"Unknown state: {state}", "state")
    else:
        result.error("TYPE_INVALID", "state must be a string.", "state")
        state = ""
    if relative.parent == Path("engineering/capsules/active") and state in COMPLETED_STATES:
        result.error(
            "STATE_LOCATION_MISMATCH",
            f"{state} capsules belong in engineering/capsules/completed.",
            "state",
        )
    if relative.parent == Path("engineering/capsules/completed") and state in ACTIVE_STATES:
        result.error(
            "STATE_LOCATION_MISMATCH",
            f"{state} capsules belong in engineering/capsules/active.",
            "state",
        )

    for key in ("title", "source_issue", "base_commit", "branch", "controller", "executor", "reviewer", "blocked_reason", "blocked_since"):
        if not isinstance(metadata.get(key), str):
            result.error("TYPE_INVALID", f"{key} must be a string.", key)
    if metadata.get("task_type") not in TASK_TYPES:
        result.error(
            "TASK_TYPE_INVALID",
            "task_type must be one of: " + ", ".join(sorted(TASK_TYPES)) + ".",
            "task_type",
        )
    if metadata.get("risk") not in RISKS:
        result.error(
            "RISK_INVALID",
            "risk must be one of: " + ", ".join(sorted(RISKS)) + ".",
            "risk",
        )
    delegation = metadata.get("delegation")
    if delegation not in DELEGATION_MODES:
        result.error("DELEGATION_INVALID", "delegation must be none or bounded.", "delegation")

    created = parse_iso_date(metadata.get("created"), "created", result)
    updated = parse_iso_date(metadata.get("updated"), "updated", result)
    if created and updated and created > updated:
        result.error("DATE_ORDER_INVALID", "created must not be later than updated.", "updated")

    dependencies = validate_string_list(metadata, "dependencies", result)
    planning_artifacts = validate_string_list(metadata, "planning_artifacts", result)
    delegation_constraints = validate_string_list(metadata, "delegation_constraints", result)
    owned_paths = validate_string_list(metadata, "owned_paths", result)
    allowed_paths = validate_string_list(metadata, "allowed_paths", result)
    forbidden_paths = validate_string_list(metadata, "forbidden_paths", result)
    validate_string_list(metadata, "specialized_qualification", result)
    del dependencies
    validate_authority_paths(repo, planning_artifacts, result)
    for key, entries in (
        ("owned_paths", owned_paths),
        ("allowed_paths", allowed_paths),
        ("forbidden_paths", forbidden_paths),
    ):
        validate_scope_paths(entries, key, result)
    for overlap, label in (
        (set(owned_paths) & set(forbidden_paths), "owned_paths and forbidden_paths"),
        (set(allowed_paths) & set(forbidden_paths), "allowed_paths and forbidden_paths"),
    ):
        for entry in sorted(overlap):
            result.error("SCOPE_PATH_CONFLICT", f"{entry} appears in both {label}.", "forbidden_paths")
    if delegation == "none" and delegation_constraints:
        result.error(
            "DELEGATION_CONSTRAINTS_STALE",
            "delegation=none requires empty delegation_constraints.",
            "delegation_constraints",
        )
    if delegation == "bounded" and not delegation_constraints:
        result.error(
            "DELEGATION_CONSTRAINTS_MISSING",
            "delegation=bounded requires explicit delegation_constraints.",
            "delegation_constraints",
        )

    blocked = metadata.get("blocked")
    if type(blocked) is not bool:
        result.error("TYPE_INVALID", "blocked must be true or false.", "blocked")
        blocked = False
    blocked_reason = metadata.get("blocked_reason") if isinstance(metadata.get("blocked_reason"), str) else ""
    blocked_since_text = metadata.get("blocked_since") if isinstance(metadata.get("blocked_since"), str) else ""
    blocked_since: date | None = None
    if blocked:
        if not meaningful(blocked_reason):
            result.error("BLOCK_REASON_MISSING", "blocked=true requires a concrete blocked_reason.", "blocked_reason")
        blocked_since = parse_iso_date(blocked_since_text, "blocked_since", result)
    elif blocked_reason or blocked_since_text:
        result.error(
            "BLOCK_FIELDS_STALE",
            "blocked=false requires empty blocked_reason and blocked_since.",
            "blocked",
        )
    if state in COMPLETED_STATES and blocked:
        result.error("COMPLETED_BLOCKED", "Completed or cancelled capsules cannot remain blocked.", "blocked")
    if blocked_since and updated and blocked_since > updated:
        result.error("BLOCK_DATE_INVALID", "blocked_since must not be later than updated.", "blocked_since")

    base_commit = metadata.get("base_commit") if isinstance(metadata.get("base_commit"), str) else ""
    base_valid = validate_commit(repo, base_commit, "base_commit", result) if base_commit else False
    branch = metadata.get("branch") if isinstance(metadata.get("branch"), str) else ""
    if branch and run_git(repo, "check-ref-format", "--branch", branch).returncode:
        result.error("BRANCH_INVALID", f"Invalid branch name: {branch}", "branch")

    sections = split_sections(body, result)
    if state in ALL_STATES and "State history" in sections:
        parse_state_history(sections["State history"], state, updated, result)

    if state in READY_OR_LATER:
        source_issue = metadata.get("source_issue", "")
        if not isinstance(source_issue, str) or not meaningful(source_issue):
            result.error(
                "SOURCE_ISSUE_MISSING",
                "READY or later requires source_issue or a reasoned Not applicable value.",
                "source_issue",
            )
        if not base_commit:
            result.error("BASE_COMMIT_MISSING", "READY or later requires an exact base_commit.", "base_commit")
        elif base_valid and state in ACTIVE_STATES:
            if run_git(repo, "merge-base", "--is-ancestor", base_commit, context["head"]).returncode:
                result.error(
                    "BASE_COMMIT_NOT_ANCESTOR",
                    "Active capsule base_commit must be an ancestor of current HEAD.",
                    "base_commit",
                )
        if not branch:
            result.error("BRANCH_MISSING", "READY or later requires the expected branch.", "branch")
        for role in ("title", "controller", "executor", "reviewer"):
            value = metadata.get(role)
            if not isinstance(value, str) or not meaningful(value):
                result.error(
                    "METADATA_INCOMPLETE",
                    f"{role} contains a template placeholder or is incomplete.",
                    role,
                )
        if not planning_artifacts:
            result.error("AUTHORITY_EMPTY", "READY or later requires at least one planning_artifact.", "planning_artifacts")
        if not owned_paths:
            result.error("OWNED_PATHS_EMPTY", "READY or later requires at least one owned_paths entry.", "owned_paths")
        for section_name in REQUIRED_SECTIONS:
            if section_name == "Completion record" and state not in COMPLETED_STATES:
                continue
            if not meaningful(sections.get(section_name, "")):
                result.error(
                    "SECTION_INCOMPLETE",
                    f"Section is empty or contains template placeholders: {section_name}",
                    section_name,
                )
        validate_acceptance(sections.get("Acceptance criteria", ""), state, result)
        verification = split_verification(sections.get("Required verification", ""), result)
        for name in REQUIRED_VERIFICATION_SUBSECTIONS:
            if name in verification and not meaningful(verification[name]):
                result.error(
                    "VERIFICATION_SUBSECTION_INCOMPLETE",
                    f"Verification subsection is incomplete: {name}",
                    "Required verification",
                )
    elif "Required verification" in sections:
        split_verification(sections["Required verification"], result)

    if state in COMPLETED_STATES:
        validate_completion(repo, state, sections.get("Completion record", ""), result)

    if execution:
        details: dict[str, Any] = {
            "head": context["head"],
            "branch": context["branch"],
            "clean": context["clean"],
            "overlay_paths": [],
        }
        result.execution = details
        if state != "READY":
            result.error("EXECUTION_STATE_INVALID", "Execution preflight requires state=READY.", "state")
        if blocked:
            result.error("EXECUTION_BLOCKED", "Execution preflight cannot pass while blocked=true.", "blocked")
        if not context["clean"]:
            result.error("EXECUTION_WORKTREE_DIRTY", "Execution preflight requires a clean working tree.")
        if branch and context["branch"] != branch:
            result.error(
                "EXECUTION_BRANCH_MISMATCH",
                f"Current branch is {context['branch']}; capsule requires {branch}.",
                "branch",
            )
        if base_commit and COMMIT_PATTERN.fullmatch(base_commit):
            ancestor = run_git(repo, "merge-base", "--is-ancestor", base_commit, context["head"])
            if ancestor.returncode:
                result.error(
                    "EXECUTION_BASE_MISMATCH",
                    "base_commit is not an ancestor of current HEAD.",
                    "base_commit",
                )
            else:
                diff = run_git(repo, "diff", "--name-only", f"{base_commit}..{context['head']}", check=True)
                overlay = [line for line in diff.stdout.splitlines() if line]
                details["overlay_paths"] = overlay
                expected_overlay = [relative.as_posix()]
                if overlay != expected_overlay:
                    result.error(
                        "EXECUTION_OVERLAY_INVALID",
                        "Commits after base_commit must modify exactly the capsule itself; "
                        f"expected {expected_overlay}, found {overlay}.",
                        "base_commit",
                    )
    return result


def result_document(
    context: dict[str, Any], results: list[CapsuleResult], mode: str
) -> dict[str, Any]:
    failed = sum(not result.valid for result in results)
    warning_count = sum(len(result.warnings) for result in results)
    return {
        "validation_schema_version": 1,
        "capsule_schema_versions_supported": [SCHEMA_VERSION],
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "repository": context,
        "summary": {
            "total": len(results),
            "passed": len(results) - failed,
            "failed": failed,
            "warnings": warning_count,
            "status": "passed" if failed == 0 else "failed",
        },
        "capsules": [
            {
                **asdict(result),
                "errors": [asdict(item) for item in result.errors],
                "warnings": [asdict(item) for item in result.warnings],
            }
            for result in results
        ],
    }


def print_human(document: dict[str, Any]) -> None:
    capsules = document["capsules"]
    if not capsules:
        print("PASS: no task capsules found.")
    for capsule in capsules:
        label = capsule["path"]
        state = capsule.get("state") or "unknown-state"
        print(f"{'PASS' if capsule['valid'] else 'FAIL'} {label} [{state}]")
        for finding in capsule["errors"]:
            field_name = f" ({finding['field']})" if finding.get("field") else ""
            print(f"  ERROR {finding['code']}{field_name}: {finding['message']}")
        for finding in capsule["warnings"]:
            field_name = f" ({finding['field']})" if finding.get("field") else ""
            print(f"  WARN {finding['code']}{field_name}: {finding['message']}")
    summary = document["summary"]
    print(
        "Task capsule validation: "
        f"{summary['passed']} passed, {summary['failed']} failed, "
        f"{summary['warnings']} warning(s)."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Capsules to validate; defaults to all active and completed capsules.",
    )
    parser.add_argument("--all", action="store_true", help="Validate every active and completed capsule.")
    parser.add_argument(
        "--execution",
        action="store_true",
        help="Run strict execution preflight for exactly one READY capsule.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--output", type=Path, help="Also write the JSON result to this path.")
    parser.add_argument("--repo-root", type=Path, help="Repository root override.")
    args = parser.parse_args()
    if args.all and args.paths:
        parser.error("--all cannot be combined with explicit capsule paths")
    if args.execution and len(args.paths) != 1:
        parser.error("--execution requires exactly one explicit capsule path")
    repo = (args.repo_root or Path(__file__).resolve().parents[1]).resolve()
    try:
        context = repository_context(repo)
        if args.paths:
            paths = [
                (path if path.is_absolute() else repo / path).resolve()
                for path in args.paths
            ]
        else:
            paths = discover_capsules(repo)
        results = [
            validate_capsule(repo, path, execution=args.execution, context=context)
            for path in paths
        ]
        document = result_document(
            context,
            results,
            "execution" if args.execution else "validation",
        )
    except InvocationError as exc:
        print(f"ERROR INVOCATION: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(document, indent=2) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else Path.cwd() / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    if args.json:
        print(rendered, end="")
    else:
        print_human(document)
    return 0 if document["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
