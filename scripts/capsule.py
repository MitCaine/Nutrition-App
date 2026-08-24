#!/usr/bin/env python3
"""Repository-owned Task Capsule lifecycle and qualification orchestration."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
import time
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

from lib.qualification_profiles import (
    QualificationProfileError,
    parse_profile_tokens,
    required_checks_for_profiles,
)

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

TRANSITIONS: dict[str, set[str]] = {
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

ACTIVE_TARGETS = {
    "GRILLED",
    "SPECIFIED",
    "DECOMPOSED",
    "READY",
    "IN_PROGRESS",
    "IMPLEMENTED",
    "VERIFIED",
    "REVIEWED",
}


class CapsuleError(RuntimeError):
    pass


def run(
    command: list[str],
    *,
    cwd: Path,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )

    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise CapsuleError(
            f"Command failed ({' '.join(command)}): {detail}"
        )

    return completed


def git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return run(
        ["git", "-C", str(repo), *args],
        cwd=repo,
        check=check,
    )


def resolve_repo_root(candidate: Path | None) -> Path:
    start = (candidate or Path.cwd()).resolve()
    result = git(start, "rev-parse", "--show-toplevel", check=True)
    root = Path(result.stdout.strip()).resolve()

    if candidate is not None and root != start:
        raise CapsuleError(
            f"--repo-root must identify the repository root exactly: {root}"
        )

    return root


def capsule_path(repo: Path, task_id: str) -> Path:
    if not ID_PATTERN.fullmatch(task_id):
        raise CapsuleError(f"Invalid Task Capsule ID: {task_id}")

    path = repo / "engineering" / "capsules" / "active" / f"{task_id}.md"

    if not path.is_file():
        raise CapsuleError(f"Active Task Capsule not found: {path}")

    return path


def read_capsule(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    if not lines or lines[0].strip() != "+++":
        raise CapsuleError(f"Capsule front matter is missing: {path}")

    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "+++"
        )
    except StopIteration as exc:
        raise CapsuleError(f"Capsule front matter is unterminated: {path}") from exc

    metadata = tomllib.loads("\n".join(lines[1:end]))
    return metadata, text


def exact_head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD", check=True).stdout.strip()


def current_branch(repo: Path) -> str:
    return git(repo, "branch", "--show-current", check=True).stdout.strip()


def dirty_status(repo: Path) -> str:
    return git(
        repo,
        "status",
        "--porcelain=v1",
        "-uall",
        check=True,
    ).stdout.strip()


def path_matches(path: str, pattern: str) -> bool:
    return path == pattern or fnmatch.fnmatchcase(path, pattern)


def validate_scope(
    repo: Path,
    metadata: dict[str, Any],
    *,
    head: str,
) -> list[str]:
    base = metadata.get("base_commit", "")

    if not isinstance(base, str) or not COMMIT_PATTERN.fullmatch(base):
        raise CapsuleError("BASE_COMMIT_INVALID")

    ancestor = git(
        repo,
        "merge-base",
        "--is-ancestor",
        base,
        head,
    )

    if ancestor.returncode:
        raise CapsuleError(
            f"BASE_COMMIT_NOT_ANCESTOR: {base} is not an ancestor of {head}"
        )

    overlay = [
        item
        for item in git(
            repo,
            "diff",
            "--name-only",
            f"{base}..{head}",
            check=True,
        ).stdout.splitlines()
        if item
    ]

    owned = list(metadata.get("owned_paths") or [])
    allowed = list(metadata.get("allowed_paths") or [])
    forbidden = list(metadata.get("forbidden_paths") or [])

    for path in overlay:
        if any(path_matches(path, pattern) for pattern in forbidden):
            raise CapsuleError(
                f"SCOPE_FORBIDDEN: {path}"
            )

        if not any(
            path_matches(path, pattern)
            for pattern in [*owned, *allowed]
        ):
            raise CapsuleError(
                f"SCOPE_UNEXPECTED: {path}"
            )

    return overlay


def preflight(
    repo: Path,
    metadata: dict[str, Any],
    *,
    require_clean: bool,
) -> dict[str, Any]:
    head = exact_head(repo)
    branch = current_branch(repo)
    expected_branch = metadata.get("branch", "")

    if branch != expected_branch:
        raise CapsuleError(
            f"BRANCH_MISMATCH: current={branch} expected={expected_branch}"
        )

    if metadata.get("blocked") is True:
        raise CapsuleError("CAPSULE_BLOCKED")

    if require_clean:
        dirty = dirty_status(repo)

        if dirty:
            raise CapsuleError(
                "WORKTREE_DIRTY:\n" + dirty
            )

    overlay = validate_scope(
        repo,
        metadata,
        head=head,
    )

    base = metadata["base_commit"]
    origin_main = git(
        repo,
        "rev-parse",
        "--verify",
        "refs/remotes/origin/main",
    )

    if origin_main.returncode == 0:
        observed = origin_main.stdout.strip()

        if observed != base:
            raise CapsuleError(
                (
                    "BASE_AUTHORITY_STALE: "
                    f"capsule={base} origin/main={observed}"
                )
            )

    return {
        "head": head,
        "branch": branch,
        "base_commit": base,
        "overlay_paths": overlay,
    }


def validator_path() -> Path:
    return Path(__file__).resolve().parent / "validate-task-capsules.py"


def validate_repository(repo: Path) -> dict[str, Any]:
    completed = run(
        [
            sys.executable,
            str(validator_path()),
            "--repo-root",
            str(repo),
            "--all",
            "--json",
        ],
        cwd=repo,
    )

    if not completed.stdout.strip():
        detail = completed.stderr.strip() or "validator returned no JSON output"
        raise CapsuleError(f"Task Capsule validation failed: {detail}")

    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CapsuleError(
            "Task Capsule validator returned invalid JSON."
        ) from exc

    if (
        completed.returncode
        or document.get("summary", {}).get("status") != "passed"
    ):
        findings: list[str] = []

        for capsule in document.get("capsules", []):
            for finding in capsule.get("errors", []):
                findings.append(
                    (
                        f"{finding.get('code', 'VALIDATION_ERROR')}: "
                        f"{finding.get('message', 'validation failed')}"
                    )
                )

        detail = "; ".join(findings) or completed.stderr.strip()
        raise CapsuleError(
            f"Task Capsule validation failed: {detail}"
        )

    return document


def replace_metadata_value(
    text: str,
    key: str,
    replacement: str,
) -> str:
    pattern = re.compile(
        rf"(?m)^{re.escape(key)} = .+$"
    )
    matches = list(pattern.finditer(text))

    if len(matches) != 1:
        raise CapsuleError(
            f"Expected exactly one metadata field: {key}"
        )

    return pattern.sub(
        f'{key} = "{replacement}"',
        text,
        count=1,
    )


def append_state_history(
    text: str,
    *,
    today: str,
    old_state: str,
    new_state: str,
    actor: str,
    reason: str,
) -> str:
    heading = "\n## Completion record\n"

    if heading not in text:
        raise CapsuleError("Completion record heading not found.")

    before, after = text.split(heading, 1)

    row = (
        f"| {today} | {old_state} | {new_state} | "
        f"{actor} | {reason} |"
    )

    if row in before:
        raise CapsuleError(
            "The requested state-history row already exists."
        )

    return before.rstrip() + "\n" + row + "\n" + heading + after


def transition(
    repo: Path,
    task_id: str,
    target: str,
    *,
    actor: str,
    reason: str,
    commit_message: str | None,
    no_commit: bool,
) -> dict[str, Any]:
    path = capsule_path(repo, task_id)
    metadata, original = read_capsule(path)
    old_state = str(metadata.get("state", ""))

    if target not in TRANSITIONS.get(old_state, set()):
        raise CapsuleError(
            f"STATE_TRANSITION_INVALID: {old_state} -> {target}"
        )

    if target not in ACTIVE_TARGETS:
        raise CapsuleError(
            (
                f"{target} is a terminal or unsupported automated target. "
                "Terminal HISTORY closeout remains separately controlled."
            )
        )

    preflight(
        repo,
        metadata,
        require_clean=True,
    )

    today = date.today().isoformat()
    modified = replace_metadata_value(
        original,
        "state",
        target,
    )
    modified = replace_metadata_value(
        modified,
        "updated",
        today,
    )
    modified = append_state_history(
        modified,
        today=today,
        old_state=old_state,
        new_state=target,
        actor=actor,
        reason=reason,
    )

    path.write_text(
        modified,
        encoding="utf-8",
    )

    try:
        validate_repository(repo)
    except Exception:
        path.write_text(
            original,
            encoding="utf-8",
        )
        raise

    result: dict[str, Any] = {
        "task": task_id,
        "from": old_state,
        "to": target,
        "committed": False,
    }

    if no_commit:
        return result

    git(
        repo,
        "add",
        path.relative_to(repo).as_posix(),
        check=True,
    )

    staged = [
        item
        for item in git(
            repo,
            "diff",
            "--cached",
            "--name-only",
            check=True,
        ).stdout.splitlines()
        if item
    ]

    expected = path.relative_to(repo).as_posix()

    if staged != [expected]:
        git(
            repo,
            "restore",
            "--staged",
            expected,
        )
        path.write_text(
            original,
            encoding="utf-8",
        )
        raise CapsuleError(
            f"TRANSITION_STAGE_SCOPE_INVALID: {staged}"
        )

    message = (
        commit_message
        or f"workflow: {task_id} state {target.lower()}"
    )

    git(
        repo,
        "commit",
        "-m",
        message,
        check=True,
    )

    validate_repository(repo)

    result["committed"] = True
    result["commit"] = exact_head(repo)
    return result


def repository_slug(repo: Path) -> str:
    remote = git(
        repo,
        "remote",
        "get-url",
        "origin",
        check=True,
    ).stdout.strip()

    if remote.startswith("git@github.com:"):
        value = remote.removeprefix("git@github.com:")
    elif remote.startswith("https://github.com/"):
        value = remote.removeprefix("https://github.com/")
    else:
        raise CapsuleError(
            f"Unsupported GitHub origin URL: {remote}"
        )

    return value.removesuffix(".git")


def gh_json(
    repo: Path,
    endpoint: str,
) -> dict[str, Any]:
    completed = run(
        [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            endpoint,
        ],
        cwd=repo,
    )

    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise CapsuleError(
            f"GitHub API request failed: {endpoint}: {detail}"
        )

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CapsuleError(
            f"GitHub API returned invalid JSON: {endpoint}"
        ) from exc


def wait_for_main_qualification(
    repo: Path,
    slug: str,
    sha: str,
    *,
    timeout_seconds: int,
    interval_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    endpoint = f"/repos/{slug}/commits/{sha}/check-runs?per_page=100"

    while time.monotonic() < deadline:
        document = gh_json(
            repo,
            endpoint,
        )

        candidates = [
            item
            for item in document.get("check_runs", [])
            if item.get("name") == "Main qualification"
        ]

        if candidates:
            latest = max(
                candidates,
                key=lambda item: int(item.get("id", 0)),
            )

            if latest.get("status") == "completed":
                conclusion = latest.get("conclusion")

                if conclusion != "success":
                    raise CapsuleError(
                        (
                            "MAIN_QUALIFICATION_FAILED: "
                            f"conclusion={conclusion} "
                            f"url={latest.get('details_url', '')}"
                        )
                    )

                return latest

        time.sleep(interval_seconds)

    raise CapsuleError(
        f"MAIN_QUALIFICATION_TIMEOUT after {timeout_seconds}s"
    )


def wait_for_qualification_artifact(
    repo: Path,
    slug: str,
    run_id: int,
    artifact_name: str,
    *,
    timeout_seconds: int = 120,
    interval_seconds: int = 2,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        document = gh_json(
            repo,
            (
                f"/repos/{slug}/actions/runs/{run_id}/"
                "artifacts?per_page=100"
            ),
        )

        candidates = [
            item
            for item in document.get("artifacts", [])
            if item.get("name") == artifact_name
        ]

        if candidates:
            return max(
                candidates,
                key=lambda item: int(item.get("id", 0)),
            )

        time.sleep(interval_seconds)

    raise CapsuleError(
        f"QUALIFICATION_ARTIFACT_TIMEOUT: {artifact_name}"
    )


def find_qualification_run(
    repo: Path,
    slug: str,
    sha: str,
    ref_name: str,
) -> dict[str, Any]:
    document = gh_json(
        repo,
        (
            f"/repos/{slug}/actions/runs"
            f"?head_sha={sha}&event=push&per_page=100"
        ),
    )

    candidates = [
        item
        for item in document.get("workflow_runs", [])
        if (
            item.get("name") == "Main qualification"
            and item.get("head_sha") == sha
            and item.get("head_branch") == ref_name
        )
    ]

    if not candidates:
        raise CapsuleError(
            "Main qualification workflow run could not be located."
        )

    return max(
        candidates,
        key=lambda item: int(item.get("id", 0)),
    )


def qualify(
    repo: Path,
    task_id: str,
    *,
    timeout_seconds: int,
    interval_seconds: int,
    evidence_dir: Path | None,
) -> dict[str, Any]:
    path = capsule_path(repo, task_id)
    metadata, _ = read_capsule(path)

    context = preflight(
        repo,
        metadata,
        require_clean=True,
    )

    profiles = parse_profile_tokens(
        metadata.get("specialized_qualification", [])
    )

    if not profiles:
        raise CapsuleError(
            "No profile:NAME qualification entries are selected."
        )

    required_checks_for_profiles(profiles)

    sha = context["head"]
    slug = repository_slug(repo)
    ref_name = f"qualification/{task_id}/{sha[:12]}"

    existing = git(
        repo,
        "ls-remote",
        "--exit-code",
        "--heads",
        "origin",
        ref_name,
    )

    if existing.returncode == 0:
        raise CapsuleError(
            f"Remote qualification ref already exists: {ref_name}"
        )

    pushed = False

    try:
        git(
            repo,
            "push",
            "origin",
            f"HEAD:refs/heads/{ref_name}",
            check=True,
        )
        pushed = True

        check = wait_for_main_qualification(
            repo,
            slug,
            sha,
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
        )

        workflow_run = find_qualification_run(
            repo,
            slug,
            sha,
            ref_name,
        )

        artifact_name = f"main-qualification-{sha}"
        artifact = wait_for_qualification_artifact(
            repo,
            slug,
            int(workflow_run["id"]),
            artifact_name,
        )

        result = {
            "task": task_id,
            "capsule_revision": metadata.get("capsule_revision"),
            "sha": sha,
            "profiles": profiles,
            "qualification_ref": ref_name,
            "check_id": check.get("id"),
            "check_url": check.get("details_url"),
            "check_conclusion": check.get("conclusion"),
            "workflow_run_id": workflow_run.get("id"),
            "workflow_run_url": workflow_run.get("html_url"),
            "artifact_name": artifact_name,
            "artifact_id": artifact.get("id"),
            "artifact_digest": artifact.get("digest"),
            "artifact_size_in_bytes": artifact.get("size_in_bytes"),
            "result": "PASS",
        }

        if evidence_dir is not None:
            evidence_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            completed = run(
                [
                    "gh",
                    "run",
                    "download",
                    str(workflow_run["id"]),
                    "--repo",
                    slug,
                    "--name",
                    result["artifact_name"],
                    "--dir",
                    str(evidence_dir),
                ],
                cwd=repo,
            )

            if completed.returncode:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise CapsuleError(
                    f"Qualification artifact download failed: {detail}"
                )

            manifest_path = (
                evidence_dir / "main-qualification.json"
            )

            if not manifest_path.is_file():
                raise CapsuleError(
                    "Downloaded qualification artifact does not contain "
                    "main-qualification.json."
                )

            result["manifest_sha256"] = hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest()

            result_path = evidence_dir / "qualification-result.json"
            result_path.write_text(
                json.dumps(
                    result,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

        git(
            repo,
            "push",
            "origin",
            "--delete",
            ref_name,
            check=True,
        )
        pushed = False
        result["qualification_ref_removed"] = True
        return result

    except Exception as exc:
        if pushed:
            raise CapsuleError(
                (
                    f"{exc}\n"
                    f"Remote qualification ref retained for inspection: {ref_name}"
                )
            ) from exc
        raise


def print_status(
    repo: Path,
    task_id: str,
    *,
    as_json: bool,
) -> None:
    path = capsule_path(repo, task_id)
    metadata, _ = read_capsule(path)

    document = {
        "task": task_id,
        "state": metadata.get("state"),
        "capsule_revision": metadata.get("capsule_revision"),
        "base_commit": metadata.get("base_commit"),
        "expected_branch": metadata.get("branch"),
        "current_branch": current_branch(repo),
        "head": exact_head(repo),
        "clean": not bool(dirty_status(repo)),
        "blocked": metadata.get("blocked"),
        "profiles": parse_profile_tokens(
            metadata.get("specialized_qualification", [])
        ),
    }

    if as_json:
        print(
            json.dumps(
                document,
                indent=2,
                sort_keys=True,
            )
        )
        return

    for key, value in document.items():
        if isinstance(value, list):
            rendered = ",".join(value)
        else:
            rendered = str(value)
        print(f"{key}={rendered}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    status = subparsers.add_parser("status")
    status.add_argument("task_id")
    status.add_argument("--json", action="store_true")

    transition_parser = subparsers.add_parser("transition")
    transition_parser.add_argument("task_id")
    transition_parser.add_argument("target")
    transition_parser.add_argument("--actor", required=True)
    transition_parser.add_argument("--reason", required=True)
    transition_parser.add_argument("--commit-message")
    transition_parser.add_argument("--no-commit", action="store_true")

    aliases = {
        "ready": "READY",
        "start": "IN_PROGRESS",
        "implemented": "IMPLEMENTED",
        "verify": "VERIFIED",
        "review": "REVIEWED",
    }

    for name, target in aliases.items():
        item = subparsers.add_parser(name)
        item.set_defaults(alias_target=target)
        item.add_argument("task_id")
        item.add_argument("--actor", required=True)
        item.add_argument("--reason", required=True)
        item.add_argument("--commit-message")
        item.add_argument("--no-commit", action="store_true")

    qualify_parser = subparsers.add_parser("qualify")
    qualify_parser.add_argument("task_id")
    qualify_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=3600,
    )
    qualify_parser.add_argument(
        "--interval-seconds",
        type=int,
        default=10,
    )
    qualify_parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    repo = resolve_repo_root(args.repo_root)

    try:
        if args.command == "status":
            print_status(
                repo,
                args.task_id,
                as_json=args.json,
            )
            return 0

        if args.command == "qualify":
            result = qualify(
                repo,
                args.task_id,
                timeout_seconds=args.timeout_seconds,
                interval_seconds=args.interval_seconds,
                evidence_dir=args.evidence_dir,
            )
            print(
                json.dumps(
                    result,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        target = getattr(
            args,
            "alias_target",
            None,
        )

        if target is None:
            target = args.target

        result = transition(
            repo,
            args.task_id,
            target,
            actor=args.actor,
            reason=args.reason,
            commit_message=args.commit_message,
            no_commit=args.no_commit,
        )

        print(
            json.dumps(
                result,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    except (
        CapsuleError,
        QualificationProfileError,
    ) as exc:
        print(
            f"capsule: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
