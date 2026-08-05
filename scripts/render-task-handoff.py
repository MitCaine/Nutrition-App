#!/usr/bin/env python3
"""Render a validated READY task capsule into deterministic execution-handoff artifacts."""

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HANDOFF_SCHEMA_VERSION = 1
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class HandoffError(RuntimeError):
    """Raised when a task handoff cannot be produced safely."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run(
    command: list[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def repository_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_repo_root(candidate: Path | None) -> Path:
    repo = (candidate or repository_root_from_script()).resolve()
    result = run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        cwd=repo,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise HandoffError(f"Not a Git repository: {repo}: {detail}")
    resolved = Path(result.stdout.strip()).resolve()
    if resolved != repo:
        raise HandoffError(
            f"--repo-root must identify the repository root exactly: {resolved}"
        )
    return repo


def resolve_capsule(repo: Path, candidate: Path) -> Path:
    path = candidate if candidate.is_absolute() else repo / candidate
    path = path.resolve()
    try:
        path.relative_to(repo)
    except ValueError as exc:
        raise HandoffError("Capsule path must remain inside the repository.") from exc
    if not path.is_file():
        raise HandoffError(f"Capsule does not exist: {path}")
    return path


def fixed_or_current_time() -> tuple[str, str]:
    override = os.environ.get("NUTRITION_TASK_HANDOFF_GENERATED_AT", "").strip()
    if override:
        try:
            parsed = datetime.fromisoformat(override.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HandoffError(
                "NUTRITION_TASK_HANDOFF_GENERATED_AT must be an ISO-8601 timestamp."
            ) from exc
        if parsed.tzinfo is None:
            raise HandoffError(
                "NUTRITION_TASK_HANDOFF_GENERATED_AT must include a timezone."
            )
        parsed = parsed.astimezone(timezone.utc)
    else:
        parsed = datetime.now(timezone.utc)
    iso = parsed.isoformat().replace("+00:00", "Z")
    compact = parsed.strftime("%Y%m%d-%H%M%S")
    return iso, compact


def output_is_outside_repo(repo: Path, output: Path) -> bool:
    try:
        output.resolve().relative_to(repo.resolve())
    except ValueError:
        return True
    return False


def validate_capsule(
    repo: Path,
    capsule: Path,
) -> dict[str, Any]:
    validator = repository_root_from_script() / "scripts" / "validate-task-capsules.py"
    if not validator.is_file():
        raise HandoffError(
            "Missing task-capsule validator: scripts/validate-task-capsules.py"
        )
    relative = capsule.relative_to(repo).as_posix()
    completed = run(
        [
            sys.executable,
            str(validator),
            "--repo-root",
            str(repo),
            "--execution",
            relative,
            "--json",
        ],
        cwd=repo,
    )
    if not completed.stdout.strip():
        detail = completed.stderr.strip() or "validator returned no JSON output"
        raise HandoffError(f"Task-capsule validation failed: {detail}")
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        detail = completed.stderr.strip()
        raise HandoffError(
            "Task-capsule validator returned invalid JSON"
            + (f": {detail}" if detail else "")
        ) from exc
    if completed.returncode or document.get("summary", {}).get("status") != "passed":
        messages: list[str] = []
        for item in document.get("capsules", []):
            for finding in item.get("errors", []):
                messages.append(
                    f"{finding.get('code', 'VALIDATION_ERROR')}: "
                    f"{finding.get('message', 'validation failed')}"
                )
        detail = "; ".join(messages) or completed.stderr.strip() or "validation failed"
        raise HandoffError(f"READY capsule did not pass execution preflight: {detail}")
    capsules = document.get("capsules", [])
    if len(capsules) != 1:
        raise HandoffError("Execution validation must return exactly one capsule.")
    return document


def render_markdown(
    *,
    repo: Path,
    capsule_path: Path,
    capsule_text: str,
    validation: dict[str, Any],
    generated_at: str,
    capsule_sha256: str,
) -> str:
    capsule = validation["capsules"][0]
    metadata = capsule["metadata"]
    repository = validation["repository"]
    capsule_relative = capsule_path.relative_to(repo).as_posix()
    planning = metadata.get("planning_artifacts", [])
    owned = metadata.get("owned_paths", [])
    allowed = metadata.get("allowed_paths", [])
    forbidden = metadata.get("forbidden_paths", [])
    qualification = metadata.get("specialized_qualification", [])
    constraints = metadata.get("delegation_constraints", [])

    def bullets(values: list[str], empty: str) -> str:
        if not values:
            return f"- {empty}"
        return "\n".join(f"- `{value}`" for value in values)

    return f"""# Execution handoff — {metadata['id']}: {metadata['title']}

