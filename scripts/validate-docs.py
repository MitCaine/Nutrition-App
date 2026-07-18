#!/usr/bin/env python3
"""Validate repository-local Markdown links, anchors, and fenced blocks."""

from __future__ import annotations

import html
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
FENCE_PATTERN = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
HEADING_PATTERN = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


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


def main() -> int:
    errors: list[str] = []
    documents: dict[Path, tuple[str, set[str]]] = {}

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
