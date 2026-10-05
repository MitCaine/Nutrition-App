#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
    canonical_json,
    render_authorization_comment,
    resolve_comment,
    resolve_comments,
    validate_candidate_scope,
)

from lib.trusted_qualification import CHECK_NAME
from lib.capsule_contract import (ExecutionError, EvidenceError,
    GOVERNING_ISSUE_REPLAN_REQUIRED, GOVERNING_ISSUE_REVALIDATION_UNAVAILABLE,
    GOVERNING_ISSUE_REVALIDATION_INVALID)
from lib import task_closeout
from lib.ri_consumer import RIError


def _legacy_evidence():
    """Load mutating historical recovery capabilities only for an explicit old lane."""
    from lib.legacy_ri import candidate_evidence
    return candidate_evidence


class TaskControllerError(RuntimeError):
    pass


WORKFLOW_MODE_MARKER = "<!-- nutrition-task-workflow:v1 -->"
WORKFLOW_MODE_BLOCK_PATTERN = re.compile(
    r"```nutrition-task-workflow-v1[ \t]*\r?\n(?P<body>.*?)[ \t]*\r?\n```",
    re.DOTALL,
)
WORKFLOW_MODE_REASON_MAX_LENGTH = 500


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

    def get_issue(
        self,
        repository: str,
        issue_number: int,
    ) -> dict[str, Any]:
        return self._api(
            method="GET",
            path=f"/repos/{repository}/issues/{issue_number}",
        )


