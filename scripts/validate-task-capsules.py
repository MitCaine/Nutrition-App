#!/usr/bin/env python3
"""Validate repository-owned task capsules and strict execution readiness."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _reexec_with_supported_python() -> None:
    if sys.version_info >= (3, 11):
        return

    repository_root = Path(__file__).resolve().parents[1]
    candidates: list[Path] = [
        repository_root / "apps/backend/.venv/bin/python",
    ]

    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "worktree",
            "list",
            "--porcelain",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode == 0:
        for line in completed.stdout.splitlines():
            if not line.startswith("worktree "):
                continue

            worktree = Path(line.removeprefix("worktree "))
            candidates.append(
                worktree / "apps/backend/.venv/bin/python"
            )

    current = Path(sys.executable).resolve()

    for candidate in candidates:
        if not candidate.is_file():
            continue

        target = candidate.resolve()

        if current == target:
            continue

        os.execv(
            str(target),
            [
                str(target),
                str(Path(__file__).resolve()),
                *sys.argv[1:],
            ],
        )

    raise SystemExit(
        "Python 3.11 or newer is required. "
        "The validator could not locate a supported interpreter "
        "in this or any linked repository worktree."
    )


_reexec_with_supported_python()

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable

from lib.qualification_profiles import (
    QualificationProfileError,
    parse_profile_tokens,
)

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

TEMPLATE_PATH = Path("engineering/capsules/TEMPLATE.md")
HISTORY_PATH = Path("engineering/capsules/HISTORY.md")
HISTORY_FORMAT_MARKER = "History format version: **1**."
HISTORY_ENTRY_PATTERN = re.compile(
    r"(?m)^### ([A-Za-z0-9][A-Za-z0-9._-]*) - (.+?)$"
)
HISTORY_FIELD_PATTERN = re.compile(
    r"(?m)^- \*\*(.+?):\*\* (.*)$"
)
HISTORY_ACCEPTANCE_PATTERN = re.compile(
    r"^([0-9]+)/([0-9]+) checked in the terminal source capsule\.$"
)
HISTORY_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HISTORY_RECOVERY_PREFIXES = (
    "engineering/capsules/active/",
    "engineering/capsules/completed/",
)
HISTORY_REQUIRED_FIELDS = (
    "ID",
    "Title",
    "Final state",
    "Capsule revision",
    "Task type",
    "Risk",
    "Source issue/authority",
    "Issue disposition",
    "Created",
    "Completed/updated",
    "Base commit",
    "Task branch",
    "Controller",
    "Executor",
    "Reviewer",
    "Delegation",
    "Implementation commit(s)",
    "Verified commit reference(s)",
    "Reviewed source commit",
    "Reviewed task/checkpoint commit(s)",
    "Integration/merged commit",
    "Integration-related commit reference(s)",
    "Acceptance result",
    "Review disposition",
    "Verification summary",
    "Specialized qualification",
    "Known warnings",
    "Deferred work/follow-up IDs",
    "Retrospective",
    "Referenced commits",
    "Full-capsule recovery commit",
    "Full-capsule recovery path",
    "Historical capsule SHA-256",
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


@dataclass
class HistoryResult:
    path: str
    valid: bool = True
    record_count: int = 0
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)

    def error(
        self,
        code: str,
        message: str,
        field_name: str | None = None,
    ) -> None:
        self.valid = False
        self.errors.append(
            Finding(code, message, field_name)
        )

    def warning(
        self,
        code: str,
        message: str,
        field_name: str | None = None,
    ) -> None:
        self.warnings.append(
            Finding(code, message, field_name)
        )


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
    directory = (
        repo
        / "engineering"
        / "capsules"
        / "active"
    )

    if not directory.is_dir():
        return []

    return [
        path
        for path in sorted(directory.glob("*.md"))
        if path.name not in {"README.md", "TEMPLATE.md"}
    ]

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


def validate_template_structure(
    repo: Path,
) -> CapsuleResult | None:
    path = repo / TEMPLATE_PATH

    if not path.is_file():
        return None

    result = CapsuleResult(
        path=TEMPLATE_PATH.as_posix(),
        state="schema-v1-template",
    )

    parsed = parse_document(
        path,
        result,
    )

    if parsed is None:
        return result

    metadata, body = parsed
    result.metadata = json_safe(
        metadata
    )

    for key in REQUIRED_METADATA:
        if key not in metadata:
            result.error(
                "METADATA_MISSING",
                (
                    "Canonical template is missing "
                    f"schema-v1 metadata: {key}"
                ),
                key,
            )

    for key in sorted(
        set(metadata)
        - set(REQUIRED_METADATA)
    ):
        result.error(
            "METADATA_UNKNOWN",
            (
                "Canonical template contains unknown "
                f"schema-v1 metadata: {key}"
            ),
            key,
        )

    schema = metadata.get(
        "schema_version"
    )

    if (
        type(schema) is not int
        or schema != SCHEMA_VERSION
    ):
        result.error(
            "SCHEMA_UNSUPPORTED",
            (
                "Canonical template schema_version "
                f"must be {SCHEMA_VERSION}."
            ),
            "schema_version",
        )

    revision = metadata.get(
        "capsule_revision"
    )

    if (
        type(revision) is not int
        or revision < 1
    ):
        result.error(
            "CAPSULE_REVISION_INVALID",
            (
                "Canonical template capsule_revision "
                "must be a positive integer."
            ),
            "capsule_revision",
        )

    sections = split_sections(
        body,
        result,
    )

    if "Required verification" in sections:
        split_verification(
            sections[
                "Required verification"
            ],
            result,
        )

    return result

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


def validate_commit_syntax(
    value: str,
    field_name: str,
    result: CapsuleResult,
) -> bool:
    if not COMMIT_PATTERN.fullmatch(value):
        result.error(
            "COMMIT_INVALID",
            f"{field_name} must be an exact lowercase 40-character commit hash.",
            field_name,
        )
        return False
    return True


def validate_commit(repo: Path, value: str, field_name: str, result: CapsuleResult) -> bool:
    if not validate_commit_syntax(value, field_name, result):
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


def extract_commit_reference(
    value: str,
    field_name: str,
    result: CapsuleResult,
) -> str | None:
    matches = re.findall(r"(?<![0-9A-Za-z])[0-9a-f]{40}(?![0-9A-Za-z])", value)
    if len(matches) != 1:
        result.error(
            "COMMIT_INVALID",
            f"{field_name} must contain exactly one lowercase 40-character commit hash.",
            field_name,
        )
        return None
    return matches[0]


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


def validate_authority_paths(
    repo: Path,
    entries: Iterable[str],
    result: CapsuleResult,
    base_commit: str,
) -> None:
    for entry in entries:
        raw = entry.split("#", 1)[0].strip()
        candidate = Path(raw)

        if (
            not raw
            or candidate.is_absolute()
            or ".." in candidate.parts
            or "://" in raw
        ):
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

        if resolved.is_file():
            continue

        historical_type = None

        if COMMIT_PATTERN.fullmatch(base_commit):
            historical = run_git(
                repo,
                "cat-file",
                "-t",
                f"{base_commit}:{raw}",
            )

            if historical.returncode == 0:
                historical_type = historical.stdout.strip()

        if historical_type == "blob":
            continue

        result.error(
            "AUTHORITY_PATH_MISSING",
            (
                "Authority artifact does not exist as a file "
                "in the current tree or exact base_commit: "
                f"{entry}"
            ),
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
    pattern = re.compile(r"(?m)^[ \t]*-[ \t]+\*\*(.+?):\*\*[ \t]*(.*)$")
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
            validate_commit_syntax(reviewed, "Reviewed commit", result)

        if "Merged commit" not in values:
            result.error(
                "COMPLETION_FIELD_MISSING",
                "Completion field is missing: Merged commit",
                "Completion record",
            )
        elif not meaningful(values["Merged commit"]):
            result.error(
                "COMPLETION_FIELD_INCOMPLETE",
                "Completion field is incomplete: Merged commit",
                "Completion record",
            )
        else:
            merged_commit = extract_commit_reference(
                values["Merged commit"],
                "Merged commit",
                result,
            )
            if merged_commit is not None:
                validate_commit(
                    repo,
                    merged_commit,
                    "Merged commit",
                    result,
                )

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


def strip_history_code(value: str) -> str:
    stripped = value.strip()

    if (
        len(stripped) >= 2
        and stripped.startswith("`")
        and stripped.endswith("`")
    ):
        return stripped[1:-1]

    return stripped


def historical_capsule_identity(
    content: str,
) -> tuple[int | None, str | None]:
    lines = content.splitlines()

    if not lines or lines[0].strip() != "+++":
        return None, None

    try:
        end = next(
            index
            for index, line in enumerate(
                lines[1:],
                start=1,
            )
            if line.strip() == "+++"
        )
    except StopIteration:
        return None, None

    try:
        metadata = tomllib.loads(
            "\n".join(lines[1:end])
        )
    except tomllib.TOMLDecodeError:
        return None, None

    schema = metadata.get("schema_version")
    capsule_id = metadata.get("id")

    return (
        schema if type(schema) is int else None,
        capsule_id
        if isinstance(capsule_id, str)
        else None,
    )


def validate_history(
    repo: Path,
    active_ids: Iterable[str],
) -> HistoryResult | None:
    relative = HISTORY_PATH
    path = repo / relative

    completed_directory = (
        repo
        / "engineering"
        / "capsules"
        / "completed"
    )

    stale_completed: list[str] = []

    if completed_directory.is_dir():
        stale_completed = [
            item.relative_to(repo).as_posix()
            for item in sorted(
                completed_directory.glob("*.md")
            )
        ]

    if not path.is_file() and not stale_completed:
        return None

    result = HistoryResult(
        path=relative.as_posix()
    )

    if stale_completed:
        result.error(
            "COMPLETED_CAPSULES_PRESENT",
            (
                "The current tree must not retain "
                "terminal capsule files under "
                "engineering/capsules/completed: "
                + ", ".join(stale_completed)
            ),
        )

    if not path.is_file():
        result.error(
            "HISTORY_MISSING",
            (
                "Terminal history is required when "
                "legacy completed-capsule files exist."
            ),
        )
        return result

    try:
        content = path.read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        result.error(
            "HISTORY_READ_FAILED",
            str(exc),
        )
        return result

    if HISTORY_FORMAT_MARKER not in content:
        result.error(
            "HISTORY_FORMAT_INVALID",
            (
                "HISTORY.md must declare "
                "history format version 1."
            ),
        )

    matches = list(
        HISTORY_ENTRY_PATTERN.finditer(
            content
        )
    )

    result.record_count = len(matches)

    if not matches:
        result.error(
            "HISTORY_ENTRY_MISSING",
            (
                "HISTORY.md must contain at least "
                "one terminal task record."
            ),
        )
        return result

    seen_ids: set[str] = set()
    active_id_set = set(active_ids)

    for index, match in enumerate(matches):
        capsule_id = match.group(1)
        heading_title = match.group(2).strip()

        if capsule_id in seen_ids:
            result.error(
                "HISTORY_ID_DUPLICATE",
                (
                    "Terminal history ID appears "
                    f"more than once: {capsule_id}"
                ),
                capsule_id,
            )

        seen_ids.add(capsule_id)

        if capsule_id in active_id_set:
            result.error(
                "HISTORY_ID_ACTIVE_CONFLICT",
                (
                    "A terminal task ID may not be "
                    "reused by an active capsule: "
                    f"{capsule_id}"
                ),
                capsule_id,
            )

        block_start = match.end()
        block_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(content)
        )

        block = content[
            block_start:block_end
        ]

        field_matches = list(
            HISTORY_FIELD_PATTERN.finditer(
                block
            )
        )

        field_names = [
            item.group(1).strip()
            for item in field_matches
        ]

        duplicate_fields = sorted(
            {
                name
                for name in field_names
                if field_names.count(name) > 1
            }
        )

        for field_name in duplicate_fields:
            result.error(
                "HISTORY_FIELD_DUPLICATE",
                (
                    f"{capsule_id} contains duplicate "
                    f"history field: {field_name}"
                ),
                capsule_id,
            )

        fields = {
            item.group(1).strip():
            item.group(2).strip()
            for item in field_matches
        }

        missing_required = False

        for field_name in HISTORY_REQUIRED_FIELDS:
            if field_name not in fields:
                result.error(
                    "HISTORY_FIELD_MISSING",
                    (
                        f"{capsule_id} is missing "
                        f"history field: {field_name}"
                    ),
                    capsule_id,
                )
                missing_required = True
            elif not fields[field_name].strip():
                result.error(
                    "HISTORY_FIELD_INCOMPLETE",
                    (
                        f"{capsule_id} has an empty "
                        f"history field: {field_name}"
                    ),
                    capsule_id,
                )

        if missing_required:
            continue

        recorded_id = strip_history_code(
            fields["ID"]
        )

        if recorded_id != capsule_id:
            result.error(
                "HISTORY_ID_MISMATCH",
                (
                    f"Heading ID {capsule_id} does "
                    f"not match ID field {recorded_id}."
                ),
                capsule_id,
            )

        if fields["Title"] != heading_title:
            result.error(
                "HISTORY_TITLE_MISMATCH",
                (
                    f"{capsule_id} heading title "
                    "does not match its Title field."
                ),
                capsule_id,
            )

        state = strip_history_code(
            fields["Final state"]
        )

        if state not in COMPLETED_STATES:
            result.error(
                "HISTORY_STATE_INVALID",
                (
                    f"{capsule_id} has non-terminal "
                    f"history state: {state}"
                ),
                capsule_id,
            )

        try:
            revision = int(
                fields["Capsule revision"]
            )
        except ValueError:
            revision = 0

        if revision < 1:
            result.error(
                "HISTORY_REVISION_INVALID",
                (
                    f"{capsule_id} capsule revision "
                    "must be a positive integer."
                ),
                capsule_id,
            )

        if fields["Task type"] not in TASK_TYPES:
            result.error(
                "HISTORY_TASK_TYPE_INVALID",
                (
                    f"{capsule_id} has invalid "
                    "task type: "
                    f"{fields['Task type']}"
                ),
                capsule_id,
            )

        if fields["Risk"] not in RISKS:
            result.error(
                "HISTORY_RISK_INVALID",
                (
                    f"{capsule_id} has invalid risk: "
                    f"{fields['Risk']}"
                ),
                capsule_id,
            )

        acceptance = (
            HISTORY_ACCEPTANCE_PATTERN.fullmatch(
                fields["Acceptance result"]
            )
        )

        if acceptance is None:
            result.error(
                "HISTORY_ACCEPTANCE_INVALID",
                (
                    f"{capsule_id} has malformed "
                    "Acceptance result."
                ),
                capsule_id,
            )
        else:
            checked = int(
                acceptance.group(1)
            )
            total = int(
                acceptance.group(2)
            )

            if checked > total:
                result.error(
                    "HISTORY_ACCEPTANCE_INVALID",
                    (
                        f"{capsule_id} records more "
                        "checked acceptance criteria "
                        "than total criteria."
                    ),
                    capsule_id,
                )

            if (
                state in {"MERGED", "RETROSPECTED"}
                and (
                    total < 1
                    or checked != total
                )
            ):
                result.error(
                    "HISTORY_ACCEPTANCE_UNVERIFIED",
                    (
                        f"{capsule_id} is {state} but "
                        "its terminal acceptance result "
                        "is not fully checked."
                    ),
                    capsule_id,
                )

        if (
            state in {"MERGED", "RETROSPECTED"}
            and not fields[
                "Review disposition"
            ].lower().startswith("approved")
        ):
            result.error(
                "HISTORY_DISPOSITION_INVALID",
                (
                    f"{capsule_id} is {state} but "
                    "does not record an Approved "
                    "review disposition."
                ),
                capsule_id,
            )

        if state in {"MERGED", "RETROSPECTED"}:
            merged_commit = (
                extract_commit_reference(
                    fields[
                        "Integration/merged commit"
                    ],
                    "Integration/merged commit",
                    result,
                )
            )

            if merged_commit is not None:
                validate_commit(
                    repo,
                    merged_commit,
                    "Integration/merged commit",
                    result,
                )

        recovery_commit = strip_history_code(
            fields[
                "Full-capsule recovery commit"
            ]
        )

        commit_valid = True

        if not COMMIT_PATTERN.fullmatch(
            recovery_commit
        ):
            result.error(
                "HISTORY_RECOVERY_COMMIT_INVALID",
                (
                    f"{capsule_id} recovery commit "
                    "must be an exact lowercase "
                    "40-character commit hash."
                ),
                capsule_id,
            )
            commit_valid = False
        else:
            resolved = run_git(
                repo,
                "rev-parse",
                f"{recovery_commit}^{{commit}}",
            )

            if (
                resolved.returncode
                or resolved.stdout.strip()
                != recovery_commit
            ):
                result.error(
                    "HISTORY_RECOVERY_COMMIT_UNKNOWN",
                    (
                        f"{capsule_id} recovery commit "
                        "does not resolve in this "
                        "repository."
                    ),
                    capsule_id,
                )
                commit_valid = False

        recovery_path = strip_history_code(
            fields[
                "Full-capsule recovery path"
            ]
        )

        candidate = Path(recovery_path)

        path_valid = not (
            candidate.is_absolute()
            or ".." in candidate.parts
            or "\\" in recovery_path
            or not recovery_path.endswith(".md")
            or not recovery_path.startswith(
                HISTORY_RECOVERY_PREFIXES
            )
        )

        if not path_valid:
            result.error(
                "HISTORY_RECOVERY_PATH_INVALID",
                (
                    f"{capsule_id} has invalid "
                    "full-capsule recovery path: "
                    f"{recovery_path}"
                ),
                capsule_id,
            )
        elif candidate.stem != capsule_id:
            result.error(
                "HISTORY_RECOVERY_ID_MISMATCH",
                (
                    f"{capsule_id} recovery path "
                    "filename does not match its ID."
                ),
                capsule_id,
            )
            path_valid = False

        expected_hash = strip_history_code(
            fields[
                "Historical capsule SHA-256"
            ]
        )

        hash_valid = bool(
            HISTORY_SHA256_PATTERN.fullmatch(
                expected_hash
            )
        )

        if not hash_valid:
            result.error(
                "HISTORY_SHA256_INVALID",
                (
                    f"{capsule_id} historical "
                    "capsule SHA-256 is malformed."
                ),
                capsule_id,
            )

        if commit_valid and path_valid:
            historical = run_git(
                repo,
                "show",
                (
                    f"{recovery_commit}:"
                    f"{recovery_path}"
                ),
            )

            if historical.returncode:
                result.error(
                    "HISTORY_RECOVERY_LOCATOR_INVALID",
                    (
                        f"{capsule_id} full capsule "
                        "cannot be recovered from "
                        "its recorded commit/path."
                    ),
                    capsule_id,
                )
            else:
                schema, historical_id = (
                    historical_capsule_identity(
                        historical.stdout
                    )
                )

                if schema != SCHEMA_VERSION:
                    result.error(
                        "HISTORY_RECOVERY_SCHEMA_INVALID",
                        (
                            f"{capsule_id} recovery "
                            "target is not a supported "
                            "full task capsule."
                        ),
                        capsule_id,
                    )

                if historical_id != capsule_id:
                    result.error(
                        "HISTORY_RECOVERY_CAPSULE_ID_MISMATCH",
                        (
                            f"{capsule_id} recovery "
                            "target records capsule ID "
                            f"{historical_id!r}."
                        ),
                        capsule_id,
                    )

                if hash_valid:
                    actual_hash = hashlib.sha256(
                        historical.stdout.encode(
                            "utf-8"
                        )
                    ).hexdigest()

                    if actual_hash != expected_hash:
                        result.error(
                            "HISTORY_SHA256_MISMATCH",
                            (
                                f"{capsule_id} historical "
                                "capsule content does not "
                                "match its recorded SHA-256."
                            ),
                            capsule_id,
                        )

    return result

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
            "Terminal states are recorded in "
            "engineering/capsules/HISTORY.md; "
            "remove the full active capsule during closeout.",
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
    specialized_qualification = validate_string_list(
        metadata,
        "specialized_qualification",
        result,
    )

    try:
        parse_profile_tokens(
            specialized_qualification
        )
    except QualificationProfileError as exc:
        result.error(
            exc.code,
            str(exc),
            "specialized_qualification",
        )
    del dependencies
    authority_base = (
        metadata.get("base_commit", "")
        if isinstance(metadata.get("base_commit"), str)
        else ""
    )

    validate_authority_paths(
        repo,
        planning_artifacts,
        result,
        authority_base,
    )
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
    context: dict[str, Any],
    results: list[CapsuleResult],
    mode: str,
    history: HistoryResult | None = None,
    template: CapsuleResult | None = None,
) -> dict[str, Any]:
    capsule_failures = sum(
        not result.valid
        for result in results
    )

    history_failures = int(
        history is not None
        and not history.valid
    )

    template_failures = int(
        template is not None
        and not template.valid
    )

    failed = (
        capsule_failures
        + history_failures
        + template_failures
    )

    warning_count = sum(
        len(result.warnings)
        for result in results
    )

    if history is not None:
        warning_count += len(
            history.warnings
        )

    if template is not None:
        warning_count += len(
            template.warnings
        )

    total = (
        len(results)
        + (1 if history is not None else 0)
        + (1 if template is not None else 0)
    )

    history_document = None

    if history is not None:
        history_document = {
            **asdict(history),
            "errors": [
                asdict(item)
                for item in history.errors
            ],
            "warnings": [
                asdict(item)
                for item in history.warnings
            ],
        }

    template_document = None

    if template is not None:
        template_document = {
            **asdict(template),
            "errors": [
                asdict(item)
                for item in template.errors
            ],
            "warnings": [
                asdict(item)
                for item in template.warnings
            ],
        }

    return {
        "validation_schema_version": 1,
        "capsule_schema_versions_supported": [
            SCHEMA_VERSION
        ],
        "history_format_versions_supported": [1],
        "generated_at": (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "mode": mode,
        "repository": context,
        "summary": {
            "total": total,
            "passed": total - failed,
            "failed": failed,
            "warnings": warning_count,
            "status": (
                "passed"
                if failed == 0
                else "failed"
            ),
        },
        "capsules": [
            {
                **asdict(result),
                "errors": [
                    asdict(item)
                    for item in result.errors
                ],
                "warnings": [
                    asdict(item)
                    for item in result.warnings
                ],
            }
            for result in results
        ],
        "template": template_document,
        "history": history_document,
    }


def print_human(
    document: dict[str, Any]
) -> None:
    capsules = document["capsules"]
    template = document.get("template")
    history = document.get("history")

    if (
        not capsules
        and template is None
        and history is None
    ):
        print(
            "PASS: no active task capsules "
            "or terminal history found."
        )

    if template is not None:
        label = template["path"]

        print(
            f"{'PASS' if template['valid'] else 'FAIL'} "
            f"{label} [schema-v1 template]"
        )

        for finding in template["errors"]:
            field_name = (
                f" ({finding['field']})"
                if finding.get("field")
                else ""
            )

            print(
                f"  ERROR {finding['code']}"
                f"{field_name}: "
                f"{finding['message']}"
            )

        for finding in template["warnings"]:
            field_name = (
                f" ({finding['field']})"
                if finding.get("field")
                else ""
            )

            print(
                f"  WARN {finding['code']}"
                f"{field_name}: "
                f"{finding['message']}"
            )

    for capsule in capsules:
        label = capsule["path"]

        state = (
            capsule.get("state")
            or "unknown-state"
        )

        print(
            f"{'PASS' if capsule['valid'] else 'FAIL'} "
            f"{label} [{state}]"
        )

        for finding in capsule["errors"]:
            field_name = (
                f" ({finding['field']})"
                if finding.get("field")
                else ""
            )

            print(
                f"  ERROR {finding['code']}"
                f"{field_name}: "
                f"{finding['message']}"
            )

        for finding in capsule["warnings"]:
            field_name = (
                f" ({finding['field']})"
                if finding.get("field")
                else ""
            )

            print(
                f"  WARN {finding['code']}"
                f"{field_name}: "
                f"{finding['message']}"
            )

    if history is not None:
        label = history["path"]
        count = history["record_count"]

        print(
            f"{'PASS' if history['valid'] else 'FAIL'} "
            f"{label} "
            f"[{count} terminal record(s)]"
        )

        for finding in history["errors"]:
            field_name = (
                f" ({finding['field']})"
                if finding.get("field")
                else ""
            )

            print(
                f"  ERROR {finding['code']}"
                f"{field_name}: "
                f"{finding['message']}"
            )

        for finding in history["warnings"]:
            field_name = (
                f" ({finding['field']})"
                if finding.get("field")
                else ""
            )

            print(
                f"  WARN {finding['code']}"
                f"{field_name}: "
                f"{finding['message']}"
            )

    summary = document["summary"]

    print(
        "Task capsule/history validation: "
        f"{summary['passed']} passed, "
        f"{summary['failed']} failed, "
        f"{summary['warnings']} warning(s)."
    )

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=(
            "Capsules to validate; by default "
            "validate all active capsules plus "
            "the terminal history."
        ),
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Validate all active capsules, "
            "terminal history, and current-tree "
            "archive invariants."
        ),
    )

    parser.add_argument(
        "--execution",
        action="store_true",
        help=(
            "Run strict execution preflight for "
            "exactly one READY capsule."
        ),
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Also write the JSON result "
            "to this path."
        ),
    )

    parser.add_argument(
        "--repo-root",
        type=Path,
        help="Repository root override.",
    )

    args = parser.parse_args()

    if args.all and args.paths:
        parser.error(
            "--all cannot be combined with "
            "explicit capsule paths"
        )

    if (
        args.execution
        and len(args.paths) != 1
    ):
        parser.error(
            "--execution requires exactly one "
            "explicit capsule path"
        )

    repo = (
        args.repo_root
        or Path(__file__).resolve().parents[1]
    ).resolve()

    try:
        context = repository_context(repo)

        if args.paths:
            paths = [
                (
                    path
                    if path.is_absolute()
                    else repo / path
                ).resolve()
                for path in args.paths
            ]
        else:
            paths = discover_capsules(repo)

        results = [
            validate_capsule(
                repo,
                path,
                execution=args.execution,
                context=context,
            )
            for path in paths
        ]

        template_result = None
        history_result = None

        if not args.paths:
            template_result = (
                validate_template_structure(
                    repo
                )
            )

            history_result = validate_history(
                repo,
                [
                    result.capsule_id
                    for result in results
                    if result.capsule_id
                ],
            )

        document = result_document(
            context,
            results,
            (
                "execution"
                if args.execution
                else "validation"
            ),
            history_result,
            template_result,
        )

    except InvocationError as exc:
        print(
            f"ERROR INVOCATION: {exc}",
            file=sys.stderr,
        )
        return 2

    rendered = (
        json.dumps(
            document,
            indent=2,
        )
        + "\n"
    )

    if args.output:
        output = (
            args.output
            if args.output.is_absolute()
            else Path.cwd() / args.output
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            rendered,
            encoding="utf-8",
        )

    if args.json:
        print(rendered, end="")
    else:
        print_human(document)

    return (
        0
        if document["summary"]["failed"] == 0
        else 1
    )

if __name__ == "__main__":
    raise SystemExit(main())
