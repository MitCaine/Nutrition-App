#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Protocol

from lib.task_authorization import (
    AuthorizationError,
    ResolvedAuthorization,
    build_payload,
    render_authorization_comment,
    resolve_comment,
    resolve_comments,
    validate_candidate_scope,
)

from lib.trusted_qualification import CHECK_NAME


class TaskControllerError(RuntimeError):
    pass


class IssueAuthorizationTransport(Protocol):
    def create_issue_comment(
        self,
        repository: str,
        issue_number: int,
        body: str,
    ) -> dict[str, Any]:
        ...

    def get_issue_comment(
        self,
        repository: str,
        comment_id: int,
    ) -> dict[str, Any]:
        ...


class GhIssueAuthorizationTransport:
    def _api(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        command = [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
        ]

        if method != "GET":
            command.extend(
                [
                    "--method",
                    method,
                ]
            )

        command.append(path)

        input_text: str | None = None

        if payload is not None:
            command.extend(
                [
                    "--input",
                    "-",
                ]
            )

            input_text = json.dumps(
                payload,
                sort_keys=True,
            )

        completed = subprocess.run(
            command,
            text=True,
            input=input_text,
            capture_output=True,
            check=False,
        )

        if completed.returncode:
            detail = (
                completed.stderr.strip()
                or completed.stdout.strip()
            )

            raise TaskControllerError(
                f"GITHUB_API_ERROR: {detail}"
            )

        try:
            document = json.loads(
                completed.stdout
            )
        except json.JSONDecodeError as exc:
            raise TaskControllerError(
                "GITHUB_API_RESPONSE_INVALID"
            ) from exc

        if not isinstance(document, dict):
            raise TaskControllerError(
                "GITHUB_API_RESPONSE_INVALID"
            )

        return document

    def create_issue_comment(
        self,
        repository: str,
        issue_number: int,
        body: str,
    ) -> dict[str, Any]:
        return self._api(
            method="POST",
            path=(
                f"/repos/{repository}/issues/"
                f"{issue_number}/comments"
            ),
            payload={
                "body": body,
            },
        )

    def get_issue_comment(
        self,
        repository: str,
        comment_id: int,
    ) -> dict[str, Any]:
        return self._api(
            method="GET",
            path=(
                f"/repos/{repository}/issues/comments/"
                f"{comment_id}"
            ),
        )


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


def git(
    repo: Path,
    *args: str,
) -> str:
    completed = run(
        [
            "git",
            "-C",
            str(repo),
            *args,
        ],
        cwd=repo,
    )

    if completed.returncode:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
        )

        raise TaskControllerError(
            f"GIT_ERROR: {detail}"
        )

    return completed.stdout.strip()


def resolve_repo_root(
    candidate: Path | None,
) -> Path:
    start = (
        candidate
        or Path.cwd()
    ).resolve()

    completed = run(
        [
            "git",
            "-C",
            str(start),
            "rev-parse",
            "--show-toplevel",
        ],
        cwd=start,
    )

    if completed.returncode:
        raise TaskControllerError(
            "Unable to resolve repository root."
        )

    return Path(
        completed.stdout.strip()
    ).resolve()


def repository_slug(
    repo: Path,
) -> str:
    remote = git(
        repo,
        "remote",
        "get-url",
        "origin",
    )

    if remote.startswith(
        "git@github.com:"
    ):
        value = remote.removeprefix(
            "git@github.com:"
        )
    elif remote.startswith(
        "https://github.com/"
    ):
        value = remote.removeprefix(
            "https://github.com/"
        )
    else:
        raise TaskControllerError(
            (
                "Unsupported GitHub origin URL: "
                f"{remote}"
            )
        )

    return value.removesuffix(".git")


def configured_trusted_author(
    repository: str,
) -> str:
    owner = repository.split(
        "/",
        1,
    )[0]

    configured = os.environ.get(
        "NUTRITION_TASK_TRUSTED_AUTHOR",
        owner,
    )

    if not configured:
        raise TaskControllerError(
            "TRUSTED_AUTHOR_NOT_CONFIGURED"
        )

    return configured


def default_state_dir() -> Path:
    configured = os.environ.get(
        "NUTRITION_TASK_STATE_DIR"
    )

    if configured:
        return Path(configured).expanduser()

    return (
        Path.home()
        / ".nutrition-app"
        / "task-controller"
    )


def state_path(
    state_dir: Path,
    issue_number: int,
) -> Path:
    return (
        state_dir
        / f"issue-{issue_number}.json"
    )


def authorization_draft_path(
    state_dir: Path,
    issue_number: int,
    revision: int,
) -> Path:
    return (
        state_dir
        / (
            f"issue-{issue_number}"
            f"-revision-{revision}"
            "-authorization.md"
        )
    )


def atomic_write_json(
    path: Path,
    document: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)

        json.dump(
            document,
            handle,
            indent=2,
            sort_keys=True,
        )

        handle.write("\n")

    temporary.replace(path)


def load_state(
    state_dir: Path,
    issue_number: int,
) -> dict[str, Any]:
    path = state_path(
        state_dir,
        issue_number,
    )

    if not path.is_file():
        raise TaskControllerError(
            (
                "TASK_STATE_MISSING: "
                f"{path}"
            )
        )

    try:
        document = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as exc:
        raise TaskControllerError(
            "TASK_STATE_INVALID"
        ) from exc

    if not isinstance(document, dict):
        raise TaskControllerError(
            "TASK_STATE_INVALID"
        )

    return document


