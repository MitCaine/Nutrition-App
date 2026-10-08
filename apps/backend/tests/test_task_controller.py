from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import threading
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
# Explicit historical fixtures do not make these modules standard startup dependencies.
from lib.legacy_ri import candidate_evidence as LEGACY_EVIDENCE  # noqa: E402


def test_retired_execution_command_cannot_create_a_checkpoint(tmp_path):
    state_dir = tmp_path / "controller"
    with pytest.raises(SystemExit) as result:
        TASK.build_parser().parse_args(["--state-dir", str(state_dir), "execution", "999", "prepare"])
    assert result.value.code == 2
    assert not state_dir.exists()


def test_retired_execution_command_preserves_existing_attempt(tmp_path):
    state_dir = tmp_path / "controller"
    state_dir.mkdir()
    checkpoint = state_dir / "execution-999.json"
    original = b'{"phase":"STOP_REPLAN","allowance_used":1}'
    checkpoint.write_bytes(original)
    with pytest.raises(SystemExit):
        TASK.build_parser().parse_args(["--state-dir", str(state_dir), "execution", "999", "resume"])
    assert checkpoint.read_bytes() == original


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
    revision: int = 1,
    nonce: str = "nonce-1234567890abcdef",
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
        revision=revision,
        nonce=nonce,
    )


def commit_paths(
    repo: Path,
    contents: dict[str, str],
    *,
    message: str = "candidate",
) -> str:
    for relative_path, content in contents.items():
        path = repo / relative_path
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            content,
            encoding="utf-8",
        )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        message,
    )
    return git(repo, "rev-parse", "HEAD")


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
    revision: int = 1,
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
        expected_revision=revision,
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


