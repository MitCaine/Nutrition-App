#!/usr/bin/env python3
"""Create a complete GitHub delivery workflow from a structured Markdown backlog.

The utility deliberately depends only on the Python standard library. GitHub
operations are delegated to the authenticated GitHub CLI (``gh``), which keeps
credential storage and host selection outside this script.

Idempotency is provided by two complementary mechanisms:

* an atomically written local state file records issue numbers and URLs after
  every successful create operation; and
* unobtrusive HTML markers in issue bodies allow state to be reconstructed from
  GitHub after a local state file is lost or a run is interrupted.

Optional backlog labels and milestone headings become repository metadata. An
optional owner-level GitHub Project contains the Epic and children. The Epic
body contains a generated metadata block with planning links, progress, and the
child checklist. Reruns replace only that block, preserving human-authored Epic
text outside it. Existing child issue bodies are never overwritten
automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote


STATE_SCHEMA_VERSION = 1
MAX_GITHUB_TITLE_LENGTH = 256
MAX_GITHUB_BODY_LENGTH = 65_536
MANAGED_CHECKLIST_START = "<!-- create-issues:children:start -->"
MANAGED_CHECKLIST_END = "<!-- create-issues:children:end -->"

H1_RE = re.compile(r"^#\s+(.+?)\s*$")
H2_RE = re.compile(r"^##\s+(.+?)\s*$")
H3_RE = re.compile(r"^###\s+(.+?)\s*$")
MILESTONE_RE = re.compile(r"^Milestone(?:\s+\d+)?\s*(?:[—–-]\s*)?.+$", re.IGNORECASE)
ISSUE_HEADING_RE = re.compile(
    r"^(?P<identifier>[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)+)\s+[—–-]\s+(?P<title>.+?)\s*$"
)
REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
BACKLOG_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")
LABELS_RE = re.compile(r"^Labels:\s*(.*?)\s*$", re.IGNORECASE)
MAX_GITHUB_LABEL_LENGTH = 50
DEFAULT_PROJECT_WORKFLOW = ("Backlog", "Ready", "In Progress", "Review", "Done")

REQUIRED_ISSUE_SECTIONS = (
    "Purpose",
    "Background",
    "Acceptance criteria",
    "Out of scope",
    "Dependencies",
    "Backend work",
    "Frontend work",
    "API work",
    "Migration work",
    "Testing requirements",
    "Estimated implementation size",
)


class CreateIssuesError(RuntimeError):
    """Base class for expected, user-actionable utility failures."""


class BacklogFormatError(CreateIssuesError):
    """Raised when the Markdown backlog does not satisfy the input contract."""


class StateFileError(CreateIssuesError):
    """Raised when persisted state is invalid or belongs to another backlog."""


class GitHubCliError(CreateIssuesError):
    """Raised when ``gh`` is unavailable or returns an unsuccessful result."""


@dataclass(frozen=True)
class IssueSpec:
    """One child issue parsed from the backlog."""

    identifier: str
    title: str
    milestone: str
    body: str
    labels: tuple[str, ...] = ()

    @property
    def github_title(self) -> str:
        """Return the complete GitHub title, including the stable backlog ID."""

        return f"{self.identifier} — {self.title}"

    @property
    def body_hash(self) -> str:
        """Return a stable digest used to report source drift on reruns."""

        return sha256_text(self.body)


@dataclass(frozen=True)
class BacklogSpec:
    """The Epic title, introductory text, milestones, and child issues."""

    title: str
    intro: str
    issues: tuple[IssueSpec, ...]
    labels: tuple[str, ...] = ()

    @property
    def milestones(self) -> tuple[str, ...]:
        """Return milestone names in their first-seen source order."""

        return tuple(dict.fromkeys(issue.milestone for issue in self.issues))


@dataclass(frozen=True)
class RemoteIssue:
    """Minimal GitHub issue metadata used for reconciliation."""

    number: int
    title: str
    url: str
    body: str
    state: str
    labels: tuple[str, ...] = ()
    milestone: Optional[str] = None


@dataclass(frozen=True)
class MilestoneRecord:
    """Repository milestone metadata required for assignment and Epic links."""

    number: int
    title: str
    url: str
    state: str


@dataclass(frozen=True)
class ProjectRecord:
    """GitHub Project metadata required for idempotent item management."""

    number: int
    node_id: str
    title: str
    url: str
    closed: bool = False


@dataclass(frozen=True)
class ProjectOption:
    """One single-select option in a GitHub Project field."""

    option_id: str
    name: str


@dataclass(frozen=True)
class ProjectField:
    """One GitHub Project field and any single-select options it exposes."""

    field_id: str
    name: str
    data_type: str
    options: tuple[ProjectOption, ...] = ()


@dataclass(frozen=True)
class ProjectItem:
    """A GitHub issue or pull request already attached to a Project."""

    item_id: str
    content_url: str


@dataclass(frozen=True)
class RepositoryDetails:
    """Repository identity used to construct stable source-document links."""

    name_with_owner: str
    url: str
    default_branch: str


@dataclass(frozen=True)
class PlanningDocument:
    """A source planning document displayed in generated Epic metadata."""

    label: str
    url: str


def sha256_text(value: str) -> str:
    """Return the hexadecimal SHA-256 digest of UTF-8 text."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_markdown(lines: Iterable[str]) -> str:
    """Trim surrounding blank lines and return newline-terminated Markdown."""

    values = list(lines)
    while values and not values[0].strip():
        values.pop(0)
    while values and not values[-1].strip():
        values.pop()
    return "\n".join(values) + ("\n" if values else "")


def extract_labels(
    lines: Iterable[str], *, context: str, metadata_only: bool
) -> tuple[list[str], tuple[str, ...]]:
    """Extract optional comma-separated ``Labels:`` metadata from Markdown.

    Child issue labels are recognized only before the first level-three section,
    which prevents prose examples inside acceptance criteria from becoming
    metadata. Epic labels may occur anywhere in the pre-milestone introduction.
    The metadata line is removed from the body sent to GitHub.
    """

    body: list[str] = []
    labels: list[str] = []
    labels_by_folded_name: dict[str, str] = {}
    metadata_open = True
    for line in lines:
        if metadata_only and (H2_RE.fullmatch(line) or H3_RE.fullmatch(line)):
            metadata_open = False
        match = LABELS_RE.fullmatch(line) if (metadata_open or not metadata_only) else None
        if not match:
            body.append(line)
            continue
        values = [value.strip() for value in match.group(1).split(",")]
        if not values or any(not value for value in values):
            raise BacklogFormatError(f"{context} contains an empty label name.")
        for value in values:
            if len(value) > MAX_GITHUB_LABEL_LENGTH:
                raise BacklogFormatError(
                    f"{context} label {value!r} exceeds {MAX_GITHUB_LABEL_LENGTH} characters."
                )
            folded = value.casefold()
            if folded not in labels_by_folded_name:
                labels_by_folded_name[folded] = value
                labels.append(value)
    return body, tuple(labels)


