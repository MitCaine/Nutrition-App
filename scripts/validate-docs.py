#!/usr/bin/env python3
"""Validate repository-local Markdown links, anchors, and fenced blocks."""

from __future__ import annotations

import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_FILES = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    *sorted((ROOT / "docs").rglob("*.md")),
]
FENCE_PATTERN = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
HEADING_PATTERN = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
EXECUTABLE_PATTERN = re.compile(
    r"(?<![\w.-])(?P<path>(?:\./)?(?:apps/backend/)?scripts/"
    r"[A-Za-z0-9_.\-/]+\.(?:py|sh))"
)
SESSION_WORKFLOW = ROOT / "docs" / "operations" / "session-contract.md"
SESSION_LINK_SOURCES = [
    ROOT / "CONTRIBUTING.md",
    ROOT / "docs" / "project" / "development-guide.md",
    ROOT / "docs" / "README.md",
]
QUALIFICATION_DOCUMENT = (
    ROOT / "docs" / "operations" / "version-1.0-release-qualification.md"
)
RELEASE_DOCUMENT = (
    ROOT
    / "docs"
    / "historical"
    / "releases"
    / "production-hardening-phase5c4.9.md"
)
CURRENT_STATE_DOCUMENT = ROOT / "docs" / "project" / "current-state.md"
INDEX_DIRECT_LINKS = [
    CURRENT_STATE_DOCUMENT,
    ROOT / "docs" / "project" / "onboarding.md",
    ROOT / "docs" / "architecture" / "overview.md",
    ROOT / "docs" / "operations" / "README.md",
    ROOT / "docs" / "historical" / "README.md",
    ROOT / "docs" / "reference" / "glossary.md",
]