def test_scope_rejects_forbidden_commit_hidden_by_restore(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    forbidden = repo / "src/forbidden/item.py"
    forbidden.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    forbidden.write_text(
        "TEMPORARY = True\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "introduce forbidden path")

    forbidden.unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "restore forbidden path")

    allowed = repo / "src/final.py"
    allowed.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "add allowed final change")

    candidate = git(repo, "rev-parse", "HEAD")
    assert git(
        repo,
        "diff",
        "--name-only",
        f"{base}..{candidate}",
    ) == "src/final.py"

    auth = resolve(
        authorization_payload(
            base,
            allowed_paths=["src/**"],
            forbidden_paths=["src/forbidden/**"],
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


def test_scope_accepts_allowed_multi_commit_history(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    for name in ("first.py", "second.py"):
        path = repo / "src" / name
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            f"NAME = {name!r}\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", f"add {name}")

    candidate = git(repo, "rev-parse", "HEAD")
    auth = resolve(authorization_payload(base))

    assert validate_candidate_scope(
        repo,
        auth,
        candidate_sha=candidate,
    ) == [
        "src/first.py",
        "src/second.py",
    ]


def test_scope_rejects_implementation_merge_history(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)
    git(repo, "branch", "-m", "candidate")

    main_change = repo / "src/main.py"
    main_change.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    main_change.write_text(
        "MAIN = True\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "candidate change")

    git(repo, "checkout", "-q", "-b", "side", base)
    side_change = repo / "src/side.py"
    side_change.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    side_change.write_text(
        "SIDE = True\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "side change")

    git(repo, "checkout", "-q", "candidate")
    git(repo, "merge", "--no-ff", "-q", "side", "-m", "merge side history")
    candidate = git(repo, "rev-parse", "HEAD")
    auth = resolve(authorization_payload(base))

    with pytest.raises(
        AuthorizationError,
        match="SCOPE_MERGE_UNSUPPORTED",
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


def test_native_path_requires_ios_native_profile(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    path = repo / "apps/mobile/app.json"
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "{}\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "native candidate",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    auth = resolve(
        authorization_payload(
            base,
            allowed_paths=[
                "apps/mobile/app.json",
            ],
            profiles=[
                "repository",
                "mobile",
            ],
        )
    )

    with pytest.raises(
        AuthorizationError,
        match="QUALIFICATION_PROFILE_REQUIRED",
    ):
        validate_candidate_scope(
            repo,
            auth,
            candidate_sha=candidate,
        )


def test_native_path_accepts_ios_native_profile(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)

    path = repo / "apps/mobile/app.json"
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "{}\n",
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "native candidate",
    )

    candidate = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    auth = resolve(
        authorization_payload(
            base,
            allowed_paths=[
                "apps/mobile/app.json",
            ],
            profiles=[
                "repository",
                "mobile",
                "ios-native",
            ],
        )
    )

    assert validate_candidate_scope(
        repo,
        auth,
        candidate_sha=candidate,
    ) == [
        "apps/mobile/app.json",
    ]


@pytest.mark.parametrize(
    ("path", "profiles", "missing_profile"),
    [
        (
            "apps/backend/tests/test_task_controller.py",
            ["repository"],
            "backend",
        ),
        (
            "apps/mobile/src/runtime/session.ts",
            ["repository"],
            "mobile",
        ),
        (
            "apps/backend/app/migrations/versions/0034_example.py",
            ["repository", "backend"],
            "postgresql",
        ),
        (
            "scripts/lib/task_authorization.py",
            ["repository", "backend"],
            "ios-native",
        ),
    ],
)
def test_candidate_scope_rejects_each_missing_minimum_profile(
    tmp_path: Path,
    path: str,
    profiles: list[str],
    missing_profile: str,
) -> None:
    repo, base = init_repo(tmp_path)
    candidate = commit_paths(
        repo,
        {path: "candidate change\n"},
    )
    auth = resolve(
        authorization_payload(
            base,
            allowed_paths=[path],
            profiles=profiles,
        )
    )
    authorized_profiles = auth.profiles

    with pytest.raises(
        AuthorizationError,
        match="QUALIFICATION_PROFILE_REQUIRED",
    ) as context:
        validate_candidate_scope(
            repo,
            auth,
            candidate_sha=candidate,
        )

    assert missing_profile in str(context.value)
    assert auth.profiles == authorized_profiles


def test_candidate_scope_requires_combined_floor_without_changing_authorization(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)
    changed = {
        "apps/backend/app/models/food.py": "class Food: pass\n",
        "apps/mobile/app.json": "{}\n",
    }
    candidate = commit_paths(repo, changed)
    selected_profiles = ["repository", "backend"]
    auth = resolve(
        authorization_payload(
            base,
            allowed_paths=sorted(changed),
            profiles=selected_profiles,
        )
    )
    authorized_profiles = auth.profiles

    with pytest.raises(
        AuthorizationError,
        match="QUALIFICATION_PROFILE_REQUIRED",
    ) as context:
        validate_candidate_scope(
            repo,
            auth,
            candidate_sha=candidate,
        )

    message = str(context.value)
    assert "mobile" in message
    assert "postgresql" in message
    assert "ios-native" in message
    assert auth.profiles == authorized_profiles


def test_planning_rejects_insufficient_profiles_then_accepts_owner_revision(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)
    planning_path = "engineering/capsules/active/GH-999-P1.md"
    owned_path = "apps/backend/app/models/food.py"
    candidate = commit_paths(
        repo,
        {planning_path: "capsule-only planning change\n"},
    )
    selected_profiles = ["repository", "backend"]
    allowed_paths = [planning_path, owned_path]
    insufficient_payload = authorization_payload(
        base,
        allowed_paths=allowed_paths,
        profiles=selected_profiles,
    )
    auth = resolve(
        insufficient_payload,
        comment_id=12345,
        revision=1,
    )
    authorized_profiles = auth.profiles

    with pytest.raises(
        AuthorizationError,
        match="QUALIFICATION_PROFILE_REQUIRED",
    ) as context:
        build_plan(
            repo,
            auth,
            candidate_sha=candidate,
            candidate_ref=(
                "task-candidate/999/"
                + candidate[:12]
            ),
        )

    assert "planned or changed paths" in str(context.value)
    assert auth.profiles == authorized_profiles

    revised_profiles = [
        "repository",
        "backend",
        "postgresql",
        "mobile",
    ]
    revised_payload = authorization_payload(
        base,
        allowed_paths=allowed_paths,
        profiles=revised_profiles,
        revision=2,
        nonce="nonce-2234567890abcdef",
    )
    revised_auth = resolve(
        revised_payload,
        comment_id=12346,
        revision=2,
    )
    revised_plan = build_plan(
        repo,
        revised_auth,
        candidate_sha=candidate,
        candidate_ref=(
            "task-candidate/999/"
            + candidate[:12]
        ),
    )

    assert revised_plan["authorization_revision"] == 2
    assert revised_plan["authorization_comment_id"] == 12346
    assert revised_plan["changed_paths"] == [planning_path]
    assert revised_plan["profiles"] == revised_profiles


def test_docs_only_plan_keeps_exact_owner_selected_profiles(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)
    path = "docs/operations/testing.md"
    candidate = commit_paths(
        repo,
        {path: "Documentation only.\n"},
    )
    auth = resolve(
        authorization_payload(
            base,
            allowed_paths=[path],
            profiles=["repository"],
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

    assert plan["changed_paths"] == [path]
    assert plan["profiles"] == ["repository"]
    assert auth.profiles == ("repository",)


def test_ordinary_backend_scope_does_not_require_postgresql(
    tmp_path: Path,
) -> None:
    repo, base = init_repo(tmp_path)
    path = "apps/backend/tests/test_task_controller.py"
    candidate = commit_paths(
        repo,
        {path: "ordinary backend regression\n"},
    )
    auth = resolve(
        authorization_payload(
            base,
            allowed_paths=["apps/backend/**"],
            profiles=["repository", "backend"],
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

    assert plan["profiles"] == ["repository", "backend"]


@pytest.mark.parametrize(
    ("path", "profiles"),
    [
        (
            "apps/backendish/app/models/food.py",
            ["repository"],
        ),
        (
            "apps/mobileish/app.json",
            ["repository"],
        ),
        (
            "apps/backend/app/migrations_extra/versions/0034_example.py",
            ["repository", "backend"],
        ),
        (
            "apps/backend/app/repositories_extra/food_repository.py",
            ["repository", "backend"],
        ),
    ],
)
def test_scope_path_lookalikes_do_not_trigger_neighboring_floors(
    tmp_path: Path,
    path: str,
    profiles: list[str],
) -> None:
    repo, base = init_repo(tmp_path)
    candidate = commit_paths(
        repo,
        {path: "lookalike path\n"},
    )
    auth = resolve(
        authorization_payload(
            base,
            allowed_paths=[path],
            profiles=profiles,
        )
    )

    assert validate_candidate_scope(
        repo,
        auth,
        candidate_sha=candidate,
    ) == [path]


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
    assert state["workflow"]["mode"] == "standard"
    assert state["workflow"]["reason"] is None
    assert state["workflow"]["authority"] is None

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
    assert TASK.WORKFLOW_MODE_MARKER in draft.read_text(encoding="utf-8")

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
    *,
    workflow_mode: str = "attached",
    compatibility_reason: str | None = None,
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
        workflow_mode=workflow_mode,
        compatibility_reason=compatibility_reason,
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


def test_compatibility_mode_is_bound_to_the_trusted_owner_comment(
    tmp_path: Path,
) -> None:
    state = prepared_external_state(
        tmp_path,
        workflow_mode="compatibility",
        compatibility_reason="Existing automation is still in flight.",
    )
    transport = FakeIssueAuthorizationTransport()
    authorized = TASK.authorize_task(state, transport=transport)

    assert authorized["workflow"]["mode"] == "compatibility"
    assert authorized["workflow"]["reason"] == "Existing automation is still in flight."
    assert authorized["workflow"]["authority"]["comment_id"] == 7001
    assert authorized["workflow"]["authority"]["author_login"] == "owner"

    class CommentReader:
        def list_issue_comments(self, repository: str, issue_number: int) -> list[dict]:
            assert repository == "owner/repo"
            assert issue_number == 999
            return list(transport.comments.values())

    TASK.resolve_current_authorization(authorized, CommentReader())
    authorized_body = transport.comments[7001]["body"]
    transport.comments[7001]["body"] = authorized_body.split(
        TASK.WORKFLOW_MODE_MARKER, 1
    )[0].rstrip()
    with pytest.raises(TASK.TaskControllerError, match="WORKFLOW_SELECTION_MARKER_INVALID"):
        TASK.resolve_current_authorization(authorized, CommentReader())
    transport.comments[7001]["body"] = authorized_body

    transport.comments[7001]["body"] = transport.comments[7001]["body"].replace(
        "Existing automation is still in flight.",
        "The mode reason was edited.",
    )
    with pytest.raises(TASK.TaskControllerError, match="WORKFLOW_AUTHORITY_CURRENT_IDENTITY_MISMATCH"):
        TASK.resolve_current_authorization(authorized, CommentReader())


def test_compatibility_mode_requires_a_nonempty_reason(
    tmp_path: Path,
) -> None:
    with pytest.raises(TASK.TaskControllerError, match="WORKFLOW_COMPATIBILITY_REASON_REQUIRED"):
        prepared_external_state(tmp_path, workflow_mode="compatibility")


def test_pre_change_authorization_state_keeps_legacy_gates(
    tmp_path: Path,
) -> None:
    _, base, candidate, authorized, comment = authorized_repo_state(
        tmp_path,
        workflow_mode="compatibility",
        compatibility_reason="Existing work remains on its established route.",
    )
    # This was a valid pre-change nonce value and must not identify the new mode by shape.
    legacy_nonce = "wf-" + ("a" * 64) + "." + ("b" * 32)
    legacy_payload = build_payload(
        task_id=authorized["task_id"],
        issue_number=authorized["issue_number"],
        repository=authorized["repository"],
        base_sha=authorized["authorization"]["base_sha"],
        allowed_paths=["src/**"],
        forbidden_paths=[],
        profiles=["repository"],
        revision=authorized["authorization"]["revision"],
        nonce=legacy_nonce,
    )
    comment["body"] = render_authorization_comment(legacy_payload)
    legacy_authorization = resolve_comment(
        comment,
        trusted_author="owner",
        expected_repository="owner/repo",
        expected_issue_number=999,
        expected_task_id="GH-999-P1",
        expected_revision=1,
        expected_comment_id=7001,
    )
    authorized.pop("workflow")
    authorized["authorization"].pop("workflow_selection_sha256")
    authorized["authorization"].update(
        {
            "nonce": legacy_authorization.nonce,
            "payload_sha256": legacy_authorization.payload_sha256,
            "identity_sha256": legacy_authorization.identity_sha256,
        }
    )
    assert "workflow" not in authorized

    qualification_transport = FakeQualificationTransport(
        comment=comment,
        controller_sha=base,
        candidate_sha=candidate,
        identity_sha256=legacy_authorization.identity_sha256,
    )
    qualified = TASK.qualify_task(
        authorized,
        candidate_repo=tmp_path / "repo",
        controller_main_sha=base,
        expected_app_id=424242,
        transport=qualification_transport,
        ref_transport=FakeCandidateRefTransport(),
        poll_attempts=2,
        sleep_seconds=0,
        sleep_fn=lambda _: None,
    )
    assert qualified["phase"] == "QUALIFIED"
    assert qualification_transport.dispatch_inputs is not None
    verified = TASK.record_verification(
        qualified,
        candidate_sha=candidate,
        actor="verifier",
        decision="pass",
        evidence="legacy check record",
    )
    reviewed = TASK.record_review(
        verified,
        candidate_sha=candidate,
        actor="reviewer",
        decision="approved",
        summary="legacy review",
    )
    assert reviewed["phase"] == "REVIEWED_APPROVED"


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
    nonce = state["authorization"]["nonce"]
    changed_nonce = nonce[:-1] + ("0" if nonce[-1] != "0" else "1")

    def mutate(body: str) -> str:
        return body.replace(f'"nonce": "{nonce}"', f'"nonce": "{changed_nonce}"')

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

TRUSTED_EXECUTOR_WORKFLOW = (
    ROOT
    / ".github/workflows/trusted-qualification-execute.yml"
)


def workflow_text(
    path: Path = TRUSTED_WORKFLOW,
) -> str:
    return path.read_text(
        encoding="utf-8"
    )


def workflow_job_slice(
    job_name: str,
    next_job_name: str | None,
    *,
    path: Path = TRUSTED_EXECUTOR_WORKFLOW,
) -> str:
    text = workflow_text(path)

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
    executor_text = workflow_text(
        TRUSTED_EXECUTOR_WORKFLOW
    )

    assert "\n  workflow_dispatch:\n" in text
    assert "\n  push:" not in text
    assert "\n  pull_request:" not in text
    assert "run-name: >-" in text

    plan = workflow_job_slice(
        "plan",
        "repository",
    )

    assert (
        "ref: ${{ github.event.workflow_run.head_sha }}"
        in plan
    )
    assert "ref: main" not in plan
    assert (
        "ref: ${{ needs.handoff.outputs.candidate_sha }}"
        in plan
    )
    assert (
        "trusted/scripts/lib/trusted_qualification.py"
        in plan
    )

    assert (
        executor_text.count(
            "ref: ${{ github.event.workflow_run.head_sha }}"
        )
        == 5
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
        assert text.count(binding) == 1

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
        expected_count = 8 if binding == '--candidate-sha "${CANDIDATE_SHA}"' else 2
        assert executor_text.count(binding) == expected_count

    repository_job = workflow_job_slice("repository", "backend")
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in repository_job
    assert "path: trusted" in repository_job
    assert "trusted/scripts/lib/tooling_qualification.py" in repository_job
    assert "persist-credentials: false" in repository_job

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
        if job in {"backend", "backend-postgres"}:
            assert "Prepare ordinary exact candidate checkout" in body
            assert "working-directory: ${{ github.workspace }}" in body
            assert "CANDIDATE_SHA: ${{ needs.plan.outputs.candidate_sha }}" in body
            assert "trusted/scripts/lib/backend_qualification.py checkout" in body
            assert '--candidate-root candidate --candidate-sha "${CANDIDATE_SHA}"' in body
            assert "github.token" not in body
            assert "GH_TOKEN" not in body
        else:
            assert (
                "ref: ${{ needs.plan.outputs.candidate_sha }}"
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
        "ref: ${{ github.event.workflow_run.head_sha }}"
        in body
    )
    assert "ref: main" not in body
    assert (
        "ref: ${{ needs.plan.outputs.candidate_sha }}"
        in body
    )
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
        self.dispatch_calls = 0

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

        self.dispatch_calls += 1
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
    def __init__(self, *, fail_delete_count: int = 0) -> None:
        self.published: list[
            tuple[str, str]
        ] = []
        self.deleted: list[str] = []
        self.main_pushes: list[str] = []
        self.main_sha: str | None = None
        self.fail_delete_count = fail_delete_count

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
        if self.fail_delete_count:
            self.fail_delete_count -= 1
            raise TASK.TaskControllerError("CANDIDATE_REF_CLEANUP_FAILED")
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
    *,
    forbidden_paths: list[str] | None = None,
    workflow_mode: str = "compatibility",
    compatibility_reason: str | None = "Existing test caller retains the compatibility route.",
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
        forbidden_paths=forbidden_paths or [],
        profiles=["repository"],
        revision=1,
        nonce="nonce-1234567890abcdef",
        workflow_mode=workflow_mode,
        compatibility_reason=compatibility_reason,
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
    *,
    workflow_mode: str = "compatibility",
    compatibility_reason: str | None = "Existing test caller retains the compatibility route.",
    **transport_kwargs,
):
    (
        repo,
        base,
        candidate,
        state,
        comment,
    ) = authorized_repo_state(
        tmp_path,
        workflow_mode=workflow_mode,
        compatibility_reason=compatibility_reason,
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


def test_explicit_compatibility_mode_uses_its_authenticated_legacy_route(
    tmp_path: Path,
) -> None:
    (
        _,
        _,
        candidate,
        qualified,
        transport,
        _,
    ) = qualify_fixture(
        tmp_path,
        workflow_mode="compatibility",
        compatibility_reason="Existing caller has no capsule transport yet.",
    )

    assert qualified["workflow"]["mode"] == "compatibility"
    assert qualified["phase"] == "QUALIFIED"
    assert transport.dispatch_inputs is not None

    verified = TASK.record_verification(
        qualified,
        candidate_sha=candidate,
        actor="verifier",
        decision="pass",
        evidence="candidate check passed",
    )
    reviewed = TASK.record_review(
        verified,
        candidate_sha=candidate,
        actor="reviewer",
        decision="approved",
        summary="compatibility review passed",
    )
    assert reviewed["phase"] == "REVIEWED_APPROVED"


def test_attached_default_requires_evidence_across_public_gates(
    tmp_path: Path,
) -> None:
    from lib.legacy_ri.candidate_evidence import EvidenceError

    repo, base, candidate, state, comment = authorized_repo_state(
        tmp_path,
        workflow_mode="attached",
        compatibility_reason=None,
    )
    transport = FakeQualificationTransport(
        comment=comment,
        controller_sha=base,
        candidate_sha=candidate,
        identity_sha256=state["authorization"]["identity_sha256"],
    )
    refs = FakeCandidateRefTransport()
    with pytest.raises(EvidenceError, match="FRESH_CANDIDATE_ATTACHMENT_REQUIRED"):
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
    assert transport.dispatch_inputs is None

    with pytest.raises(EvidenceError, match="FRESH_CANDIDATE_ATTACHMENT_REQUIRED"):
        TASK.record_qualification(
            state,
            candidate_sha=candidate,
            workflow_run_id=8800,
            check_id=9900,
            check_app_id=424242,
            result="PASS",
        )

    state["qualification"] = {"result": "PASS", "candidate_sha": candidate}
    with pytest.raises(EvidenceError, match="FRESH_CANDIDATE_ATTACHMENT_REQUIRED"):
        TASK.record_verification(
            state,
            candidate_sha=candidate,
            actor="verifier",
            decision="pass",
            evidence="assertion only",
        )
    with pytest.raises(EvidenceError, match="FRESH_CANDIDATE_ATTACHMENT_REQUIRED"):
        TASK.record_review(
            state,
            candidate_sha=candidate,
            actor="reviewer",
            decision="approved",
            summary="assertion only",
        )

    state.update(
        phase="REVIEWED_APPROVED",
        verification={"decision": "pass", "candidate_sha": candidate},
        review={"decision": "approved", "candidate_sha": candidate},
        qualification={
            "result": "PASS",
            "candidate_sha": candidate,
            "check_app_id": 424242,
            "candidate_ref_removed": True,
            "check_id": 9900,
            "workflow_run_id": 8800,
        },
    )
    with pytest.raises(EvidenceError, match="CANDIDATE_ATTACHMENT_REQUIRED"):
        TASK.integrate_task(
            state,
            candidate_repo=repo,
            controller_main_sha=base,
            expected_app_id=424242,
            transport=transport,
            ref_transport=refs,
            human_owner_authorized=True,
        )


def test_record_qualification_authenticates_binding_and_review_preflight(
    tmp_path: Path,
) -> None:
    from lib.legacy_ri.candidate_evidence import EvidenceError

    _, base, candidate, state, comment = authorized_repo_state(
        tmp_path,
        workflow_mode="attached",
        compatibility_reason=None,
    )
    authorization = resolve_comment(
        comment,
        trusted_author="owner",
        expected_repository="owner/repo",
        expected_issue_number=999,
        expected_task_id="GH-999-P1",
        expected_revision=1,
        expected_comment_id=7001,
    )

    state["capsule_evidence"] = {"binding": {"candidate": candidate}}
    with pytest.raises(EvidenceError, match="ATTACHMENT_DIGEST_MISMATCH"):
        TASK.record_qualification(
            state,
            candidate_sha=candidate,
            workflow_run_id=8800,
            check_id=9900,
            check_app_id=424242,
            result="PASS",
            authorization=authorization,
        )

    binding = {"authorization": authorization.to_dict(), "candidate": candidate}
    binding["binding_sha256"] = LEGACY_EVIDENCE.digest(binding)
    state["capsule_evidence"] = {"binding": binding}
    with pytest.raises(EvidenceError, match="REVIEW_PREFLIGHT_REQUIRED_OR_STALE"):
        TASK.record_qualification(
            state,
            candidate_sha=candidate,
            workflow_run_id=8800,
            check_id=9900,
            check_app_id=424242,
            result="PASS",
            authorization=authorization,
        )

    state["capsule_evidence"]["review_preflight"] = {
        "binding_sha256": binding["binding_sha256"],
        "candidate_sha": candidate,
        "failure_count": 0,
        "model": "gpt-6-sol",
        "effort": "medium",
        "runtime": {"executable": str(Path(sys.executable).resolve()), "sha256": "a" * 64},
    }
    qualified = TASK.record_qualification(
        state,
        candidate_sha=candidate,
        workflow_run_id=8800,
        check_id=9900,
        check_app_id=424242,
        result="PASS",
        authorization=authorization,
    )
    assert qualified["phase"] == "QUALIFIED"


def test_authorize_and_qualify_guidance_tracks_workflow_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    for mode, reason, expected_authorize, expected_qualify in (
        ("standard", None, "qualify", "verify"),
        (
            "attached",
            None,
            "plan_capsule",
            "historical_evidence_sealing_unsupported_owner_decision_required",
        ),
        ("compatibility", "Existing caller is not capsule-ready.", "qualify", "verify"),
    ):
        case_root = tmp_path / mode
        case_root.mkdir(parents=True)
        prepared = prepared_external_state(
            case_root,
            workflow_mode=mode,
            compatibility_reason=reason,
        )
        authorized = TASK.authorize_task(
            prepared,
            transport=FakeIssueAuthorizationTransport(),
        )
        outputs: list[dict] = []
        repo = case_root / "repo"
        state_dir = case_root / "controller-state"

        monkeypatch.setattr(TASK, "load_state", lambda *_args, value=prepared: value)
        monkeypatch.setattr(TASK, "resolve_repo_root", lambda _root: repo)
        monkeypatch.setattr(TASK, "git", lambda *_args: "")
        monkeypatch.setattr(TASK, "require_trusted_main_controller", lambda *_args, **_kwargs: prepared["authorization"]["base_sha"])
        monkeypatch.setattr(TASK, "authorize_task", lambda _state, *, transport, value=authorized: value)
        monkeypatch.setattr(TASK, "state_path", lambda *_args: state_dir / "state.json")
        monkeypatch.setattr(TASK, "atomic_write_json", lambda *_args: None)
        monkeypatch.setattr(TASK, "emit", outputs.append)

        TASK.command_authorize(
            SimpleNamespace(repo_root=repo, state_dir=state_dir, issue_number=999)
        )
        assert outputs[-1]["workflow_mode"] == mode
        assert outputs[-1]["next"] == expected_authorize

        candidate_sha = "a" * 40
        qualified = dict(authorized)
        qualified.update(
            phase="QUALIFIED",
            qualification={
                "candidate_sha": candidate_sha,
                "workflow_run_id": 8800,
                "check_id": 9900,
                "check_app_id": 424242,
                "result": "PASS",
                "candidate_ref_removed": True,
            },
        )
        monkeypatch.setattr(TASK, "load_state", lambda *_args, value=authorized: value)
        monkeypatch.setattr(TASK, "require_candidate_repository", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(TASK, "configured_qualification_app_id", lambda: 424242)
        monkeypatch.setattr(TASK, "qualify_task", lambda *_args, value=qualified, **_kwargs: value)
        monkeypatch.setattr(TASK, "GitCandidateRefTransport", lambda _repo: object())

        TASK.command_qualify(
            SimpleNamespace(
                repo_root=repo,
                state_dir=state_dir,
                issue_number=999,
                candidate_root=repo,
            )
        )
        assert outputs[-1]["workflow_mode"] == mode
        assert outputs[-1]["next"] == expected_qualify
        monkeypatch.undo()


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


def test_qualification_terminal_rejects_real_writer_stop_during_long_run(
    tmp_path: Path,
) -> None:
    repo, base, candidate, state, comment = authorized_repo_state(
        tmp_path,
        workflow_mode="standard",
        compatibility_reason=None,
    )
    state_dir = tmp_path / "state"
    state["attempt_history"] = ["prior-attempt"]
    state["unrelated"] = {"preserve": "during-long-run"}
    TASK.state_path(state_dir, 999).write_text(json.dumps(state) + "\n")
    entered_dispatch = threading.Event()
    release_dispatch = threading.Event()

    class BlockingQualificationTransport(FakeQualificationTransport):
        def dispatch_workflow(self, repository, workflow, ref, inputs):
            entered_dispatch.set()
            assert release_dispatch.wait(5)
            return super().dispatch_workflow(repository, workflow, ref, inputs)

    transport = BlockingQualificationTransport(
        comment=comment,
        controller_sha=base,
        candidate_sha=candidate,
        identity_sha256=state["authorization"]["identity_sha256"],
    )
    refs = FakeCandidateRefTransport()
    errors: list[BaseException] = []

    def run_qualification() -> None:
        def operation_writer(operation):
            TASK.begin_qualification_operation(state_dir, 999, operation)

        def ref_writer(operation):
            TASK.mark_qualification_ref_published(state_dir, 999, operation)

        def terminal_writer(result, operation):
            return TASK.apply_qualification_terminal_result(
                state_dir, 999, operation, result, transport,
                candidate_repo=repo)

        def cleanup_writer(operation, removed, error):
            try:
                TASK.record_qualification_cleanup(
                    state_dir, 999, operation, removed=removed, error=error)
            except TASK.TaskControllerError:
                pass

        try:
            TASK.qualify_task(
                state,
                candidate_repo=repo,
                controller_main_sha=base,
                expected_app_id=424242,
                transport=transport,
                ref_transport=refs,
                poll_attempts=2,
                sleep_seconds=0,
                sleep_fn=lambda _: None,
                dispatch_nonce="dispatch-1234567890",
                operation_writer=operation_writer,
                ref_published_writer=ref_writer,
                terminal_writer=terminal_writer,
                cleanup_writer=cleanup_writer,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    worker = threading.Thread(target=run_qualification)
    worker.start()
    assert entered_dispatch.wait(5)
    TASK.checkpoint_transaction(
        state_dir,
        999,
        lambda current: {
            **current,
            "phase": "STOP_REPLAN",
            "stop_reason": "intervening terminal stop",
        },
    )
    release_dispatch.set()
    worker.join(5)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], TASK.TaskControllerError)
    assert str(errors[0]) == "STOP_REPLAN_PRESERVE_ATTEMPT"
    persisted = TASK.load_state(state_dir, 999)
    assert persisted["phase"] == "STOP_REPLAN"
    assert persisted["stop_reason"] == "intervening terminal stop"
    assert persisted["attempt_history"] == ["prior-attempt"]
    assert persisted["unrelated"] == {"preserve": "during-long-run"}
    assert persisted["qualification"] is None
    assert persisted["qualification_operation"]["status"] == "RUNNING"
    assert len(refs.deleted) == 1


def test_qualification_terminal_rejects_changed_live_authority(
    tmp_path: Path,
) -> None:
    repo, base, candidate, state, comment = authorized_repo_state(
        tmp_path,
        workflow_mode="standard",
        compatibility_reason=None,
    )
    state_dir = tmp_path / "state"
    state["attempt_history"] = ["prior-attempt"]
    state["unrelated"] = {"preserve": "during-long-run"}
    TASK.state_path(state_dir, 999).write_text(json.dumps(state) + "\n")
    transport = FakeQualificationTransport(
        comment=comment,
        controller_sha=base,
        candidate_sha=candidate,
        identity_sha256=state["authorization"]["identity_sha256"],
    )
    resolved = TASK.resolve_current_authorization(state, transport)
    operation = {
        "operation_id": "dispatch-1234567890",
        "candidate_sha": candidate,
        "candidate_ref": f"task-candidate/999/dispatch-1234567890/{candidate[:12]}",
        "dispatch_nonce": "dispatch-1234567890",
        "controller_main_sha": base,
        "workflow": "trusted-qualification.yml",
        "authorization": TASK._checkpoint_authorization_identity(state),
        "resolved_authorization": resolved.to_dict(),
    }
    TASK.begin_qualification_operation(state_dir, 999, operation)
    TASK.checkpoint_transaction(
        state_dir,
        999,
        lambda current: {
            **current,
            "authorization": {
                **current["authorization"],
                "identity_sha256": "f" * 64,
            },
        },
    )

    with pytest.raises(
        TASK.TaskControllerError,
        match="WORKFLOW_AUTHORITY_MISMATCH|AUTHORIZATION_CURRENT_IDENTITY_MISMATCH",
    ):
        TASK.apply_qualification_terminal_result(
            state_dir,
            999,
            operation,
            {
                "phase": "QUALIFIED",
                "qualification": {"candidate_sha": candidate},
            },
            transport,
        )

    persisted = TASK.load_state(state_dir, 999)
    assert persisted["phase"] == "AUTHORIZED"
    assert persisted["qualification"] is None
    assert persisted["authorization"]["identity_sha256"] == "f" * 64


@pytest.mark.parametrize("stale_kind", ["operation", "candidate"])
def test_qualification_terminal_rejects_stale_operation_or_candidate(
    tmp_path: Path,
    stale_kind: str,
) -> None:
    repo, base, candidate, state, comment = authorized_repo_state(
        tmp_path,
        workflow_mode="standard",
        compatibility_reason=None,
    )
    state_dir = tmp_path / "state"
    TASK.state_path(state_dir, 999).write_text(json.dumps(state) + "\n")
    transport = FakeQualificationTransport(
        comment=comment,
        controller_sha=base,
        candidate_sha=candidate,
        identity_sha256=state["authorization"]["identity_sha256"],
    )
    operation = {
        "operation_id": "dispatch-1234567890",
        "candidate_sha": candidate,
        "candidate_ref": f"task-candidate/999/dispatch-1234567890/{candidate[:12]}",
        "dispatch_nonce": "dispatch-1234567890",
        "controller_main_sha": base,
        "workflow": "trusted-qualification.yml",
        "expected_app_id": 424242,
        "authorization": TASK._checkpoint_authorization_identity(state),
        "resolved_authorization": TASK.resolve_current_authorization(state, transport).to_dict(),
    }
    TASK.begin_qualification_operation(state_dir, 999, operation)
    if stale_kind == "operation":
        TASK.checkpoint_transaction(
            state_dir,
            999,
            lambda current: {
                **current,
                "qualification_operation": {
                    **current["qualification_operation"],
                    "operation_id": "different-dispatch",
                },
            },
        )
        expected_error = "QUALIFICATION_OPERATION_STALE"
    else:
        commit_paths(repo, {"src/changed.py": "CHANGED = True\n"}, message="candidate drift")
        expected_error = "QUALIFICATION_CANDIDATE_CHANGED"

    with pytest.raises(TASK.TaskControllerError, match=expected_error):
        TASK.apply_qualification_terminal_result(
            state_dir,
            999,
            operation,
            {
                "phase": "QUALIFIED",
                "qualification": {
                    "candidate_sha": candidate,
                    "result": "PASS",
                },
            },
            transport,
            candidate_repo=repo,
        )

    persisted = TASK.load_state(state_dir, 999)
    assert persisted["phase"] == "AUTHORIZED"
    assert persisted["qualification"] is None


def test_qualification_cleanup_unknown_is_reconciled_without_redispatch(
    tmp_path: Path,
) -> None:
    repo, base, candidate, state, comment = authorized_repo_state(
        tmp_path,
        workflow_mode="standard",
        compatibility_reason=None,
    )
    state_dir = tmp_path / "state"
    TASK.state_path(state_dir, 999).write_text(json.dumps(state) + "\n")
    transport = FakeQualificationTransport(
        comment=comment,
        controller_sha=base,
        candidate_sha=candidate,
        identity_sha256=state["authorization"]["identity_sha256"],
    )
    operation = {
        "operation_id": "dispatch-1234567890",
        "candidate_sha": candidate,
        "candidate_ref": f"task-candidate/999/dispatch-1234567890/{candidate[:12]}",
        "dispatch_nonce": "dispatch-1234567890",
        "controller_main_sha": base,
        "workflow": "trusted-qualification.yml",
        "expected_app_id": 424242,
        "authorization": TASK._checkpoint_authorization_identity(state),
        "resolved_authorization": TASK.resolve_current_authorization(state, transport).to_dict(),
    }
    TASK.begin_qualification_operation(state_dir, 999, operation)
    TASK.checkpoint_transaction(
        state_dir,
        999,
        lambda current: {
            **current,
            "phase": "QUALIFIED",
            "qualification": {
                "candidate_sha": candidate,
                "candidate_ref": operation["candidate_ref"],
                "candidate_ref_removed": False,
                "result": "PASS",
            },
            "qualification_operation": {
                **current["qualification_operation"],
                "status": "TERMINAL",
            },
        },
    )
    refs = FakeCandidateRefTransport(fail_delete_count=1)

    with pytest.raises(TASK.TaskControllerError, match="CANDIDATE_REF_CLEANUP_FAILED"):
        TASK.reconcile_qualification_operation(
            state_dir,
            999,
            transport=transport,
            ref_transport=refs,
            expected_app_id=424242,
            candidate_repo=repo,
        )
    uncertain = TASK.load_state(state_dir, 999)
    assert uncertain["qualification_operation"]["status"] == "CLEANUP_UNKNOWN"
    assert uncertain["qualification"]["candidate_ref_removed"] is False

    reconciled = TASK.reconcile_qualification_operation(
        state_dir,
        999,
        transport=transport,
        ref_transport=refs,
        expected_app_id=424242,
        candidate_repo=repo,
    )
    assert reconciled["qualification_operation"]["status"] == "COMPLETE"
    assert reconciled["qualification"]["candidate_ref_removed"] is True
    assert transport.dispatch_calls == 0
    assert len(refs.deleted) == 1


def test_unknown_qualification_reconciles_completed_run_without_redispatch(
    tmp_path: Path,
) -> None:
    repo, base, candidate, state, comment = authorized_repo_state(
        tmp_path,
        workflow_mode="standard",
        compatibility_reason=None,
    )
    state_dir = tmp_path / "state"
    TASK.state_path(state_dir, 999).write_text(json.dumps(state) + "\n")
    transport = FakeQualificationTransport(
        comment=comment,
        controller_sha=base,
        candidate_sha=candidate,
        identity_sha256=state["authorization"]["identity_sha256"],
    )
    operation = {
        "operation_id": "dispatch-1234567890",
        "candidate_sha": candidate,
        "candidate_ref": f"task-candidate/999/dispatch-1234567890/{candidate[:12]}",
        "dispatch_nonce": "dispatch-1234567890",
        "controller_main_sha": base,
        "workflow": "trusted-qualification.yml",
        "expected_app_id": 424242,
        "authorization": TASK._checkpoint_authorization_identity(state),
        "resolved_authorization": TASK.resolve_current_authorization(state, transport).to_dict(),
    }
    TASK.begin_qualification_operation(state_dir, 999, operation)
    TASK.checkpoint_transaction(
        state_dir,
        999,
        lambda current: {
            **current,
            "qualification_operation": {
                **current["qualification_operation"],
                "status": "UNKNOWN",
            },
        },
    )
    transport.dispatch_inputs = {
        "task_id": state["task_id"],
        "dispatch_nonce": operation["dispatch_nonce"],
        "candidate_sha": candidate,
    }
    refs = FakeCandidateRefTransport()

    reconciled = TASK.reconcile_qualification_operation(
        state_dir,
        999,
        transport=transport,
        ref_transport=refs,
        expected_app_id=424242,
        candidate_repo=repo,
    )

    assert reconciled["phase"] == "QUALIFIED"
    assert reconciled["qualification"]["result"] == "PASS"
    assert reconciled["qualification_operation"]["status"] == "COMPLETE"
    assert reconciled["qualification"]["candidate_ref_removed"] is True
    assert transport.dispatch_calls == 0
    assert len(refs.deleted) == 1


@pytest.mark.parametrize(
    ("run_conclusion", "check_conclusion", "expected_phase", "expected_result"),
    [("success", "success", "QUALIFIED", "PASS"),
     ("failure", "failure", "QUALIFICATION_FAILED", "FAIL")],
)
def test_qualification_operation_persists_terminal_result_and_ref_cleanup(
    tmp_path: Path,
    run_conclusion: str,
    check_conclusion: str,
    expected_phase: str,
    expected_result: str,
) -> None:
    repo, base, candidate, state, comment = authorized_repo_state(
        tmp_path,
        workflow_mode="standard",
        compatibility_reason=None,
    )
    state_dir = tmp_path / "state"
    state["attempt_history"] = ["prior-attempt"]
    state["unrelated"] = {"preserve": "during-long-run"}
    TASK.state_path(state_dir, 999).write_text(json.dumps(state) + "\n")
    transport = FakeQualificationTransport(
        comment=comment,
        controller_sha=base,
        candidate_sha=candidate,
        identity_sha256=state["authorization"]["identity_sha256"],
        run_conclusion=run_conclusion,
        check_conclusion=check_conclusion,
    )
    refs = FakeCandidateRefTransport()

    def operation_writer(operation):
        TASK.begin_qualification_operation(state_dir, 999, operation)

    def ref_writer(operation):
        TASK.mark_qualification_ref_published(state_dir, 999, operation)

    def terminal_writer(result, operation):
        return TASK.apply_qualification_terminal_result(
            state_dir, 999, operation, result, transport, candidate_repo=repo)

    def cleanup_writer(operation, removed, error):
        TASK.record_qualification_cleanup(
            state_dir, 999, operation, removed=removed, error=error)

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
        dispatch_nonce="dispatch-1234567890",
        operation_writer=operation_writer,
        ref_published_writer=ref_writer,
        terminal_writer=terminal_writer,
        cleanup_writer=cleanup_writer,
    )

    persisted = TASK.load_state(state_dir, 999)
    assert updated["phase"] == expected_phase
    assert persisted["phase"] == expected_phase
    assert persisted["qualification"]["result"] == expected_result
    assert persisted["attempt_history"] == ["prior-attempt"]
    assert persisted["unrelated"] == {"preserve": "during-long-run"}
    assert persisted["qualification"]["candidate_ref_removed"] is True
    assert persisted["qualification_operation"]["status"] == "COMPLETE"
    assert persisted["qualification_operation"]["terminal_result"] == expected_result
    assert len(refs.published) == len(refs.deleted) == 1


def test_public_qualification_rejects_restored_forbidden_commit(
    tmp_path: Path,
) -> None:
    repo, base, _, state, comment = authorized_repo_state(
        tmp_path,
        forbidden_paths=["src/forbidden/**"],
    )

    forbidden = repo / "src/forbidden/item.py"
    forbidden.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    forbidden.write_text(
        "TEMPORARY = True\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "introduce forbidden path")

    forbidden.unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "restore forbidden path")

    allowed = repo / "src/final.py"
    allowed.write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "add allowed final change")
    candidate = git(repo, "rev-parse", "HEAD")

    transport = FakeQualificationTransport(
        comment=comment,
        controller_sha=base,
        candidate_sha=candidate,
        identity_sha256=state["authorization"][
            "identity_sha256"
        ],
    )
    refs = FakeCandidateRefTransport()

    with pytest.raises(
        AuthorizationError,
        match="SCOPE_FORBIDDEN",
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

    assert transport.dispatch_inputs is None
    assert refs.published == []


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


def governing_issue_fixture(**changes) -> dict:
    issue = {
        "number": 999,
        "title": "Bounded controller task",
        "body": "Keep the implementation within its authorized scope.",
        "state": "open",
        "updated_at": "2026-09-29T12:00:00Z",
        "html_url": "https://github.com/owner/repo/issues/999",
    }
    issue.update(changes)
    return issue


class FakeGoverningIssueTransport:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[tuple[str, int]] = []

    def get_issue(self, repository: str, issue_number: int) -> dict:
        self.calls.append((repository, issue_number))
        if isinstance(self.response, BaseException):
            raise self.response
        return dict(self.response)


def attach_synthetic_issue_binding(
    reviewed: dict,
    repo: Path,
    candidate: str,
    issue: dict,
    qualification_transport,
) -> None:
    authorization = TASK.resolve_current_authorization(
        reviewed, qualification_transport
    )
    binding = {
        "authorization": authorization.to_dict(),
        "candidate": candidate,
        "issue_fingerprint": LEGACY_EVIDENCE.governing_issue_fingerprint(
            issue, authorization.issue_number
        ),
        "source": LEGACY_EVIDENCE.observe(repo, candidate),
    }
    binding["binding_sha256"] = LEGACY_EVIDENCE.digest(binding)
    reviewed["capsule_evidence"] = {"binding": binding, "commands": {}}


def test_governing_issue_fingerprint_uses_only_material_fields() -> None:
    original = governing_issue_fixture()
    binding = {
        "authorization": {"issue_number": 999},
        "issue_fingerprint": LEGACY_EVIDENCE.governing_issue_fingerprint(
            original, 999
        ),
    }
    noisy = {
        **original,
        "updated_at": "2026-09-30T12:00:00Z",
        "html_url": "https://github.com/owner/repo/issues/999?view=timeline",
        "labels": [{"name": "triage"}],
        "comments": 37,
    }

    LEGACY_EVIDENCE.revalidate_governing_issue(binding, noisy)

    for changed in (
        {**original, "title": "Expanded controller task"},
        {**original, "body": original["body"] + " Include another subsystem."},
        {**original, "state": "closed"},
    ):
        with pytest.raises(
            TASK.EvidenceError,
            match="GOVERNING_ISSUE_REPLAN_REQUIRED",
        ):
            LEGACY_EVIDENCE.revalidate_governing_issue(binding, changed)

    with pytest.raises(
        TASK.EvidenceError,
        match="GOVERNING_ISSUE_REVALIDATION_INVALID",
    ):
        LEGACY_EVIDENCE.revalidate_governing_issue(
            binding, {"number": 999, "title": "missing body and state"}
        )


def test_capsule_attachment_persists_canonical_open_issue_fingerprint(
    tmp_path: Path, monkeypatch
) -> None:
    repo, base = init_repo(tmp_path)
    authorization = resolve(authorization_payload(base))
    planning = "e" * 40
    candidate = "f" * 40
    capsule_path = "engineering/capsules/active/GH-999-P1.md"
    metadata = {
        "id": "GH-999-P1",
        "capsule_revision": 1,
        "base_commit": base,
        "state": "READY",
        "blocked": False,
        "source_issue": "https://github.com/owner/repo/issues/999",
        "specialized_qualification": ["profile:backend", "profile:repository"],
        "owned_paths": ["src/**"],
        "allowed_paths": [],
        "forbidden_paths": [],
        "branch": "task/GH-999-P1-r1",
    }
    monkeypatch.setattr(
        LEGACY_EVIDENCE,
        "git_text",
        lambda _repo, *args: (
            f"{planning} {base}" if args[0] == "rev-list" else capsule_path
        ),
    )
    monkeypatch.setattr(LEGACY_EVIDENCE, "git", lambda *_args: b"")
    monkeypatch.setattr(
        LEGACY_EVIDENCE,
        "read_blob",
        lambda _repo, commit, _path: b"planning" if commit == planning else b"candidate",
    )
    monkeypatch.setattr(
        LEGACY_EVIDENCE,
        "capsule_metadata",
        lambda raw: {**metadata, "state": "READY" if raw == b"planning" else "IMPLEMENTED"},
    )
    monkeypatch.setattr(
        LEGACY_EVIDENCE,
        "frozen_contract",
        lambda _raw: {"sections": {"Acceptance criteria": "- [ ] AC-1: Preserve scope."}},
    )
    monkeypatch.setattr(LEGACY_EVIDENCE, "requirements", lambda _raw: [])
    monkeypatch.setattr(LEGACY_EVIDENCE, "validate_candidate_scope", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        LEGACY_EVIDENCE,
        "observe",
        lambda *_args: {"branch": metadata["branch"], "candidate": candidate},
    )
    monkeypatch.setattr(
        LEGACY_EVIDENCE,
        "review_obligations",
        lambda *_args: {"outcomes": [], "standards": []},
    )
    monkeypatch.setattr(LEGACY_EVIDENCE.ri_delta, "configuration", lambda _text: None)

    issue = governing_issue_fixture()
    binding = LEGACY_EVIDENCE.attach(
        repo,
        authorization,
        planning=planning,
        candidate=candidate,
        issue=issue,
    )

    assert binding["issue_fingerprint"] == LEGACY_EVIDENCE.governing_issue_fingerprint(
        issue, authorization.issue_number
    )
    assert binding["issue"] == issue

    with pytest.raises(
        TASK.EvidenceError,
        match="GOVERNING_ISSUE_REPLAN_REQUIRED",
    ):
        LEGACY_EVIDENCE.attach(
            repo,
            authorization,
            planning=planning,
            candidate=candidate,
            issue={**issue, "state": "closed"},
        )







@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Changed governing title"),
        ("body", "Expanded governing scope."),
        ("state", "closed"),
    ],
)
def test_integrate_rejects_live_issue_drift(
    tmp_path: Path, monkeypatch, field: str, value: str
) -> None:
    repo, base, candidate, reviewed, qualification, refs = reviewed_qualified_fixture(
        tmp_path
    )
    attached_issue = governing_issue_fixture()
    issue = {**attached_issue, field: value}
    issue_transport = FakeGoverningIssueTransport(issue)
    attach_synthetic_issue_binding(
        reviewed, repo, candidate, attached_issue, qualification
    )
    monkeypatch.setattr(LEGACY_EVIDENCE, "gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(TASK, "GhIssueAuthorizationTransport", lambda: issue_transport)

    with pytest.raises(
        TASK.EvidenceError,
        match="GOVERNING_ISSUE_REPLAN_REQUIRED",
    ):
        TASK.integrate_task(
            reviewed,
            candidate_repo=repo,
            controller_main_sha=base,
            expected_app_id=424242,
            transport=qualification,
            ref_transport=refs,
            human_owner_authorized=True,
        )

    assert issue_transport.calls == [("owner/repo", 999)]
    assert refs.main_pushes == []


def test_integrate_ignores_issue_metadata_and_rechecks_on_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    repo, base, candidate, reviewed, qualification, refs = reviewed_qualified_fixture(
        tmp_path
    )
    attached_issue = governing_issue_fixture()
    live_issue = {
        **attached_issue,
        "updated_at": "2026-10-01T12:00:00Z",
        "labels": [{"name": "changed"}],
        "comments": 42,
    }
    issue_transport = FakeGoverningIssueTransport(live_issue)
    attach_synthetic_issue_binding(
        reviewed, repo, candidate, attached_issue, qualification
    )
    monkeypatch.setattr(LEGACY_EVIDENCE, "gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(TASK, "GhIssueAuthorizationTransport", lambda: issue_transport)

    pending = TASK.integrate_task(
        reviewed,
        candidate_repo=repo,
        controller_main_sha=base,
        expected_app_id=424242,
        transport=qualification,
        ref_transport=refs,
        human_owner_authorized=True,
    )
    assert pending["phase"] == "INTEGRATION_PENDING"
    assert issue_transport.calls == [("owner/repo", 999)]

    issue_transport.response = {**live_issue, "body": live_issue["body"] + " Expanded."}
    with pytest.raises(
        TASK.EvidenceError,
        match="GOVERNING_ISSUE_REPLAN_REQUIRED",
    ):
        TASK.revalidate_integration_state(
            pending,
            candidate_repo=repo,
            expected_app_id=424242,
            transport=qualification,
            ref_transport=refs,
        )

    assert issue_transport.calls == [("owner/repo", 999), ("owner/repo", 999)]
    assert refs.main_pushes == []


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (TASK.TaskControllerError("GITHUB_API_ERROR: offline"), "GOVERNING_ISSUE_REVALIDATION_UNAVAILABLE"),
        ({"number": 999, "title": "missing material fields"}, "GOVERNING_ISSUE_REVALIDATION_INVALID"),
    ],
)
def test_integrate_fails_closed_when_issue_get_is_unavailable_or_malformed(
    tmp_path: Path, monkeypatch, response, error
) -> None:
    repo, base, candidate, reviewed, qualification, refs = reviewed_qualified_fixture(
        tmp_path
    )
    attached_issue = governing_issue_fixture()
    issue_transport = FakeGoverningIssueTransport(response)
    attach_synthetic_issue_binding(
        reviewed, repo, candidate, attached_issue, qualification
    )
    monkeypatch.setattr(LEGACY_EVIDENCE, "gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(TASK, "GhIssueAuthorizationTransport", lambda: issue_transport)

    with pytest.raises(TASK.EvidenceError, match=error):
        TASK.integrate_task(
            reviewed,
            candidate_repo=repo,
            controller_main_sha=base,
            expected_app_id=424242,
            transport=qualification,
            ref_transport=refs,
            human_owner_authorized=True,
        )

    assert issue_transport.calls == [("owner/repo", 999)]
    assert refs.main_pushes == []


def test_compatibility_lane_keeps_its_separate_terminal_authority(
    tmp_path: Path, monkeypatch
) -> None:
    repo, base, _, reviewed, qualification, refs = reviewed_qualified_fixture(tmp_path)

    class UnexpectedIssueTransport:
        def get_issue(self, *_args, **_kwargs):
            raise AssertionError("compatibility integration must retain its established authority lane")

    monkeypatch.setattr(
        TASK,
        "GhIssueAuthorizationTransport",
        UnexpectedIssueTransport,
    )
    pending = TASK.integrate_task(
        reviewed,
        candidate_repo=repo,
        controller_main_sha=base,
        expected_app_id=424242,
        transport=qualification,
        ref_transport=refs,
        human_owner_authorized=True,
    )

    assert pending["phase"] == "INTEGRATION_PENDING"


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


@pytest.mark.parametrize("changed_field", ["authority", "review", "verification"])
def test_pending_integration_revalidates_same_phase_current_gates(
    tmp_path: Path,
    changed_field: str,
) -> None:
    repo, base, candidate, reviewed, transport, refs = reviewed_qualified_fixture(
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
    state_dir = tmp_path / "controller-state"
    state_dir.mkdir()
    TASK.state_path(state_dir, 999).write_text(json.dumps(reviewed) + "\n")

    def change(current):
        updated = json.loads(json.dumps(current))
        if changed_field == "authority":
            updated["authorization"]["identity_sha256"] = "f" * 64
        elif changed_field == "review":
            updated["review"]["summary"] = "changed after approval"
        else:
            updated["verification"]["evidence"] = "changed after verification"
        return updated

    TASK.checkpoint_transaction(state_dir, 999, change)
    expected_error = (
        "AUTHORIZATION_CURRENT_IDENTITY_MISMATCH|WORKFLOW_AUTHORITY_CURRENT_IDENTITY_MISMATCH|WORKFLOW_AUTHORITY_MISMATCH"
        if changed_field == "authority"
        else "INTEGRATION_STATE_STALE"
    )
    with pytest.raises(TASK.TaskControllerError, match=expected_error):
        TASK.persist_integration_pending(
            state_dir,
            999,
            pending,
            candidate_repo=repo,
            controller_main_sha=base,
            expected_app_id=424242,
            transport=transport,
            ref_transport=refs,
            human_owner_authorized=True,
        )
    persisted = TASK.load_state(state_dir, 999)
    assert persisted["phase"] == "REVIEWED_APPROVED"
    assert persisted.get("integration") is None
    assert refs.main_pushes == []


def test_integration_completion_revalidates_current_review_before_remote_push(
    tmp_path: Path,
) -> None:
    repo, base, candidate, reviewed, transport, refs = reviewed_qualified_fixture(
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
    pending["review"]["summary"] = "changed after pending intent"
    refs.main_sha = base

    with pytest.raises(
        TASK.TaskControllerError,
        match="INTEGRATION_RECOVERY_REVALIDATION_CHANGED",
    ):
        TASK.reconcile_integration_completion(
            pending,
            candidate_repo=repo,
            candidate_sha=candidate,
            expected_app_id=424242,
            transport=transport,
            ref_transport=refs,
        )
    assert refs.main_pushes == []


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


def test_recovery_revalidates_live_check_review_and_owner(
    tmp_path: Path,
) -> None:
    repo, base, candidate, reviewed, transport, refs = reviewed_qualified_fixture(tmp_path)
    pending = TASK.integrate_task(
        reviewed, candidate_repo=repo, controller_main_sha=base,
        expected_app_id=424242, transport=transport, ref_transport=refs,
        human_owner_authorized=True)
    TASK.revalidate_integration_state(
        pending, candidate_repo=repo, expected_app_id=424242,
        transport=transport, ref_transport=refs)
    refs.main_sha = candidate
    integrated = TASK.reconcile_integration(pending, candidate_sha=candidate, ref_transport=refs)
    TASK.revalidate_integration_state(
        integrated, candidate_repo=repo, expected_app_id=424242,
        transport=transport, ref_transport=refs)
    transport.app_id = 15368
    with pytest.raises(TASK.TaskControllerError, match="CHECK_REVALIDATION_FAILED"):
        TASK.revalidate_integration_state(
            integrated, candidate_repo=repo, expected_app_id=424242,
            transport=transport, ref_transport=refs)
    transport.app_id = 424242
    stale_review = {**integrated, "review": {**integrated["review"], "decision": "changes-requested"}}
    with pytest.raises(TASK.TaskControllerError, match="REVIEW_MISMATCH"):
        TASK.revalidate_integration_state(
            stale_review, candidate_repo=repo, expected_app_id=424242,
            transport=transport, ref_transport=refs)
    no_owner = {**integrated, "integration": {**integrated["integration"], "human_owner_authorized": False}}
    with pytest.raises(TASK.TaskControllerError, match="REVALIDATION_CHANGED"):
        TASK.revalidate_integration_state(
            no_owner, candidate_repo=repo, expected_app_id=424242,
            transport=transport, ref_transport=refs)
    failed_terminal = {**integrated, "qualification": {**integrated["qualification"], "result": "FAIL"}}
    with pytest.raises(TASK.TaskControllerError, match="QUALIFICATION_MISMATCH"):
        TASK.revalidate_integration_state(
            failed_terminal, candidate_repo=repo, expected_app_id=424242,
            transport=transport, ref_transport=refs)
    transport.comments[0]["body"] = "authorization withdrawn"
    with pytest.raises(AuthorizationError):
        TASK.revalidate_integration_state(
            integrated, candidate_repo=repo, expected_app_id=424242,
            transport=transport, ref_transport=refs)


def test_recovery_accepts_legacy_pending_without_state_binding(
    tmp_path: Path,
) -> None:
    repo, base, _candidate, reviewed, transport, refs = reviewed_qualified_fixture(tmp_path)
    pending = TASK.integrate_task(
        reviewed, candidate_repo=repo, controller_main_sha=base,
        expected_app_id=424242, transport=transport, ref_transport=refs,
        human_owner_authorized=True)
    pending["integration"].pop("state_binding_sha256")

    TASK.revalidate_integration_state(
        pending, candidate_repo=repo, expected_app_id=424242,
        transport=transport, ref_transport=refs)

    assert "state_binding_sha256" not in pending["integration"]


def test_recovery_accepts_legacy_integrated_without_state_binding(
    tmp_path: Path,
) -> None:
    repo, base, candidate, reviewed, transport, refs = reviewed_qualified_fixture(tmp_path)
    pending = TASK.integrate_task(
        reviewed, candidate_repo=repo, controller_main_sha=base,
        expected_app_id=424242, transport=transport, ref_transport=refs,
        human_owner_authorized=True)
    refs.main_sha = base
    integrated = TASK.reconcile_integration(
        pending, candidate_sha=candidate, ref_transport=refs)
    integrated["integration"].pop("state_binding_sha256")

    TASK.revalidate_integration_state(
        integrated, candidate_repo=repo, expected_app_id=424242,
        transport=transport, ref_transport=refs)

    assert "state_binding_sha256" not in integrated["integration"]


@pytest.mark.parametrize("integrated", [False, True])
@pytest.mark.parametrize("binding", ["0" * 64, "not-a-sha256"])
def test_recovery_rejects_tampered_or_malformed_state_binding(
    tmp_path: Path, integrated: bool, binding: str,
) -> None:
    repo, base, candidate, reviewed, transport, refs = reviewed_qualified_fixture(tmp_path)
    pending = TASK.integrate_task(
        reviewed, candidate_repo=repo, controller_main_sha=base,
        expected_app_id=424242, transport=transport, ref_transport=refs,
        human_owner_authorized=True)
    state = pending
    if integrated:
        refs.main_sha = base
        state = TASK.reconcile_integration(
            pending, candidate_sha=candidate, ref_transport=refs)
    state["integration"]["state_binding_sha256"] = binding

    expected_error = (
        "INTEGRATION_RECOVERY_BINDING_INVALID"
        if binding == "not-a-sha256"
        else "INTEGRATION_RECOVERY_REVALIDATION_CHANGED"
    )
    with pytest.raises(TASK.TaskControllerError, match=expected_error):
        TASK.revalidate_integration_state(
            state, candidate_repo=repo, expected_app_id=424242,
            transport=transport, ref_transport=refs)


def test_attached_revalidation_allows_only_receipted_main_fetch(tmp_path: Path, monkeypatch) -> None:
    repo, base, candidate, reviewed, transport, refs = reviewed_qualified_fixture(tmp_path)
    original = {"candidate": candidate, "branch": "task/fixture", "source_sha256": "source",
                "index_sha256": "index", "refs_sha256": "before",
                "refs": {"refs/remotes/origin/main": base, "refs/heads/main": base}}
    issue = governing_issue_fixture()
    issue_transport = FakeGoverningIssueTransport(issue)
    reviewed["capsule_evidence"] = {"binding": {
        "source": original,
        "authorization": {"repository": "owner/repo", "issue_number": 999},
        "issue_fingerprint": LEGACY_EVIDENCE.governing_issue_fingerprint(issue, 999),
    }}
    monkeypatch.setattr(LEGACY_EVIDENCE, "authenticate_binding", lambda *_args: None)
    monkeypatch.setattr(LEGACY_EVIDENCE, "gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(LEGACY_EVIDENCE, "revalidate_manual", lambda *_args: None)
    monkeypatch.setattr(LEGACY_EVIDENCE, "qualify", lambda *_args: None)
    monkeypatch.setattr(TASK, "GhIssueAuthorizationTransport", lambda: issue_transport)
    observed = dict(original)
    monkeypatch.setattr(LEGACY_EVIDENCE, "observe", lambda *_args: observed)
    pending = TASK.integrate_task(
        reviewed, candidate_repo=repo, controller_main_sha=base, expected_app_id=424242,
        transport=transport, ref_transport=refs, human_owner_authorized=True)
    observed = {**original, "refs_sha256": "after",
                "refs": {"refs/remotes/origin/main": candidate, "refs/heads/main": candidate}}
    TASK.revalidate_integration_state(
        pending, candidate_repo=repo, expected_app_id=424242,
        transport=transport, ref_transport=refs)
    refs.main_sha = candidate
    integrated = TASK.reconcile_integration(pending, candidate_sha=candidate, ref_transport=refs)
    TASK.revalidate_integration_state(
        integrated, candidate_repo=repo, expected_app_id=424242,
        transport=transport, ref_transport=refs)
    observed = {**observed, "refs": {**observed["refs"], "refs/heads/unrelated": candidate}}
    with pytest.raises(TASK.EvidenceError, match="ATTACHED_SOURCE_CHANGED"):
        TASK.revalidate_integration_state(
            integrated, candidate_repo=repo, expected_app_id=424242,
            transport=transport, ref_transport=refs)


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


def test_attached_lane_cannot_use_assertion_only_review():
    from lib.legacy_ri.candidate_evidence import EvidenceError
    state = {"capsule_evidence": {}, "verification": {"decision": "pass", "candidate_sha": "a" * 40}}
    with pytest.raises(EvidenceError, match="FRESH_CANDIDATE_ATTACHMENT_REQUIRED"):
        TASK.record_review(state, candidate_sha="a" * 40, actor="author", decision="approved", summary="looks good")


def test_attached_lane_cannot_verify_missing_or_corrected_evidence():
    from lib.legacy_ri.candidate_evidence import EvidenceError
    for attached in ({}, {"requires_fresh_candidate": True}):
        state = {"capsule_evidence": attached, "qualification": {"result": "PASS", "candidate_sha": "a" * 40}}
        with pytest.raises(EvidenceError, match="FRESH_CANDIDATE"):
            TASK.record_verification(state, candidate_sha="a" * 40, actor="author", decision="pass", evidence="tests passed")


def test_pre_change_sealed_candidate_evidence_remains_usable():
    candidate = "a" * 40
    binding_sha256 = "b" * 64
    state = {
        "authorization": {"nonce": "legacy-nonce-123456"},
        "qualification": {"result": "PASS", "candidate_sha": candidate},
        "capsule_evidence": {
            "binding": {
                "candidate": candidate,
                "binding_sha256": binding_sha256,
                "requirements": [],
                "review_obligations": {"outcomes": []},
            },
            "commands": {},
            "qualified": {"binding_sha256": binding_sha256},
        },
    }
    original = json.loads(json.dumps(state))

    verified = TASK.record_verification(
        state,
        candidate_sha=candidate,
        actor="verifier",
        decision="pass",
        evidence="sealed legacy qualification and command packet",
    )

    assert verified["phase"] == "VERIFIED"
    assert verified["capsule_evidence"] == original["capsule_evidence"]
    assert "workflow" not in verified
    assert state == original


def test_standard_route_completes_qualification_verification_and_source_review(tmp_path):
    repo, base, candidate, qualified, transport, refs = qualify_fixture(
        tmp_path, workflow_mode="standard", compatibility_reason=None)
    assert qualified["workflow"]["mode"] == "standard"
    assert qualified["phase"] == "QUALIFIED"
    assert transport.dispatch_inputs is not None
    assert qualified["qualification"]["candidate_sha"] == candidate
    assert len(refs.published) == len(refs.deleted) == 1
    verified = TASK.record_verification(qualified, candidate_sha=candidate, actor="controller",
        decision="pass", evidence="actual exact-candidate check")
    reviewed = TASK.record_review(verified, candidate_sha=candidate, actor="fresh-independent-reviewer",
        decision="approved", summary="exact source/diff and all task criteria reviewed")
    assert reviewed["phase"] == "REVIEWED_APPROVED"
    assert "capsule_evidence" not in reviewed
    # Standard mode never bypasses the separate human integration permission.
    with pytest.raises(TASK.TaskControllerError, match="HUMAN_OWNER_AUTHORIZATION_REQUIRED"):
        TASK.integrate_task(reviewed, candidate_repo=repo, controller_main_sha=base,
            expected_app_id=424242, transport=transport, ref_transport=refs,
            human_owner_authorized=False)


def test_public_prepare_defaults_to_owner_bound_standard_and_rejects_new_attachment():
    parser = TASK.build_parser()
    args = parser.parse_args(["prepare", "999", "--task-id", "GH-999", "--allowed-path", "src/**", "--profile", "repository"])
    assert args.workflow_mode == "standard"
    with pytest.raises(SystemExit):
        parser.parse_args(["prepare", "999", "--task-id", "GH-999", "--allowed-path", "src/**", "--profile", "repository", "--workflow-mode", "attached"])


def test_new_prepare_preserves_stopped_state_and_consumed_allowance(tmp_path):
    repo, base = init_repo(tmp_path)
    state_dir = tmp_path / "preserved-state"
    path = TASK.state_path(state_dir, 999)
    path.parent.mkdir(parents=True)
    original = b'{"phase":"STOP_REPLAN","launches_used":1,"candidate":"retained"}'
    path.write_bytes(original)
    with pytest.raises(TASK.TaskControllerError, match="TASK_STATE_EXISTS_PRESERVE_HISTORY"):
        TASK.prepare_task(repo=repo, state_dir=state_dir, issue_number=999, task_id="GH-999-new",
            trusted_author="owner", repository="owner/repo", base_sha=base, allowed_paths=["src/**"],
            forbidden_paths=[], profiles=["repository"], revision=2, nonce="new-nonce-123456789")
    assert path.read_bytes() == original


def test_standard_authorized_full_path_never_loads_historical_capabilities(tmp_path, monkeypatch):
    """Actual acceptance calls; only external service/ref operations are fixtures."""
    def retired(*_args, **_kwargs):
        pytest.fail("standard acceptance entered historical RI machinery")

    monkeypatch.setattr(TASK, "_legacy_evidence", retired)
    monkeypatch.setattr(TASK, "require_review_preflight", retired)
    repo, base, candidate, qualified, transport, refs = qualify_fixture(
        tmp_path, workflow_mode="standard", compatibility_reason=None,
    )
    assert qualified["phase"] == "QUALIFIED"
    assert TASK.workflow_mode_for_state(qualified) == "standard"
    assert qualified["qualification"]["candidate_ref_removed"] is True
    verified = TASK.record_verification(qualified, candidate_sha=candidate,
        actor="controller", decision="pass", evidence="exact source and required checks")
    reviewed = TASK.record_review(verified, candidate_sha=candidate,
        actor="distinct-native-reviewer", decision="approved", summary="full diff, criteria and standards")
    pending = TASK.integrate_task(reviewed, candidate_repo=repo, controller_main_sha=base,
        expected_app_id=424242, transport=transport, ref_transport=refs, human_owner_authorized=True)
    refs.main_sha = base
    integrated = TASK.reconcile_integration(pending, candidate_sha=candidate, ref_transport=refs)
    assert integrated["phase"] == "INTEGRATED"
    assert integrated["integration"]["origin_main_after"] == candidate
    assert refs.main_pushes == [candidate]
    assert "capsule_evidence" not in integrated
    # Idempotent recovery must not push twice or create a signing key.
    again = TASK.reconcile_integration(integrated, candidate_sha=candidate, ref_transport=refs)
    assert again == integrated
    assert refs.main_pushes == [candidate]


@pytest.mark.parametrize("phase", ["QUALIFIED", "VERIFIED", "REVIEWED"])
def test_prepare_preserves_active_state_and_all_retained_artifacts(tmp_path, phase):
    repo, base = init_repo(tmp_path)
    state_dir = tmp_path / "retained-controller"
    path = TASK.state_path(state_dir, 999)
    path.parent.mkdir(parents=True)
    state = {
        "phase": phase,
        "launches_used": 1,
        "candidate": base,
        "capsule_evidence": {"commands": {}, "signed_receipt": "retained"},
    }
    # Deliberately preserve noncanonical JSON bytes, not only equivalent values.
    path.write_text(json.dumps(state, indent=1) + "\n\n")
    artifacts = {
        "authorization-999.md": b"existing owner authorization draft\n",
        "review-999.json": b'{"signature":"retained-review"}\n',
        "integration-999.json": b'{"candidate":"retained-integration"}\n',
        "failed-attempt.log": b"failure exit 1\n",
        "passed-attempt.log": b"success exit 0\n",
    }
    for name, content in artifacts.items():
        (state_dir / name).write_bytes(content)
    before = {p.name: p.read_bytes() for p in state_dir.iterdir()}

    with pytest.raises(TASK.TaskControllerError, match="TASK_STATE_EXISTS_PRESERVE_HISTORY"):
        TASK.prepare_task(
            repo=repo, state_dir=state_dir, issue_number=999, task_id="GH-999-new",
            trusted_author="owner", repository="owner/repo", base_sha=base,
            allowed_paths=["src/**"], forbidden_paths=[], profiles=["repository"],
            revision=2, nonce="new-nonce-123456789",
        )

    # Existing recovery entrypoint reloads the retained state without normalizing
    # state/receipt bytes, repairing keys, or resetting the consumed allowance.
    recovered = TASK.load_state(state_dir, 999)
    assert recovered == state
    assert recovered["launches_used"] == 1
    assert {p.name: p.read_bytes() for p in state_dir.iterdir()} == before


def public_standard_rework_fixture(
    tmp_path: Path,
    monkeypatch,
    *,
    workflow_mode: str = "standard",
    allowed_paths: list[str] | None = None,
    profiles: list[str] | None = None,
    extra_c2_files: dict[str, str] | None = None,
):
    """Create a disposable C1 checkpoint through the public parser and handlers."""
    issue_number = 999
    task_id = "GH-999-P1"
    repository = "owner/repo"
    controller_parent = tmp_path / "controller-parent"
    controller_parent.mkdir(parents=True)
    repo, base = init_repo(controller_parent)
    git(repo, "branch", "-M", "main")
    git(repo, "remote", "add", "origin", "https://github.com/owner/repo.git")
    git(repo, "update-ref", "refs/remotes/origin/main", base)

    candidate_repo = tmp_path / "candidate-repo"
    git(repo, "clone", "--quiet", "--no-hardlinks", str(repo), str(candidate_repo))
    git(candidate_repo, "config", "user.name", "Task Controller Test")
    git(candidate_repo, "config", "user.email", "task-test@example.invalid")
    git(candidate_repo, "remote", "set-url", "origin", "https://github.com/owner/repo.git")
    git(candidate_repo, "update-ref", "refs/remotes/origin/main", base)

    real_task_git = TASK.git

    def fixture_task_git(root: Path, *args: str) -> str:
        if args == ("fetch", "origin", "main"):
            return ""
        return real_task_git(root, *args)

    monkeypatch.setattr(TASK, "git", fixture_task_git)
    monkeypatch.setattr(TASK, "configured_qualification_app_id", lambda: 424242)
    monkeypatch.setenv("NUTRITION_TASK_TRUSTED_AUTHOR", "owner")
    issue_transport = FakeIssueAuthorizationTransport(author="owner")
    monkeypatch.setattr(TASK, "GhIssueAuthorizationTransport", lambda: issue_transport)
    ref_transport = FakeCandidateRefTransport()
    monkeypatch.setattr(TASK, "GitCandidateRefTransport", lambda _repo: ref_transport)

    tokens = iter(("a" * 24, "b" * 24, "c" * 24))
    monkeypatch.setattr(TASK.secrets, "token_hex", lambda _size: next(tokens))
    transports: dict[str, FakeQualificationTransport] = {}

    class SequencedQualificationTransport(FakeQualificationTransport):
        def __init__(self, *, run_id: int, check_id: int, **kwargs) -> None:
            self.run_id = run_id
            self.check_id = check_id
            super().__init__(**kwargs)

        def dispatch_workflow(self, repository, workflow, ref, inputs):
            super().dispatch_workflow(repository, workflow, ref, inputs)
            return {"workflow_run_id": self.run_id}

        def _run(self):
            run = super()._run()
            run["id"] = self.run_id
            return run

        def get_workflow_run(self, repository, run_id):
            assert run_id == self.run_id
            return self._run()

        def _check(self):
            check = super()._check()
            check["id"] = self.check_id
            return check

        def list_check_runs(self, repository, candidate_sha, app_id):
            assert candidate_sha == self.candidate_sha
            check = self._check()
            return [dict(check)]

        def get_check_run(self, repository, check_id):
            assert check_id == self.check_id
            return self._check()

    def qualification_transport():
        state = TASK.load_state(state_dir, issue_number)
        candidate_sha = git(candidate_repo, "rev-parse", "HEAD")
        if candidate_sha not in transports:
            sequence = len(transports) + 1
            transports[candidate_sha] = SequencedQualificationTransport(
                comment=next(iter(issue_transport.comments.values())),
                controller_sha=base,
                candidate_sha=candidate_sha,
                identity_sha256=state["authorization"]["identity_sha256"],
                issue_number=issue_number,
                run_id=8800 + sequence,
                check_id=9900 + sequence,
            )
        return transports[candidate_sha]

    monkeypatch.setattr(TASK, "GhQualificationTransport", qualification_transport)
    state_dir = tmp_path / "controller-state"
    common = ["--repo-root", str(repo), "--state-dir", str(state_dir)]

    def run(*args: str):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = TASK.main([*common, *args])
        output = stdout.getvalue().strip()
        return code, json.loads(output), output, stderr.getvalue()

    prepare_args = [
        "prepare", str(issue_number), "--task-id", task_id,
        "--base-sha", base, "--nonce", "fixture-owner-auth-0001",
        "--allowed-path", *(allowed_paths or ["src/**"]),
        "--forbidden-path", "src/forbidden/**",
        "--profile", *(profiles or ["repository"]),
    ]
    if workflow_mode == "compatibility":
        prepare_args.extend(("--workflow-mode", "compatibility", "--compatibility-reason", "disposable legacy fixture"))
    assert run(*prepare_args)[0] == 0
    assert run("authorize", str(issue_number))[0] == 0

    c1 = commit_paths(candidate_repo, {"src/food.py": "VALUE = 1\n"}, message="C1 candidate")
    assert run("qualify", str(issue_number), "--candidate-root", str(candidate_repo))[0] == 0
    assert run(
        "verify", str(issue_number), "--candidate-sha", c1,
        "--actor", "fixture-controller", "--decision", "pass",
        "--evidence", "fixture exact-candidate verification",
    )[0] == 0
    assert run(
        "review", str(issue_number), "--candidate-sha", c1,
        "--actor", "fixture-independent-reviewer", "--decision", "changes-requested",
        "--summary", "fixture correction required",
    )[0] == 0

    c2_files = {"src/food.py": "VALUE = 2\n"}
    c2_files.update(extra_c2_files or {})
    c2 = commit_paths(candidate_repo, c2_files, message="C2 corrected candidate")
    assert c1 != c2

    c1_repo_cache: list[Path] = []

    def candidate_c1_repo() -> Path:
        if not c1_repo_cache:
            c1_repo = tmp_path / "candidate-c1-repo"
            git(candidate_repo, "clone", "--quiet", "--no-hardlinks", str(candidate_repo), str(c1_repo))
            git(c1_repo, "remote", "set-url", "origin", "https://github.com/owner/repo.git")
            git(c1_repo, "update-ref", "refs/remotes/origin/main", base)
            git(c1_repo, "checkout", "--quiet", "--detach", c1)
            c1_repo_cache.append(c1_repo)
        return c1_repo_cache[0]

    def rework_argv(
        *,
        expected_candidate_sha: str | None = None,
        candidate_sha: str | None = None,
        candidate_root: Path | None = None,
    ) -> list[str]:
        return [
            *common,
            "rework", str(issue_number),
            "--candidate-root", str(candidate_root or candidate_repo),
            "--expected-candidate-sha", expected_candidate_sha or c1,
            "--candidate-sha", candidate_sha or c2,
        ]

    return {
        "run": run,
        "common": common,
        "rework_argv": rework_argv,
        "repo": repo,
        "candidate_repo": candidate_repo,
        "candidate_c1_repo": candidate_c1_repo,
        "state_dir": state_dir,
        "issue_number": issue_number,
        "task_id": task_id,
        "repository": repository,
        "base": base,
        "c1": c1,
        "c2": c2,
        "issue_transport": issue_transport,
        "transports": transports,
        "ref_transport": ref_transport,
        "workflow_mode": workflow_mode,
    }


def test_public_standard_rework_archives_c1_and_requalifies_only_selected_c2(tmp_path, monkeypatch):
    fixture = public_standard_rework_fixture(tmp_path, monkeypatch)
    issue = fixture["issue_number"]
    state_path = TASK.state_path(fixture["state_dir"], issue)

    TASK.checkpoint_transaction(
        fixture["state_dir"], issue,
        lambda current: {
            **current,
            "attempt_history": ["prior-attempt", "C1-reconciled-failure"],
            "launches_used": 2,
            "unrelated_checkpoint_field": {"retain": True},
            "qualification_operation": {
                **current["qualification_operation"],
                "error": "earlier failed reconciliation retained",
            },
        },
    )
    c1_state = TASK.load_state(fixture["state_dir"], issue)
    c1_sha256 = TASK.checkpoint_state_binding_sha256(c1_state)
    c1_qualification = json.loads(json.dumps(c1_state["qualification"]))
    c1_verification = json.loads(json.dumps(c1_state["verification"]))
    c1_review = json.loads(json.dumps(c1_state["review"]))
    c1_operation = json.loads(json.dumps(c1_state["qualification_operation"]))
    c1_transport = fixture["transports"][fixture["c1"]]
    c1_dispatch_count = c1_transport.dispatch_calls
    published_before = list(fixture["ref_transport"].published)
    deleted_before = list(fixture["ref_transport"].deleted)

    code, result, _, _ = fixture["run"](*fixture["rework_argv"]()[len(fixture["common"]):])
    assert code == 0
    assert result["phase"] == "AUTHORIZED"
    assert result["expected_candidate_sha"] == fixture["c1"]
    assert result["candidate_sha"] == fixture["c2"]
    assert result["next"] == "qualify"

    selected = TASK.load_state(fixture["state_dir"], issue)
    archived = selected["rework_history"][0]
    assert archived["checkpoint_sha256"] == c1_sha256
    assert archived["from_candidate_sha"] == fixture["c1"]
    assert archived["selected_candidate_sha"] == fixture["c2"]
    assert archived["qualification"] == c1_qualification
    assert archived["verification"] == c1_verification
    assert archived["review"] == c1_review
    assert archived["qualification_operation"] == c1_operation
    assert archived["existing_history"]["attempt_history"] == c1_state["attempt_history"]
    assert archived["previous_rework_binding"] is None
    assert selected["rework"]["authorization"] == c1_operation["resolved_authorization"]

    # The current C1 authority and unrelated fields survive; only active proof is retired.
    assert selected["authorization"] == c1_state["authorization"]
    assert selected["workflow"] == c1_state["workflow"]
    assert selected["attempt_history"] == c1_state["attempt_history"]
    assert selected["launches_used"] == 2
    assert selected["unrelated_checkpoint_field"] == {"retain": True}
    assert selected["qualification"] is None
    assert selected["verification"] is None
    assert selected["review"] is None
    assert selected["integration"] is None
    assert selected["qualification_operation"] is None
    assert c1_transport.dispatch_calls == c1_dispatch_count
    assert fixture["ref_transport"].published == published_before
    assert fixture["ref_transport"].deleted == deleted_before

    before_refusals = state_path.read_bytes()
    repeat_code, repeat, _, _ = fixture["run"](*fixture["rework_argv"]()[len(fixture["common"]):])
    assert repeat_code == 1
    assert repeat["error"] == "REWORK_ALREADY_APPLIED"
    assert state_path.read_bytes() == before_refusals

    c1_root = fixture["candidate_c1_repo"]()
    wrong_head_code, wrong_head, _, _ = fixture["run"](
        "qualify", str(issue), "--candidate-root", str(c1_root),
    )
    assert wrong_head_code == 1
    assert wrong_head["error"] == "REWORK_CANDIDATE_MISMATCH"
    assert state_path.read_bytes() == before_refusals

    stale_verify_code, stale_verify, _, _ = fixture["run"](
        "verify", str(issue), "--candidate-sha", fixture["c1"],
        "--actor", "fixture-controller", "--decision", "pass", "--evidence", "stale C1 proof",
    )
    assert stale_verify_code == 1
    assert stale_verify["error"] == "VERIFICATION_REQUIRES_EXACT_QUALIFICATION"
    stale_review_code, stale_review, _, _ = fixture["run"](
        "review", str(issue), "--candidate-sha", fixture["c1"],
        "--actor", "fixture-reviewer", "--decision", "approved", "--summary", "stale C1 approval",
    )
    assert stale_review_code == 1
    assert stale_review["error"] == "REVIEW_APPROVAL_REQUIRES_EXACT_VERIFICATION"
    assert state_path.read_bytes() == before_refusals

    stale_callback = {
        "phase": "QUALIFIED",
        "qualification": c1_qualification,
    }
    with pytest.raises(TASK.TaskControllerError, match="QUALIFICATION_OPERATION_STALE"):
        TASK.apply_qualification_terminal_result(
            fixture["state_dir"], issue, c1_operation, stale_callback,
            c1_transport, candidate_repo=c1_root,
        )
    assert state_path.read_bytes() == before_refusals

    stale_reconcile_code, stale_reconcile, _, _ = fixture["run"](
        "qualify-reconcile", str(issue), "--candidate-root", str(c1_root),
    )
    assert stale_reconcile_code == 1
    assert stale_reconcile["error"] == "QUALIFICATION_OPERATION_MISSING"
    assert state_path.read_bytes() == before_refusals

    c2_qualified_code, c2_qualified, _, _ = fixture["run"](
        "qualify", str(issue), "--candidate-root", str(fixture["candidate_repo"]),
    )
    assert c2_qualified_code == 0
    assert c2_qualified["candidate_sha"] == fixture["c2"]
    c2_state = TASK.load_state(fixture["state_dir"], issue)
    c2_qualification = c2_state["qualification"]
    c2_operation = c2_state["qualification_operation"]
    c2_transport = fixture["transports"][fixture["c2"]]
    assert c2_operation["dispatch_nonce"] != c1_operation["dispatch_nonce"]
    assert c2_operation["operation_id"] != c1_operation["operation_id"]
    assert c2_operation["candidate_ref"] != c1_operation["candidate_ref"]
    assert c2_qualification["workflow_run_id"] != c1_qualification["workflow_run_id"]
    assert c2_qualification["check_id"] != c1_qualification["check_id"]
    assert c2_qualification["candidate_sha"] == fixture["c2"]
    assert c2_qualification["check_app_id"] == 424242
    assert c2_transport.dispatch_inputs["candidate_sha"] == fixture["c2"]
    assert c2_transport.dispatch_inputs["dispatch_nonce"] == c2_operation["dispatch_nonce"]
    assert len(c2_state["rework_history"]) == 1

    before_approval = state_path.read_bytes()
    early_approval_code, early_approval, _, _ = fixture["run"](
        "review", str(issue), "--candidate-sha", fixture["c2"],
        "--actor", "fixture-independent-reviewer", "--decision", "approved",
        "--summary", "approval before fresh verification",
    )
    assert early_approval_code == 1
    assert early_approval["error"] == "REVIEW_APPROVAL_REQUIRES_EXACT_VERIFICATION"
    assert state_path.read_bytes() == before_approval

    assert fixture["run"](
        "verify", str(issue), "--candidate-sha", fixture["c2"],
        "--actor", "fixture-controller", "--decision", "pass",
        "--evidence", "fresh exact C2 verification",
    )[0] == 0
    assert fixture["run"](
        "review", str(issue), "--candidate-sha", fixture["c2"],
        "--actor", "fresh-independent-C2-reviewer", "--decision", "approved",
        "--summary", "fresh independent C2 source review",
    )[0] == 0
    final_state = TASK.load_state(fixture["state_dir"], issue)
    assert final_state["phase"] == "REVIEWED_APPROVED"
    assert final_state["qualification"]["candidate_sha"] == fixture["c2"]
    assert final_state["verification"]["candidate_sha"] == fixture["c2"]
    assert final_state["review"]["candidate_sha"] == fixture["c2"]

    before_integrity_checks = state_path.read_bytes()
    c1_integration_code, c1_integration, _, _ = fixture["run"](
        "integrate", str(issue), "--candidate-root", str(c1_root), "--human-owner-authorized",
    )
    assert c1_integration_code == 1
    assert c1_integration["error"] == "INTEGRATION_QUALIFICATION_MISMATCH"
    owner_gate_code, owner_gate, _, _ = fixture["run"](
        "integrate", str(issue), "--candidate-root", str(fixture["candidate_repo"]),
    )
    assert owner_gate_code == 1
    assert owner_gate["error"] == "HUMAN_OWNER_AUTHORIZATION_REQUIRED"
    assert state_path.read_bytes() == before_integrity_checks
    assert fixture["ref_transport"].main_pushes == []

    pending = TASK.integrate_task(
        final_state,
        candidate_repo=fixture["candidate_repo"],
        controller_main_sha=fixture["base"],
        expected_app_id=424242,
        transport=c2_transport,
        ref_transport=fixture["ref_transport"],
        human_owner_authorized=True,
    )
    assert pending["phase"] == "INTEGRATION_PENDING"
    assert pending["integration"]["candidate_sha"] == fixture["c2"]
    assert pending["integration"]["check_id"] == c2_qualification["check_id"]
    assert TASK.load_state(fixture["state_dir"], issue) == final_state


def test_public_rework_parser_requires_full_c1_and_c2_and_explains_limits(capsys, tmp_path):
    parser = TASK.build_parser()
    with pytest.raises(SystemExit) as missing:
        parser.parse_args(["rework", "999", "--candidate-root", str(tmp_path)])
    assert missing.value.code == 2

    with pytest.raises(SystemExit) as help_result:
        parser.parse_args(["rework", "--help"])
    assert help_result.value.code == 0
    help_text = capsys.readouterr().out
    for phrase in (
        "--expected-candidate-sha",
        "--candidate-sha",
        "REVIEWED_CHANGES_REQUESTED",
        "current owner authorization",
        "proof and operation history are retained",
        "does not create fresh authority",
        "does not accept legacy records",
    ):
        assert phrase in help_text

    args = parser.parse_args([
        "rework", "999", "--candidate-root", str(tmp_path),
        "--expected-candidate-sha", "a" * 40, "--candidate-sha", "b" * 40,
    ])
    assert args.handler is TASK.command_rework


@pytest.mark.parametrize("case", ["malformed", "same", "wrong-c1", "wrong-c2", "dirty-c2"])
def test_public_rework_rejects_invalid_candidate_identities_without_mutation(tmp_path, monkeypatch, case):
    fixture = public_standard_rework_fixture(tmp_path, monkeypatch)
    state_path = TASK.state_path(fixture["state_dir"], fixture["issue_number"])
    before = state_path.read_bytes()
    expected = fixture["c1"]
    candidate = fixture["c2"]
    root = fixture["candidate_repo"]
    if case == "malformed":
        expected = "abc"
        error = "REWORK_CANDIDATE_SHA_INVALID"
    elif case == "same":
        candidate = fixture["c1"]
        error = "REWORK_CANDIDATES_MUST_DIFFER"
    elif case == "wrong-c1":
        expected = "f" * 40
        error = "REWORK_C1_MISMATCH"
    elif case == "wrong-c2":
        candidate = "f" * 40
        error = "REWORK_CANDIDATE_HEAD_MISMATCH"
    else:
        (root / "untracked.txt").write_text("dirty candidate\n", encoding="utf-8")
        error = "CANDIDATE_WORKTREE_DIRTY"

    code, result, _, _ = fixture["run"](*fixture["rework_argv"](
        expected_candidate_sha=expected,
        candidate_sha=candidate,
        candidate_root=root,
    )[len(fixture["common"]):])
    assert code == 1
    assert error in result["error"]
    assert state_path.read_bytes() == before
    assert sum(item.dispatch_calls for item in fixture["transports"].values()) == 1
    assert len(fixture["ref_transport"].published) == 1
    assert fixture["ref_transport"].main_pushes == []


def test_public_rework_rejects_stale_c1_proof_and_unresolved_operation_states(tmp_path, monkeypatch):
    fixture = public_standard_rework_fixture(tmp_path, monkeypatch)
    state_path = TASK.state_path(fixture["state_dir"], fixture["issue_number"])
    TASK.checkpoint_transaction(
        fixture["state_dir"], fixture["issue_number"],
        lambda current: {
            **current,
            "verification": {**current["verification"], "candidate_sha": "f" * 40},
        },
    )
    before = state_path.read_bytes()
    code, result, _, _ = fixture["run"](*fixture["rework_argv"]()[len(fixture["common"]):])
    assert code == 1
    assert result["error"] == "REWORK_C1_PROOF_MISMATCH"
    assert state_path.read_bytes() == before


@pytest.mark.parametrize("status", ["DISPATCH_PENDING", "RUNNING", "UNKNOWN", "TERMINAL", "CLEANUP_UNKNOWN", "UNRECOGNIZED", None])
def test_public_rework_rejects_each_unresolved_qualification_operation(tmp_path, monkeypatch, status):
    fixture = public_standard_rework_fixture(tmp_path, monkeypatch)
    state_path = TASK.state_path(fixture["state_dir"], fixture["issue_number"])
    TASK.checkpoint_transaction(
        fixture["state_dir"], fixture["issue_number"],
        lambda current: {
            **current,
            "qualification_operation": {**current["qualification_operation"], "status": status},
        },
    )
    before = state_path.read_bytes()
    code, result, _, _ = fixture["run"](*fixture["rework_argv"]()[len(fixture["common"]):])
    assert code == 1
    assert result["error"] == "REWORK_QUALIFICATION_OPERATION_UNSAFE"
    assert state_path.read_bytes() == before
    assert sum(item.dispatch_calls for item in fixture["transports"].values()) == 1
    assert len(fixture["ref_transport"].published) == 1


@pytest.mark.parametrize("field", ["cleanup_error", "candidate_ref_removed"])
def test_public_rework_rejects_unclean_qualification_ref_state(tmp_path, monkeypatch, field):
    fixture = public_standard_rework_fixture(tmp_path, monkeypatch)
    state_path = TASK.state_path(fixture["state_dir"], fixture["issue_number"])

    def make_unclean(current):
        updated = json.loads(json.dumps(current))
        if field == "cleanup_error":
            updated["qualification_operation"]["cleanup_error"] = "cleanup uncertain"
        else:
            updated["qualification"]["candidate_ref_removed"] = False
        return updated

    TASK.checkpoint_transaction(fixture["state_dir"], fixture["issue_number"], make_unclean)
    before = state_path.read_bytes()
    code, result, _, _ = fixture["run"](*fixture["rework_argv"]()[len(fixture["common"]):])
    assert code == 1
    assert result["error"] in {
        "REWORK_QUALIFICATION_OPERATION_UNSAFE",
        "REWORK_QUALIFICATION_PROOF_INVALID",
    }
    assert state_path.read_bytes() == before


def test_public_rework_rejects_pending_integration_without_mutation(tmp_path, monkeypatch):
    fixture = public_standard_rework_fixture(tmp_path, monkeypatch)
    state_path = TASK.state_path(fixture["state_dir"], fixture["issue_number"])
    TASK.checkpoint_transaction(
        fixture["state_dir"], fixture["issue_number"],
        lambda current: {**current, "integration": {"phase": "INTEGRATION_PENDING", "candidate_sha": fixture["c1"]}},
    )
    before = state_path.read_bytes()
    code, result, _, _ = fixture["run"](*fixture["rework_argv"]()[len(fixture["common"]):])
    assert code == 1
    assert result["error"] == "REWORK_INTEGRATION_UNRESOLVED"
    assert state_path.read_bytes() == before


@pytest.mark.parametrize(
    "case",
    [
        "edited-authorization",
        "untrusted-author",
        "ambiguous-authorization",
        "stale-base",
        "unauthorized-path",
        "missing-profile",
    ],
)
def test_public_rework_revalidates_authority_main_scope_and_profile_floor(tmp_path, monkeypatch, case):
    allowed_paths = ["**"] if case == "missing-profile" else ["src/**"]
    profiles = ["repository"]
    extra = None
    if case == "unauthorized-path":
        extra = {"docs/outside-scope.md": "outside\n"}
    elif case == "missing-profile":
        extra = {"apps/backend/new_route.py": "ROUTE = True\n"}
    fixture = public_standard_rework_fixture(
        tmp_path,
        monkeypatch,
        allowed_paths=allowed_paths,
        profiles=profiles,
        extra_c2_files=extra,
    )
    state_path = TASK.state_path(fixture["state_dir"], fixture["issue_number"])
    if case == "edited-authorization":
        comment = fixture["issue_transport"].comments[7001]
        comment["body"] = comment["body"].replace("fixture-owner-auth-0001", "fixture-owner-auth-edited")
        expected_error = "AUTHORIZATION_DIGEST_MISMATCH"
    elif case == "untrusted-author":
        fixture["transports"][fixture["c1"]].comments[0]["user"]["login"] = "attacker"
        expected_error = "AUTHORIZATION_AUTHOR_UNTRUSTED"
    elif case == "ambiguous-authorization":
        transport = TASK.GhQualificationTransport()
        transport.comments.append({**transport.comments[0], "id": 7002})
        expected_error = "AUTHORIZATION_AMBIGUOUS"
    elif case == "stale-base":
        (fixture["repo"] / "README.md").write_text("advanced main\n", encoding="utf-8")
        git(fixture["repo"], "add", "README.md")
        git(fixture["repo"], "commit", "--quiet", "-m", "advance fixture main")
        advanced = git(fixture["repo"], "rev-parse", "HEAD")
        git(fixture["repo"], "update-ref", "refs/remotes/origin/main", advanced)
        expected_error = "REWORK_BASE_AUTHORITY_STALE"
    elif case == "unauthorized-path":
        expected_error = "SCOPE_UNEXPECTED"
    else:
        expected_error = "QUALIFICATION_PROFILE_REQUIRED"
    before = state_path.read_bytes()
    code, result, _, _ = fixture["run"](*fixture["rework_argv"]()[len(fixture["common"]):])
    assert code == 1
    assert expected_error in result["error"]
    assert state_path.read_bytes() == before
    assert sum(item.dispatch_calls for item in fixture["transports"].values()) == 1
    assert fixture["ref_transport"].main_pushes == []


def test_public_rework_rejects_compatibility_implicit_legacy_and_injected_bindings(tmp_path, monkeypatch):
    compatibility = public_standard_rework_fixture(tmp_path / "compat", monkeypatch, workflow_mode="compatibility")
    state_path = TASK.state_path(compatibility["state_dir"], compatibility["issue_number"])
    before = state_path.read_bytes()
    code, result, _, _ = compatibility["run"](*compatibility["rework_argv"]()[len(compatibility["common"]):])
    assert code == 1
    assert result["error"] == "REWORK_STANDARD_WORKFLOW_REQUIRED"
    assert state_path.read_bytes() == before

    standard = public_standard_rework_fixture(tmp_path / "injected", monkeypatch)
    state_path = TASK.state_path(standard["state_dir"], standard["issue_number"])
    TASK.checkpoint_transaction(
        standard["state_dir"], standard["issue_number"],
        lambda current: {**current, "capsule_evidence": {"binding": {"candidate": standard["c1"]}}},
    )
    before = state_path.read_bytes()
    code, result, _, _ = standard["run"](*standard["rework_argv"]()[len(standard["common"]):])
    assert code == 1
    assert result["error"] == "REWORK_HISTORICAL_BINDING_UNSUPPORTED"
    assert state_path.read_bytes() == before

    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    legacy_repo, _ = init_repo(legacy_root)
    legacy_state_dir = tmp_path / "implicit-legacy-state"
    legacy_state = {
        "phase": "REVIEWED_CHANGES_REQUESTED",
        "issue_number": 999,
        "task_id": "GH-999-P1",
        "authorization": {"revision": 1},
    }
    TASK.atomic_write_json(TASK.state_path(legacy_state_dir, 999), legacy_state)
    legacy_path = TASK.state_path(legacy_state_dir, 999)
    legacy_before = legacy_path.read_bytes()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = TASK.main([
            "--repo-root", str(legacy_repo), "--state-dir", str(legacy_state_dir),
            "rework", "999", "--candidate-root", str(legacy_repo),
            "--expected-candidate-sha", "a" * 40, "--candidate-sha", "b" * 40,
        ])
    assert code == 1
    assert json.loads(output.getvalue())["error"] == "REWORK_STANDARD_WORKFLOW_REQUIRED"
    assert legacy_path.read_bytes() == legacy_before


@pytest.mark.parametrize(
    ("phase", "stop_reason", "expected_error"),
    [
        ("STOP_REPLAN", "owner-directed stop", "STOP_REPLAN_PRESERVE_ATTEMPT"),
        ("AUTHORIZED", None, "REWORK_REQUIRES_CHANGES_REQUESTED_REVIEW"),
        ("QUALIFICATION_FAILED", None, "REWORK_REQUIRES_CHANGES_REQUESTED_REVIEW"),
        ("INTEGRATED", None, "REWORK_REQUIRES_CHANGES_REQUESTED_REVIEW"),
        ("UNSUPPORTED_PHASE", None, "REWORK_REQUIRES_CHANGES_REQUESTED_REVIEW"),
    ],
)
def test_public_rework_preserves_stops_and_rejects_unsupported_phase(
    tmp_path, monkeypatch, phase, stop_reason, expected_error,
):
    fixture = public_standard_rework_fixture(tmp_path, monkeypatch)
    state_path = TASK.state_path(fixture["state_dir"], fixture["issue_number"])

    def select_phase(current):
        updated = {**current, "phase": phase, "launches_used": 2}
        if stop_reason is not None:
            updated["stop_reason"] = stop_reason
        return updated

    TASK.checkpoint_transaction(
        fixture["state_dir"], fixture["issue_number"],
        select_phase,
    )
    before = state_path.read_bytes()
    dispatch_calls = sum(item.dispatch_calls for item in fixture["transports"].values())
    published = list(fixture["ref_transport"].published)
    deleted = list(fixture["ref_transport"].deleted)
    main_pushes = list(fixture["ref_transport"].main_pushes)

    code, result, _, _ = fixture["run"](*fixture["rework_argv"]()[len(fixture["common"]):])
    assert code == 1
    assert result["error"] == expected_error
    assert state_path.read_bytes() == before
    state = TASK.load_state(fixture["state_dir"], fixture["issue_number"])
    assert state["phase"] == phase
    assert state["launches_used"] == 2
    assert state.get("rework_history", []) == []
    if stop_reason is not None:
        assert state["stop_reason"] == stop_reason
    assert sum(item.dispatch_calls for item in fixture["transports"].values()) == dispatch_calls
    assert fixture["ref_transport"].published == published
    assert fixture["ref_transport"].deleted == deleted
    assert fixture["ref_transport"].main_pushes == main_pushes


def test_overlapping_rework_calls_use_issue_lock_and_write_one_archive(tmp_path, monkeypatch):
    fixture = public_standard_rework_fixture(tmp_path, monkeypatch)
    barrier = threading.Barrier(2)
    local = threading.local()
    original_resolve = TASK.resolve_current_authorization
    original_transaction = TASK.checkpoint_transaction
    transaction_calls: list[int] = []

    def barrier_resolve(state, transport):
        if not getattr(local, "passed_barrier", False):
            local.passed_barrier = True
            barrier.wait(timeout=10)
        return original_resolve(state, transport)

    def tracked_transaction(state_dir, issue_number, mutation):
        transaction_calls.append(issue_number)
        return original_transaction(state_dir, issue_number, mutation)

    monkeypatch.setattr(TASK, "resolve_current_authorization", barrier_resolve)
    monkeypatch.setattr(TASK, "checkpoint_transaction", tracked_transaction)
    outcomes: list[tuple[str, object]] = []

    def run_rework():
        args = TASK.build_parser().parse_args(fixture["rework_argv"]())
        try:
            outcomes.append(("return", args.handler(args)))
        except BaseException as exc:  # captured for assertion in the parent test
            outcomes.append(("error", str(exc)))

    workers = [threading.Thread(target=run_rework) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)

    assert all(not worker.is_alive() for worker in workers)
    assert sorted(outcomes, key=lambda item: item[0]) == sorted(
        [("return", 0), ("error", "REWORK_STATE_CHANGED")],
        key=lambda item: item[0],
    )
    assert transaction_calls == [999, 999]
    state = TASK.load_state(fixture["state_dir"], fixture["issue_number"])
    assert state["phase"] == "AUTHORIZED"
    assert len(state["rework_history"]) == 1
    assert state["rework_history"][0]["from_candidate_sha"] == fixture["c1"]
    assert state["qualification_operation"] is None
    assert sum(item.dispatch_calls for item in fixture["transports"].values()) == 1
    assert len(fixture["ref_transport"].published) == 1
    assert fixture["ref_transport"].main_pushes == []


@pytest.mark.parametrize("intervening_change", ["review", "owner-stop"])
def test_stale_rework_caller_preserves_intervening_decision_under_issue_lock(
    tmp_path, monkeypatch, intervening_change,
):
    fixture = public_standard_rework_fixture(tmp_path, monkeypatch)
    entered_authorization = threading.Event()
    release_authorization = threading.Event()
    local = threading.local()
    original_resolve = TASK.resolve_current_authorization
    original_transaction = TASK.checkpoint_transaction
    transaction_calls: list[int] = []

    def blocking_resolve(state, transport):
        if not getattr(local, "blocked_once", False):
            local.blocked_once = True
            entered_authorization.set()
            assert release_authorization.wait(10)
        return original_resolve(state, transport)

    def tracked_transaction(state_dir, issue_number, mutation):
        transaction_calls.append(issue_number)
        return original_transaction(state_dir, issue_number, mutation)

    monkeypatch.setattr(TASK, "resolve_current_authorization", blocking_resolve)
    monkeypatch.setattr(TASK, "checkpoint_transaction", tracked_transaction)
    outcome: list[str] = []

    def run_rework():
        args = TASK.build_parser().parse_args(fixture["rework_argv"]())
        try:
            args.handler(args)
            outcome.append("unexpected success")
        except BaseException as exc:  # captured for assertion in the parent test
            outcome.append(str(exc))

    worker = threading.Thread(target=run_rework)
    worker.start()
    assert entered_authorization.wait(10)

    def record_intervening_decision(current):
        if intervening_change == "review":
            return {
                **current,
                "review": {**current["review"], "summary": "newer concurrent review decision"},
            }
        return {
            **current,
            "phase": "STOP_REPLAN",
            "stop_reason": "owner-directed stop during rework",
            "launches_used": 2,
        }

    TASK.checkpoint_transaction(
        fixture["state_dir"], fixture["issue_number"],
        record_intervening_decision,
    )
    newer_bytes = TASK.state_path(fixture["state_dir"], fixture["issue_number"]).read_bytes()
    release_authorization.set()
    worker.join(10)

    assert not worker.is_alive()
    assert outcome == ["REWORK_STATE_CHANGED"]
    assert transaction_calls == [999, 999]
    current = TASK.load_state(fixture["state_dir"], fixture["issue_number"])
    if intervening_change == "review":
        assert current["review"]["summary"] == "newer concurrent review decision"
        assert current["phase"] == "REVIEWED_CHANGES_REQUESTED"
    else:
        assert current["phase"] == "STOP_REPLAN"
        assert current["stop_reason"] == "owner-directed stop during rework"
        assert current["launches_used"] == 2
    assert current.get("rework_history", []) == []
    assert TASK.state_path(fixture["state_dir"], fixture["issue_number"]).read_bytes() == newer_bytes