def parse_backlog(text: str) -> BacklogSpec:
    """Parse and validate a structured implementation backlog.

    Expected source shape::

        # Epic title
        # Milestone 1 — Foundation
        ## ABC-01 — Child issue title
        ### Purpose
        ...

    Child bodies may contain arbitrary Markdown below their level-two heading,
    but all required level-three sections must be present and non-empty. Content
    after a milestone ends is ignored until another milestone begins, allowing a
    backlog to contain ordering and traceability appendices.

    Args:
        text: Complete UTF-8 Markdown source.

    Returns:
        A validated :class:`BacklogSpec`.

    Raises:
        BacklogFormatError: If headings, identifiers, or required sections are
            missing, duplicated, or ambiguous.
    """

    lines = text.splitlines()
    title_index = next(
        (index for index, line in enumerate(lines) if H1_RE.fullmatch(line)),
        None,
    )
    if title_index is None:
        raise BacklogFormatError("Backlog must contain a level-one Epic title.")
    title_match = H1_RE.fullmatch(lines[title_index])
    assert title_match is not None
    epic_title = title_match.group(1).strip()
    validate_title(epic_title, "Epic")

    first_milestone_index = next(
        (
            index
            for index in range(title_index + 1, len(lines))
            if (match := H1_RE.fullmatch(lines[index]))
            and MILESTONE_RE.fullmatch(match.group(1).strip())
        ),
        None,
    )
    if first_milestone_index is None:
        raise BacklogFormatError("Backlog must contain at least one '# Milestone …' section.")
    intro_lines, epic_labels = extract_labels(
        lines[title_index + 1 : first_milestone_index],
        context="Epic",
        metadata_only=True,
    )
    intro = normalize_markdown(intro_lines)

    issues: list[IssueSpec] = []
    identifiers: set[str] = set()
    current_milestone: Optional[str] = None
    current_heading: Optional[Tuple[str, str]] = None
    current_body: list[str] = []

    def finish_issue() -> None:
        """Validate and append the issue currently accumulated by the parser."""

        nonlocal current_heading, current_body
        if current_heading is None:
            return
        assert current_milestone is not None
        identifier, issue_title = current_heading
        body_lines, labels = extract_labels(
            current_body,
            context=f"Issue {identifier}",
            metadata_only=True,
        )
        body = normalize_markdown(body_lines)
        validate_issue_body(identifier, body)
        issue = IssueSpec(identifier, issue_title, current_milestone, body, labels)
        validate_title(issue.github_title, f"Issue {identifier}")
        if identifier in identifiers:
            raise BacklogFormatError(f"Duplicate issue identifier: {identifier}")
        identifiers.add(identifier)
        issues.append(issue)
        current_heading = None
        current_body = []

    for line_number, line in enumerate(
        lines[first_milestone_index:], start=first_milestone_index + 1
    ):
        h1 = H1_RE.fullmatch(line)
        if h1:
            finish_issue()
            heading = h1.group(1).strip()
            current_milestone = heading if MILESTONE_RE.fullmatch(heading) else None
            continue

        h2 = H2_RE.fullmatch(line)
        if h2:
            issue_heading = ISSUE_HEADING_RE.fullmatch(h2.group(1).strip())
            if issue_heading:
                if current_milestone is None:
                    raise BacklogFormatError(
                        f"Line {line_number}: issue is not inside a Milestone section."
                    )
                finish_issue()
                current_heading = (
                    issue_heading.group("identifier"),
                    issue_heading.group("title").strip(),
                )
                continue
            if current_heading is not None:
                raise BacklogFormatError(
                    f"Line {line_number}: child issue subsections must use level-three headings."
                )

        if current_heading is not None:
            current_body.append(line)

    finish_issue()
    if not issues:
        raise BacklogFormatError("Backlog contains no child issue headings.")

    return BacklogSpec(epic_title, intro, tuple(issues), epic_labels)


def validate_title(title: str, kind: str) -> None:
    """Validate a title against GitHub's practical title constraints."""

    if not title:
        raise BacklogFormatError(f"{kind} title must not be empty.")
    if len(title) > MAX_GITHUB_TITLE_LENGTH:
        raise BacklogFormatError(
            f"{kind} title is {len(title)} characters; maximum is {MAX_GITHUB_TITLE_LENGTH}."
        )


def validate_issue_body(identifier: str, body: str) -> None:
    """Require the reusable implementation-issue template and non-empty sections."""

    if not body:
        raise BacklogFormatError(f"Issue {identifier} has an empty body.")
    headings: list[tuple[str, int]] = []
    lines = body.splitlines()
    for index, line in enumerate(lines):
        match = H3_RE.fullmatch(line)
        if match:
            headings.append((match.group(1).strip(), index))

    by_name = {name.casefold(): (name, index) for name, index in headings}
    for required in REQUIRED_ISSUE_SECTIONS:
        found = by_name.get(required.casefold())
        if found is None:
            raise BacklogFormatError(f"Issue {identifier} is missing '### {required}'.")
        _, start = found
        next_heading = next((index for _, index in headings if index > start), len(lines))
        if not any(line.strip() for line in lines[start + 1 : next_heading]):
            raise BacklogFormatError(
                f"Issue {identifier} has an empty '### {required}' section."
            )


def default_backlog_key(epic_title: str) -> str:
    """Derive a readable, stable idempotency namespace from the Epic title."""

    slug = re.sub(r"[^a-z0-9]+", "-", epic_title.casefold()).strip("-")[:48]
    digest = sha256_text(epic_title)[:12]
    return f"{slug or 'epic'}-{digest}"


def validate_backlog_key(value: str) -> str:
    """Validate a user-supplied marker namespace for safe HTML embedding."""

    if not BACKLOG_KEY_RE.fullmatch(value):
        raise CreateIssuesError(
            "--key may contain only ASCII letters, numbers, period, underscore, and hyphen."
        )
    return value


def epic_marker(backlog_key: str) -> str:
    """Return the hidden ownership marker for the Epic issue."""

    return f"<!-- create-issues:key:{backlog_key}:kind:epic -->"


def child_marker(backlog_key: str, identifier: str) -> str:
    """Return the hidden ownership marker for one child issue."""

    return f"<!-- create-issues:key:{backlog_key}:child:{identifier} -->"


def build_child_body(issue: IssueSpec, backlog_key: str) -> str:
    """Build a child body without changing the source issue requirements."""

    body = (
        f"{child_marker(backlog_key, issue.identifier)}\n\n"
        f"> Milestone: {issue.milestone}\n\n"
        f"{issue.body.rstrip()}\n"
    )
    validate_body_length(body, issue.github_title)
    return body