def revalidate_attached_governing_issue(attached: dict[str, Any]) -> None:
    """Fail closed unless the live issue still matches its attached material fields."""
    binding = attached.get("binding")
    authorization = binding.get("authorization") if isinstance(binding, dict) else None
    if not isinstance(authorization, dict):
        raise EvidenceError(GOVERNING_ISSUE_REPLAN_REQUIRED)

    repository = authorization.get("repository")
    issue_number = authorization.get("issue_number")
    if (not isinstance(repository, str) or not repository
            or type(issue_number) is not int):
        raise EvidenceError(GOVERNING_ISSUE_REPLAN_REQUIRED)

    try:
        issue = GhIssueAuthorizationTransport().get_issue(repository, issue_number)
    except TaskControllerError as exc:
        code = (GOVERNING_ISSUE_REVALIDATION_INVALID
                if str(exc) == "GITHUB_API_RESPONSE_INVALID"
                else GOVERNING_ISSUE_REVALIDATION_UNAVAILABLE)
        raise EvidenceError(code) from exc
    except UnicodeError as exc:
        raise EvidenceError(
            GOVERNING_ISSUE_REVALIDATION_INVALID
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError(
            GOVERNING_ISSUE_REVALIDATION_UNAVAILABLE
        ) from exc

    _legacy_evidence().revalidate_governing_issue(binding, issue)


def persist_governing_issue_replan(
    state: dict[str, Any],
    path: Path,
    candidate_sha: str | None = None,
) -> None:
    state["phase"] = "STOP_REPLAN"
    state["governing_issue_replan"] = {
        "reason": GOVERNING_ISSUE_REPLAN_REQUIRED,
        "candidate_sha": candidate_sha,
    }
    atomic_write_json(path, state)


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


def _normalize_workflow_selection(
    mode: str,
    reason: str | None,
) -> dict[str, Any]:
    if not isinstance(mode, str) or mode not in {"standard", "attached", "compatibility"}:
        raise TaskControllerError("WORKFLOW_MODE_INVALID")

    if mode == "compatibility":
        if not isinstance(reason, str):
            raise TaskControllerError("WORKFLOW_COMPATIBILITY_REASON_REQUIRED")
        normalized_reason = reason.strip()
        if (
            not 1 <= len(normalized_reason) <= WORKFLOW_MODE_REASON_MAX_LENGTH
            or WORKFLOW_MODE_MARKER in normalized_reason
        ):
            raise TaskControllerError("WORKFLOW_COMPATIBILITY_REASON_INVALID")
        reason = normalized_reason
    elif reason is not None and reason != "":
        raise TaskControllerError("WORKFLOW_REASON_NOT_APPLICABLE")
    else:
        reason = None

    return {"schema_version": 1, "mode": mode, "reason": reason}


def _workflow_selection_digest(selection: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(selection).encode()).hexdigest()


def _render_workflow_selection(
    selection: dict[str, Any],
) -> str:
    return (
        f"{WORKFLOW_MODE_MARKER}\n"
        "```nutrition-task-workflow-v1\n"
        + json.dumps(selection, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n```\n"
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_workflow_selection(body: Any) -> tuple[dict[str, Any], str]:
    if not isinstance(body, str) or body.count(WORKFLOW_MODE_MARKER) != 1:
        raise TaskControllerError("WORKFLOW_SELECTION_MARKER_INVALID")

    matches = list(WORKFLOW_MODE_BLOCK_PATTERN.finditer(body))
    marker_at = body.index(WORKFLOW_MODE_MARKER)
    if len(matches) != 1 or matches[0].start() < marker_at:
        raise TaskControllerError("WORKFLOW_SELECTION_BLOCK_INVALID")

    try:
        parsed = json.loads(
            matches[0].group("body"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TaskControllerError("WORKFLOW_SELECTION_JSON_INVALID") from exc

    if not isinstance(parsed, dict) or set(parsed) != {"schema_version", "mode", "reason"}:
        raise TaskControllerError("WORKFLOW_SELECTION_FIELDS_INVALID")
    if type(parsed["schema_version"]) is not int or parsed["schema_version"] != 1:
        raise TaskControllerError("WORKFLOW_SELECTION_SCHEMA_UNSUPPORTED")

    selection = _normalize_workflow_selection(parsed["mode"], parsed["reason"])
    if parsed != selection:
        raise TaskControllerError("WORKFLOW_SELECTION_NOT_CANONICAL")
    return selection, _workflow_selection_digest(selection)


def workflow_mode_for_state(
    state: dict[str, Any],
    *,
    require_authority: bool = True,
) -> str:
    """Return the explicit mode, retaining the pre-change compatibility route."""
    workflow = state.get("workflow")
    authorization = state.get("authorization")
    authorization = authorization if isinstance(authorization, dict) else {}

    if workflow is None:
        if "workflow_selection_sha256" in authorization:
            raise TaskControllerError("WORKFLOW_MODE_STATE_INCOMPLETE")
        return "attached" if "capsule_evidence" in state else "compatibility"

    if not isinstance(workflow, dict) or set(workflow) != {
        "mode", "reason", "selection_sha256", "authority"
    }:
        raise TaskControllerError("WORKFLOW_MODE_STATE_INVALID")

    selection = _normalize_workflow_selection(workflow["mode"], workflow["reason"])
    selection_sha256 = _workflow_selection_digest(selection)
    if (
        workflow["selection_sha256"] != selection_sha256
        or authorization.get("workflow_selection_sha256") != selection_sha256
    ):
        raise TaskControllerError("WORKFLOW_SELECTION_DIGEST_MISMATCH")

    authority = workflow["authority"]
    if authority is None:
        if require_authority:
            raise TaskControllerError("WORKFLOW_AUTHORITY_REQUIRED")
        return selection["mode"]

    if not isinstance(authority, dict) or set(authority) != {
        "comment_id", "author_login", "authorization_identity_sha256", "selection_sha256"
    }:
        raise TaskControllerError("WORKFLOW_AUTHORITY_INVALID")
    if (
        type(authority["comment_id"]) is not int
        or authority["comment_id"] < 1
        or not isinstance(authority["author_login"], str)
        or not authority["author_login"]
        or not isinstance(authority["authorization_identity_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", authority["authorization_identity_sha256"])
        or authority["selection_sha256"] != selection_sha256
        or authority["comment_id"] != authorization.get("comment_id")
        or authority["author_login"] != authorization.get("author_login")
        or authority["authorization_identity_sha256"] != authorization.get("identity_sha256")
    ):
        raise TaskControllerError("WORKFLOW_AUTHORITY_MISMATCH")
    return selection["mode"]


def _require_workflow_candidate_attachment(
    state: dict[str, Any],
    *,
    mode: str,
    candidate_sha: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if mode == "standard" and "capsule_evidence" in state:
        raise EvidenceError("FRESH_CANDIDATE_ATTACHMENT_REQUIRED")
    attached = state.get("capsule_evidence")
    if mode != "attached" and "capsule_evidence" not in state:
        return None, None

    if not isinstance(attached, dict):
        raise EvidenceError("FRESH_CANDIDATE_ATTACHMENT_REQUIRED")
    binding = attached.get("binding")
    if (
        not isinstance(binding, dict)
        or binding.get("candidate") != candidate_sha
        or attached.get("requires_fresh_candidate")
    ):
        raise EvidenceError("FRESH_CANDIDATE_ATTACHMENT_REQUIRED")
    return attached, binding


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
    workflow_mode: str = "standard",
    compatibility_reason: str | None = None,
) -> dict[str, Any]:
    if state_path(state_dir, issue_number).exists():
        raise TaskControllerError("TASK_STATE_EXISTS_PRESERVE_HISTORY")
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

    workflow_selection = _normalize_workflow_selection(
        workflow_mode,
        compatibility_reason,
    )
    workflow_selection_sha256 = _workflow_selection_digest(workflow_selection)

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

    body = render_authorization_comment(payload).rstrip() + "\n\n" + _render_workflow_selection(
        workflow_selection
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
        "workflow": {
            "mode": workflow_selection["mode"],
            "reason": workflow_selection["reason"],
            "selection_sha256": workflow_selection_sha256,
            "authority": None,
        },
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
            "workflow_selection_sha256": workflow_selection_sha256,
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
    prepared_mode = workflow_mode_for_state(
        state,
        require_authority=False,
    )
    prepared_selection, prepared_selection_sha256 = _parse_workflow_selection(body)
    workflow = state["workflow"]
    if (
        prepared_selection["mode"] != prepared_mode
        or prepared_selection["reason"] != workflow["reason"]
        or prepared_selection_sha256 != workflow["selection_sha256"]
    ):
        raise TaskControllerError("WORKFLOW_DRAFT_SELECTION_MISMATCH")

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
    observed_selection, observed_selection_sha256 = _parse_workflow_selection(
        observed.get("body")
    )
    if (
        observed_selection != prepared_selection
        or observed_selection_sha256 != prepared_selection_sha256
    ):
        raise TaskControllerError("WORKFLOW_AUTHORIZATION_SELECTION_MISMATCH")

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

    updated["workflow"]["authority"] = {
        "comment_id": resolved.comment_id,
        "author_login": resolved.author_login,
        "authorization_identity_sha256": resolved.identity_sha256,
        "selection_sha256": observed_selection_sha256,
    }

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

    matching_comments = [
        comment for comment in comments
        if comment.get("id") == resolved.comment_id
    ]
    if len(matching_comments) != 1:
        raise TaskControllerError("AUTHORIZATION_COMMENT_REFETCH_INVALID")
    comment_body = matching_comments[0].get("body")
    workflow = state.get("workflow")
    mode_marker_present = (
        isinstance(comment_body, str)
        and WORKFLOW_MODE_MARKER in comment_body
    )
    if workflow is None:
        if (
            mode_marker_present
            or "workflow_selection_sha256" in authorization_state
        ):
            raise TaskControllerError("WORKFLOW_MODE_STATE_INCOMPLETE")
    else:
        mode = workflow_mode_for_state(state)
        selection, selection_sha256 = _parse_workflow_selection(comment_body)
        authority = workflow.get("authority")
        expected_authority = {
            "comment_id": resolved.comment_id,
            "author_login": resolved.author_login,
            "authorization_identity_sha256": resolved.identity_sha256,
            "selection_sha256": selection_sha256,
        }
        if (
            selection["mode"] != mode
            or selection["reason"] != workflow.get("reason")
            or selection_sha256 != workflow.get("selection_sha256")
            or authority != expected_authority
        ):
            raise TaskControllerError("WORKFLOW_AUTHORITY_CURRENT_IDENTITY_MISMATCH")

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


def require_review_preflight(attached: dict, binding: dict, candidate_sha: str, *,
                             runtime: Path | None = None, runtime_sha256: str | None = None,
                             model: str | None = None, effort: str | None = None,
                             runtime_version: str = "0.153.4",
                             setup_identity: dict | None = None) -> dict:
    """Historical attached-state validator; no reviewer dispatch interface remains."""
    preflight = attached.get("review_preflight")
    if (not isinstance(preflight, dict)
            or preflight.get("binding_sha256") != binding["binding_sha256"]
            or preflight.get("candidate_sha") != candidate_sha
            or preflight.get("failure_count") != len(attached.get("pre_review_failures", []))
            or not isinstance(preflight.get("model"), str) or not preflight["model"]
            or not isinstance(preflight.get("effort"), str) or not preflight["effort"]
            or not isinstance(preflight.get("runtime"), dict)
            or not isinstance(preflight["runtime"].get("executable"), str)
            or not Path(preflight["runtime"]["executable"]).is_absolute()
            or preflight["runtime"].get("version", "0.153.4") not in ("0.153.4", "0.159.2")
            or not isinstance(preflight["runtime"].get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", preflight["runtime"].get("sha256", ""))):
        raise EvidenceError("REVIEW_PREFLIGHT_REQUIRED_OR_STALE")
    if runtime is not None and (
            str(runtime.resolve()) != preflight["runtime"]["executable"]
            or runtime_sha256 != preflight["runtime"]["sha256"]
            or runtime_version != preflight["runtime"].get("version", "0.153.4")
            or model != preflight["model"] or effort != preflight["effort"]):
        raise EvidenceError("REVIEW_SELECTION_NOT_PREFLIGHTED")
    if preflight.get("setup_identity", {}) != (setup_identity or {}):
        raise EvidenceError("REVIEW_SETUP_NOT_PREFLIGHTED")
    return preflight


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
    mode = workflow_mode_for_state(state)

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

    attached, binding = _require_workflow_candidate_attachment(
        state,
        mode=mode,
        candidate_sha=candidate_sha,
    )
    if attached is not None and binding is not None:
        _legacy_evidence().authenticate_binding(binding, authorization, candidate_sha)
        if not _legacy_evidence().source_matches(
            binding["source"], _legacy_evidence().observe(candidate_repo, candidate_sha)):
            raise EvidenceError("ATTACHED_SOURCE_CHANGED")
        require_review_preflight(attached, binding, candidate_sha)

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
    source_main_after: str | None = None,
    source_added_refs: dict[str, str] | None = None,
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
    mode = workflow_mode_for_state(state)

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

    if mode == "standard":
        _require_workflow_candidate_attachment(state, mode=mode, candidate_sha=candidate_sha)
    if mode == "attached" or "capsule_evidence" in state:
        _legacy_evidence().gate(state, candidate_sha, review_required=True)
    if "capsule_evidence" in state:
        attached = state["capsule_evidence"]
        _legacy_evidence().authenticate_binding(attached["binding"], authorization, candidate_sha)
        revalidate_attached_governing_issue(attached)
        _legacy_evidence().revalidate_manual(attached, GhIssueAuthorizationTransport())
        _legacy_evidence().qualify(attached["binding"], qualification, check, expected_app_id)
        integration_receipt = state.get("integration") or {}
        main_transition = None
        if (integration_receipt.get("candidate_sha") == candidate_sha
                and integration_receipt.get("controller_main_sha") == controller_main_sha
                and integration_receipt.get("human_owner_authorized") is True
                and type(integration_receipt.get("check_id")) is int):
            main_transition = (controller_main_sha, source_main_after or candidate_sha)
        if not _legacy_evidence().source_matches(
            attached["binding"]["source"], _legacy_evidence().observe(candidate_repo, candidate_sha),
            main_transition=main_transition, added_refs=source_added_refs):
            raise EvidenceError("ATTACHED_SOURCE_CHANGED")

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


def revalidate_integration_state(
    state: dict[str, Any], *, candidate_repo: Path,
    expected_app_id: int, transport: QualificationTransport,
    ref_transport: CandidateRefTransport,
    source_main_after: str | None = None,
    source_added_refs: dict[str, str] | None = None,
) -> None:
    """Recheck live authority/check/review before resuming an accepted push."""
    integration = state.get("integration") or {}
    base = integration.get("controller_main_sha")
    if state.get("phase") not in {"INTEGRATION_PENDING", "INTEGRATED"} or not isinstance(base, str):
        raise TaskControllerError("INTEGRATION_RECOVERY_STATE_INVALID")
    revalidated = integrate_task(
        {**state, "phase": "REVIEWED_APPROVED"},
        candidate_repo=candidate_repo, controller_main_sha=base,
        expected_app_id=expected_app_id, transport=transport,
        ref_transport=ref_transport, human_owner_authorized=True,
        source_main_after=source_main_after, source_added_refs=source_added_refs,
    )
    if revalidated["integration"] != {**integration, "origin_main_after": None}:
        raise TaskControllerError("INTEGRATION_RECOVERY_REVALIDATION_CHANGED")

def record_qualification(
    state: dict[str, Any],
    *,
    candidate_sha: str,
    workflow_run_id: int,
    check_id: int,
    check_app_id: int,
    result: str,
    authorization: ResolvedAuthorization | None = None,
) -> dict[str, Any]:
    if state.get("phase") == "STOP_REPLAN":
        raise TaskControllerError("STOP_REPLAN_PRESERVE_ATTEMPT")
    mode = workflow_mode_for_state(state)
    if result not in {
        "PASS",
        "FAIL",
    }:
        raise TaskControllerError(
            "QUALIFICATION_RESULT_INVALID"
        )

    attached, binding = _require_workflow_candidate_attachment(
        state,
        mode=mode,
        candidate_sha=candidate_sha,
    )
    if attached is not None and binding is not None:
        if authorization is None:
            raise EvidenceError("ATTACHED_AUTHORIZATION_REQUIRED")
        authorization_state = state.get("authorization") or {}
        if (
            authorization.task_id != state.get("task_id")
            or authorization.issue_number != state.get("issue_number")
            or authorization.repository != state.get("repository")
            or authorization.base_sha != authorization_state.get("base_sha")
            or authorization.revision != authorization_state.get("revision")
            or authorization.nonce != authorization_state.get("nonce")
            or authorization.comment_id != authorization_state.get("comment_id")
            or authorization.author_login != authorization_state.get("author_login")
            or authorization.payload_sha256 != authorization_state.get("payload_sha256")
            or authorization.identity_sha256 != authorization_state.get("identity_sha256")
        ):
            raise EvidenceError("ATTACHED_AUTHORIZATION_MISMATCH")
        _legacy_evidence().authenticate_binding(binding, authorization, candidate_sha)
        require_review_preflight(attached, binding, candidate_sha)

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
    if state.get("phase") == "STOP_REPLAN":
        raise TaskControllerError("STOP_REPLAN_PRESERVE_ATTEMPT")
    if decision not in {
        "pass",
        "fail",
    }:
        raise TaskControllerError(
            "VERIFICATION_DECISION_INVALID"
        )

    mode = workflow_mode_for_state(state)
    _require_workflow_candidate_attachment(
        state,
        mode=mode,
        candidate_sha=candidate_sha,
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

    if "capsule_evidence" in state:
        _legacy_evidence().gate(state, candidate_sha)

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
    if state.get("phase") == "STOP_REPLAN":
        raise TaskControllerError("STOP_REPLAN_PRESERVE_ATTEMPT")
    if decision not in {
        "approved",
        "changes-requested",
    }:
        raise TaskControllerError(
            "REVIEW_DECISION_INVALID"
        )

    mode = workflow_mode_for_state(state)
    attached, _ = _require_workflow_candidate_attachment(
        state,
        mode=mode,
        candidate_sha=candidate_sha,
    )
    if attached is not None:
        raise EvidenceError("OBSERVED_REVIEW_COMMAND_REQUIRED")

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
        workflow_mode=getattr(args, "workflow_mode", "standard"),
        compatibility_reason=getattr(args, "compatibility_reason", None),
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
            "workflow_mode": state["workflow"]["mode"],
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
    mode = workflow_mode_for_state(updated)

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
            "workflow_mode": mode,
            "next": "plan_capsule" if mode == "attached" else "qualify",
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
    mode = workflow_mode_for_state(updated)

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
            "workflow_mode": mode,
            "next": (
                (
                    "historical_evidence_sealing_unsupported_owner_decision_required"
                    if mode == "attached"
                    else "verify"
                )
                if qualification["result"] == "PASS"
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
    resolve_current_authorization(
        state,
        GhQualificationTransport(),
    )

    updated = record_verification(
        state,
        candidate_sha=args.candidate_sha,
        actor=args.actor,
        decision=args.decision,
        evidence=args.evidence,
    )
    mode = workflow_mode_for_state(updated)

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
            "workflow_mode": mode,
            "next": (
                (
                    "historical_review_unsupported_owner_decision_required"
                    if mode == "attached"
                    else "review"
                )
                if args.decision == "pass" else "rework"
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
    resolve_current_authorization(
        state,
        GhQualificationTransport(),
    )

    updated = record_review(
        state,
        candidate_sha=args.candidate_sha,
        actor=args.actor,
        decision=args.decision,
        summary=args.summary,
    )
    mode = workflow_mode_for_state(updated)

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
            "workflow_mode": mode,
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

        try:
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
        except EvidenceError as exc:
            if str(exc) == GOVERNING_ISSUE_REPLAN_REQUIRED:
                persist_governing_issue_replan(
                    state, state_file, candidate_sha)
            raise

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

        # Recovery is another integration attempt, not a license to reuse
        # yesterday's check, authorization, source, or review evidence.
        try:
            revalidate_integration_state(
                state,
                candidate_repo=candidate_repo,
                expected_app_id=expected_app_id,
                transport=GhQualificationTransport(),
                ref_transport=GitCandidateRefTransport(candidate_repo),
            )
        except EvidenceError as exc:
            if str(exc) == GOVERNING_ISSUE_REPLAN_REQUIRED:
                persist_governing_issue_replan(
                    state, state_file, candidate_sha)
            raise

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


def validated_finalize_terminal(state: dict[str, Any], args: argparse.Namespace,
                                implementation: str) -> tuple[dict, Path, str, dict, dict[str, str]]:
    """Authenticate the exact terminal transaction before allowing its ref additions."""
    terminal_state = load_state(args.terminal_state_dir, args.issue_number)
    terminal_repo = resolve_repo_root(args.terminal_root)
    terminal = require_candidate_repository(
        terminal_repo, expected_repository=state["repository"])
    terminal_authorization = resolve_current_authorization(
        terminal_state, GhQualificationTransport())
    capsule_path = task_closeout.active_capsule_path(args.issue_number, state["task_id"])
    if (terminal_state["task_id"] != state["task_id"] + "-closeout"
            or terminal_state["repository"] != state["repository"]
            or terminal_authorization.base_sha != implementation
            or set(terminal_authorization.allowed_paths) != {
                "engineering/capsules/HISTORY.md", capsule_path}
            or terminal_authorization.profiles != ("repository",)):
        raise TaskControllerError("FINALIZE_TERMINAL_AUTHORITY_INVALID")
    attached_binding = (state.get("capsule_evidence") or {}).get("binding") or {}
    recovery = task_closeout.validate(terminal_repo, issue_number=args.issue_number,
                                       implementation=implementation, terminal=terminal,
                                       recovery=args.recovery_sha,
                                       expected_contract_sha256=attached_binding.get("contract_sha256"),
                                       task_id=state["task_id"])
    if terminal_state["phase"] in {"INTEGRATION_PENDING", "INTEGRATED"}:
        try:
            revalidate_integration_state(
                terminal_state, candidate_repo=terminal_repo,
                expected_app_id=configured_qualification_app_id(),
                transport=GhQualificationTransport(),
                ref_transport=GitCandidateRefTransport(terminal_repo))
        except EvidenceError as exc:
            if str(exc) == GOVERNING_ISSUE_REPLAN_REQUIRED:
                persist_governing_issue_replan(
                    terminal_state,
                    state_path(args.terminal_state_dir, args.issue_number),
                    terminal)
            raise
        if (terminal_state["phase"] == "INTEGRATED"
                and terminal_state["integration"]["origin_main_after"] != terminal):
            raise TaskControllerError("FINALIZE_TERMINAL_NOT_INTEGRATED")
    refs = {f"refs/heads/evidence/GH-{args.issue_number}-recovery": args.recovery_sha,
            f"refs/heads/task/GH-{args.issue_number}-closeout": terminal}
    return terminal_state, terminal_repo, terminal, recovery, refs


def command_finalize(args: argparse.Namespace) -> int:
    """Resume implementation and separately authorized terminal acceptance."""
    repo = resolve_repo_root(args.repo_root)
    state_dir = args.state_dir.resolve()
    state = load_state(state_dir, args.issue_number)
    candidate_repo = resolve_repo_root(args.candidate_root)
    implementation = require_candidate_repository(
        candidate_repo, expected_repository=state["repository"])
    intent_path = state_dir / f"issue-{args.issue_number}-finalize.json"
    intent = {"schema_version": 1, "issue_number": args.issue_number,
              "repository": state["repository"], "implementation": implementation,
              "terminal_state_dir": str(args.terminal_state_dir.resolve())}
    if intent_path.exists():
        previous = json.loads(intent_path.read_text())
        if any(previous.get(key) != value for key, value in intent.items()):
            raise TaskControllerError("FINALIZE_INTENT_CHANGED")
    else:
        if state["phase"] not in {"REVIEWED_APPROVED", "INTEGRATION_PENDING", "INTEGRATED"}:
            raise TaskControllerError("FINALIZE_IMPLEMENTATION_NOT_REVIEWED")
        atomic_write_json(intent_path, {**intent, "phase": "IMPLEMENTATION_PENDING"})

    terminal_state_path = state_path(args.terminal_state_dir, args.issue_number)
    terminal_inputs = terminal_state_path.is_file() and args.terminal_root is not None and args.recovery_sha is not None
    terminal_context = None
    if state["phase"] == "INTEGRATED" and terminal_inputs:
        terminal_context = validated_finalize_terminal(state, args, implementation)

    if state["phase"] != "INTEGRATED":
        command_integrate(argparse.Namespace(
            state_dir=state_dir, issue_number=args.issue_number, repo_root=repo,
            candidate_root=candidate_repo,
            human_owner_authorized=args.human_owner_authorized))
        state = load_state(state_dir, args.issue_number)
    else:
        source_main_after = None
        if terminal_context is not None:
            git(repo, "fetch", "origin", "main")
            current_main = git(repo, "rev-parse", "refs/remotes/origin/main")
            terminal_phase = terminal_context[0]["phase"]
            if current_main == terminal_context[2] and terminal_phase in {
                    "INTEGRATION_PENDING", "INTEGRATED"}:
                source_main_after = current_main
            elif current_main != implementation:
                raise TaskControllerError("FINALIZE_REMOTE_MAIN_DIVERGED")
        try:
            revalidate_integration_state(
                state, candidate_repo=candidate_repo,
                expected_app_id=configured_qualification_app_id(),
                transport=GhQualificationTransport(),
                ref_transport=GitCandidateRefTransport(candidate_repo),
                source_main_after=source_main_after,
                source_added_refs=terminal_context[4] if terminal_context is not None else None)
        except EvidenceError as exc:
            if str(exc) == GOVERNING_ISSUE_REPLAN_REQUIRED:
                persist_governing_issue_replan(
                    state, state_path(state_dir, args.issue_number), implementation)
            raise
    if state["phase"] != "INTEGRATED" or state["integration"]["origin_main_after"] != implementation:
        raise TaskControllerError("FINALIZE_IMPLEMENTATION_NOT_INTEGRATED")
    existing = json.loads(intent_path.read_text())
    if existing["phase"] == "IMPLEMENTATION_PENDING":
        atomic_write_json(intent_path, {**intent, "phase": "IMPLEMENTATION_INTEGRATED"})

    git(repo, "fetch", "origin", "main")
    observed_main = git(repo, "rev-parse", "refs/remotes/origin/main")
    if observed_main != implementation:
        if existing.get("terminal") != observed_main:
            raise TaskControllerError("FINALIZE_REMOTE_MAIN_DIVERGED")

    if not terminal_state_path.is_file() or args.terminal_root is None or args.recovery_sha is None:
        if observed_main != implementation:
            raise TaskControllerError("FINALIZE_TERMINAL_INPUT_REQUIRED")
        emit({"task": state["task_id"], "phase": "IMPLEMENTATION_INTEGRATED",
              "next": "prepare_and_review_separate_terminal_candidate"})
        return 0

    if terminal_context is None:
        terminal_context = validated_finalize_terminal(state, args, implementation)
    terminal_state, terminal_repo, terminal, recovery, _ = terminal_context
    attached_binding = (state.get("capsule_evidence") or {}).get("binding") or {}
    previous = json.loads(intent_path.read_text())
    if previous.get("terminal") not in (None, terminal) or previous.get("recovery") not in (None, recovery):
        raise TaskControllerError("FINALIZE_TERMINAL_INTENT_CHANGED")
    if previous.get("terminal_root") not in (None, str(terminal_repo)):
        raise TaskControllerError("FINALIZE_TERMINAL_ROOT_CHANGED")
    atomic_write_json(intent_path, {**intent, "phase": "TERMINAL_PENDING",
                                    "terminal": terminal, "recovery": recovery,
                                    "terminal_root": str(terminal_repo)})
    if terminal_state["phase"] != "INTEGRATED":
        command_integrate(argparse.Namespace(
            state_dir=args.terminal_state_dir, issue_number=args.issue_number,
            repo_root=repo, candidate_root=terminal_repo,
            human_owner_authorized=args.human_owner_authorized))
        terminal_state = load_state(args.terminal_state_dir, args.issue_number)
    else:
        try:
            revalidate_integration_state(
                terminal_state, candidate_repo=terminal_repo,
                expected_app_id=configured_qualification_app_id(),
                transport=GhQualificationTransport(),
                ref_transport=GitCandidateRefTransport(terminal_repo))
        except EvidenceError as exc:
            if str(exc) == GOVERNING_ISSUE_REPLAN_REQUIRED:
                persist_governing_issue_replan(
                    terminal_state,
                    state_path(args.terminal_state_dir, args.issue_number),
                    terminal)
            raise
    if (terminal_state["phase"] != "INTEGRATED"
            or terminal_state["integration"]["origin_main_after"] != terminal):
        raise TaskControllerError("FINALIZE_TERMINAL_NOT_INTEGRATED")
    git(repo, "fetch", "origin", "main")
    if git(repo, "rev-parse", "refs/remotes/origin/main") != terminal:
        raise TaskControllerError("FINALIZE_REMOTE_MAIN_MISMATCH")
    task_closeout.validate(terminal_repo, issue_number=args.issue_number,
                           implementation=implementation, terminal=terminal,
                           recovery=args.recovery_sha,
                           expected_contract_sha256=attached_binding.get("contract_sha256"),
                           task_id=state["task_id"])
    atomic_write_json(intent_path, {**intent, "phase": "TERMINAL_INTEGRATED",
                                    "terminal": terminal, "recovery": recovery,
                                    "terminal_root": str(terminal_repo)})
    issue = GhIssueAuthorizationTransport()._api(
        method="PATCH", path=f"/repos/{state['repository']}/issues/{args.issue_number}",
        payload={"state": "closed", "state_reason": "completed"})
    if issue.get("state") != "closed":
        raise TaskControllerError("FINALIZE_ISSUE_CLOSE_NOT_CONFIRMED")
    atomic_write_json(intent_path, {**intent, "phase": "COMPLETE",
                                    "terminal": terminal, "recovery": recovery,
                                    "terminal_root": str(terminal_repo)})
    emit({"task": state["task_id"], "phase": "COMPLETE", "origin_main": terminal,
          "recovery": recovery, "issue_closed": True})
    return 0


def command_finalize_cleanup(args: argparse.Namespace) -> int:
    """Remove only an exact clean disposable terminal checkout after completion."""
    repo = resolve_repo_root(args.repo_root)
    intent_path = args.state_dir / f"issue-{args.issue_number}-finalize.json"
    if not intent_path.is_file():
        raise TaskControllerError("FINALIZE_INTENT_MISSING")
    intent = json.loads(intent_path.read_text())
    if intent.get("phase") not in {"COMPLETE", "CLEANUP_PENDING"} or intent.get("issue_number") != args.issue_number:
        raise TaskControllerError("FINALIZE_NOT_COMPLETE")
    terminal = intent["terminal"]
    root = args.cleanup_root.resolve()
    target = {"root": str(root), "branch": args.cleanup_branch}
    if intent.get("terminal_root") != str(root):
        raise TaskControllerError("FINALIZE_CLEANUP_ROOT_MISMATCH")
    if intent.get("phase") == "COMPLETE" and intent.get("cleanup") == target:
        emit({"task": f"GH-{args.issue_number}", "cleanup": "already_complete"})
        return 0
    if "cleanup" in intent and intent["cleanup"] != target:
        raise TaskControllerError("FINALIZE_CLEANUP_INTENT_CHANGED")
    git(repo, "fetch", "origin", "main")
    if git(repo, "rev-parse", "refs/remotes/origin/main") != terminal:
        raise TaskControllerError("FINALIZE_CLEANUP_REMOTE_MAIN_CHANGED")
    if root.exists():
        task_closeout.cleanup_target(repo, issue_number=args.issue_number,
                                     root=root, branch=args.cleanup_branch,
                                     terminal=terminal)
    elif intent["phase"] != "CLEANUP_PENDING" or f"worktree {root}\n" in git(repo, "worktree", "list", "--porcelain"):
        raise TaskControllerError("FINALIZE_CLEANUP_TARGET_MISSING")
    atomic_write_json(intent_path, {**intent, "phase": "CLEANUP_PENDING", "cleanup": target})
    if root.exists():
        git(repo, "worktree", "remove", str(root))
    branch_ref = f"refs/heads/{args.cleanup_branch}"
    if run(["git", "show-ref", "--verify", "--quiet", branch_ref], cwd=repo).returncode == 0:
        if git(repo, "rev-parse", branch_ref) != terminal:
            raise TaskControllerError("FINALIZE_CLEANUP_BRANCH_CHANGED")
        git(repo, "branch", "-d", args.cleanup_branch)
    intent["phase"] = "COMPLETE"
    intent["cleanup"] = target
    atomic_write_json(intent_path, intent)
    emit({"task": f"GH-{args.issue_number}", "cleanup": "complete",
          "root": str(root), "branch": args.cleanup_branch})
    return 0


def command_finalize_cancel(args: argparse.Namespace) -> int:
    """Accept a separately reviewed CANCELLED capsule terminal transaction."""
    repo = resolve_repo_root(args.repo_root)
    state = load_state(args.terminal_state_dir, args.issue_number)
    terminal_repo = resolve_repo_root(args.terminal_root)
    terminal = require_candidate_repository(terminal_repo, expected_repository=state["repository"])
    authorization = resolve_current_authorization(state, GhQualificationTransport())
    capsule_id = state["task_id"].removesuffix("-closeout")
    capsule_path = task_closeout.active_capsule_path(args.issue_number, capsule_id)
    if (state["task_id"] != capsule_id + "-closeout"
            or authorization.profiles != ("repository",)
            or set(authorization.allowed_paths) != {
                "engineering/capsules/HISTORY.md",
                capsule_path}):
        raise TaskControllerError("FINALIZE_CANCEL_AUTHORITY_INVALID")
    recovery = task_closeout.validate(
        terminal_repo, issue_number=args.issue_number,
        implementation=authorization.base_sha, terminal=terminal,
        recovery=args.recovery_sha, final_state="CANCELLED", task_id=capsule_id)
    intent_path = args.state_dir / f"issue-{args.issue_number}-cancel-finalize.json"
    intent = {"schema_version": 1, "issue_number": args.issue_number,
              "terminal": terminal, "base": authorization.base_sha,
              "recovery": recovery, "terminal_root": str(terminal_repo)}
    if intent_path.exists():
        prior = json.loads(intent_path.read_text())
        if any(prior.get(key) != value for key, value in intent.items()):
            raise TaskControllerError("FINALIZE_CANCEL_INTENT_CHANGED")
    else:
        atomic_write_json(intent_path, {**intent, "phase": "TERMINAL_PENDING"})
    if state["phase"] != "INTEGRATED":
        command_integrate(argparse.Namespace(
            state_dir=args.terminal_state_dir, issue_number=args.issue_number,
            repo_root=repo, candidate_root=terminal_repo,
            human_owner_authorized=args.human_owner_authorized))
        state = load_state(args.terminal_state_dir, args.issue_number)
    else:
        try:
            revalidate_integration_state(
                state, candidate_repo=terminal_repo,
                expected_app_id=configured_qualification_app_id(),
                transport=GhQualificationTransport(),
                ref_transport=GitCandidateRefTransport(terminal_repo))
        except EvidenceError as exc:
            if str(exc) == GOVERNING_ISSUE_REPLAN_REQUIRED:
                persist_governing_issue_replan(
                    state,
                    state_path(args.terminal_state_dir, args.issue_number),
                    terminal)
            raise
    if state["phase"] != "INTEGRATED" or state["integration"]["origin_main_after"] != terminal:
        raise TaskControllerError("FINALIZE_CANCEL_TERMINAL_NOT_INTEGRATED")
    git(repo, "fetch", "origin", "main")
    if git(repo, "rev-parse", "refs/remotes/origin/main") != terminal:
        raise TaskControllerError("FINALIZE_CANCEL_REMOTE_MAIN_MISMATCH")
    task_closeout.validate(
        terminal_repo, issue_number=args.issue_number,
        implementation=authorization.base_sha, terminal=terminal,
        recovery=args.recovery_sha, final_state="CANCELLED", task_id=capsule_id)
    issue = GhIssueAuthorizationTransport()._api(
        method="PATCH", path=f"/repos/{state['repository']}/issues/{args.issue_number}",
        payload={"state": "closed", "state_reason": "not_planned"})
    if issue.get("state") != "closed":
        raise TaskControllerError("FINALIZE_CANCEL_ISSUE_CLOSE_NOT_CONFIRMED")
    atomic_write_json(intent_path, {**intent, "phase": "COMPLETE"})
    emit({"task": state["task_id"], "phase": "CANCELLED", "origin_main": terminal,
          "recovery": recovery, "issue_closed": True})
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
    prepare.add_argument(
        "--workflow-mode",
        choices=("standard", "compatibility"),
        default="standard",
        help="Standard source/diff review is the default; attached RI transport is retired.",
    )
    prepare.add_argument(
        "--compatibility-reason",
        help="Required owner-authenticated reason for compatibility mode.",
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

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("issue_number", type=int)
    finalize.add_argument("--candidate-root", type=Path, required=True)
    finalize.add_argument("--terminal-state-dir", type=Path, required=True)
    finalize.add_argument("--terminal-root", type=Path)
    finalize.add_argument("--recovery-sha")
    finalize.add_argument("--human-owner-authorized", action="store_true")
    finalize.set_defaults(handler=command_finalize)

    cleanup = subparsers.add_parser("finalize-cleanup")
    cleanup.add_argument("issue_number", type=int)
    cleanup.add_argument("--cleanup-root", type=Path, required=True)
    cleanup.add_argument("--cleanup-branch", required=True)
    cleanup.set_defaults(handler=command_finalize_cleanup)

    cancel = subparsers.add_parser("finalize-cancel")
    cancel.add_argument("issue_number", type=int)
    cancel.add_argument("--terminal-state-dir", type=Path, required=True)
    cancel.add_argument("--terminal-root", type=Path, required=True)
    cancel.add_argument("--recovery-sha", required=True)
    cancel.add_argument("--human-owner-authorized", action="store_true")
    cancel.set_defaults(handler=command_finalize_cancel)

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
        ExecutionError,
        EvidenceError,
        RIError,
        task_closeout.CloseoutError,
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
