#!/usr/bin/env python3
"""Aggregate repository CI checks into one exact-SHA Main qualification result."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from lib.qualification_profiles import (
    QualificationProfileError,
    parse_profile_tokens,
    required_checks_for_profiles,
)


class QualificationError(RuntimeError):
    pass


def git_head(repo: Path) -> str:
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise QualificationError(f"Could not resolve HEAD: {detail}")

    return completed.stdout.strip()


def task_from_ref(ref_name: str) -> tuple[str, str]:
    parts = ref_name.split("/", 2)

    if len(parts) != 3 or parts[0] != "qualification":
        raise QualificationError(
            (
                "Qualification ref must use "
                "qualification/TASK-ID/SHA-PREFIX syntax."
            )
        )

    task_id = parts[1]
    sha_prefix = parts[2]

    if not task_id or not sha_prefix:
        raise QualificationError("Qualification ref identity is incomplete.")

    return task_id, sha_prefix


def read_capsule(repo: Path, task_id: str) -> dict[str, Any]:
    path = (
        repo
        / "engineering"
        / "capsules"
        / "active"
        / f"{task_id}.md"
    )

    if not path.is_file():
        raise QualificationError(
            f"Active Task Capsule not found for qualification: {path}"
        )

    lines = path.read_text(encoding="utf-8").splitlines()

    if not lines or lines[0].strip() != "+++":
        raise QualificationError("Task Capsule front matter is missing.")

    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "+++"
        )
    except StopIteration as exc:
        raise QualificationError(
            "Task Capsule front matter is unterminated."
        ) from exc

    return tomllib.loads("\n".join(lines[1:end]))


def fetch_json(
    url: str,
    *,
    token: str,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nutrition-app-main-qualification",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            return json.loads(
                response.read().decode("utf-8")
            )
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
    ) as exc:
        raise QualificationError(
            f"GitHub check-run query failed: {exc}"
        ) from exc


def latest_checks_by_name(
    document: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}

    for item in document.get("check_runs", []):
        name = item.get("name")

        if not isinstance(name, str):
            continue

        current = latest.get(name)

        if (
            current is None
            or int(item.get("id", 0)) > int(current.get("id", 0))
        ):
            latest[name] = item

    return latest


def evaluate_checks(
    check_document: dict[str, Any],
    profile_checks: dict[str, tuple[str, ...]],
) -> tuple[
    bool,
    bool,
    dict[str, dict[str, Any]],
]:
    latest = latest_checks_by_name(check_document)
    waiting = False
    failed = False
    profile_results: dict[str, dict[str, Any]] = {}

    for profile, required_names in profile_checks.items():
        entries: list[dict[str, Any]] = []

        for name in required_names:
            item = latest.get(name)

            if item is None:
                waiting = True
                entries.append(
                    {
                        "name": name,
                        "status": "missing",
                        "conclusion": None,
                    }
                )
                continue

            status = item.get("status")
            conclusion = item.get("conclusion")

            entries.append(
                {
                    "name": name,
                    "id": item.get("id"),
                    "status": status,
                    "conclusion": conclusion,
                    "details_url": item.get("details_url"),
                }
            )

            if status != "completed":
                waiting = True
            elif conclusion != "success":
                failed = True

        profile_results[profile] = {
            "checks": entries,
            "result": (
                "FAIL"
                if any(
                    item.get("status") == "completed"
                    and item.get("conclusion") != "success"
                    for item in entries
                )
                else (
                    "WAIT"
                    if any(
                        item.get("status") in {"missing", "queued", "in_progress", "pending", "requested", "waiting"}
                        or item.get("status") != "completed"
                        for item in entries
                    )
                    else "PASS"
                )
            ),
        }

    return waiting, failed, profile_results


def wait_for_checks(
    *,
    repository: str,
    sha: str,
    token: str,
    profile_checks: dict[str, tuple[str, ...]],
    timeout_seconds: int,
    interval_seconds: int,
) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    url = (
        f"https://api.github.com/repos/{repository}/"
        f"commits/{sha}/check-runs?per_page=100"
    )

    while time.monotonic() < deadline:
        document = fetch_json(
            url,
            token=token,
        )
        waiting, failed, results = evaluate_checks(
            document,
            profile_checks,
        )

        if failed:
            raise QualificationError(
                "One or more selected qualification checks failed."
            )

        if not waiting:
            return results

        time.sleep(interval_seconds)

    raise QualificationError(
        f"Timed out after {timeout_seconds}s waiting for selected checks."
    )


def manifest_digest(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--ref-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checks-json", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=2700)
    parser.add_argument("--interval-seconds", type=int, default=10)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo = args.repo_root.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "profile": "main-qualification",
        "repository": args.repository,
        "commit": args.sha,
        "qualification_ref": args.ref_name,
        "result": "FAIL",
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "artifact_name": f"main-qualification-{args.sha}",
        "task": None,
        "capsule_revision": None,
        "profiles": [],
        "checks": {},
    }

    try:
        observed_head = git_head(repo)

        if observed_head != args.sha:
            raise QualificationError(
                (
                    "Exact SHA mismatch: "
                    f"requested={args.sha} checked_out={observed_head}"
                )
            )

        task_id, sha_prefix = task_from_ref(
            args.ref_name
        )

        if not args.sha.startswith(sha_prefix):
            raise QualificationError(
                (
                    "Qualification ref SHA prefix does not match "
                    f"the exact commit: {sha_prefix}"
                )
            )

        metadata = read_capsule(
            repo,
            task_id,
        )

        if metadata.get("id") != task_id:
            raise QualificationError(
                "Task Capsule ID does not match qualification ref."
            )

        profiles = parse_profile_tokens(
            metadata.get("specialized_qualification", [])
        )

        if not profiles:
            raise QualificationError(
                "The Task Capsule selected no machine qualification profiles."
            )

        profile_checks = required_checks_for_profiles(
            profiles
        )

        manifest["task"] = task_id
        manifest["capsule_revision"] = metadata.get(
            "capsule_revision"
        )
        manifest["profiles"] = profiles

        if args.checks_json is not None:
            document = json.loads(
                args.checks_json.read_text(
                    encoding="utf-8"
                )
            )
            waiting, failed, results = evaluate_checks(
                document,
                profile_checks,
            )

            if failed:
                raise QualificationError(
                    "Offline check evidence contains a failed selected check."
                )

            if waiting:
                raise QualificationError(
                    "Offline check evidence is missing or still waiting on a selected check."
                )

            profile_results = results
        else:
            token = os.environ.get("GH_TOKEN", "")

            if not token:
                raise QualificationError(
                    "GH_TOKEN is required for live qualification."
                )

            profile_results = wait_for_checks(
                repository=args.repository,
                sha=args.sha,
                token=token,
                profile_checks=profile_checks,
                timeout_seconds=args.timeout_seconds,
                interval_seconds=args.interval_seconds,
            )

        manifest["checks"] = profile_results
        manifest["result"] = "PASS"

        output.write_text(
            json.dumps(
                manifest,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        print(f"main_qualification=PASS")
        print(f"manifest={output}")
        print(f"manifest_sha256={manifest_digest(output)}")
        return 0

    except (
        QualificationError,
        QualificationProfileError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        manifest["error"] = str(exc)

        output.write_text(
            json.dumps(
                manifest,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        print(
            f"main_qualification=FAIL: {exc}",
            file=sys.stderr,
        )
        print(
            f"manifest={output}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