> Generated from a mechanically validated `READY` task capsule. Do not reinterpret, broaden, or
> replace the capsule from conversation context. Repository authority outranks this generated view.

## Exact execution identity

- **Task:** `{metadata['id']}`
- **Capsule revision:** `{metadata['capsule_revision']}`
- **Task type:** `{metadata['task_type']}`
- **Risk:** `{metadata['risk']}`
- **Source issue:** `{metadata['source_issue']}`
- **Repository:** `{repository['root']}`
- **Implementation baseline:** `{metadata['base_commit']}`
- **Current validated HEAD:** `{repository['head']}`
- **Expected branch:** `{metadata['branch']}`
- **Capsule:** `{capsule_relative}`
- **Capsule SHA-256:** `{capsule_sha256}`
- **Generated UTC:** `{generated_at}`

## Accountable roles and delegation

- **Controller:** {metadata['controller']}
- **Executor:** {metadata['executor']}
- **Reviewer:** {metadata['reviewer']}
- **Delegation:** `{metadata['delegation']}`

### Delegation constraints

{bullets(constraints, 'No delegated execution is authorized.')}

## Execution protocol

1. Read every authority artifact listed below before editing.
2. Verify and report the actual model, tool, and any delegated model identity. Do not claim an
   identity that cannot be verified.
3. Re-run the strict preflight before editing:

   `python3 scripts/validate-task-capsules.py --execution {capsule_relative}`

4. Change the capsule from `READY` to `IN_PROGRESS`, update `updated`, and append State History
   before implementation. Do not change contract fields or `capsule_revision` unless the controller
   requalifies the task.
5. Work only inside the owned and allowed surfaces. The capsule itself may be updated for valid state
   transitions and evidence references. Stop on any forbidden surface or escalation condition.
6. Preserve all higher-authority product, architecture, ownership, security, historical-data,
   migration, concurrency, recovery, and compatibility contracts.
7. Run focused verification during implementation and every required baseline or specialized check
   named by the capsule. Keep passed, failed, skipped, blocked, and not-applicable outcomes distinct.
8. On bounded completion, change the capsule to `IMPLEMENTED`, update State History, and return the
   evidence contract below. Do not mark `VERIFIED`, `REVIEWED`, or `MERGED` yourself.
9. Stop rather than improvise when authority conflicts, scope expands, repository state differs,
   required qualification is unavailable, or an irreversible decision is required.

## Authority artifacts

{bullets(planning, 'No authority artifacts were recorded; this should have failed READY validation.')}

## Machine-readable scope

### Owned paths

{bullets(owned, 'No owned paths recorded.')}

### Narrow adjacent paths allowed

{bullets(allowed, 'No adjacent paths are allowed.')}

### Forbidden paths

{bullets(forbidden, 'No additional forbidden path patterns recorded.')}

## Specialized qualification selected by the capsule

{bullets(qualification, 'Not applicable — the capsule selected no specialized qualification.')}

## Required implementation return

Return a structured implementation summary containing:

- task ID, capsule revision, final capsule state, actual model/tool identity, and delegation;
- base commit, starting HEAD, ending HEAD or working-tree state, and branch;
- changed files with rationale and intentionally unchanged behavior;
- acceptance criteria addressed and any criterion not satisfied;
- migration, API/schema, ownership/security, concurrency, recovery, compatibility, and historical-data
  impact, using `none` only with a reason;
- exact focused, baseline, and specialized commands with pass/fail/skip/block outcomes;
- warnings, limitations, assumptions, deviations, deferred work, and review questions;
- the final review-bundle path or identifier after `Run Nutrition Review.command` completes.

## Authoritative task capsule

The exact validated capsule follows. It remains the execution contract.