def _visible_markdown(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("`", "")
    text = re.sub(r"[*_~]", "", text)
    return html.unescape(text).strip()


def _github_slug(value: str) -> str:
    value = _visible_markdown(value).lower()
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return re.sub(r"[ ]+", "-", value.strip())


def _scan_document(path: Path) -> tuple[str, set[str], list[str]]:
    text = path.read_text(encoding="utf-8")
    visible_lines: list[str] = []
    headings: set[str] = set()
    slug_counts: defaultdict[str, int] = defaultdict(int)
    errors: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    fence_line = 0
    mermaid_line: int | None = None
    mermaid_has_content = False

    for line_number, line in enumerate(text.splitlines(), start=1):
        fence = FENCE_PATTERN.match(line)
        if fence:
            marker, info = fence.groups()
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
                fence_line = line_number
                if info.strip().lower() == "mermaid":
                    mermaid_line = line_number
                    mermaid_has_content = False
            elif (
                marker[0] == fence_character
                and len(marker) >= fence_length
                and not info.strip()
            ):
                if mermaid_line is not None and not mermaid_has_content:
                    errors.append(
                        f"{path.relative_to(ROOT)}:{mermaid_line}: empty Mermaid fence"
                    )
                fence_character = None
                fence_length = 0
                mermaid_line = None
            continue

        if fence_character is not None:
            if mermaid_line is not None and line.strip():
                mermaid_has_content = True
            continue

        visible_lines.append(line)
        heading = HEADING_PATTERN.match(line)
        if heading:
            base = _github_slug(heading.group(2))
            duplicate = slug_counts[base]
            slug_counts[base] += 1
            headings.add(base if duplicate == 0 else f"{base}-{duplicate}")

    if fence_character is not None:
        errors.append(f"{path.relative_to(ROOT)}:{fence_line}: unclosed fenced block")

    return "\n".join(visible_lines), headings, errors


def _split_target(raw: str) -> tuple[str, str]:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    path, separator, fragment = target.partition("#")
    return unquote(path), unquote(fragment) if separator else ""


def _script_candidates(reference: str) -> list[Path]:
    normalized = reference.removeprefix("./")
    candidates = [ROOT / normalized]
    if normalized.startswith("scripts/"):
        candidates.append(ROOT / "apps" / "backend" / normalized)
    return candidates


def _expected_migration_heads() -> tuple[str, str]:
    config = json.loads((ROOT / "scripts" / "project-audit.json").read_text(encoding="utf-8"))
    application = config.get("expected_application_heads", [])
    control = config.get("expected_control_heads", [])
    if not (
        isinstance(application, list)
        and len(application) == 1
        and isinstance(application[0], str)
        and isinstance(control, list)
        and len(control) == 1
        and isinstance(control[0], str)
    ):
        raise ValueError("project audit must configure exactly one application and control head")
    return application[0], control[0]


def main() -> int:
    errors: list[str] = []
    documents: dict[Path, tuple[str, set[str]]] = {}
    local_links: defaultdict[Path, set[Path]] = defaultdict(set)

    for path in MARKDOWN_FILES:
        visible, headings, document_errors = _scan_document(path)
        documents[path.resolve()] = (visible, headings)
        errors.extend(document_errors)

    link_count = 0
    for source in MARKDOWN_FILES:
        visible, _ = documents[source.resolve()]
        for match in LINK_PATTERN.finditer(visible):
            raw = match.group(1)
            if raw.startswith(("http://", "https://", "mailto:")):
                continue
            link_count += 1
            path_text, fragment = _split_target(raw)
            target = source if not path_text else source.parent / path_text
            target = target.resolve()
            if not target.exists():
                errors.append(
                    f"{source.relative_to(ROOT)}: missing local target {raw!r}"
                )
                continue
            local_links[source.resolve()].add(target)
            if fragment and target.suffix.lower() == ".md":
                target_document = documents.get(target)
                if target_document is None:
                    errors.append(
                        f"{source.relative_to(ROOT)}: Markdown target is outside validation scope "
                        f"{raw!r}"
                    )
                elif fragment not in target_document[1]:
                    errors.append(
                        f"{source.relative_to(ROOT)}: missing anchor #{fragment} in "
                        f"{target.relative_to(ROOT)}"
                    )

    for source in MARKDOWN_FILES:
        text = source.read_text(encoding="utf-8")
        for match in EXECUTABLE_PATTERN.finditer(text):
            reference = match.group("path")
            if not any(candidate.is_file() for candidate in _script_candidates(reference)):
                errors.append(
                    f"{source.relative_to(ROOT)}: referenced executable script does not exist "
                    f"{reference!r}"
                )

    workflow = SESSION_WORKFLOW.resolve()
    for source in SESSION_LINK_SOURCES:
        if workflow not in local_links[source.resolve()]:
            errors.append(
                f"{source.relative_to(ROOT)}: missing direct link to the repository session "
                "contract"
            )

    current_state = CURRENT_STATE_DOCUMENT.resolve()
    if current_state not in local_links[(ROOT / "README.md").resolve()]:
        errors.append("README.md: missing direct link to canonical current state")

    documentation_index = (ROOT / "docs" / "README.md").resolve()
    for required in INDEX_DIRECT_LINKS:
        if required.resolve() not in local_links[documentation_index]:
            errors.append(
                "docs/README.md: missing direct link to "
                f"{required.relative_to(ROOT)}"
            )

    unexpected_root_documents = sorted(
        path for path in (ROOT / "docs").glob("*.md") if path.name != "README.md"
    )
    for path in unexpected_root_documents:
        errors.append(
            f"{path.relative_to(ROOT)}: active taxonomy requires Markdown to live in a "
            "purpose directory"
        )

    reachable: set[Path] = set()
    pending = [(ROOT / "README.md").resolve()]
    while pending:
        source = pending.pop()
        if source in reachable:
            continue
        reachable.add(source)
        pending.extend(
            target
            for target in local_links[source]
            if target in documents and target not in reachable
        )
    mandatory_reachable = {
        path.resolve() for path in (ROOT / "docs").rglob("*.md")
    }
    for path in sorted(mandatory_reachable - reachable):
        errors.append(
            f"{path.relative_to(ROOT)}: mandatory document is unreachable from README.md"
        )

    try:
        application_head, control_head = _expected_migration_heads()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"scripts/project-audit.json: cannot resolve migration heads: {exc}")
    else:
        for path in [
            CURRENT_STATE_DOCUMENT,
            QUALIFICATION_DOCUMENT,
            ROOT / "docs" / "operations" / "runbooks" / "recovery-and-cutback.md",
            RELEASE_DOCUMENT,
        ]:
            text = path.read_text(encoding="utf-8")
            for head in [application_head, control_head]:
                if head not in text:
                    errors.append(
                        f"{path.relative_to(ROOT)}: missing current migration/control head {head!r}"
                    )
        target_activation = (
            ROOT / "docs" / "operations" / "runbooks" / "target-activation.md"
        )
        if application_head not in target_activation.read_text(encoding="utf-8"):
            errors.append(
                f"{target_activation.relative_to(ROOT)}: missing current application head "
                f"{application_head!r}"
            )

    qualification_text = QUALIFICATION_DOCUMENT.read_text(encoding="utf-8")
    required_qualification_tokens = [
        "set -euo pipefail",
        "REQUIRE_POSTGRES_TESTS=1",
        "NUTRITION_TEST_POSTGRES_URL",
        "server_version_num",
        "160000 <= version < 170000",
        "test_initial_migration_replay_postgres.py",
        "test_phase5c4_roles_postgres.py",
        "test_phase5c4_target_activation_postgres.py",
        "test_phase5c4_recovery_postgres.py",
        "test_phase5c4_cutback_control_postgres.py",
        "test_phase5c4_recovery_qualification_control_postgres.py",
        "selected test(s) skipped",
        "qualify-phase5c4-infrastructure.sh",
        "dirty_tree: false",
    ]
    for token in required_qualification_tokens:
        if token not in qualification_text:
            errors.append(
                f"{QUALIFICATION_DOCUMENT.relative_to(ROOT)}: canonical qualification is "
                f"missing {token!r}"
            )

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print(
            f"Documentation validation failed with {len(errors)} error(s).",
            file=sys.stderr,
        )
        return 1

    print(
        f"Validated {len(MARKDOWN_FILES)} Markdown files and {link_count} local links."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
