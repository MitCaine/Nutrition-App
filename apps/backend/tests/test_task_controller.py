from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"

sys.path.insert(
    0,
    str(SCRIPTS),
)

from lib.task_authorization import (  # noqa: E402
    AUTHORIZATION_MARKER,
    AuthorizationError,
    build_payload,
    render_authorization_comment,
    resolve_comment,
    resolve_comments,
    validate_candidate_scope,
)
from lib.trusted_qualification import (  # noqa: E402
    TrustedQualificationError,
    build_check_request,
    build_plan,
    publish_check,
    revalidate_plan_authorization,
)


def load_task_module():
    path = SCRIPTS / "task.py"

    spec = importlib.util.spec_from_file_location(
        "nutrition_task_controller_test",
        path,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(
        spec
    )
    spec.loader.exec_module(module)
    return module


TASK = load_task_module()


def git(
    repo: Path,
    *args: str,
) -> str:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, (
        completed.stderr
        or completed.stdout
    )

    return completed.stdout.strip()


def init_repo(
    tmp_path: Path,
) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()

    git(repo, "init", "-q")
    git(
        repo,
        "config",
        "user.name",
        "Task Controller Test",
    )
    git(
        repo,
        "config",
        "user.email",
        "task-test@example.invalid",
    )

    (repo / "README.md").write_text(
        "base\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")

    base = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    git(
        repo,
        "update-ref",
        "refs/remotes/origin/main",
        base,
    )

    return repo, base


def authorization_payload(
    base: str,
    *,
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    profiles: list[str] | None = None,
) -> dict:
    return build_payload(
        task_id="GH-999-P1",
        issue_number=999,
        repository="owner/repo",
        base_sha=base,
        allowed_paths=(
            allowed_paths
            or ["src/**"]
        ),
        forbidden_paths=(
            forbidden_paths
            or ["src/forbidden/**"]
        ),
        profiles=(
            profiles
            or [
                "repository",
                "backend",
            ]
        ),
        revision=1,
        nonce=(
            "nonce-1234567890abcdef"
        ),
    )


def comment_for(
    payload: dict,
    *,
    comment_id: int = 12345,
    author: str = "trusted-owner",
) -> dict:
    return {
        "id": comment_id,
        "user": {
            "login": author,
        },
        "body": render_authorization_comment(
            payload
        ),
    }


def resolve(
    payload: dict,
    *,
    comment_id: int = 12345,
    author: str = "trusted-owner",
):
    return resolve_comment(
        comment_for(
            payload,
            comment_id=comment_id,
            author=author,
        ),
        trusted_author="trusted-owner",
        expected_repository="owner/repo",
        expected_issue_number=999,
        expected_task_id="GH-999-P1",
        expected_revision=1,
        expected_comment_id=comment_id,
        expected_payload_sha256=payload[
            "payload_sha256"
        ],
    )


def test_authorization_round_trip_binds_comment_author_and_digest(
    tmp_path: Path,
) -> None:
    _, base = init_repo(tmp_path)

    payload = authorization_payload(base)
    comment = comment_for(payload)

    resolved = resolve_comment(
        comment,
        trusted_author="trusted-owner",
        expected_repository="owner/repo",
        expected_issue_number=999,
        expected_task_id="GH-999-P1",
        expected_revision=1,
        expected_comment_id=12345,
        expected_payload_sha256=payload[
            "payload_sha256"
        ],
    )

    assert (
        AUTHORIZATION_MARKER
        in comment["body"]
    )
    assert resolved.comment_id == 12345
    assert (
        resolved.author_login
        == "trusted-owner"
    )
    assert (
        resolved.payload_sha256
        == payload["payload_sha256"]
    )
    assert len(
        resolved.identity_sha256
    ) == 64


def test_wrong_author_fails_closed(
    tmp_path: Path,
) -> None:
    _, base = init_repo(tmp_path)
    payload = authorization_payload(base)

    with pytest.raises(
        AuthorizationError,
        match="AUTHORIZATION_AUTHOR_UNTRUSTED",
    ):
        resolve_comment(
            comment_for(
                payload,
                author="untrusted",
            ),
            trusted_author="trusted-owner",
            expected_repository="owner/repo",
            expected_issue_number=999,
            expected_task_id="GH-999-P1",
            expected_revision=1,
        )


def test_edited_authorization_digest_fails_closed(
    tmp_path: Path,
) -> None:
    _, base = init_repo(tmp_path)
    payload = authorization_payload(base)

    body = render_authorization_comment(
        payload
    ).replace(
        '"nonce": "nonce-1234567890abcdef"',
        '"nonce": "nonce-1234567890abcdeg"',
    )

    comment = {
        "id": 12345,
        "user": {
            "login": "trusted-owner",
        },
        "body": body,
    }

    with pytest.raises(
        AuthorizationError,
        match="AUTHORIZATION_DIGEST_MISMATCH",
    ):
        resolve_comment(
            comment,
            trusted_author="trusted-owner",
            expected_repository="owner/repo",
            expected_issue_number=999,
            expected_task_id="GH-999-P1",
            expected_revision=1,
        )


def test_duplicate_authorization_comments_are_ambiguous(
    tmp_path: Path,
) -> None:
    _, base = init_repo(tmp_path)
    payload = authorization_payload(base)

    with pytest.raises(
        AuthorizationError,
        match="AUTHORIZATION_AMBIGUOUS",
    ):
        resolve_comments(
            [
                comment_for(
                    payload,
                    comment_id=100,
                ),
                comment_for(
                    payload,
                    comment_id=101,
                ),
            ],
            trusted_author="trusted-owner",
            expected_repository="owner/repo",
            expected_issue_number=999,
            expected_task_id="GH-999-P1",
            expected_revision=1,
        )


def test_scope_rejects_unexpected_path(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    (repo / "outside.txt").write_text(
        "outside\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "candidate",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    auth = resolve(
        authorization_payload(base)
    )

    with pytest.raises(
        AuthorizationError,
        match="SCOPE_UNEXPECTED",
    ):
        validate_candidate_scope(
            repo,
            auth,
            candidate_sha=candidate,
        )


def test_scope_rejects_forbidden_path_even_when_allowed(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    path = repo / "src/forbidden/item.py"
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "candidate",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    auth = resolve(
        authorization_payload(
            base,
            allowed_paths=["src/**"],
        )
    )

    with pytest.raises(
        AuthorizationError,
        match="SCOPE_FORBIDDEN",
    ):
        validate_candidate_scope(
            repo,
            auth,
            candidate_sha=candidate,
        )


def test_scope_checks_both_sides_of_rename(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    old = repo / "src/old.txt"
    old.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    old.write_text(
        "content\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "seed rename source",
    )

    rename_base = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    git(
        repo,
        "update-ref",
        "refs/remotes/origin/main",
        rename_base,
    )

    new = repo / "elsewhere/new.txt"
    new.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    git(
        repo,
        "mv",
        "src/old.txt",
        "elsewhere/new.txt",
    )

    git(
        repo,
        "commit",
        "-q",
        "-m",
        "rename outside authority",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    auth = resolve(
        authorization_payload(
            rename_base,
            allowed_paths=["src/**"],
        )
    )

    with pytest.raises(
        AuthorizationError,
        match="SCOPE_UNEXPECTED",
    ):
        validate_candidate_scope(
            repo,
            auth,
            candidate_sha=candidate,
        )


def test_stale_main_fails_closed(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    auth = resolve(
        authorization_payload(base)
    )

    other = "f" * 40

    with pytest.raises(
        AuthorizationError,
        match="BASE_AUTHORITY_STALE",
    ):
        validate_candidate_scope(
            repo,
            auth,
            candidate_sha=base,
            observed_main_sha=other,
        )


def test_plan_profiles_come_from_external_authorization(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    path = repo / "src/value.py"
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "candidate",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    auth = resolve(
        authorization_payload(
            base,
            profiles=[
                "repository",
                "mobile",
            ],
        )
    )

    plan = build_plan(
        repo,
        auth,
        candidate_sha=candidate,
        candidate_ref=(
            "task-candidate/999/"
            + candidate[:12]
        ),
    )

    assert plan["profiles"] == [
        "repository",
        "mobile",
    ]
    assert plan["changed_paths"] == [
        "src/value.py"
    ]
    assert (
        plan["authorization_comment_id"]
        == 12345
    )
    assert len(plan["plan_sha256"]) == 64


def test_plan_revalidation_rejects_edited_comment(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    path = repo / "src/value.py"
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "candidate",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    payload = authorization_payload(base)
    auth = resolve(payload)

    plan = build_plan(
        repo,
        auth,
        candidate_sha=candidate,
        candidate_ref=(
            "task-candidate/999/"
            + candidate[:12]
        ),
    )

    edited = comment_for(payload)
    edited["body"] = edited[
        "body"
    ].replace(
        '"revision": 1',
        '"revision": 2',
    )

    with pytest.raises(
        (
            AuthorizationError,
            TrustedQualificationError,
        )
    ):
        revalidate_plan_authorization(
            plan,
            edited,
            trusted_author="trusted-owner",
        )


def test_check_request_binds_exact_sha_and_profile_results(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    path = repo / "src/value.py"
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "candidate",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    plan = build_plan(
        repo,
        resolve(
            authorization_payload(base)
        ),
        candidate_sha=candidate,
        candidate_ref=(
            "task-candidate/999/"
            + candidate[:12]
        ),
    )

    request = build_check_request(
        plan,
        workflow_run_id="123456",
        profile_results={
            "repository": "success",
            "backend": "success",
        },
    )

    assert (
        request["name"]
        == "Main qualification"
    )
    assert request["head_sha"] == candidate
    assert request["conclusion"] == "success"
    assert (
        "/actions/runs/123456"
        in request["details_url"]
    )


def test_failed_selected_profile_creates_failed_check(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    path = repo / "src/value.py"
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "candidate",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    plan = build_plan(
        repo,
        resolve(
            authorization_payload(base)
        ),
        candidate_sha=candidate,
        candidate_ref=(
            "task-candidate/999/"
            + candidate[:12]
        ),
    )

    request = build_check_request(
        plan,
        workflow_run_id="123456",
        profile_results={
            "repository": "success",
            "backend": "failure",
        },
    )

    assert request["conclusion"] == "failure"


def test_check_publisher_rejects_wrong_response_sha(
    tmp_path: Path,
) -> None:
    class FakePublisher:
        def publish(self, request):
            return {
                "id": 999,
                "name": request["name"],
                "head_sha": "f" * 40,
            }

    request = {
        "name": "Main qualification",
        "head_sha": "a" * 40,
    }

    with pytest.raises(
        TrustedQualificationError,
        match="CHECK_RESPONSE_SHA_MISMATCH",
    ):
        publish_check(
            FakePublisher(),
            request,
            expected_app_id=424242,
        )


def test_prepare_emits_external_authorization_draft(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    git(
        repo,
        "remote",
        "add",
        "origin",
        "https://github.com/owner/repo.git",
    )

    state_dir = tmp_path / "state"

    state = TASK.prepare_task(
        repo=repo,
        state_dir=state_dir,
        issue_number=999,
        task_id="GH-999-P1",
        trusted_author="trusted-owner",
        repository="owner/repo",
        base_sha=base,
        allowed_paths=["src/**"],
        forbidden_paths=[],
        profiles=["repository"],
        revision=1,
        nonce="nonce-1234567890abcdef",
    )

    assert state["phase"] == "PREPARED"

    draft = Path(
        state["authorization"][
            "draft_path"
        ]
    )

    assert draft.is_file()
    assert (
        AUTHORIZATION_MARKER
        in draft.read_text(
            encoding="utf-8"
        )
    )

    persisted = json.loads(
        TASK.state_path(
            state_dir,
            999,
        ).read_text(
            encoding="utf-8"
        )
    )

    assert persisted["task_id"] == "GH-999-P1"


def test_verification_pass_requires_exact_successful_qualification() -> None:
    state = {
        "task_id": "GH-999-P1",
        "issue_number": 999,
        "qualification": {
            "candidate_sha": "a" * 40,
            "result": "FAIL",
        },
    }

    with pytest.raises(
        TASK.TaskControllerError,
        match="VERIFICATION_REQUIRES_EXACT_QUALIFICATION",
    ):
        TASK.record_verification(
            state,
            candidate_sha="a" * 40,
            actor="verifier",
            decision="pass",
            evidence="bundle.zip",
        )


def test_review_approval_requires_explicit_exact_verification() -> None:
    state = {
        "task_id": "GH-999-P1",
        "issue_number": 999,
        "verification": {
            "candidate_sha": "a" * 40,
            "decision": "fail",
        },
    }

    with pytest.raises(
        TASK.TaskControllerError,
        match="REVIEW_APPROVAL_REQUIRES_EXACT_VERIFICATION",
    ):
        TASK.record_review(
            state,
            candidate_sha="a" * 40,
            actor="reviewer",
            decision="approved",
            summary="approved",
        )


class FakeIssueAuthorizationTransport:
    def __init__(
        self,
        *,
        author: str = "owner",
        mutate_body=None,
    ) -> None:
        self.author = author
        self.mutate_body = mutate_body
        self.created: list[dict] = []
        self.comments: dict[int, dict] = {}

    def create_issue_comment(
        self,
        repository: str,
        issue_number: int,
        body: str,
    ) -> dict:
        comment_id = 7001

        stored_body = (
            self.mutate_body(body)
            if self.mutate_body is not None
            else body
        )

        comment = {
            "id": comment_id,
            "html_url": (
                "https://github.com/"
                f"{repository}/issues/"
                f"{issue_number}"
                f"#issuecomment-{comment_id}"
            ),
            "user": {
                "login": self.author,
            },
            "body": stored_body,
        }

        self.created.append(
            {
                "repository": repository,
                "issue_number": issue_number,
                "body": body,
            }
        )

        self.comments[
            comment_id
        ] = comment

        return dict(comment)

    def get_issue_comment(
        self,
        repository: str,
        comment_id: int,
    ) -> dict:
        assert repository == "owner/repo"

        return dict(
            self.comments[
                comment_id
            ]
        )


def prepared_external_state(
    tmp_path: Path,
) -> dict:
    repo, base = init_repo(tmp_path)
    state_dir = tmp_path / "controller-state"

    return TASK.prepare_task(
        repo=repo,
        state_dir=state_dir,
        issue_number=999,
        task_id="GH-999-P1",
        trusted_author="owner",
        repository="owner/repo",
        base_sha=base,
        allowed_paths=["src/**"],
        forbidden_paths=[],
        profiles=["repository"],
        revision=1,
        nonce="nonce-1234567890abcdef",
    )


def test_authorize_records_refetched_external_comment_identity(
    tmp_path: Path,
) -> None:
    state = prepared_external_state(
        tmp_path
    )

    transport = (
        FakeIssueAuthorizationTransport()
    )

    updated = TASK.authorize_task(
        state,
        transport=transport,
    )

    assert updated["phase"] == "AUTHORIZED"
    assert (
        updated["authorization"][
            "comment_id"
        ]
        == 7001
    )
    assert (
        updated["authorization"][
            "author_login"
        ]
        == "owner"
    )
    assert len(
        updated["authorization"][
            "identity_sha256"
        ]
    ) == 64
    assert (
        updated["authorization"][
            "comment_url"
        ]
        .endswith(
            "#issuecomment-7001"
        )
    )
    assert len(transport.created) == 1


def test_authorize_rejects_untrusted_comment_author(
    tmp_path: Path,
) -> None:
    state = prepared_external_state(
        tmp_path
    )

    transport = (
        FakeIssueAuthorizationTransport(
            author="attacker",
        )
    )

    with pytest.raises(
        AuthorizationError,
        match="AUTHORIZATION_AUTHOR_UNTRUSTED",
    ):
        TASK.authorize_task(
            state,
            transport=transport,
        )


def test_authorize_rejects_posted_content_digest_drift(
    tmp_path: Path,
) -> None:
    state = prepared_external_state(
        tmp_path
    )

    def mutate(body: str) -> str:
        return body.replace(
            '"nonce": "nonce-1234567890abcdef"',
            '"nonce": "nonce-1234567890abcdeg"',
        )

    transport = (
        FakeIssueAuthorizationTransport(
            mutate_body=mutate,
        )
    )

    with pytest.raises(
        AuthorizationError,
        match="AUTHORIZATION_DIGEST_MISMATCH",
    ):
        TASK.authorize_task(
            state,
            transport=transport,
        )


def test_authorize_is_not_repeatable_after_external_binding(
    tmp_path: Path,
) -> None:
    state = prepared_external_state(
        tmp_path
    )

    transport = (
        FakeIssueAuthorizationTransport()
    )

    authorized = TASK.authorize_task(
        state,
        transport=transport,
    )

    with pytest.raises(
        TASK.TaskControllerError,
        match="AUTHORIZATION_REQUIRES_PREPARED_STATE",
    ):
        TASK.authorize_task(
            authorized,
            transport=transport,
        )


def test_configured_trusted_author_defaults_to_repository_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "NUTRITION_TASK_TRUSTED_AUTHOR",
        raising=False,
    )

    assert (
        TASK.configured_trusted_author(
            "owner/repo"
        )
        == "owner"
    )


def test_configured_trusted_author_can_be_explicit_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "NUTRITION_TASK_TRUSTED_AUTHOR",
        "nutrition-controller",
    )

    assert (
        TASK.configured_trusted_author(
            "owner/repo"
        )
        == "nutrition-controller"
    )


def load_main_governance_module():
    path = SCRIPTS / "main-governance.py"

    spec = importlib.util.spec_from_file_location(
        "nutrition_main_governance_test",
        path,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(
        spec
    )
    spec.loader.exec_module(module)
    return module


MAIN_GOVERNANCE = load_main_governance_module()

TRUSTED_WORKFLOW = (
    ROOT
    / ".github/workflows/trusted-qualification.yml"
)


def workflow_text() -> str:
    return TRUSTED_WORKFLOW.read_text(
        encoding="utf-8"
    )


def workflow_job_slice(
    job_name: str,
    next_job_name: str | None,
) -> str:
    text = workflow_text()

    start = text.index(
        f"  {job_name}:\n"
    )

    if next_job_name is None:
        return text[start:]

    end = text.index(
        f"  {next_job_name}:\n",
        start + 1,
    )

    return text[start:end]


def test_trusted_workflow_is_dispatch_only_and_anchors_trusted_checkout() -> None:
    text = workflow_text()

    assert "\n  workflow_dispatch:\n" in text
    assert "\n  push:" not in text
    assert "\n  pull_request:" not in text
    assert "run-name: >-" in text

    plan = workflow_job_slice(
        "plan",
        "repository",
    )

    assert (
        "ref: ${{ github.sha }}"
        in plan
    )
    assert "ref: main" not in plan
    assert (
        "ref: ${{ inputs.candidate_sha }}"
        in plan
    )
    assert (
        "trusted/scripts/lib/trusted_qualification.py"
        in plan
    )

    assert (
        text.count(
            "ref: ${{ github.sha }}"
        )
        == 2
    )

    direct_shell_inputs = [
        '--issue-number "${{ inputs.issue_number }}"',
        '--task-id "${{ inputs.task_id }}"',
        (
            '--authorization-revision '
            '"${{ inputs.authorization_revision }}"'
        ),
        (
            '--authorization-comment-id '
            '"${{ inputs.authorization_comment_id }}"'
        ),
        '"${{ inputs.authorization_payload_sha256 }}"',
        '--candidate-sha "${{ inputs.candidate_sha }}"',
        '--candidate-ref "${{ inputs.candidate_ref }}"',
    ]

    for expression in direct_shell_inputs:
        assert expression not in text

    env_bindings = [
        "ISSUE_NUMBER: ${{ inputs.issue_number }}",
        "TASK_ID: ${{ inputs.task_id }}",
        (
            "AUTHORIZATION_REVISION: "
            "${{ inputs.authorization_revision }}"
        ),
        (
            "AUTHORIZATION_COMMENT_ID: "
            "${{ inputs.authorization_comment_id }}"
        ),
        (
            "AUTHORIZATION_PAYLOAD_SHA256: "
            "${{ inputs.authorization_payload_sha256 }}"
        ),
        "CANDIDATE_SHA: ${{ inputs.candidate_sha }}",
        "CANDIDATE_REF: ${{ inputs.candidate_ref }}",
    ]

    for binding in env_bindings:
        assert text.count(binding) == 2

    shell_bindings = [
        '--issue-number "${ISSUE_NUMBER}"',
        '--task-id "${TASK_ID}"',
        (
            '--authorization-revision '
            '"${AUTHORIZATION_REVISION}"'
        ),
        (
            '--authorization-comment-id '
            '"${AUTHORIZATION_COMMENT_ID}"'
        ),
        '"${AUTHORIZATION_PAYLOAD_SHA256}"',
        '--candidate-sha "${CANDIDATE_SHA}"',
        '--candidate-ref "${CANDIDATE_REF}"',
    ]

    for binding in shell_bindings:
        assert text.count(binding) == 2

def test_candidate_jobs_have_no_dedicated_app_secret_or_environment() -> None:
    job_pairs = (
        ("repository", "backend"),
        ("backend", "backend-postgres"),
        ("backend-postgres", "mobile"),
        ("mobile", "finalize"),
    )

    for job, next_job in job_pairs:
        body = workflow_job_slice(
            job,
            next_job,
        )

        assert "secrets." not in body
        assert (
            "NUTRITION_QUALIFICATION_APP_PRIVATE_KEY"
            not in body
        )
        assert (
            "environment:" not in body
        )
        assert (
            "ref: ${{ inputs.candidate_sha }}"
            in body
        )


def test_finalizer_isolated_and_app_action_is_sha_pinned() -> None:
    body = workflow_job_slice(
        "finalize",
        None,
    )

    assert (
        "environment:\n"
        "      name: trusted-qualification"
        in body
    )
    assert (
        "ref: ${{ github.sha }}"
        in body
    )
    assert "ref: main" not in body
    assert (
        "Rebuild trusted plan without candidate execution"
        in body
    )
    assert (
        "actions/create-github-app-token@"
        "bcd2ba49218906704ab6c1aa796996da409d3eb1"
        in body
    )
    assert (
        "permission-checks: write"
        in body
    )
    assert (
        "NUTRITION_QUALIFICATION_APP_PRIVATE_KEY"
        in body
    )
    assert (
        "Publish authoritative Main qualification"
        in body
    )


def test_main_governance_requires_dedicated_app_integration() -> None:
    payload = (
        MAIN_GOVERNANCE.build_ruleset_payload(
            424242
        )
    )

    required = next(
        rule
        for rule in payload["rules"]
        if rule["type"]
        == "required_status_checks"
    )

    assert payload["bypass_actors"] == []
    assert payload["enforcement"] == "active"

    assert required["parameters"][
        "strict_required_status_checks_policy"
    ] is False

    assert required["parameters"][
        "required_status_checks"
    ] == [
        {
            "context": "Main qualification",
            "integration_id": 424242,
        }
    ]


def test_main_governance_rejects_generic_github_actions_source() -> None:
    with pytest.raises(
        MAIN_GOVERNANCE.GovernanceError,
        match="DEDICATED_APP_REQUIRED",
    ):
        MAIN_GOVERNANCE.build_ruleset_payload(
            15368
        )


def test_publish_check_validates_dedicated_app_source() -> None:
    class FakePublisher:
        def publish(self, request):
            return {
                "id": 9876,
                "name": request["name"],
                "head_sha": request["head_sha"],
                "external_id": request[
                    "external_id"
                ],
                "conclusion": request[
                    "conclusion"
                ],
                "app": {
                    "id": 424242,
                    "slug": "nutrition-qualification",
                },
            }

    request = {
        "name": "Main qualification",
        "head_sha": "a" * 40,
        "external_id": "nutrition-task:999:identity:sha",
        "conclusion": "success",
    }

    response = publish_check(
        FakePublisher(),
        request,
        expected_app_id=424242,
    )

    assert response["id"] == 9876
    assert response["app"]["id"] == 424242


def test_publish_check_rejects_wrong_dedicated_app_source() -> None:
    class FakePublisher:
        def publish(self, request):
            return {
                "id": 9876,
                "name": request["name"],
                "head_sha": request["head_sha"],
                "external_id": request[
                    "external_id"
                ],
                "conclusion": request[
                    "conclusion"
                ],
                "app": {
                    "id": 15368,
                    "slug": "github-actions",
                },
            }

    request = {
        "name": "Main qualification",
        "head_sha": "a" * 40,
        "external_id": "nutrition-task:999:identity:sha",
        "conclusion": "success",
    }

    with pytest.raises(
        TrustedQualificationError,
        match="CHECK_RESPONSE_APP_MISMATCH",
    ):
        publish_check(
            FakePublisher(),
            request,
            expected_app_id=424242,
        )


def test_finalizer_revalidation_detects_plan_digest_drift(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    path = repo / "src/value.py"
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "candidate",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    payload = authorization_payload(base)
    comment = comment_for(payload)

    plan = build_plan(
        repo,
        resolve(payload),
        candidate_sha=candidate,
        candidate_ref=(
            "task-candidate/999/"
            + candidate[:12]
        ),
    )

    plan["candidate_ref"] = (
        "task-candidate/999/forged"
    )

    with pytest.raises(
        TrustedQualificationError,
        match="PLAN_DIGEST_MISMATCH",
    ):
        revalidate_plan_authorization(
            plan,
            comment,
            trusted_author="trusted-owner",
        )


class FakeQualificationTransport:
    def __init__(
        self,
        *,
        comment: dict,
        controller_sha: str,
        candidate_sha: str,
        identity_sha256: str,
        issue_number: int = 999,
        app_id: int = 424242,
        run_conclusion: str = "success",
        check_conclusion: str = "success",
        dispatch_returns_id: bool = True,
        run_head_override: str | None = None,
        check_count: int = 1,
    ) -> None:
        self.comments = [comment]
        self.controller_sha = controller_sha
        self.candidate_sha = candidate_sha
        self.identity_sha256 = (
            identity_sha256
        )
        self.issue_number = issue_number
        self.app_id = app_id
        self.run_conclusion = (
            run_conclusion
        )
        self.check_conclusion = (
            check_conclusion
        )
        self.dispatch_returns_id = (
            dispatch_returns_id
        )
        self.run_head_override = (
            run_head_override
        )
        self.check_count = check_count
        self.dispatch_inputs: dict | None = None

    def list_issue_comments(
        self,
        repository: str,
        issue_number: int,
    ) -> list[dict]:
        assert repository == "owner/repo"
        assert issue_number == self.issue_number
        return [
            dict(item)
            for item in self.comments
        ]

    def dispatch_workflow(
        self,
        repository: str,
        workflow: str,
        ref: str,
        inputs: dict[str, str],
    ):
        assert repository == "owner/repo"
        assert workflow == (
            "trusted-qualification.yml"
        )
        assert ref == "main"

        self.dispatch_inputs = dict(inputs)

        if self.dispatch_returns_id:
            return {
                "workflow_run_id": 8800,
            }

        return None

    def _run(self) -> dict:
        assert self.dispatch_inputs is not None

        title = (
            "Trusted qualification "
            f"{self.dispatch_inputs['task_id']} "
            f"{self.dispatch_inputs['dispatch_nonce']} "
            f"{self.dispatch_inputs['candidate_sha']}"
        )

        return {
            "id": 8800,
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": (
                self.run_head_override
                or self.controller_sha
            ),
            "display_title": title,
            "status": "completed",
            "conclusion": self.run_conclusion,
            "html_url": (
                "https://github.com/"
                "owner/repo/actions/runs/8800"
            ),
        }

    def list_workflow_runs(
        self,
        repository: str,
        workflow: str,
    ) -> list[dict]:
        return [self._run()]

    def get_workflow_run(
        self,
        repository: str,
        run_id: int,
    ) -> dict:
        assert run_id == 8800
        return self._run()

    def _check(self) -> dict:
        external_id = (
            "nutrition-task:"
            f"{self.issue_number}:"
            f"{self.identity_sha256}:"
            f"{self.candidate_sha}"
        )

        return {
            "id": 9900,
            "name": "Main qualification",
            "head_sha": self.candidate_sha,
            "external_id": external_id,
            "status": "completed",
            "conclusion": self.check_conclusion,
            "app": {
                "id": self.app_id,
                "slug": (
                    "nutrition-qualification"
                ),
            },
        }

    def list_check_runs(
        self,
        repository: str,
        candidate_sha: str,
        app_id: int,
    ) -> list[dict]:
        assert candidate_sha == (
            self.candidate_sha
        )

        check = self._check()

        return [
            dict(check)
            for _ in range(
                self.check_count
            )
        ]

    def get_check_run(
        self,
        repository: str,
        check_id: int,
    ) -> dict:
        assert check_id == 9900
        return self._check()


class FakeCandidateRefTransport:
    def __init__(self) -> None:
        self.published: list[
            tuple[str, str]
        ] = []
        self.deleted: list[str] = []
        self.main_pushes: list[str] = []
        self.main_sha: str | None = None

    def publish_candidate_ref(
        self,
        ref_name: str,
        candidate_sha: str,
    ) -> None:
        self.published.append(
            (
                ref_name,
                candidate_sha,
            )
        )

    def delete_candidate_ref(
        self,
        ref_name: str,
    ) -> None:
        self.deleted.append(ref_name)

    def push_main(
        self,
        candidate_sha: str,
    ) -> None:
        self.main_pushes.append(
            candidate_sha
        )
        self.main_sha = candidate_sha

    def fetch_main(self) -> str:
        assert self.main_sha is not None
        return self.main_sha


def authorized_repo_state(
    tmp_path: Path,
):
    repo, base = init_repo(tmp_path)

    state_dir = tmp_path / "state"

    state = TASK.prepare_task(
        repo=repo,
        state_dir=state_dir,
        issue_number=999,
        task_id="GH-999-P1",
        trusted_author="owner",
        repository="owner/repo",
        base_sha=base,
        allowed_paths=["src/**"],
        forbidden_paths=[],
        profiles=["repository"],
        revision=1,
        nonce="nonce-1234567890abcdef",
    )

    issue_transport = (
        FakeIssueAuthorizationTransport(
            author="owner",
        )
    )

    state = TASK.authorize_task(
        state,
        transport=issue_transport,
    )

    comment = dict(
        issue_transport.comments[7001]
    )

    path = repo / "src/value.py"
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "candidate",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    return (
        repo,
        base,
        candidate,
        state,
        comment,
    )


def qualify_fixture(
    tmp_path: Path,
    **transport_kwargs,
):
    (
        repo,
        base,
        candidate,
        state,
        comment,
    ) = authorized_repo_state(
        tmp_path
    )

    transport = (
        FakeQualificationTransport(
            comment=comment,
            controller_sha=base,
            candidate_sha=candidate,
            identity_sha256=state[
                "authorization"
            ]["identity_sha256"],
            **transport_kwargs,
        )
    )

    refs = FakeCandidateRefTransport()

    updated = TASK.qualify_task(
        state,
        candidate_repo=repo,
        controller_main_sha=base,
        expected_app_id=424242,
        transport=transport,
        ref_transport=refs,
        poll_attempts=2,
        sleep_seconds=0,
        sleep_fn=lambda _: None,
        dispatch_nonce=(
            "dispatch-1234567890"
        ),
    )

    return (
        repo,
        base,
        candidate,
        updated,
        transport,
        refs,
    )


def test_qualify_binds_exact_run_check_and_cleans_ref(
    tmp_path: Path,
) -> None:
    (
        _,
        _,
        candidate,
        updated,
        _,
        refs,
    ) = qualify_fixture(tmp_path)

    qualification = updated[
        "qualification"
    ]

    assert updated["phase"] == "QUALIFIED"
    assert qualification[
        "candidate_sha"
    ] == candidate
    assert qualification[
        "workflow_run_id"
    ] == 8800
    assert qualification[
        "check_id"
    ] == 9900
    assert qualification[
        "check_app_id"
    ] == 424242
    assert qualification[
        "result"
    ] == "PASS"
    assert qualification[
        "candidate_ref_removed"
    ] is True
    assert len(refs.published) == 1
    assert len(refs.deleted) == 1


def test_qualify_records_failed_authoritative_check_and_cleans_ref(
    tmp_path: Path,
) -> None:
    (
        _,
        _,
        _,
        updated,
        _,
        refs,
    ) = qualify_fixture(
        tmp_path,
        run_conclusion="failure",
        check_conclusion="failure",
    )

    assert (
        updated["phase"]
        == "QUALIFICATION_FAILED"
    )
    assert (
        updated["qualification"]["result"]
        == "FAIL"
    )
    assert len(refs.deleted) == 1


def test_qualify_dispatch_fallback_uses_unique_run_title(
    tmp_path: Path,
) -> None:
    (
        _,
        _,
        _,
        updated,
        _,
        _,
    ) = qualify_fixture(
        tmp_path,
        dispatch_returns_id=False,
    )

    assert (
        updated["qualification"][
            "workflow_run_id"
        ]
        == 8800
    )


def test_qualify_rejects_duplicate_external_authority(
    tmp_path: Path,
) -> None:
    (
        repo,
        base,
        candidate,
        state,
        comment,
    ) = authorized_repo_state(
        tmp_path
    )

    transport = (
        FakeQualificationTransport(
            comment=comment,
            controller_sha=base,
            candidate_sha=candidate,
            identity_sha256=state[
                "authorization"
            ]["identity_sha256"],
        )
    )

    duplicate = dict(comment)
    duplicate["id"] = 7002

    transport.comments.append(
        duplicate
    )

    refs = FakeCandidateRefTransport()

    with pytest.raises(
        AuthorizationError,
        match="AUTHORIZATION_AMBIGUOUS",
    ):
        TASK.qualify_task(
            state,
            candidate_repo=repo,
            controller_main_sha=base,
            expected_app_id=424242,
            transport=transport,
            ref_transport=refs,
            poll_attempts=1,
            sleep_seconds=0,
            sleep_fn=lambda _: None,
        )

    assert refs.published == []


def test_qualify_rejects_wrong_trusted_workflow_head_and_cleans_ref(
    tmp_path: Path,
) -> None:
    (
        repo,
        base,
        candidate,
        state,
        comment,
    ) = authorized_repo_state(
        tmp_path
    )

    transport = (
        FakeQualificationTransport(
            comment=comment,
            controller_sha=base,
            candidate_sha=candidate,
            identity_sha256=state[
                "authorization"
            ]["identity_sha256"],
            run_head_override="f" * 40,
        )
    )

    refs = FakeCandidateRefTransport()

    with pytest.raises(
        TASK.TaskControllerError,
        match="WORKFLOW_RUN_IDENTITY_MISMATCH",
    ):
        TASK.qualify_task(
            state,
            candidate_repo=repo,
            controller_main_sha=base,
            expected_app_id=424242,
            transport=transport,
            ref_transport=refs,
            poll_attempts=1,
            sleep_seconds=0,
            sleep_fn=lambda _: None,
        )

    assert len(refs.deleted) == 1


def test_qualify_rejects_duplicate_authoritative_app_checks(
    tmp_path: Path,
) -> None:
    (
        repo,
        base,
        candidate,
        state,
        comment,
    ) = authorized_repo_state(
        tmp_path
    )

    transport = (
        FakeQualificationTransport(
            comment=comment,
            controller_sha=base,
            candidate_sha=candidate,
            identity_sha256=state[
                "authorization"
            ]["identity_sha256"],
            check_count=2,
        )
    )

    refs = FakeCandidateRefTransport()

    with pytest.raises(
        TASK.TaskControllerError,
        match="AUTHORITATIVE_CHECK_AMBIGUOUS",
    ):
        TASK.qualify_task(
            state,
            candidate_repo=repo,
            controller_main_sha=base,
            expected_app_id=424242,
            transport=transport,
            ref_transport=refs,
            poll_attempts=1,
            sleep_seconds=0,
            sleep_fn=lambda _: None,
        )

    assert len(refs.deleted) == 1


def reviewed_qualified_fixture(
    tmp_path: Path,
):
    (
        repo,
        base,
        candidate,
        qualified,
        transport,
        refs,
    ) = qualify_fixture(
        tmp_path
    )

    verified = TASK.record_verification(
        qualified,
        candidate_sha=candidate,
        actor="verifier",
        decision="pass",
        evidence="review-bundle.zip",
    )

    reviewed = TASK.record_review(
        verified,
        candidate_sha=candidate,
        actor="reviewer",
        decision="approved",
        summary="Approved.",
    )

    return (
        repo,
        base,
        candidate,
        reviewed,
        transport,
        refs,
    )


def test_integrate_requires_explicit_human_owner_authority(
    tmp_path: Path,
) -> None:
    (
        repo,
        base,
        _,
        reviewed,
        transport,
        refs,
    ) = reviewed_qualified_fixture(
        tmp_path
    )

    with pytest.raises(
        TASK.TaskControllerError,
        match="HUMAN_OWNER_AUTHORIZATION_REQUIRED",
    ):
        TASK.integrate_task(
            reviewed,
            candidate_repo=repo,
            controller_main_sha=base,
            expected_app_id=424242,
            transport=transport,
            ref_transport=refs,
            human_owner_authorized=False,
        )


def test_integrate_revalidates_check_and_persists_pending_before_push(
    tmp_path: Path,
) -> None:
    (
        repo,
        base,
        candidate,
        reviewed,
        transport,
        refs,
    ) = reviewed_qualified_fixture(
        tmp_path
    )

    pending = TASK.integrate_task(
        reviewed,
        candidate_repo=repo,
        controller_main_sha=base,
        expected_app_id=424242,
        transport=transport,
        ref_transport=refs,
        human_owner_authorized=True,
    )

    assert (
        pending["phase"]
        == "INTEGRATION_PENDING"
    )
    assert refs.main_pushes == []
    assert (
        pending["integration"][
            "origin_main_before"
        ]
        == base
    )
    assert (
        pending["integration"][
            "origin_main_after"
        ]
        is None
    )

    refs.main_sha = base

    integrated = (
        TASK.reconcile_integration(
            pending,
            candidate_sha=candidate,
            ref_transport=refs,
        )
    )

    assert (
        integrated["phase"]
        == "INTEGRATED"
    )
    assert refs.main_pushes == [
        candidate
    ]
    assert (
        integrated["integration"][
            "origin_main_after"
        ]
        == candidate
    )


def test_integrate_reconciles_crash_after_remote_push_without_duplicate_push(
    tmp_path: Path,
) -> None:
    (
        repo,
        base,
        candidate,
        reviewed,
        transport,
        refs,
    ) = reviewed_qualified_fixture(
        tmp_path
    )

    pending = TASK.integrate_task(
        reviewed,
        candidate_repo=repo,
        controller_main_sha=base,
        expected_app_id=424242,
        transport=transport,
        ref_transport=refs,
        human_owner_authorized=True,
    )

    # Simulate a process crash after GitHub accepted the
    # main update but before INTEGRATED was persisted.
    refs.main_sha = candidate

    recovered = (
        TASK.reconcile_integration(
            pending,
            candidate_sha=candidate,
            ref_transport=refs,
        )
    )

    assert recovered["phase"] == "INTEGRATED"
    assert refs.main_pushes == []
    assert (
        recovered["integration"][
            "origin_main_after"
        ]
        == candidate
    )

    rerun = TASK.reconcile_integration(
        recovered,
        candidate_sha=candidate,
        ref_transport=refs,
    )

    assert rerun["phase"] == "INTEGRATED"
    assert refs.main_pushes == []


def test_integrate_recovery_fails_closed_on_remote_main_divergence(
    tmp_path: Path,
) -> None:
    (
        repo,
        base,
        candidate,
        reviewed,
        transport,
        refs,
    ) = reviewed_qualified_fixture(
        tmp_path
    )

    pending = TASK.integrate_task(
        reviewed,
        candidate_repo=repo,
        controller_main_sha=base,
        expected_app_id=424242,
        transport=transport,
        ref_transport=refs,
        human_owner_authorized=True,
    )

    refs.main_sha = "f" * 40

    with pytest.raises(
        TASK.TaskControllerError,
        match="INTEGRATION_MAIN_DIVERGED",
    ):
        TASK.reconcile_integration(
            pending,
            candidate_sha=candidate,
            ref_transport=refs,
        )

    assert refs.main_pushes == []

def test_integrate_rejects_dedicated_app_source_drift(
    tmp_path: Path,
) -> None:
    (
        repo,
        base,
        _,
        reviewed,
        transport,
        refs,
    ) = reviewed_qualified_fixture(
        tmp_path
    )

    transport.app_id = 15368

    with pytest.raises(
        TASK.TaskControllerError,
        match="INTEGRATION_CHECK_REVALIDATION_FAILED",
    ):
        TASK.integrate_task(
            reviewed,
            candidate_repo=repo,
            controller_main_sha=base,
            expected_app_id=424242,
            transport=transport,
            ref_transport=refs,
            human_owner_authorized=True,
        )

    assert refs.main_pushes == []


def test_trusted_controller_requires_clean_synchronized_main(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    git(
        repo,
        "branch",
        "-M",
        "main",
    )

    git(
        repo,
        "remote",
        "add",
        "origin",
        "https://github.com/owner/repo.git",
    )

    assert (
        TASK.require_trusted_main_controller(
            repo,
            expected_repository="owner/repo",
        )
        == base
    )

    (repo / "dirty.txt").write_text(
        "dirty\n",
        encoding="utf-8",
    )

    with pytest.raises(
        TASK.TaskControllerError,
        match="TRUSTED_CONTROLLER_DIRTY",
    ):
        TASK.require_trusted_main_controller(
            repo,
            expected_repository="owner/repo",
        )


def test_trusted_qualification_cli_runs_as_standalone_script() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(
                SCRIPTS
                / "lib"
                / "trusted_qualification.py"
            ),
            "--help",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={
            key: value
            for key, value in __import__(
                "os"
            ).environ.items()
            if key != "PYTHONPATH"
        },
    )

    assert completed.returncode == 0, (
        completed.stderr
        or completed.stdout
    )

    assert (
        "Trusted candidate-independent qualification helper."
        in completed.stdout
    )