```markdown
{capsule_text.rstrip()}
```
"""


def build_json(
    *,
    repo: Path,
    capsule_path: Path,
    validation: dict[str, Any],
    generated_at: str,
    capsule_sha256: str,
) -> dict[str, Any]:
    capsule = validation["capsules"][0]
    metadata = capsule["metadata"]
    execution = capsule.get("execution") or {}
    return {
        "handoff_schema_version": HANDOFF_SCHEMA_VERSION,
        "generated_at": generated_at,
        "task": {
            "id": metadata["id"],
            "title": metadata["title"],
            "capsule_revision": metadata["capsule_revision"],
            "state": metadata["state"],
            "task_type": metadata["task_type"],
            "risk": metadata["risk"],
            "source_issue": metadata["source_issue"],
        },
        "repository": validation["repository"],
        "execution": {
            "base_commit": metadata["base_commit"],
            "expected_branch": metadata["branch"],
            "overlay_paths": execution.get("overlay_paths", []),
            "preflight_status": "passed",
        },
        "roles": {
            "controller": metadata["controller"],
            "executor": metadata["executor"],
            "reviewer": metadata["reviewer"],
            "delegation": metadata["delegation"],
            "delegation_constraints": metadata["delegation_constraints"],
        },
        "authority": metadata["planning_artifacts"],
        "scope": {
            "owned_paths": metadata["owned_paths"],
            "allowed_paths": metadata["allowed_paths"],
            "forbidden_paths": metadata["forbidden_paths"],
        },
        "specialized_qualification": metadata["specialized_qualification"],
        "artifacts": {
            "capsule_path": capsule_path.relative_to(repo).as_posix(),
            "capsule_sha256": capsule_sha256,
            "files": [
                "README.md",
                "handoff.md",
                "handoff.json",
                "validation.json",
                "capsule.md",
                "SHA256SUMS.txt",
            ],
        },
    }


def write_bundle(
    *,
    repo: Path,
    capsule_path: Path,
    validation: dict[str, Any],
    output_dir: Path,
    generated_at: str,
) -> None:
    capsule_bytes = capsule_path.read_bytes()
    capsule_text = capsule_bytes.decode("utf-8")
    capsule_sha256 = sha256_bytes(capsule_bytes)
    handoff_markdown = render_markdown(
        repo=repo,
        capsule_path=capsule_path,
        capsule_text=capsule_text,
        validation=validation,
        generated_at=generated_at,
        capsule_sha256=capsule_sha256,
    )
    handoff_document = build_json(
        repo=repo,
        capsule_path=capsule_path,
        validation=validation,
        generated_at=generated_at,
        capsule_sha256=capsule_sha256,
    )

    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        raise HandoffError(f"Output directory already exists: {output_dir}")

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=str(parent))
    )
    try:
        (temporary / "capsule.md").write_bytes(capsule_bytes)
        (temporary / "handoff.md").write_text(handoff_markdown, encoding="utf-8")
        (temporary / "handoff.json").write_text(
            json.dumps(handoff_document, indent=2) + "\n",
            encoding="utf-8",
        )
        (temporary / "validation.json").write_text(
            json.dumps(validation, indent=2) + "\n",
            encoding="utf-8",
        )
        (temporary / "README.md").write_text(
            "# Task execution handoff bundle\n\n"
            "Use `handoff.md` as the executor prompt. `capsule.md` is the exact validated "
            "contract, `validation.json` is the strict preflight evidence, and `handoff.json` "
            "is the machine-readable routing envelope.\n",
            encoding="utf-8",
        )
        checksum_names = [
            "README.md",
            "capsule.md",
            "handoff.md",
            "handoff.json",
            "validation.json",
        ]
        checksums = []
        for name in checksum_names:
            checksums.append(
                f"{sha256_bytes((temporary / name).read_bytes())}  {name}"
            )
        (temporary / "SHA256SUMS.txt").write_text(
            "\n".join(checksums) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capsule", type=Path, help="Path to one committed READY capsule.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="Repository root; defaults to the repository containing this script.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Exact output directory. It must be outside the repository and must not exist.",
    )
    parser.add_argument(
        "--print-handoff",
        action="store_true",
        help="Print the generated handoff Markdown after writing the bundle.",
    )
    args = parser.parse_args()

    try:
        repo = resolve_repo_root(args.repo_root)
        capsule = resolve_capsule(repo, args.capsule)
        validation = validate_capsule(repo, capsule)
        metadata = validation["capsules"][0]["metadata"]
        capsule_id = metadata["id"]
        if not isinstance(capsule_id, str) or not SAFE_ID_PATTERN.fullmatch(capsule_id):
            raise HandoffError("Validated capsule returned an unsafe task ID.")
        generated_at, compact = fixed_or_current_time()
        output_dir = (
            args.output_dir.resolve()
            if args.output_dir
            else (repo.parent / "nutrition-app-task-output" / f"{capsule_id}-{compact}").resolve()
        )
        if not output_is_outside_repo(repo, output_dir):
            raise HandoffError(
                "Task handoff output must be outside the repository to preserve clean preflight."
            )
        write_bundle(
            repo=repo,
            capsule_path=capsule,
            validation=validation,
            output_dir=output_dir,
            generated_at=generated_at,
        )
    except HandoffError as exc:
        print(f"ERROR TASK_HANDOFF: {exc}", file=sys.stderr)
        return 1

    print("Task execution handoff generated successfully")
    print(f"Directory:  {output_dir}")
    print(f"Prompt:     {output_dir / 'handoff.md'}")
    print(f"Machine:    {output_dir / 'handoff.json'}")
    print(f"Validation: {output_dir / 'validation.json'}")
    if args.print_handoff:
        print()
        print((output_dir / "handoff.md").read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