def emit(
    document: dict[str, Any],
) -> None:
    print(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def prepare_task(
    *,
    repo: Path,
    state_dir: Path,
    issue_number: int,
    task_id: str,
    trusted_author: str,
    repository: str,
    base_sha: str,
    allowed_paths: list[str],
    forbidden_paths: list[str],
    profiles: list[str],
    revision: int,
    nonce: str,
) -> dict[str, Any]:
    current_main = git(
        repo,
        "rev-parse",
        "--verify",
        "refs/remotes/origin/main",
    )

    if current_main != base_sha:
        raise TaskControllerError(
            (
                "BASE_AUTHORITY_STALE: "
                f"requested={base_sha} "
                f"origin_main={current_main}"
            )
        )

    payload = build_payload(
        task_id=task_id,
        issue_number=issue_number,
        repository=repository,
        base_sha=base_sha,
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
        profiles=profiles,
        revision=revision,
        nonce=nonce,
    )

    body = render_authorization_comment(
        payload
    )

    draft = authorization_draft_path(
        state_dir,
        issue_number,
        revision,
    )

    draft.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    draft.write_text(
        body,
        encoding="utf-8",
    )

    document: dict[str, Any] = {
        "schema_version": 1,
        "phase": "PREPARED",
        "issue_number": issue_number,
        "task_id": task_id,
        "repository": repository,
        "trusted_author": trusted_author,
        "authorization": {
            "revision": revision,
            "nonce": nonce,
            "base_sha": base_sha,
            "payload_sha256": payload[
                "payload_sha256"
            ],
            "draft_path": str(draft),
            "comment_id": None,
            "identity_sha256": None,
        },
        "qualification": None,
        "verification": None,
        "review": None,
        "integration": None,
    }

    atomic_write_json(
        state_path(
            state_dir,
            issue_number,
        ),
        document,
    )

    return document


def authorize_task(
    state: dict[str, Any],
    *,
    transport: IssueAuthorizationTransport,
) -> dict[str, Any]:
    if state.get("phase") != "PREPARED":
        raise TaskControllerError(
            "AUTHORIZATION_REQUIRES_PREPARED_STATE"
        )

    authorization_state = state.get(
        "authorization"
    )

    if not isinstance(
        authorization_state,
        dict,
    ):
        raise TaskControllerError(
            "AUTHORIZATION_STATE_INVALID"
        )

    draft_value = authorization_state.get(
        "draft_path"
    )

    if not isinstance(draft_value, str):
        raise TaskControllerError(
            "AUTHORIZATION_DRAFT_INVALID"
        )

    draft_path = Path(
        draft_value
    )

    if not draft_path.is_file():
        raise TaskControllerError(
            (
                "AUTHORIZATION_DRAFT_MISSING: "
                f"{draft_path}"
            )
        )

    body = draft_path.read_text(
        encoding="utf-8"
    )

    created = transport.create_issue_comment(
        state["repository"],
        state["issue_number"],
        body,
    )

    comment_id = created.get("id")

    if type(comment_id) is not int or comment_id < 1:
        raise TaskControllerError(
            "AUTHORIZATION_COMMENT_CREATE_INVALID"
        )

    observed = transport.get_issue_comment(
        state["repository"],
        comment_id,
    )

    if observed.get("id") != comment_id:
        raise TaskControllerError(
            "AUTHORIZATION_COMMENT_REFETCH_MISMATCH"
        )

    resolved = resolve_comment(
        observed,
        trusted_author=state[
            "trusted_author"
        ],
        expected_repository=state[
            "repository"
        ],
        expected_issue_number=state[
            "issue_number"
        ],
        expected_task_id=state[
            "task_id"
        ],
        expected_revision=authorization_state[
            "revision"
        ],
        expected_comment_id=comment_id,
        expected_payload_sha256=authorization_state[
            "payload_sha256"
        ],
    )

    updated = json.loads(
        json.dumps(state)
    )

    updated_authorization = updated[
        "authorization"
    ]

    updated_authorization[
        "comment_id"
    ] = resolved.comment_id

    updated_authorization[
        "identity_sha256"
    ] = resolved.identity_sha256

    updated_authorization[
        "author_login"
    ] = resolved.author_login

    html_url = observed.get(
        "html_url"
    )

    updated_authorization[
        "comment_url"
    ] = (
        html_url
        if isinstance(html_url, str)
        else None
    )

    updated["phase"] = "AUTHORIZED"

    return updated



class QualificationTransport(Protocol):
    def list_issue_comments(
        self,
        repository: str,
        issue_number: int,
    ) -> list[dict[str, Any]]:
        ...

    def dispatch_workflow(
        self,
        repository: str,
        workflow: str,
        ref: str,
        inputs: dict[str, str],
    ) -> dict[str, Any] | None:
        ...

    def list_workflow_runs(
        self,
        repository: str,
        workflow: str,
    ) -> list[dict[str, Any]]:
        ...

    def get_workflow_run(
        self,
        repository: str,
        run_id: int,
    ) -> dict[str, Any]:
        ...

    def list_check_runs(
        self,
        repository: str,
        candidate_sha: str,
        app_id: int,
    ) -> list[dict[str, Any]]:
        ...

    def get_check_run(
        self,
        repository: str,
        check_id: int,
    ) -> dict[str, Any]:
        ...


class CandidateRefTransport(Protocol):
    def publish_candidate_ref(
        self,
        ref_name: str,
        candidate_sha: str,
    ) -> None:
        ...

    def delete_candidate_ref(
        self,
        ref_name: str,
    ) -> None:
        ...

    def push_main(
        self,
        candidate_sha: str,
    ) -> None:
        ...

    def fetch_main(self) -> str:
        ...


class GhQualificationTransport:
    def _api(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        command = [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
        ]

        if method != "GET":
            command.extend(
                [
                    "--method",
                    method,
                ]
            )

        command.append(path)

        input_text: str | None = None

        if payload is not None:
            command.extend(
                [
                    "--input",
                    "-",
                ]
            )

            input_text = json.dumps(
                payload,
                sort_keys=True,
            )

        completed = subprocess.run(
            command,
            text=True,
            input=input_text,
            capture_output=True,
            check=False,
        )

        if completed.returncode:
            detail = (
                completed.stderr.strip()
                or completed.stdout.strip()
            )

            raise TaskControllerError(
                f"GITHUB_API_ERROR: {detail}"
            )

        output = completed.stdout.strip()

        if not output:
            return None

        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise TaskControllerError(
                "GITHUB_API_RESPONSE_INVALID"
            ) from exc

    def list_issue_comments(
        self,
        repository: str,
        issue_number: int,
    ) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        page = 1

        while True:
            document = self._api(
                method="GET",
                path=(
                    f"/repos/{repository}/issues/"
                    f"{issue_number}/comments"
                    f"?per_page=100&page={page}"
                ),
            )

            if not isinstance(document, list):
                raise TaskControllerError(
                    "ISSUE_COMMENTS_RESPONSE_INVALID"
                )

            for item in document:
                if not isinstance(item, dict):
                    raise TaskControllerError(
                        "ISSUE_COMMENTS_RESPONSE_INVALID"
                    )

                comments.append(item)

            if len(document) < 100:
                break

            page += 1

        return comments

    def dispatch_workflow(
        self,
        repository: str,
        workflow: str,
        ref: str,
        inputs: dict[str, str],
    ) -> dict[str, Any] | None:
        document = self._api(
            method="POST",
            path=(
                f"/repos/{repository}/actions/"
                f"workflows/{workflow}/dispatches"
            ),
            payload={
                "ref": ref,
                "inputs": inputs,
            },
        )

        if document is not None and not isinstance(
            document,
            dict,
        ):
            raise TaskControllerError(
                "WORKFLOW_DISPATCH_RESPONSE_INVALID"
            )

        return document

    def list_workflow_runs(
        self,
        repository: str,
        workflow: str,
    ) -> list[dict[str, Any]]:
        document = self._api(
            method="GET",
            path=(
                f"/repos/{repository}/actions/"
                f"workflows/{workflow}/runs"
                "?event=workflow_dispatch"
                "&branch=main"
                "&per_page=100"
            ),
        )

        if not isinstance(document, dict):
            raise TaskControllerError(
                "WORKFLOW_RUNS_RESPONSE_INVALID"
            )

        runs = document.get(
            "workflow_runs"
        )

        if not isinstance(runs, list):
            raise TaskControllerError(
                "WORKFLOW_RUNS_RESPONSE_INVALID"
            )

        if not all(
            isinstance(item, dict)
            for item in runs
        ):
            raise TaskControllerError(
                "WORKFLOW_RUNS_RESPONSE_INVALID"
            )

        return runs

    def get_workflow_run(
        self,
        repository: str,
        run_id: int,
    ) -> dict[str, Any]:
        document = self._api(
            method="GET",
            path=(
                f"/repos/{repository}/actions/runs/"
                f"{run_id}"
            ),
        )

        if not isinstance(document, dict):
            raise TaskControllerError(
                "WORKFLOW_RUN_RESPONSE_INVALID"
            )

        return document

    def list_check_runs(
        self,
        repository: str,
        candidate_sha: str,
        app_id: int,
    ) -> list[dict[str, Any]]:
        document = self._api(
            method="GET",
            path=(
                f"/repos/{repository}/commits/"
                f"{candidate_sha}/check-runs"
                f"?filter=all&per_page=100"
                f"&app_id={app_id}"
            ),
        )

        if not isinstance(document, dict):
            raise TaskControllerError(
                "CHECK_RUNS_RESPONSE_INVALID"
            )

        checks = document.get(
            "check_runs"
        )

        if not isinstance(checks, list):
            raise TaskControllerError(
                "CHECK_RUNS_RESPONSE_INVALID"
            )

        if not all(
            isinstance(item, dict)
            for item in checks
        ):
            raise TaskControllerError(
                "CHECK_RUNS_RESPONSE_INVALID"
            )

        return checks

    def get_check_run(
        self,
        repository: str,
        check_id: int,
    ) -> dict[str, Any]:
        document = self._api(
            method="GET",
            path=(
                f"/repos/{repository}/check-runs/"
                f"{check_id}"
            ),
        )

        if not isinstance(document, dict):
            raise TaskControllerError(
                "CHECK_RUN_RESPONSE_INVALID"
            )

        return document


class GitCandidateRefTransport:
    def __init__(
        self,
        repo: Path,
    ) -> None:
        self.repo = repo

    def publish_candidate_ref(
        self,
        ref_name: str,
        candidate_sha: str,
    ) -> None:
        git(
            self.repo,
            "check-ref-format",
            f"refs/heads/{ref_name}",
        )

        existing = git(
            self.repo,
            "ls-remote",
            "--heads",
            "origin",
            f"refs/heads/{ref_name}",
        )

        if existing:
            raise TaskControllerError(
                "CANDIDATE_REF_ALREADY_EXISTS"
            )

        git(
            self.repo,
            "push",
            "origin",
            (
                f"{candidate_sha}:"
                f"refs/heads/{ref_name}"
            ),
        )

        observed = git(
            self.repo,
            "ls-remote",
            "--heads",
            "origin",
            f"refs/heads/{ref_name}",
        )

        if not observed:
            raise TaskControllerError(
                "CANDIDATE_REF_PUBLICATION_MISSING"
            )

        observed_sha = observed.split(
            None,
            1,
        )[0]

        if observed_sha != candidate_sha:
            raise TaskControllerError(
                "CANDIDATE_REF_SHA_MISMATCH"
            )

    def delete_candidate_ref(
        self,
        ref_name: str,
    ) -> None:
        completed = run(
            [
                "git",
                "-C",
                str(self.repo),
                "push",
                "origin",
                "--delete",
                ref_name,
            ],
            cwd=self.repo,
        )

        if completed.returncode:
            detail = (
                completed.stderr.strip()
                or completed.stdout.strip()
            )

            raise TaskControllerError(
                (
                    "CANDIDATE_REF_CLEANUP_FAILED: "
                    f"{detail}"
                )
            )

        residual = git(
            self.repo,
            "ls-remote",
            "--heads",
            "origin",
            f"refs/heads/{ref_name}",
        )

        if residual:
            raise TaskControllerError(
                "CANDIDATE_REF_CLEANUP_FAILED"
            )

    def push_main(
        self,
        candidate_sha: str,
    ) -> None:
        git(
            self.repo,
            "push",
            "origin",
            f"{candidate_sha}:refs/heads/main",
        )

    def fetch_main(self) -> str:
        git(
            self.repo,
            "fetch",
            "origin",
            "main",
        )

        return git(
            self.repo,
            "rev-parse",
            "--verify",
            "refs/remotes/origin/main",
        )


def configured_qualification_app_id() -> int:
    raw = os.environ.get(
        "NUTRITION_QUALIFICATION_APP_INTEGRATION_ID",
        "",
    )

    if not raw:
        raise TaskControllerError(
            "QUALIFICATION_APP_ID_NOT_CONFIGURED"
        )

    try:
        value = int(raw)
    except ValueError as exc:
        raise TaskControllerError(
            "QUALIFICATION_APP_ID_INVALID"
        ) from exc

    if value < 1:
        raise TaskControllerError(
            "QUALIFICATION_APP_ID_INVALID"
        )

    if value == 15368:
        raise TaskControllerError(
            "DEDICATED_QUALIFICATION_APP_REQUIRED"
        )

    return value


def require_trusted_controller_identity(
    repo: Path,
    *,
    expected_repository: str,
) -> str:
    branch = git(
        repo,
        "branch",
        "--show-current",
    )

    if branch != "main":
        raise TaskControllerError(
            (
                "TRUSTED_CONTROLLER_BRANCH_INVALID: "
                f"{branch}"
            )
        )

    if git(
        repo,
        "status",
        "--porcelain=v1",
        "-uall",
    ):
        raise TaskControllerError(
            "TRUSTED_CONTROLLER_DIRTY"
        )

    repository = repository_slug(
        repo
    )

    if repository != expected_repository:
        raise TaskControllerError(
            (
                "TRUSTED_CONTROLLER_REPOSITORY_MISMATCH: "
                f"expected={expected_repository} "
                f"observed={repository}"
            )
        )

    return git(
        repo,
        "rev-parse",
        "HEAD",
    )


def require_trusted_main_controller(
    repo: Path,
    *,
    expected_repository: str,
) -> str:
    head = require_trusted_controller_identity(
        repo,
        expected_repository=expected_repository,
    )

    origin_main = git(
        repo,
        "rev-parse",
        "--verify",
        "refs/remotes/origin/main",
    )

    if head != origin_main:
        raise TaskControllerError(
            (
                "TRUSTED_CONTROLLER_MAIN_DRIFT: "
                f"head={head} "
                f"origin_main={origin_main}"
            )
        )

    return head

def require_candidate_repository(
    repo: Path,
    *,
    expected_repository: str,
) -> str:
    if git(
        repo,
        "status",
        "--porcelain=v1",
        "-uall",
    ):
        raise TaskControllerError(
            "CANDIDATE_WORKTREE_DIRTY"
        )

    repository = repository_slug(
        repo
    )

    if repository != expected_repository:
        raise TaskControllerError(
            (
                "CANDIDATE_REPOSITORY_MISMATCH: "
                f"expected={expected_repository} "
                f"observed={repository}"
            )
        )

    return git(
        repo,
        "rev-parse",
        "HEAD",
    )


def resolve_current_authorization(
    state: dict[str, Any],
    transport: QualificationTransport,
) -> ResolvedAuthorization:
    authorization_state = state.get(
        "authorization"
    )

    if not isinstance(
        authorization_state,
        dict,
    ):
        raise TaskControllerError(
            "AUTHORIZATION_STATE_INVALID"
        )

    comments = transport.list_issue_comments(
        state["repository"],
        state["issue_number"],
    )

    resolved = resolve_comments(
        comments,
        trusted_author=state[
            "trusted_author"
        ],
        expected_repository=state[
            "repository"
        ],
        expected_issue_number=state[
            "issue_number"
        ],
        expected_task_id=state[
            "task_id"
        ],
        expected_revision=authorization_state[
            "revision"
        ],
    )

    expected = {
        "comment_id": authorization_state.get(
            "comment_id"
        ),
        "payload_sha256": authorization_state.get(
            "payload_sha256"
        ),
        "identity_sha256": authorization_state.get(
            "identity_sha256"
        ),
        "base_sha": authorization_state.get(
            "base_sha"
        ),
        "nonce": authorization_state.get(
            "nonce"
        ),
        "author_login": state.get(
            "trusted_author"
        ),
    }

    observed = {
        "comment_id": resolved.comment_id,
        "payload_sha256": resolved.payload_sha256,
        "identity_sha256": resolved.identity_sha256,
        "base_sha": resolved.base_sha,
        "nonce": resolved.nonce,
        "author_login": resolved.author_login,
    }

    if observed != expected:
        raise TaskControllerError(
            (
                "AUTHORIZATION_CURRENT_IDENTITY_MISMATCH: "
                f"expected={expected} "
                f"observed={observed}"
            )
        )

    return resolved


def _workflow_title(
    state: dict[str, Any],
    dispatch_nonce: str,
    candidate_sha: str,
) -> str:
    return (
        "Trusted qualification "
        f"{state['task_id']} "
        f"{dispatch_nonce} "
        f"{candidate_sha}"
    )


def _validate_workflow_identity(
    run_document: dict[str, Any],
    *,
    expected_title: str,
    controller_main_sha: str,
) -> None:
    expected = {
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": controller_main_sha,
        "display_title": expected_title,
    }

    observed = {
        key: run_document.get(key)
        for key in expected
    }

    if observed != expected:
        raise TaskControllerError(
            (
                "WORKFLOW_RUN_IDENTITY_MISMATCH: "
                f"expected={expected} "
                f"observed={observed}"
            )
        )


def _wait_for_workflow_run(
    transport: QualificationTransport,
    *,
    repository: str,
    workflow: str,
    dispatch_response: dict[str, Any] | None,
    expected_title: str,
    controller_main_sha: str,
    poll_attempts: int,
    sleep_seconds: float,
    sleep_fn: Callable[[float], None],
) -> dict[str, Any]:
    run_id: int | None = None

    if isinstance(
        dispatch_response,
        dict,
    ):
        candidate = dispatch_response.get(
            "workflow_run_id"
        )

        if type(candidate) is int:
            run_id = candidate

    for _ in range(poll_attempts):
        run_document: dict[str, Any] | None = None

        if run_id is not None:
            run_document = (
                transport.get_workflow_run(
                    repository,
                    run_id,
                )
            )
        else:
            matches = [
                item
                for item
                in transport.list_workflow_runs(
                    repository,
                    workflow,
                )
                if item.get("display_title")
                == expected_title
            ]

            if len(matches) > 1:
                raise TaskControllerError(
                    "WORKFLOW_RUN_AMBIGUOUS"
                )

            if matches:
                run_document = matches[0]

                candidate_id = (
                    run_document.get("id")
                )

                if type(candidate_id) is not int:
                    raise TaskControllerError(
                        "WORKFLOW_RUN_ID_INVALID"
                    )

                run_id = candidate_id

        if run_document is not None:
            _validate_workflow_identity(
                run_document,
                expected_title=expected_title,
                controller_main_sha=(
                    controller_main_sha
                ),
            )

            if (
                run_document.get("status")
                == "completed"
            ):
                return run_document

        sleep_fn(sleep_seconds)

    raise TaskControllerError(
        "WORKFLOW_RUN_TIMEOUT"
    )


def _wait_for_authoritative_check(
    transport: QualificationTransport,
    *,
    repository: str,
    candidate_sha: str,
    expected_app_id: int,
    expected_external_id: str,
    poll_attempts: int,
    sleep_seconds: float,
    sleep_fn: Callable[[float], None],
) -> dict[str, Any] | None:
    for _ in range(poll_attempts):
        checks = (
            transport.list_check_runs(
                repository,
                candidate_sha,
                expected_app_id,
            )
        )

        matching = []

        for check in checks:
            app = check.get("app")

            if not isinstance(app, dict):
                continue

            if (
                check.get("name") == CHECK_NAME
                and check.get("head_sha")
                == candidate_sha
                and check.get("external_id")
                == expected_external_id
                and app.get("id")
                == expected_app_id
            ):
                matching.append(check)

        if len(matching) > 1:
            raise TaskControllerError(
                "AUTHORITATIVE_CHECK_AMBIGUOUS"
            )

        if matching:
            check = matching[0]

            if check.get("status") == "completed":
                return check

        sleep_fn(sleep_seconds)

    return None


def qualify_task(
    state: dict[str, Any],
    *,
    candidate_repo: Path,
    controller_main_sha: str,
    expected_app_id: int,
    transport: QualificationTransport,
    ref_transport: CandidateRefTransport,
    workflow: str = "trusted-qualification.yml",
    poll_attempts: int = 720,
    sleep_seconds: float = 5.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    dispatch_nonce: str | None = None,
) -> dict[str, Any]:
    if state.get("phase") != "AUTHORIZED":
        raise TaskControllerError(
            "QUALIFICATION_REQUIRES_AUTHORIZED_STATE"
        )

    if (
        type(expected_app_id) is not int
        or expected_app_id < 1
        or expected_app_id == 15368
    ):
        raise TaskControllerError(
            "DEDICATED_QUALIFICATION_APP_REQUIRED"
        )

    authorization = (
        resolve_current_authorization(
            state,
            transport,
        )
    )

    if controller_main_sha != authorization.base_sha:
        raise TaskControllerError(
            (
                "BASE_AUTHORITY_STALE: "
                f"authorization={authorization.base_sha} "
                f"controller_main={controller_main_sha}"
            )
        )

    candidate_sha = git(
        candidate_repo,
        "rev-parse",
        "HEAD",
    )

    if git(
        candidate_repo,
        "status",
        "--porcelain=v1",
        "-uall",
    ):
        raise TaskControllerError(
            "CANDIDATE_WORKTREE_DIRTY"
        )

    validate_candidate_scope(
        candidate_repo,
        authorization,
        candidate_sha=candidate_sha,
        observed_main_sha=controller_main_sha,
    )

    nonce = (
        dispatch_nonce
        or secrets.token_hex(12)
    )

    ref_name = (
        f"task-candidate/"
        f"{state['issue_number']}/"
        f"{nonce}/"
        f"{candidate_sha[:12]}"
    )

    expected_title = _workflow_title(
        state,
        nonce,
        candidate_sha,
    )

    expected_external_id = (
        "nutrition-task:"
        f"{state['issue_number']}:"
        f"{authorization.identity_sha256}:"
        f"{candidate_sha}"
    )

    inputs = {
        "task_id": state["task_id"],
        "issue_number": str(
            state["issue_number"]
        ),
        "authorization_revision": str(
            authorization.revision
        ),
        "authorization_comment_id": str(
            authorization.comment_id
        ),
        "authorization_payload_sha256": (
            authorization.payload_sha256
        ),
        "candidate_sha": candidate_sha,
        "candidate_ref": ref_name,
        "dispatch_nonce": nonce,
    }

    published = False
    updated: dict[str, Any] | None = None

    try:
        ref_transport.publish_candidate_ref(
            ref_name,
            candidate_sha,
        )

        published = True

        dispatch_response = (
            transport.dispatch_workflow(
                state["repository"],
                workflow,
                "main",
                inputs,
            )
        )

        run_document = _wait_for_workflow_run(
            transport,
            repository=state["repository"],
            workflow=workflow,
            dispatch_response=dispatch_response,
            expected_title=expected_title,
            controller_main_sha=controller_main_sha,
            poll_attempts=poll_attempts,
            sleep_seconds=sleep_seconds,
            sleep_fn=sleep_fn,
        )

        run_id = run_document.get("id")

        if type(run_id) is not int:
            raise TaskControllerError(
                "WORKFLOW_RUN_ID_INVALID"
            )

        check = _wait_for_authoritative_check(
            transport,
            repository=state["repository"],
            candidate_sha=candidate_sha,
            expected_app_id=expected_app_id,
            expected_external_id=(
                expected_external_id
            ),
            poll_attempts=poll_attempts,
            sleep_seconds=sleep_seconds,
            sleep_fn=sleep_fn,
        )

        workflow_conclusion = (
            run_document.get("conclusion")
        )

        if check is None:
            if workflow_conclusion == "success":
                raise TaskControllerError(
                    "AUTHORITATIVE_CHECK_MISSING"
                )

            result = "FAIL"
            check_id = None
            check_conclusion = None
            check_external_id = None
        else:
            check_id = check.get("id")

            if type(check_id) is not int:
                raise TaskControllerError(
                    "AUTHORITATIVE_CHECK_ID_INVALID"
                )

            check_conclusion = check.get(
                "conclusion"
            )

            check_external_id = check.get(
                "external_id"
            )

            if (
                check_conclusion == "success"
                and workflow_conclusion
                != "success"
            ):
                raise TaskControllerError(
                    "QUALIFICATION_EVIDENCE_INCONSISTENT"
                )

            result = (
                "PASS"
                if (
                    workflow_conclusion
                    == "success"
                    and check_conclusion
                    == "success"
                )
                else "FAIL"
            )

        updated = json.loads(
            json.dumps(state)
        )

        updated["qualification"] = {
            "candidate_sha": candidate_sha,
            "controller_main_sha": (
                controller_main_sha
            ),
            "candidate_ref": ref_name,
            "candidate_ref_removed": False,
            "dispatch_nonce": nonce,
            "workflow": workflow,
            "workflow_run_id": run_id,
            "workflow_run_url": (
                run_document.get("html_url")
            ),
            "workflow_conclusion": (
                workflow_conclusion
            ),
            "check_id": check_id,
            "check_app_id": (
                expected_app_id
                if check is not None
                else None
            ),
            "check_conclusion": (
                check_conclusion
            ),
            "check_external_id": (
                check_external_id
            ),
            "result": result,
        }

        updated["phase"] = (
            "QUALIFIED"
            if result == "PASS"
            else "QUALIFICATION_FAILED"
        )

    finally:
        if published:
            ref_transport.delete_candidate_ref(
                ref_name
            )

    if updated is None:
        raise TaskControllerError(
            "QUALIFICATION_RESULT_MISSING"
        )

    updated["qualification"][
        "candidate_ref_removed"
    ] = True

    return updated


def integrate_task(
    state: dict[str, Any],
    *,
    candidate_repo: Path,
    controller_main_sha: str,
    expected_app_id: int,
    transport: QualificationTransport,
    ref_transport: CandidateRefTransport,
    human_owner_authorized: bool,
) -> dict[str, Any]:
    if state.get("phase") != "REVIEWED_APPROVED":
        raise TaskControllerError(
            "INTEGRATION_REQUIRES_APPROVED_REVIEW"
        )

    if not human_owner_authorized:
        raise TaskControllerError(
            "HUMAN_OWNER_AUTHORIZATION_REQUIRED"
        )

    authorization = (
        resolve_current_authorization(
            state,
            transport,
        )
    )

    if controller_main_sha != authorization.base_sha:
        raise TaskControllerError(
            (
                "BASE_AUTHORITY_STALE: "
                f"authorization={authorization.base_sha} "
                f"controller_main={controller_main_sha}"
            )
        )

    candidate_sha = git(
        candidate_repo,
        "rev-parse",
        "HEAD",
    )

    if git(
        candidate_repo,
        "status",
        "--porcelain=v1",
        "-uall",
    ):
        raise TaskControllerError(
            "CANDIDATE_WORKTREE_DIRTY"
        )

    qualification = (
        state.get("qualification")
        or {}
    )

    verification = (
        state.get("verification")
        or {}
    )

    review = (
        state.get("review")
        or {}
    )

    if (
        qualification.get("result") != "PASS"
        or qualification.get(
            "candidate_sha"
        )
        != candidate_sha
        or qualification.get(
            "check_app_id"
        )
        != expected_app_id
        or qualification.get(
            "candidate_ref_removed"
        )
        is not True
    ):
        raise TaskControllerError(
            "INTEGRATION_QUALIFICATION_MISMATCH"
        )

    if (
        verification.get("decision") != "pass"
        or verification.get(
            "candidate_sha"
        )
        != candidate_sha
    ):
        raise TaskControllerError(
            "INTEGRATION_VERIFICATION_MISMATCH"
        )

    if (
        review.get("decision") != "approved"
        or review.get(
            "candidate_sha"
        )
        != candidate_sha
    ):
        raise TaskControllerError(
            "INTEGRATION_REVIEW_MISMATCH"
        )

    check_id = qualification.get(
        "check_id"
    )

    if type(check_id) is not int:
        raise TaskControllerError(
            "INTEGRATION_CHECK_ID_INVALID"
        )

    check = transport.get_check_run(
        state["repository"],
        check_id,
    )

    app = check.get("app")

    expected_external_id = (
        "nutrition-task:"
        f"{state['issue_number']}:"
        f"{authorization.identity_sha256}:"
        f"{candidate_sha}"
    )

    if (
        check.get("name") != CHECK_NAME
        or check.get("head_sha")
        != candidate_sha
        or check.get("status")
        != "completed"
        or check.get("conclusion")
        != "success"
        or check.get("external_id")
        != expected_external_id
        or not isinstance(app, dict)
        or app.get("id")
        != expected_app_id
    ):
        raise TaskControllerError(
            "INTEGRATION_CHECK_REVALIDATION_FAILED"
        )

    updated = json.loads(
        json.dumps(state)
    )

    updated["integration"] = {
        "candidate_sha": candidate_sha,
        "controller_main_sha": (
            controller_main_sha
        ),
        "check_id": check_id,
        "check_app_id": expected_app_id,
        "human_owner_authorized": True,
        "origin_main_before": (
            controller_main_sha
        ),
        "origin_main_after": None,
    }

    updated["phase"] = (
        "INTEGRATION_PENDING"
    )

    return updated


def reconcile_integration(
    state: dict[str, Any],
    *,
    candidate_sha: str,
    ref_transport: CandidateRefTransport,
) -> dict[str, Any]:
    phase = state.get("phase")

    if phase not in {
        "INTEGRATION_PENDING",
        "INTEGRATED",
    }:
        raise TaskControllerError(
            "INTEGRATION_RECONCILIATION_STATE_INVALID"
        )

    integration = (
        state.get("integration")
        or {}
    )

    if (
        integration.get("candidate_sha")
        != candidate_sha
        or integration.get(
            "human_owner_authorized"
        )
        is not True
    ):
        raise TaskControllerError(
            "INTEGRATION_RECOVERY_STATE_INVALID"
        )

    origin_main_before = integration.get(
        "origin_main_before"
    )

    if not isinstance(
        origin_main_before,
        str,
    ) or not origin_main_before:
        raise TaskControllerError(
            "INTEGRATION_RECOVERY_STATE_INVALID"
        )

    observed_main = (
        ref_transport.fetch_main()
    )

    if observed_main == candidate_sha:
        pass
    elif (
        phase == "INTEGRATION_PENDING"
        and observed_main
        == origin_main_before
    ):
        ref_transport.push_main(
            candidate_sha
        )

        observed_main = (
            ref_transport.fetch_main()
        )
    else:
        raise TaskControllerError(
            (
                "INTEGRATION_MAIN_DIVERGED: "
                f"before={origin_main_before} "
                f"candidate={candidate_sha} "
                f"observed={observed_main}"
            )
        )

    if observed_main != candidate_sha:
        raise TaskControllerError(
            (
                "INTEGRATION_MAIN_SHA_MISMATCH: "
                f"expected={candidate_sha} "
                f"observed={observed_main}"
            )
        )

    updated = json.loads(
        json.dumps(state)
    )

    updated["integration"][
        "origin_main_after"
    ] = observed_main

    updated["phase"] = "INTEGRATED"

    return updated

def record_qualification(
    state: dict[str, Any],
    *,
    candidate_sha: str,
    workflow_run_id: int,
    check_id: int,
    check_app_id: int,
    result: str,
) -> dict[str, Any]:
    if result not in {
        "PASS",
        "FAIL",
    }:
        raise TaskControllerError(
            "QUALIFICATION_RESULT_INVALID"
        )

    updated = dict(state)

    updated["qualification"] = {
        "candidate_sha": candidate_sha,
        "workflow_run_id": workflow_run_id,
        "check_id": check_id,
        "check_app_id": check_app_id,
        "result": result,
    }

    updated["phase"] = (
        "QUALIFIED"
        if result == "PASS"
        else "QUALIFICATION_FAILED"
    )

    return updated


def record_verification(
    state: dict[str, Any],
    *,
    candidate_sha: str,
    actor: str,
    decision: str,
    evidence: str,
) -> dict[str, Any]:
    if decision not in {
        "pass",
        "fail",
    }:
        raise TaskControllerError(
            "VERIFICATION_DECISION_INVALID"
        )

    if decision == "pass":
        qualification = (
            state.get("qualification")
            or {}
        )

        if (
            qualification.get("result")
            != "PASS"
            or qualification.get(
                "candidate_sha"
            )
            != candidate_sha
        ):
            raise TaskControllerError(
                (
                    "VERIFICATION_REQUIRES_"
                    "EXACT_QUALIFICATION"
                )
            )

    updated = dict(state)

    updated["verification"] = {
        "candidate_sha": candidate_sha,
        "actor": actor,
        "decision": decision,
        "evidence": evidence,
    }

    updated["phase"] = (
        "VERIFIED"
        if decision == "pass"
        else "VERIFICATION_FAILED"
    )

    return updated


def record_review(
    state: dict[str, Any],
    *,
    candidate_sha: str,
    actor: str,
    decision: str,
    summary: str,
) -> dict[str, Any]:
    if decision not in {
        "approved",
        "changes-requested",
    }:
        raise TaskControllerError(
            "REVIEW_DECISION_INVALID"
        )

    if decision == "approved":
        verification = (
            state.get("verification")
            or {}
        )

        if (
            verification.get("decision")
            != "pass"
            or verification.get(
                "candidate_sha"
            )
            != candidate_sha
        ):
            raise TaskControllerError(
                (
                    "REVIEW_APPROVAL_REQUIRES_"
                    "EXACT_VERIFICATION"
                )
            )

    updated = dict(state)

    updated["review"] = {
        "candidate_sha": candidate_sha,
        "actor": actor,
        "decision": decision,
        "summary": summary,
    }

    updated["phase"] = (
        "REVIEWED_APPROVED"
        if decision == "approved"
        else "REVIEWED_CHANGES_REQUESTED"
    )

    return updated


def command_prepare(
    args: argparse.Namespace,
) -> int:
    repo = resolve_repo_root(
        args.repo_root
    )

    repository = (
        args.repository
        or repository_slug(repo)
    )

    git(
        repo,
        "fetch",
        "origin",
        "main",
    )

    require_trusted_main_controller(
        repo,
        expected_repository=repository,
    )

    base_sha = (
        args.base_sha
        or git(
            repo,
            "rev-parse",
            "--verify",
            "refs/remotes/origin/main",
        )
    )

    nonce = (
        args.nonce
        or secrets.token_hex(16)
    )

    configured_author = configured_trusted_author(
        repository
    )

    if (
        args.trusted_author is not None
        and args.trusted_author
        != configured_author
    ):
        raise TaskControllerError(
            (
                "TRUSTED_AUTHOR_MISMATCH: "
                f"configured={configured_author} "
                f"requested={args.trusted_author}"
            )
        )

    state = prepare_task(
        repo=repo,
        state_dir=args.state_dir,
        issue_number=args.issue_number,
        task_id=args.task_id,
        trusted_author=configured_author,
        repository=repository,
        base_sha=base_sha,
        allowed_paths=args.allowed_path,
        forbidden_paths=args.forbidden_path,
        profiles=args.profile,
        revision=args.revision,
        nonce=nonce,
    )

    emit(
        {
            "task": state["task_id"],
            "issue": state[
                "issue_number"
            ],
            "phase": state["phase"],
            "base_sha": state[
                "authorization"
            ]["base_sha"],
            "authorization_payload_sha256": (
                state[
                    "authorization"
                ][
                    "payload_sha256"
                ]
            ),
            "authorization_draft": state[
                "authorization"
            ][
                "draft_path"
            ],
            "next": "authorize",
        }
    )

    return 0


def command_authorize(
    args: argparse.Namespace,
) -> int:
    state = load_state(
        args.state_dir,
        args.issue_number,
    )

    repo = resolve_repo_root(
        args.repo_root
    )

    git(
        repo,
        "fetch",
        "origin",
        "main",
    )

    require_trusted_main_controller(
        repo,
        expected_repository=state[
            "repository"
        ],
    )

    updated = authorize_task(
        state,
        transport=(
            GhIssueAuthorizationTransport()
        ),
    )

    atomic_write_json(
        state_path(
            args.state_dir,
            args.issue_number,
        ),
        updated,
    )

    authorization = updated[
        "authorization"
    ]

    emit(
        {
            "task": updated["task_id"],
            "issue": updated[
                "issue_number"
            ],
            "phase": updated["phase"],
            "authorization_comment_id": (
                authorization[
                    "comment_id"
                ]
            ),
            "authorization_identity_sha256": (
                authorization[
                    "identity_sha256"
                ]
            ),
            "authorization_author": (
                authorization[
                    "author_login"
                ]
            ),
            "next": "qualify",
        }
    )

    return 0


def command_qualify(
    args: argparse.Namespace,
) -> int:
    state = load_state(
        args.state_dir,
        args.issue_number,
    )

    repo = resolve_repo_root(
        args.repo_root
    )

    git(
        repo,
        "fetch",
        "origin",
        "main",
    )

    controller_main_sha = (
        require_trusted_main_controller(
            repo,
            expected_repository=state[
                "repository"
            ],
        )
    )

    candidate_repo = (
        resolve_repo_root(
            args.candidate_root
        )
    )

    require_candidate_repository(
        candidate_repo,
        expected_repository=state[
            "repository"
        ],
    )

    expected_app_id = (
        configured_qualification_app_id()
    )

    updated = qualify_task(
        state,
        candidate_repo=candidate_repo,
        controller_main_sha=(
            controller_main_sha
        ),
        expected_app_id=(
            expected_app_id
        ),
        transport=(
            GhQualificationTransport()
        ),
        ref_transport=(
            GitCandidateRefTransport(
                candidate_repo
            )
        ),
    )

    atomic_write_json(
        state_path(
            args.state_dir,
            args.issue_number,
        ),
        updated,
    )

    qualification = updated[
        "qualification"
    ]

    emit(
        {
            "task": updated["task_id"],
            "issue": updated[
                "issue_number"
            ],
            "phase": updated["phase"],
            "candidate_sha": (
                qualification[
                    "candidate_sha"
                ]
            ),
            "workflow_run_id": (
                qualification[
                    "workflow_run_id"
                ]
            ),
            "check_id": (
                qualification[
                    "check_id"
                ]
            ),
            "check_app_id": (
                qualification[
                    "check_app_id"
                ]
            ),
            "result": qualification[
                "result"
            ],
            "candidate_ref_removed": (
                qualification[
                    "candidate_ref_removed"
                ]
            ),
            "next": (
                "verify"
                if qualification[
                    "result"
                ]
                == "PASS"
                else "rework"
            ),
        }
    )

    return (
        0
        if qualification["result"]
        == "PASS"
        else 1
    )


def command_status(
    args: argparse.Namespace,
) -> int:
    state = load_state(
        args.state_dir,
        args.issue_number,
    )

    emit(state)
    return 0


def command_verify(
    args: argparse.Namespace,
) -> int:
    state = load_state(
        args.state_dir,
        args.issue_number,
    )

    repo = resolve_repo_root(
        args.repo_root
    )

    git(
        repo,
        "fetch",
        "origin",
        "main",
    )

    require_trusted_main_controller(
        repo,
        expected_repository=state[
            "repository"
        ],
    )

    updated = record_verification(
        state,
        candidate_sha=args.candidate_sha,
        actor=args.actor,
        decision=args.decision,
        evidence=args.evidence,
    )

    atomic_write_json(
        state_path(
            args.state_dir,
            args.issue_number,
        ),
        updated,
    )

    emit(
        {
            "task": updated["task_id"],
            "issue": updated[
                "issue_number"
            ],
            "phase": updated["phase"],
            "candidate_sha": (
                args.candidate_sha
            ),
            "decision": args.decision,
            "next": (
                "review"
                if args.decision == "pass"
                else "rework"
            ),
        }
    )

    return 0


def command_review(
    args: argparse.Namespace,
) -> int:
    state = load_state(
        args.state_dir,
        args.issue_number,
    )

    repo = resolve_repo_root(
        args.repo_root
    )

    git(
        repo,
        "fetch",
        "origin",
        "main",
    )

    require_trusted_main_controller(
        repo,
        expected_repository=state[
            "repository"
        ],
    )

    updated = record_review(
        state,
        candidate_sha=args.candidate_sha,
        actor=args.actor,
        decision=args.decision,
        summary=args.summary,
    )

    atomic_write_json(
        state_path(
            args.state_dir,
            args.issue_number,
        ),
        updated,
    )

    emit(
        {
            "task": updated["task_id"],
            "issue": updated[
                "issue_number"
            ],
            "phase": updated["phase"],
            "candidate_sha": (
                args.candidate_sha
            ),
            "decision": args.decision,
            "next": (
                "integrate"
                if args.decision == "approved"
                else "rework"
            ),
        }
    )

    return 0


def command_integrate(
    args: argparse.Namespace,
) -> int:
    state = load_state(
        args.state_dir,
        args.issue_number,
    )

    repo = resolve_repo_root(
        args.repo_root
    )

    git(
        repo,
        "fetch",
        "origin",
        "main",
    )

    candidate_repo = (
        resolve_repo_root(
            args.candidate_root
        )
    )

    candidate_sha = (
        require_candidate_repository(
            candidate_repo,
            expected_repository=state[
                "repository"
            ],
        )
    )

    expected_app_id = (
        configured_qualification_app_id()
    )

    state_file = state_path(
        args.state_dir,
        args.issue_number,
    )

    phase = state.get("phase")

    if phase == "REVIEWED_APPROVED":
        controller_main_sha = (
            require_trusted_main_controller(
                repo,
                expected_repository=state[
                    "repository"
                ],
            )
        )

        pending = integrate_task(
            state,
            candidate_repo=candidate_repo,
            controller_main_sha=(
                controller_main_sha
            ),
            expected_app_id=(
                expected_app_id
            ),
            transport=(
                GhQualificationTransport()
            ),
            ref_transport=(
                GitCandidateRefTransport(
                    candidate_repo
                )
            ),
            human_owner_authorized=(
                args.human_owner_authorized
            ),
        )

        # Durably record integration intent and all
        # revalidated authority before mutating remote main.
        atomic_write_json(
            state_file,
            pending,
        )

        state = pending

    elif phase in {
        "INTEGRATION_PENDING",
        "INTEGRATED",
    }:
        controller_head = (
            require_trusted_controller_identity(
                repo,
                expected_repository=state[
                    "repository"
                ],
            )
        )

        integration = (
            state.get("integration")
            or {}
        )

        controller_main_sha = (
            integration.get(
                "controller_main_sha"
            )
        )

        if (
            not isinstance(
                controller_main_sha,
                str,
            )
            or not controller_main_sha
            or integration.get(
                "candidate_sha"
            )
            != candidate_sha
            or integration.get(
                "check_app_id"
            )
            != expected_app_id
            or integration.get(
                "human_owner_authorized"
            )
            is not True
        ):
            raise TaskControllerError(
                "INTEGRATION_RECOVERY_STATE_INVALID"
            )

        if controller_head not in {
            controller_main_sha,
            candidate_sha,
        }:
            raise TaskControllerError(
                (
                    "INTEGRATION_CONTROLLER_HEAD_INVALID: "
                    f"controller={controller_head} "
                    f"base={controller_main_sha} "
                    f"candidate={candidate_sha}"
                )
            )

    else:
        raise TaskControllerError(
            "INTEGRATION_REQUIRES_APPROVED_REVIEW"
        )

    ref_transport = (
        GitCandidateRefTransport(
            candidate_repo
        )
    )

    updated = reconcile_integration(
        state,
        candidate_sha=candidate_sha,
        ref_transport=ref_transport,
    )

    # Persist completion immediately after remote-main
    # reconciliation. A rerun from either pending or
    # integrated state is idempotent.
    atomic_write_json(
        state_file,
        updated,
    )

    git(
        repo,
        "fetch",
        "origin",
        "main",
    )

    git(
        repo,
        "merge",
        "--ff-only",
        "refs/remotes/origin/main",
    )

    local_head = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    if local_head != candidate_sha:
        raise TaskControllerError(
            (
                "LOCAL_MAIN_SYNC_FAILED: "
                f"expected={candidate_sha} "
                f"observed={local_head}"
            )
        )

    emit(
        {
            "task": updated["task_id"],
            "issue": updated[
                "issue_number"
            ],
            "phase": updated["phase"],
            "candidate_sha": (
                candidate_sha
            ),
            "check_id": updated[
                "integration"
            ]["check_id"],
            "origin_main": updated[
                "integration"
            ]["origin_main_after"],
            "human_owner_authorized": True,
            "next": "cleanup",
        }
    )

    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Candidate-independent Nutrition App "
            "task controller."
        )
    )

    parser.add_argument(
        "--repo-root",
        type=Path,
    )

    parser.add_argument(
        "--state-dir",
        type=Path,
        default=default_state_dir(),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    prepare = subparsers.add_parser(
        "prepare"
    )

    prepare.add_argument(
        "issue_number",
        type=int,
    )
    prepare.add_argument(
        "--task-id",
        required=True,
    )
    prepare.add_argument(
        "--trusted-author",
        help=(
            "Must match the configured trusted "
            "authorization identity. Defaults to "
            "repository owner unless "
            "NUTRITION_TASK_TRUSTED_AUTHOR is set."
        ),
    )
    prepare.add_argument(
        "--repository",
    )
    prepare.add_argument(
        "--base-sha",
    )
    prepare.add_argument(
        "--allowed-path",
        action="append",
        default=[],
        required=True,
    )
    prepare.add_argument(
        "--forbidden-path",
        action="append",
        default=[],
    )
    prepare.add_argument(
        "--profile",
        action="append",
        default=[],
        required=True,
    )
    prepare.add_argument(
        "--revision",
        type=int,
        default=1,
    )
    prepare.add_argument(
        "--nonce",
    )
    prepare.set_defaults(
        handler=command_prepare
    )

    authorize = subparsers.add_parser(
        "authorize"
    )
    authorize.add_argument(
        "issue_number",
        type=int,
    )
    authorize.set_defaults(
        handler=command_authorize
    )

    qualify = subparsers.add_parser(
        "qualify"
    )
    qualify.add_argument(
        "issue_number",
        type=int,
    )
    qualify.add_argument(
        "--candidate-root",
        type=Path,
        required=True,
    )
    qualify.set_defaults(
        handler=command_qualify
    )

    status = subparsers.add_parser(
        "status"
    )
    status.add_argument(
        "issue_number",
        type=int,
    )
    status.set_defaults(
        handler=command_status
    )

    verify = subparsers.add_parser(
        "verify"
    )
    verify.add_argument(
        "issue_number",
        type=int,
    )
    verify.add_argument(
        "--candidate-sha",
        required=True,
    )
    verify.add_argument(
        "--actor",
        required=True,
    )
    verify.add_argument(
        "--decision",
        choices=[
            "pass",
            "fail",
        ],
        required=True,
    )
    verify.add_argument(
        "--evidence",
        required=True,
    )
    verify.set_defaults(
        handler=command_verify
    )

    review = subparsers.add_parser(
        "review"
    )
    review.add_argument(
        "issue_number",
        type=int,
    )
    review.add_argument(
        "--candidate-sha",
        required=True,
    )
    review.add_argument(
        "--actor",
        required=True,
    )
    review.add_argument(
        "--decision",
        choices=[
            "approved",
            "changes-requested",
        ],
        required=True,
    )
    review.add_argument(
        "--summary",
        required=True,
    )
    review.set_defaults(
        handler=command_review
    )

    integrate = subparsers.add_parser(
        "integrate"
    )
    integrate.add_argument(
        "issue_number",
        type=int,
    )
    integrate.add_argument(
        "--candidate-root",
        type=Path,
        required=True,
    )
    integrate.add_argument(
        "--human-owner-authorized",
        action="store_true",
    )
    integrate.set_defaults(
        handler=command_integrate
    )

    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.handler(args)
    except (
        AuthorizationError,
        TaskControllerError,
        OSError,
    ) as exc:
        emit(
            {
                "result": "FAIL",
                "error": str(exc),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