def build_checklist(
    backlog: BacklogSpec,
    records: Mapping[str, RemoteIssue],
    milestones: Optional[Mapping[str, MilestoneRecord]] = None,
) -> str:
    """Build the linked child checklist, reflecting authoritative issue state."""

    lines = ["### Implementation checklist", ""]
    for milestone in backlog.milestones:
        milestone_record = (milestones or {}).get(milestone)
        heading = (
            f"#### [{milestone}]({milestone_record.url})"
            if milestone_record
            else f"#### {milestone}"
        )
        lines.extend((heading, ""))
        for issue in (item for item in backlog.issues if item.milestone == milestone):
            record = records.get(issue.identifier)
            if record is None:
                raise StateFileError(
                    f"Cannot build Epic checklist: {issue.identifier} has no GitHub issue."
                )
            check = "x" if record.state.casefold() == "closed" else " "
            lines.append(
                f"- [{check}] [#{record.number} — {issue.github_title}]({record.url})"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def epic_purpose(backlog: BacklogSpec) -> str:
    """Return an explicit Epic purpose or a stable implementation default."""

    lines = backlog.intro.splitlines()
    purpose_start = None
    for index, line in enumerate(lines):
        match = H2_RE.fullmatch(line)
        if match and match.group(1).strip().casefold() == "purpose":
            purpose_start = index
            break
    if purpose_start is not None:
        collected: list[str] = []
        for line in lines[purpose_start + 1 :]:
            if H2_RE.fullmatch(line):
                break
            collected.append(line)
        purpose = normalize_markdown(collected).strip()
        if purpose:
            return purpose
    return (
        "Deliver the approved implementation backlog through reviewable GitHub issues while "
        "preserving the linked product and architecture requirements."
    )


def build_generated_epic_section(
    backlog: BacklogSpec,
    records: Mapping[str, RemoteIssue],
    milestones: Mapping[str, MilestoneRecord],
    planning_documents: Sequence[PlanningDocument],
    project: Optional[ProjectRecord],
) -> str:
    """Build all utility-owned Epic metadata and the generated checklist."""

    closed_count = sum(
        1 for issue in backlog.issues if records[issue.identifier].state.casefold() == "closed"
    )
    total_count = len(backlog.issues)
    percent = round((closed_count / total_count) * 100) if total_count else 0
    lines = [
        MANAGED_CHECKLIST_START,
        "## Generated Epic metadata",
        "",
        "> This section is maintained by `scripts/github/create_issues.py`. "
        "Manual content outside it is preserved.",
        "",
        "### Purpose",
        "",
        epic_purpose(backlog),
        "",
        "### Milestone summary",
        "",
    ]
    for milestone in backlog.milestones:
        milestone_issues = [issue for issue in backlog.issues if issue.milestone == milestone]
        milestone_closed = sum(
            1
            for issue in milestone_issues
            if records[issue.identifier].state.casefold() == "closed"
        )
        milestone_record = milestones[milestone]
        lines.append(
            f"- [{milestone}]({milestone_record.url}): "
            f"{milestone_closed}/{len(milestone_issues)} complete"
        )
    lines.extend(
        (
            "",
            "### Progress summary",
            "",
            f"**{closed_count} of {total_count} issues complete ({percent}%).**",
            "",
            f"- Open: {total_count - closed_count}",
            f"- Closed: {closed_count}",
        )
    )
    if project is not None:
        lines.extend(("", f"- Project: [{project.title}]({project.url})"))
    lines.extend(("", "### Source planning documents", ""))
    if planning_documents:
        lines.extend(f"- [{document.label}]({document.url})" for document in planning_documents)
    else:
        lines.append("- Source planning documents were not discoverable from this checkout.")
    lines.extend(("", build_checklist(backlog, records, milestones), "", MANAGED_CHECKLIST_END))
    return "\n".join(lines)


def build_initial_epic_body(backlog: BacklogSpec, backlog_key: str) -> str:
    """Build the initial Epic body with a generated-section placeholder."""

    parts = [
        epic_marker(backlog_key),
        "",
        "> Managed by `scripts/github/create_issues.py`. "
        "Text outside the generated section is preserved on reruns.",
    ]
    if backlog.intro:
        parts.extend(("", backlog.intro.rstrip()))
    parts.extend(
        (
            "",
            MANAGED_CHECKLIST_START,
            "## Generated Epic metadata",
            "",
            "Child issues and repository metadata are being reconciled. Rerun the utility "
            "to complete this section after an interruption.",
            MANAGED_CHECKLIST_END,
            "",
        )
    )
    body = "\n".join(parts)
    validate_body_length(body, backlog.title)
    return body


def replace_managed_checklist(existing_body: str, generated_section: str) -> str:
    """Replace only the utility-owned generated block in an Epic body.

    If the block is absent, it is appended. A partially removed or duplicated
    marker is treated as an error so the utility cannot overwrite ambiguous
    human-authored content.
    """

    starts = [
        match.start()
        for match in re.finditer(re.escape(MANAGED_CHECKLIST_START), existing_body)
    ]
    ends = [match.end() for match in re.finditer(re.escape(MANAGED_CHECKLIST_END), existing_body)]
    if not starts and not ends:
        return existing_body.rstrip() + "\n\n" + generated_section + "\n"
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise StateFileError(
            "Epic body has missing, duplicated, or misordered managed checklist markers."
        )
    return existing_body[: starts[0]] + generated_section + existing_body[ends[0] :]


def validate_body_length(body: str, title: str) -> None:
    """Fail before invoking GitHub when a generated body is too large."""

    if len(body) > MAX_GITHUB_BODY_LENGTH:
        raise CreateIssuesError(
            f"Generated body for '{title}' is {len(body)} characters; "
            f"maximum is {MAX_GITHUB_BODY_LENGTH}."
        )


class GitHubCli:
    """Small, injectable wrapper around the GitHub CLI."""

    def __init__(self, cwd: Path) -> None:
        """Bind GitHub CLI calls to a checkout directory and verify availability."""

        self.cwd = cwd
        if shutil.which("gh") is None:
            raise GitHubCliError(
                "GitHub CLI 'gh' was not found. Install it and run 'gh auth login'."
            )

    def run(self, arguments: Sequence[str], *, input_text: Optional[str] = None) -> str:
        """Run ``gh`` without a shell and return stripped stdout."""

        command = ["gh", *arguments]
        try:
            result = subprocess.run(
                command,
                cwd=self.cwd,
                input=input_text,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubCliError(f"Could not execute gh: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise GitHubCliError(f"gh {' '.join(arguments)} failed: {detail}")
        return result.stdout.strip()

    def repository(self) -> str:
        """Resolve the current repository as ``OWNER/REPO``."""

        output = self.run(["repo", "view", "--json", "nameWithOwner"])
        try:
            value = json.loads(output)["nameWithOwner"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise GitHubCliError("gh returned an invalid repository response.") from exc
        return validate_repository(str(value))

    def repository_details(self, repository: str) -> RepositoryDetails:
        """Read repository URL and default branch for source-document links."""

        output = self.run(
            [
                "repo",
                "view",
                repository,
                "--json",
                "nameWithOwner,url,defaultBranchRef",
            ]
        )
        try:
            item = json.loads(output)
            default_branch = item["defaultBranchRef"]["name"]
            return RepositoryDetails(
                validate_repository(str(item["nameWithOwner"])),
                str(item["url"]),
                str(default_branch),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise GitHubCliError("gh returned invalid repository details.") from exc

    def list_issues(self, repository: str) -> list[RemoteIssue]:
        """List all repository issues, excluding pull requests.

        ``gh api --paginate --slurp`` is used instead of search because GitHub's
        search index may lag immediately after issue creation. Exact body markers
        are therefore available for crash recovery as soon as GitHub returns.
        """

        output = self.run(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repository}/issues?state=all&per_page=100",
            ]
        )
        try:
            pages = json.loads(output)
        except json.JSONDecodeError as exc:
            raise GitHubCliError("gh returned invalid JSON while listing issues.") from exc
        if not isinstance(pages, list):
            raise GitHubCliError("gh returned an unexpected issue-list response.")
        raw_issues: list[dict[str, Any]] = []
        for page in pages:
            if isinstance(page, list):
                raw_issues.extend(item for item in page if isinstance(item, dict))
            elif isinstance(page, dict):
                raw_issues.append(page)
        records: list[RemoteIssue] = []
        for item in raw_issues:
            if "pull_request" in item:
                continue
            try:
                records.append(
                    RemoteIssue(
                        number=int(item["number"]),
                        title=str(item["title"]),
                        url=str(item["html_url"]),
                        body=str(item.get("body") or ""),
                        state=str(item.get("state") or "unknown"),
                        labels=tuple(
                            str(label["name"])
                            for label in item.get("labels") or []
                            if isinstance(label, dict) and label.get("name")
                        ),
                        milestone=(
                            str(item["milestone"]["title"])
                            if isinstance(item.get("milestone"), dict)
                            and item["milestone"].get("title")
                            else None
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise GitHubCliError("gh returned malformed issue metadata.") from exc
        return records

    def create_issue(
        self,
        repository: str,
        title: str,
        body: str,
        *,
        labels: Sequence[str] = (),
        milestone: Optional[str] = None,
    ) -> RemoteIssue:
        """Create one issue and parse the resulting issue URL."""

        arguments = [
            "issue",
            "create",
            "--repo",
            repository,
            "--title",
            title,
            "--body-file",
            "-",
        ]
        for label in labels:
            arguments.extend(("--label", label))
        if milestone:
            arguments.extend(("--milestone", milestone))
        output = self.run(arguments, input_text=body)
        match = next(
            (
                candidate
                for line in reversed(output.splitlines())
                if (candidate := re.search(r"https?://\S+/issues/(\d+)(?:\?\S*)?$", line.strip()))
            ),
            None,
        )
        if match is None:
            raise GitHubCliError(f"Could not parse created issue URL from gh output: {output!r}")
        url = match.group(0)
        return RemoteIssue(
            int(match.group(1)), title, url, body, "open", tuple(labels), milestone
        )

    def read_issue(self, repository: str, number: int) -> RemoteIssue:
        """Read current issue metadata before updating managed Epic content."""

        output = self.run(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                repository,
                "--json",
                "number,title,url,body,state,labels,milestone",
            ]
        )
        try:
            item = json.loads(output)
            return RemoteIssue(
                number=int(item["number"]),
                title=str(item["title"]),
                url=str(item["url"]),
                body=str(item.get("body") or ""),
                state=str(item.get("state") or "unknown"),
                labels=tuple(
                    str(label["name"])
                    for label in item.get("labels") or []
                    if isinstance(label, dict) and label.get("name")
                ),
                milestone=(
                    str(item["milestone"]["title"])
                    if isinstance(item.get("milestone"), dict)
                    and item["milestone"].get("title")
                    else None
                ),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise GitHubCliError("gh returned malformed issue metadata.") from exc

    def update_issue_body(self, repository: str, number: int, body: str) -> None:
        """Update an issue body using stdin to avoid shell quoting and size limits."""

        self.run(
            [
                "issue",
                "edit",
                str(number),
                "--repo",
                repository,
                "--body-file",
                "-",
            ],
            input_text=body,
        )

    def update_issue_metadata(
        self,
        repository: str,
        number: int,
        *,
        labels: Sequence[str],
        milestone: Optional[str],
    ) -> None:
        """Add missing labels and set a milestone without removing manual metadata."""

        arguments = ["issue", "edit", str(number), "--repo", repository]
        for label in labels:
            arguments.extend(("--add-label", label))
        if milestone:
            arguments.extend(("--milestone", milestone))
        if len(arguments) > 5:
            self.run(arguments)

    def list_labels(self, repository: str) -> tuple[str, ...]:
        """List every repository label name."""

        output = self.run(
            [
                "label",
                "list",
                "--repo",
                repository,
                "--limit",
                "1000",
                "--json",
                "name",
            ]
        )
        try:
            items = json.loads(output)
            return tuple(str(item["name"]) for item in items if item.get("name"))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise GitHubCliError("gh returned invalid label metadata.") from exc

    def create_label(self, repository: str, name: str) -> None:
        """Create a deterministic label without overwriting an existing label."""

        color = sha256_text(name.casefold())[:6].upper()
        self.run(
            [
                "label",
                "create",
                name,
                "--repo",
                repository,
                "--color",
                color,
                "--description",
                "Created from implementation backlog metadata.",
            ]
        )

    def list_milestones(self, repository: str) -> tuple[MilestoneRecord, ...]:
        """List open and closed repository milestones without search-index delay."""

        output = self.run(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repository}/milestones?state=all&per_page=100",
            ]
        )
        try:
            pages = json.loads(output)
            raw_items = [
                item
                for page in pages
                for item in (page if isinstance(page, list) else [page])
                if isinstance(item, dict)
            ]
            return tuple(
                MilestoneRecord(
                    int(item["number"]),
                    str(item["title"]),
                    str(item["html_url"]),
                    str(item.get("state") or "unknown"),
                )
                for item in raw_items
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise GitHubCliError("gh returned invalid milestone metadata.") from exc

    def create_milestone(self, repository: str, title: str) -> MilestoneRecord:
        """Create one GitHub milestone and return its authoritative metadata."""

        output = self.run(
            [
                "api",
                "--method",
                "POST",
                f"repos/{repository}/milestones",
                "-f",
                f"title={title}",
                "-f",
                "description=Created from a structured implementation backlog.",
            ]
        )
        try:
            item = json.loads(output)
            return MilestoneRecord(
                int(item["number"]),
                str(item["title"]),
                str(item["html_url"]),
                str(item.get("state") or "open"),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise GitHubCliError("gh returned invalid created-milestone metadata.") from exc

    def list_projects(self, owner: str) -> tuple[ProjectRecord, ...]:
        """List all open and closed Projects owned by a user or organization."""

        output = self.run(
            [
                "project",
                "list",
                "--owner",
                owner,
                "--closed",
                "--limit",
                "1000",
                "--format",
                "json",
            ]
        )
        try:
            payload = json.loads(output)
            items = payload.get("projects", payload) if isinstance(payload, dict) else payload
            return tuple(parse_project(item) for item in items)
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
            raise GitHubCliError("gh returned invalid Project metadata.") from exc

    def create_project(self, owner: str, title: str) -> ProjectRecord:
        """Create one owner-level GitHub Project."""

        output = self.run(
            [
                "project",
                "create",
                "--owner",
                owner,
                "--title",
                title,
                "--format",
                "json",
            ]
        )
        try:
            return parse_project(json.loads(output))
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
            raise GitHubCliError("gh returned invalid created-Project metadata.") from exc

    def list_project_fields(self, owner: str, project: ProjectRecord) -> tuple[ProjectField, ...]:
        """List fields and single-select options for one Project."""

        output = self.run(
            [
                "project",
                "field-list",
                str(project.number),
                "--owner",
                owner,
                "--limit",
                "100",
                "--format",
                "json",
            ]
        )
        try:
            payload = json.loads(output)
            items = payload.get("fields", payload) if isinstance(payload, dict) else payload
            return tuple(
                ProjectField(
                    str(item["id"]),
                    str(item["name"]),
                    str(item.get("type") or item.get("dataType") or ""),
                    tuple(
                        ProjectOption(str(option["id"]), str(option["name"]))
                        for option in item.get("options") or []
                    ),
                )
                for item in items
            )
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
            raise GitHubCliError("gh returned invalid Project field metadata.") from exc

    def set_project_workflow(self, status_field_id: str) -> None:
        """Replace a newly created Project's Status options with the default workflow."""

        colors = ("GRAY", "BLUE", "YELLOW", "PURPLE", "GREEN")
        descriptions = (
            "Work captured but not yet ready to start.",
            "Work ready for implementation.",
            "Work currently being implemented.",
            "Work awaiting review.",
            "Completed work.",
        )
        query = """
mutation($input: UpdateProjectV2FieldInput!) {
  updateProjectV2Field(input: $input) {
    projectV2Field { ... on ProjectV2SingleSelectField { id name } }
  }
}
""".strip()
        payload = {
            "query": query,
            "variables": {
                "input": {
                    "fieldId": status_field_id,
                    "singleSelectOptions": [
                        {"name": name, "color": color, "description": description}
                        for name, color, description in zip(
                            DEFAULT_PROJECT_WORKFLOW, colors, descriptions
                        )
                    ],
                }
            },
        }
        self.run(["api", "graphql", "--input", "-"], input_text=json.dumps(payload))

    def list_project_items(self, owner: str, project: ProjectRecord) -> tuple[ProjectItem, ...]:
        """List issue-backed items currently present in a Project."""

        output = self.run(
            [
                "project",
                "item-list",
                str(project.number),
                "--owner",
                owner,
                "--limit",
                "1000",
                "--format",
                "json",
            ]
        )
        try:
            payload = json.loads(output)
            items = payload.get("items", payload) if isinstance(payload, dict) else payload
            records = []
            for item in items:
                content = item.get("content") or {}
                url = content.get("url") or item.get("url")
                if item.get("id") and url:
                    records.append(ProjectItem(str(item["id"]), str(url)))
            return tuple(records)
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
            raise GitHubCliError("gh returned invalid Project item metadata.") from exc

    def add_project_item(
        self, owner: str, project: ProjectRecord, issue_url: str
    ) -> ProjectItem:
        """Add an issue to a Project and return the new Project item identity."""

        output = self.run(
            [
                "project",
                "item-add",
                str(project.number),
                "--owner",
                owner,
                "--url",
                issue_url,
                "--format",
                "json",
            ]
        )
        try:
            item = json.loads(output)
            return ProjectItem(str(item["id"]), issue_url)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise GitHubCliError("gh returned invalid added-Project-item metadata.") from exc

    def set_project_item_status(
        self,
        project: ProjectRecord,
        item: ProjectItem,
        status_field: ProjectField,
        option: ProjectOption,
    ) -> None:
        """Set a newly added Project item to the Backlog workflow state."""

        self.run(
            [
                "project",
                "item-edit",
                "--id",
                item.item_id,
                "--project-id",
                project.node_id,
                "--field-id",
                status_field.field_id,
                "--single-select-option-id",
                option.option_id,
            ]
        )


def validate_repository(value: str) -> str:
    """Validate and return an ``OWNER/REPO`` repository name."""

    if not REPOSITORY_RE.fullmatch(value):
        raise CreateIssuesError(f"Invalid GitHub repository '{value}'; expected OWNER/REPO.")
    return value


def parse_project(item: Mapping[str, Any]) -> ProjectRecord:
    """Normalize the JSON shapes returned by ``gh project`` commands."""

    number = int(item["number"])
    node_id = str(item.get("id") or item.get("nodeId") or "")
    title = str(item["title"])
    url = str(item["url"])
    if not node_id:
        raise ValueError("Project response has no GraphQL node ID")
    state = str(item.get("state") or "").casefold()
    closed = bool(item.get("closed")) or state == "closed"
    return ProjectRecord(number, node_id, title, url, closed)


def unique_label_names(backlog: BacklogSpec) -> tuple[str, ...]:
    """Return every requested Epic and child label once, case-insensitively."""

    names: dict[str, str] = {}
    for label in (*backlog.labels, *(label for issue in backlog.issues for label in issue.labels)):
        names.setdefault(label.casefold(), label)
    return tuple(names.values())


def ensure_labels(
    gh: GitHubCli, repository: str, requested: Sequence[str]
) -> dict[str, str]:
    """Create missing labels and return requested names keyed case-insensitively."""

    if not requested:
        return {}
    existing = {name.casefold(): name for name in gh.list_labels(repository)}
    resolved: dict[str, str] = {}
    for requested_name in requested:
        folded = requested_name.casefold()
        if folded not in existing:
            try:
                gh.create_label(repository, requested_name)
            except GitHubCliError:
                # A concurrent run may have created the label after our list.
                refreshed = {name.casefold(): name for name in gh.list_labels(repository)}
                if folded not in refreshed:
                    raise
                existing.update(refreshed)
            else:
                existing[folded] = requested_name
                print(f"Created label: {requested_name}")
        resolved[folded] = existing[folded]
    return resolved


def ensure_milestones(
    gh: GitHubCli, repository: str, titles: Sequence[str]
) -> dict[str, MilestoneRecord]:
    """Create or reuse every source milestone, failing on ambiguous duplicates."""

    existing: dict[str, list[MilestoneRecord]] = {}
    for milestone in gh.list_milestones(repository):
        existing.setdefault(milestone.title.casefold(), []).append(milestone)
    resolved: dict[str, MilestoneRecord] = {}
    for title in titles:
        folded = title.casefold()
        matches = existing.get(folded, [])
        if len(matches) > 1:
            numbers = ", ".join(f"#{item.number}" for item in matches)
            raise StateFileError(
                f"Multiple GitHub milestones match {title!r} ({numbers}); refusing to choose."
            )
        if matches:
            resolved[title] = matches[0]
            continue
        try:
            milestone = gh.create_milestone(repository, title)
        except GitHubCliError:
            # Recover the common concurrent-creator race without hiding other
            # failures such as authorization or validation errors.
            refreshed = [
                item
                for item in gh.list_milestones(repository)
                if item.title.casefold() == folded
            ]
            if len(refreshed) != 1:
                raise
            milestone = refreshed[0]
        existing[folded] = [milestone]
        resolved[title] = milestone
        print(f"Created milestone: {title}")
    return resolved


def ensure_project(
    gh: GitHubCli, owner: str, title: str
) -> tuple[ProjectRecord, bool]:
    """Create or uniquely reuse an owner-level GitHub Project by title."""

    matches = [
        project
        for project in gh.list_projects(owner)
        if project.title.casefold() == title.casefold()
    ]
    if len(matches) > 1:
        numbers = ", ".join(f"#{item.number}" for item in matches)
        raise StateFileError(
            f"Multiple GitHub Projects match {title!r} ({numbers}); refusing to choose."
        )
    if matches:
        project = matches[0]
        if project.closed:
            raise StateFileError(
                f"GitHub Project {title!r} exists but is closed; reopen it before rerunning."
            )
        return project, False
    try:
        project = gh.create_project(owner, title)
    except GitHubCliError:
        refreshed = [
            item
            for item in gh.list_projects(owner)
            if item.title.casefold() == title.casefold()
        ]
        if len(refreshed) != 1:
            raise
        return refreshed[0], False
    print(f"Created GitHub Project: {project.title} ({project.url})")
    return project, True


def project_state_entry(
    project: ProjectRecord,
    *,
    owner: str,
    created_by_tool: bool,
    workflow_initialized: bool,
) -> dict[str, Any]:
    """Serialize Project identity and initialization ownership to local state."""

    return {
        "owner": owner,
        "number": project.number,
        "id": project.node_id,
        "title": project.title,
        "url": project.url,
        "created_by_tool": created_by_tool,
        "workflow_initialized": workflow_initialized,
    }


def initialize_project_workflow(
    gh: GitHubCli,
    owner: str,
    project: ProjectRecord,
    *,
    may_modify: bool,
) -> tuple[Optional[ProjectField], Optional[ProjectOption], bool]:
    """Initialize a new Project's workflow without changing customized Projects.

    Only Projects created by this utility and not yet marked initialized may be
    modified. Existing Projects are inspected so a pre-existing Backlog option
    can be used for new items, but their fields and options are never changed.
    """

    fields = gh.list_project_fields(owner, project)
    status_fields = [field for field in fields if field.name.casefold() == "status"]
    if len(status_fields) > 1:
        raise StateFileError(
            f"Project {project.title!r} has multiple Status fields; refusing to choose."
        )
    if not status_fields:
        if may_modify:
            raise StateFileError(
                f"New Project {project.title!r} has no Status field to initialize."
            )
        return None, None, False
    status = status_fields[0]
    option_names = tuple(option.name for option in status.options)
    initialized = option_names == DEFAULT_PROJECT_WORKFLOW
    if may_modify and not initialized:
        default_options = ("Todo", "In Progress", "Done")
        if option_names != default_options:
            print(
                f"Preserving customized workflow in Project {project.title!r}.",
                file=sys.stderr,
            )
            backlog_option = next(
                (option for option in status.options if option.name.casefold() == "backlog"),
                None,
            )
            return status, backlog_option, True
        gh.set_project_workflow(status.field_id)
        fields = gh.list_project_fields(owner, project)
        status_fields = [field for field in fields if field.name.casefold() == "status"]
        if len(status_fields) != 1:
            raise StateFileError("Project Status field could not be verified after initialization.")
        status = status_fields[0]
        option_names = tuple(option.name for option in status.options)
        if option_names != DEFAULT_PROJECT_WORKFLOW:
            raise StateFileError(
                "Project workflow initialization did not produce the expected Status options."
            )
        initialized = True
        print(f"Initialized Project workflow: {', '.join(DEFAULT_PROJECT_WORKFLOW)}")
    backlog_option = next(
        (option for option in status.options if option.name.casefold() == "backlog"),
        None,
    )
    return status, backlog_option, initialized


def ensure_project_items(
    gh: GitHubCli,
    owner: str,
    project: ProjectRecord,
    issues: Sequence[RemoteIssue],
    status_field: Optional[ProjectField],
    backlog_option: Optional[ProjectOption],
) -> None:
    """Add missing issues to a Project and initialize only newly added items."""

    items_by_url = {
        item.content_url.rstrip("/"): item for item in gh.list_project_items(owner, project)
    }
    for issue in issues:
        normalized_url = issue.url.rstrip("/")
        if normalized_url in items_by_url:
            continue
        try:
            item = gh.add_project_item(owner, project, issue.url)
        except GitHubCliError:
            refreshed = {
                value.content_url.rstrip("/"): value
                for value in gh.list_project_items(owner, project)
            }
            if normalized_url not in refreshed:
                raise
            item = refreshed[normalized_url]
        else:
            print(f"Added issue #{issue.number} to Project {project.title!r}.")
        items_by_url[normalized_url] = item
        if status_field is not None and backlog_option is not None:
            gh.set_project_item_status(project, item, status_field, backlog_option)


def repository_root(source: Path) -> Path:
    """Resolve the checkout root used for repository-relative planning links."""

    result = subprocess.run(
        ["git", "-C", str(source.parent), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise CreateIssuesError(
            "Backlog must be inside a Git checkout to generate source planning links."
        )
    return Path(result.stdout.strip()).resolve()


def discover_planning_documents(
    source: Path, root: Path, repository: RepositoryDetails
) -> tuple[PlanningDocument, ...]:
    """Discover nearby planning artifacts and build default-branch GitHub links."""

    try:
        source.relative_to(root)
    except ValueError as exc:
        raise CreateIssuesError("Backlog is outside the resolved Git checkout.") from exc
    roles = (
        ("Roadmap", ("roadmap",)),
        ("Grill record", ("grill",)),
        ("Feature PRD", ("feature-prd", "feature_prd")),
        ("Architecture Review", ("architecture-review", "architecture_review")),
        ("Implementation Backlog", ("implementation-backlog", "implementation_backlog")),
    )
    directories: list[Path] = []
    current = source.parent
    while True:
        directories.append(current)
        if current == root:
            break
        if root not in current.parents:
            break
        current = current.parent
    candidates = sorted(
        {path.resolve() for directory in directories for path in directory.glob("*.md")}
    )
    selected: list[tuple[str, Path]] = []
    for label, fragments in roles:
        matches = [
            path
            for path in candidates
            if any(fragment in path.stem.casefold() for fragment in fragments)
        ]
        if label == "Implementation Backlog" and source.resolve() not in matches:
            matches.insert(0, source.resolve())
        if matches:
            matches.sort(
                key=lambda path: (
                    directories.index(path.parent),
                    str(path),
                )
            )
            selected.append((label, matches[0]))
    if not any(path == source.resolve() for _, path in selected):
        selected.append(("Implementation Backlog", source.resolve()))
    documents = []
    for label, path in selected:
        relative = path.relative_to(root).as_posix()
        url = (
            f"{repository.url}/blob/{quote(repository.default_branch, safe='')}/"
            f"{quote(relative, safe='/')}"
        )
        documents.append(PlanningDocument(label, url))
    return tuple(documents)


def default_state_file(source: Path) -> Path:
    """Return the default hidden state file adjacent to the backlog."""

    return source.with_name(f".{source.stem}.github-issues.json")


def relative_source_file(source: Path, *, relative_to: Path) -> str:
    """Return a portable source reference relative to the state-file directory."""

    try:
        return Path(
            os.path.relpath(source.resolve(), start=relative_to.resolve())
        ).as_posix()
    except ValueError:
        # A relative path cannot cross filesystem roots (for example, Windows
        # drive letters). Preserve the usable absolute reference in that
        # exceptional case rather than writing an invalid path.
        return str(source)


def empty_state(
    backlog_key: str,
    repository: str,
    source: Path,
    *,
    source_base: Path,
) -> dict[str, Any]:
    """Create the initial serializable state document."""

    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "backlog_key": backlog_key,
        "repository": repository,
        "source_file": relative_source_file(source, relative_to=source_base),
        "source_sha256": None,
        "epic": None,
        "children": {},
    }


def load_state(
    path: Path,
    *,
    backlog_key: str,
    repository: Optional[str],
    source: Path,
) -> dict[str, Any]:
    """Load and validate state, or return a new in-memory state document."""

    if not path.exists():
        return empty_state(
            backlog_key,
            repository or "",
            source,
            source_base=path.parent,
        )
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateFileError(f"Cannot read state file {path}: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise StateFileError(
            f"State file {path} has an unsupported or missing schema_version."
        )
    if state.get("backlog_key") != backlog_key:
        raise StateFileError(
            f"State file {path} belongs to backlog key {state.get('backlog_key')!r}, "
            f"not {backlog_key!r}."
        )
    state_repository = state.get("repository")
    if repository and state_repository and state_repository != repository:
        raise StateFileError(
            f"State file repository is {state_repository}, not requested repository {repository}."
        )
    if not isinstance(state.get("children"), dict):
        raise StateFileError(f"State file {path} has invalid children data.")
    return state


def write_state(path: Path, state: Mapping[str, Any]) -> None:
    """Atomically persist state in the destination directory.

    The temporary file is flushed and fsynced before ``os.replace`` so a crash
    cannot leave a partially written JSON document at the requested path.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    temporary_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except OSError as exc:
        raise StateFileError(f"Cannot write state file {path}: {exc}") from exc
    finally:
        if temporary_name and os.path.exists(temporary_name):
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def record_to_state(
    record: RemoteIssue, *, title: str, body_hash: Optional[str] = None
) -> dict[str, Any]:
    """Convert remote issue metadata to the stable state-file representation."""

    value: dict[str, Any] = {
        "number": record.number,
        "url": record.url,
        "title": title,
    }
    if body_hash is not None:
        value["source_body_sha256"] = body_hash
    return value


def index_owned_issues(
    issues: Sequence[RemoteIssue], backlog: BacklogSpec, backlog_key: str
) -> tuple[dict[str, RemoteIssue], dict[str, list[RemoteIssue]]]:
    """Index exact ownership markers and report duplicates explicitly."""

    expected = {"epic": epic_marker(backlog_key)}
    expected.update(
        {issue.identifier: child_marker(backlog_key, issue.identifier) for issue in backlog.issues}
    )
    found: dict[str, list[RemoteIssue]] = {key: [] for key in expected}
    for record in issues:
        for key, marker in expected.items():
            if marker in record.body:
                found[key].append(record)
    duplicates = {key: values for key, values in found.items() if len(values) > 1}
    if duplicates:
        detail = ", ".join(
            f"{key}: {', '.join('#' + str(item.number) for item in values)}"
            for key, values in duplicates.items()
        )
        raise StateFileError(f"Duplicate GitHub ownership markers found ({detail}).")
    return (
        {key: values[0] for key, values in found.items() if values},
        found,
    )


def state_issue_number(value: Any, label: str) -> Optional[int]:
    """Read and validate an optional issue number from state."""

    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("number"), int):
        raise StateFileError(f"State entry for {label} is malformed.")
    return int(value["number"])


def resolve_existing(
    *,
    label: str,
    marker: str,
    state_entry: Any,
    by_number: Mapping[int, RemoteIssue],
    by_marker: Mapping[str, RemoteIssue],
) -> Optional[RemoteIssue]:
    """Resolve one owned issue from state first, then from its remote marker."""

    number = state_issue_number(state_entry, label)
    if number is not None:
        record = by_number.get(number)
        if record is None:
            raise StateFileError(
                f"State references {label} issue #{number}, but it was not found on GitHub."
            )
        if marker not in record.body:
            raise StateFileError(
                f"State references {label} issue #{number}, but its ownership marker is missing."
            )
        return record
    return by_marker.get(label)


def execute(
    *,
    source: Path,
    backlog: BacklogSpec,
    source_text: str,
    repository: Optional[str],
    state_path: Path,
    backlog_key: str,
    dry_run: bool,
    project_title: Optional[str] = None,
) -> int:
    """Create or reconcile the Epic, child issues, checklist, and local state."""

    source_file = relative_source_file(source, relative_to=state_path.parent)
    state = load_state(
        state_path,
        backlog_key=backlog_key,
        repository=repository,
        source=source,
    )
    state["source_file"] = source_file
    stored_project = state.get("project")
    if project_title is None and isinstance(stored_project, dict):
        stored_title = stored_project.get("title")
        if isinstance(stored_title, str) and stored_title.strip():
            project_title = stored_title
    if dry_run:
        print(f"DRY RUN: {backlog.title}")
        print(f"Repository: {repository or '<current gh repository>'}")
        print(f"State file: {state_path}")
        if backlog.labels:
            print(f"Epic labels: {', '.join(backlog.labels)}")
        if project_title:
            print(f"Project: create or reuse {project_title!r}")
        epic_state = state.get("epic")
        epic_number = state_issue_number(epic_state, "Epic")
        print(f"{'REUSE' if epic_number else 'CREATE'} Epic: {backlog.title}")
        children_state = state["children"]
        for milestone in backlog.milestones:
            print(f"\n{milestone} (create or reuse GitHub milestone)")
            for issue in (item for item in backlog.issues if item.milestone == milestone):
                child_number = state_issue_number(
                    children_state.get(issue.identifier), issue.identifier
                )
                suffix = f" as #{child_number}" if child_number else ""
                labels = f" [labels: {', '.join(issue.labels)}]" if issue.labels else ""
                print(
                    f"  {'REUSE' if child_number else 'CREATE'} "
                    f"{issue.github_title}{suffix}{labels}"
                )
        print("\nNo GitHub commands were run and no state was written.")
        return 0

    gh = GitHubCli(source.parent)
    resolved_repository = validate_repository(repository) if repository else gh.repository()
    state_repository = str(state.get("repository") or "")
    if state_repository and state_repository != resolved_repository:
        raise StateFileError(
            f"State file repository is {state_repository}, not {resolved_repository}."
        )
    state["repository"] = resolved_repository

    repository_details = gh.repository_details(resolved_repository)
    root = repository_root(source)
    planning_documents = discover_planning_documents(
        source, root, repository_details
    )

    requested_labels = unique_label_names(backlog)
    resolved_labels = ensure_labels(gh, resolved_repository, requested_labels)
    milestones = ensure_milestones(gh, resolved_repository, backlog.milestones)

    project: Optional[ProjectRecord] = None
    project_owner: Optional[str] = None
    project_status_field: Optional[ProjectField] = None
    project_backlog_option: Optional[ProjectOption] = None
    if project_title:
        project_owner = resolved_repository.split("/", 1)[0]
        existing_project_state = state.get("project")
        if existing_project_state is not None:
            if not isinstance(existing_project_state, dict):
                raise StateFileError("State file contains malformed Project data.")
            if (
                existing_project_state.get("title") != project_title
                or existing_project_state.get("owner") != project_owner
            ):
                raise StateFileError(
                    "State file belongs to a different --project selection."
                )
        project, project_created = ensure_project(gh, project_owner, project_title)
        if existing_project_state and existing_project_state.get("number") != project.number:
            raise StateFileError(
                "State Project number does not match the uniquely resolved GitHub Project."
            )
        created_by_tool = project_created or bool(
            existing_project_state and existing_project_state.get("created_by_tool")
        )
        workflow_initialized = bool(
            existing_project_state and existing_project_state.get("workflow_initialized")
        )
        state["project"] = project_state_entry(
            project,
            owner=project_owner,
            created_by_tool=created_by_tool,
            workflow_initialized=workflow_initialized,
        )
        write_state(state_path, state)
        project_status_field, project_backlog_option, workflow_handled = (
            initialize_project_workflow(
                gh,
                project_owner,
                project,
                may_modify=created_by_tool and not workflow_initialized,
            )
        )
        if workflow_handled:
            state["project"]["workflow_initialized"] = True
            write_state(state_path, state)

    remote_issues = gh.list_issues(resolved_repository)
    by_number = {issue.number: issue for issue in remote_issues}
    by_marker, _ = index_owned_issues(remote_issues, backlog, backlog_key)

    epic = resolve_existing(
        label="epic",
        marker=epic_marker(backlog_key),
        state_entry=state.get("epic"),
        by_number=by_number,
        by_marker=by_marker,
    )
    if epic is None:
        epic_labels = tuple(resolved_labels[label.casefold()] for label in backlog.labels)
        epic = gh.create_issue(
            resolved_repository,
            backlog.title,
            build_initial_epic_body(backlog, backlog_key),
            labels=epic_labels,
        )
        print(f"Created Epic #{epic.number}: {epic.url}")
    else:
        print(f"Reusing Epic #{epic.number}: {epic.url}")
        missing_epic_labels = tuple(
            resolved_labels[label.casefold()]
            for label in backlog.labels
            if label.casefold() not in {value.casefold() for value in epic.labels}
        )
        if missing_epic_labels:
            gh.update_issue_metadata(
                resolved_repository,
                epic.number,
                labels=missing_epic_labels,
                milestone=None,
            )
            epic = replace(epic, labels=(*epic.labels, *missing_epic_labels))
    state["epic"] = record_to_state(epic, title=backlog.title)
    write_state(state_path, state)

    records: dict[str, RemoteIssue] = {}
    for issue in backlog.issues:
        record = resolve_existing(
            label=issue.identifier,
            marker=child_marker(backlog_key, issue.identifier),
            state_entry=state["children"].get(issue.identifier),
            by_number=by_number,
            by_marker=by_marker,
        )
        if record is None:
            issue_labels = tuple(
                resolved_labels[label.casefold()] for label in issue.labels
            )
            record = gh.create_issue(
                resolved_repository,
                issue.github_title,
                build_child_body(issue, backlog_key),
                labels=issue_labels,
                milestone=milestones[issue.milestone].title,
            )
            by_number[record.number] = record
            print(f"Created {issue.identifier} as #{record.number}: {record.url}")
        else:
            previous_hash = (state["children"].get(issue.identifier) or {}).get(
                "source_body_sha256"
            )
            if previous_hash and previous_hash != issue.body_hash:
                print(
                    f"Warning: {issue.identifier} source changed; existing issue "
                    f"#{record.number} was not overwritten.",
                    file=sys.stderr,
                )
            print(f"Reusing {issue.identifier} as #{record.number}: {record.url}")
            existing_labels = {value.casefold() for value in record.labels}
            missing_labels = tuple(
                resolved_labels[label.casefold()]
                for label in issue.labels
                if label.casefold() not in existing_labels
            )
            desired_milestone = milestones[issue.milestone].title
            milestone_update = (
                desired_milestone
                if (record.milestone or "").casefold() != desired_milestone.casefold()
                else None
            )
            if missing_labels or milestone_update:
                gh.update_issue_metadata(
                    resolved_repository,
                    record.number,
                    labels=missing_labels,
                    milestone=milestone_update,
                )
                record = replace(
                    record,
                    labels=(*record.labels, *missing_labels),
                    milestone=desired_milestone,
                )
        records[issue.identifier] = record
        state["children"][issue.identifier] = record_to_state(
            record,
            title=issue.github_title,
            body_hash=issue.body_hash,
        )
        # Persist after every create/recovery so an interruption loses at most
        # the currently executing gh call. Remote markers recover that edge.
        write_state(state_path, state)

    if project is not None and project_owner is not None:
        ensure_project_items(
            gh,
            project_owner,
            project,
            (epic, *records.values()),
            project_status_field,
            project_backlog_option,
        )

    generated_section = build_generated_epic_section(
        backlog,
        records,
        milestones,
        planning_documents,
        project,
    )
    current_epic = gh.read_issue(resolved_repository, epic.number)
    if epic_marker(backlog_key) not in current_epic.body:
        raise StateFileError(
            f"Epic #{epic.number} no longer contains its ownership marker; refusing to edit it."
        )
    updated_epic_body = replace_managed_checklist(
        current_epic.body, generated_section
    )
    validate_body_length(updated_epic_body, backlog.title)
    if updated_epic_body != current_epic.body:
        gh.update_issue_body(resolved_repository, epic.number, updated_epic_body)
        print(f"Updated Epic #{epic.number} generated metadata and checklist.")
    else:
        print(f"Epic #{epic.number} generated metadata is already current.")

    state["source_file"] = source_file
    state["source_sha256"] = sha256_text(source_text)
    state["epic_checklist_sha256"] = sha256_text(generated_section)
    write_state(state_path, state)
    print(f"State saved to {state_path}")
    return 0


def build_argument_parser() -> argparse.ArgumentParser:
    """Construct the command-line parser."""

    parser = argparse.ArgumentParser(
        description="Create a GitHub Epic and child issues from a Markdown backlog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 scripts/github/create_issues.py docs/project/backlog.md --dry-run
  python3 scripts/github/create_issues.py docs/project/backlog.md --repo owner/repo
  python3 scripts/github/create_issues.py docs/project/backlog.md \\
      --state-file .local/github/backlog-state.json
  python3 scripts/github/create_issues.py docs/project/backlog.md \\
      --project "Engineering Delivery"
""",
    )
    parser.add_argument("backlog", type=Path, help="Path to the structured Markdown backlog.")
    parser.add_argument(
        "--repo",
        metavar="OWNER/REPO",
        help="Target repository. Defaults to the repository resolved by gh.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        help="State path. Defaults to a hidden file adjacent to the backlog.",
    )
    parser.add_argument(
        "--key",
        help="Stable idempotency namespace. Defaults to a value derived from the Epic title.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the plan without invoking gh or writing state.",
    )
    parser.add_argument(
        "--project",
        metavar="TITLE",
        help="Create or reuse an owner-level GitHub Project and add every issue.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Command-line entry point with concise, actionable failures."""

    args = build_argument_parser().parse_args(argv)
    source = args.backlog.expanduser().resolve()
    if not source.is_file():
        print(f"error: backlog file does not exist: {source}", file=sys.stderr)
        return 2
    try:
        source_text = source.read_text(encoding="utf-8")
        backlog = parse_backlog(source_text)
        repository = validate_repository(args.repo) if args.repo else None
        backlog_key = validate_backlog_key(args.key or default_backlog_key(backlog.title))
        project_title = args.project.strip() if args.project else None
        if args.project and not project_title:
            raise CreateIssuesError("--project title must not be empty.")
        state_path = (
            args.state_file.expanduser().resolve()
            if args.state_file
            else default_state_file(source)
        )
        return execute(
            source=source,
            backlog=backlog,
            source_text=source_text,
            repository=repository,
            state_path=state_path,
            backlog_key=backlog_key,
            dry_run=args.dry_run,
            project_title=project_title,
        )
    except CreateIssuesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
