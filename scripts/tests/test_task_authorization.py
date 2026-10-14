from __future__ import annotations

import copy
import dataclasses
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

from lib.task_authorization import (  # noqa: E402
    AUTHORIZATION_MARKER,
    AUTHORIZATION_MARKER_V1,
    AUTHORIZATION_MARKER_V2,
    AuthorizationError,
    build_payload,
    extract_payload,
    render_authorization_comment,
    required_profiles_for_paths,
    ResolvedAuthorization,
    resolve_comments,
    validate_candidate_scope,
)


REPOSITORY = "MitCaine/Nutrition-App"
ISSUE_NUMBER = 179
BASE_SHA = "1" * 40
TRUSTED_AUTHOR = "MitCaine"


def payload(
    task_id: str,
    *,
    revision: int = 1,
    nonce: str = "0123456789abcdef",
):
    return build_payload(
        task_id=task_id,
        issue_number=ISSUE_NUMBER,
        repository=REPOSITORY,
        base_sha=BASE_SHA,
        allowed_paths=[
            "scripts/lib/task_authorization.py",
        ],
        forbidden_paths=[],
        profiles=["repository", "ios-native"],
        revision=revision,
        nonce=nonce,
    )


def comment(
    comment_id: int,
    task_id: str,
    *,
    author: str = TRUSTED_AUTHOR,
    revision: int = 1,
):
    return {
        "id": comment_id,
        "user": {"login": author},
        "body": render_authorization_comment(
            payload(
                task_id,
                revision=revision,
                nonce=f"nonce-{comment_id:016d}",
            )
        ),
    }


class ResolveCommentsTests(unittest.TestCase):
    def resolve(self, comments):
        return resolve_comments(
            comments,
            trusted_author=TRUSTED_AUTHOR,
            expected_repository=REPOSITORY,
            expected_issue_number=ISSUE_NUMBER,
            expected_task_id="GH-179-P1",
            expected_revision=1,
        )

    def test_one_matching_authorization_passes(self):
        resolved = self.resolve(
            [comment(1001, "GH-179-P1")]
        )

        self.assertEqual(
            resolved.task_id,
            "GH-179-P1",
        )
        self.assertEqual(
            resolved.comment_id,
            1001,
        )
        self.assertEqual(resolved.schema_version, 2)
        self.assertIn("schema_version", resolved.to_dict())

    def test_v1_comment_digest_identity_and_serialized_shape_stay_frozen(self):
        legacy = build_payload(
            task_id="GH-179-P1", issue_number=ISSUE_NUMBER, repository=REPOSITORY,
            base_sha=BASE_SHA, allowed_paths=["scripts/lib/task_authorization.py"],
            forbidden_paths=[], profiles=["repository", "ios-native"], revision=1,
            nonce="nonce-0000000000001001", schema_version=1,
        )
        body = render_authorization_comment(legacy)
        self.assertIn(AUTHORIZATION_MARKER_V1, body)
        self.assertNotIn(AUTHORIZATION_MARKER_V2, body)
        self.assertEqual(
            legacy["payload_sha256"],
            "718d63a1471f8642ce9f5d44cf23cca3e86df9c8058f4eaf7f5e5463b064906d",
        )
        resolved = self.resolve([{
            "id": 1001, "user": {"login": TRUSTED_AUTHOR}, "body": body,
        }])
        self.assertEqual(resolved.schema_version, 1)
        self.assertEqual(
            resolved.identity_sha256,
            "134fa03bc0b3e29e0aabec4089541010c755a90dc846eb4d122693f9faf60405",
        )
        self.assertNotIn("schema_version", resolved.to_dict())

    def test_v2_marker_schema_mismatch_and_malformed_v2_patterns_fail_closed(self):
        current = comment(1001, "GH-179-P1")["body"]
        self.assertIn(AUTHORIZATION_MARKER_V2, current)
        with self.assertRaises(AuthorizationError) as context:
            extract_payload(current.replace(AUTHORIZATION_MARKER_V2, AUTHORIZATION_MARKER_V1))
        self.assertEqual(context.exception.code, "AUTHORIZATION_MARKER_SCHEMA_MISMATCH")

        arguments = dict(task_id="GH-179-P1", issue_number=ISSUE_NUMBER,
                         repository=REPOSITORY, base_sha=BASE_SHA,
                         forbidden_paths=[], profiles=["repository"], revision=1,
                         nonce="malformed-v2-pattern-01")
        with self.assertRaises(AuthorizationError) as context:
            build_payload(allowed_paths=["src/foo*bar.py"], **arguments)
        self.assertEqual(context.exception.code, "AUTHORIZATION_PATH_INVALID")
        legacy = build_payload(allowed_paths=["src/foo*bar.py"], schema_version=1, **arguments)
        self.assertEqual(legacy["schema_version"], 1)

    def test_v2_reauthorization_uses_new_comment_nonce_revision_and_identity(self):
        old = build_payload(
            task_id="GH-179-P1", issue_number=ISSUE_NUMBER, repository=REPOSITORY,
            base_sha=BASE_SHA, allowed_paths=["scripts/lib/task_authorization.py"],
            forbidden_paths=[], profiles=["repository", "ios-native"], revision=1,
            nonce="old-v1-nonce-0000001", schema_version=1,
        )
        fresh = build_payload(
            task_id="GH-179-P1", issue_number=ISSUE_NUMBER, repository=REPOSITORY,
            base_sha=BASE_SHA, allowed_paths=["scripts/lib/task_authorization.py"],
            forbidden_paths=[], profiles=["repository", "ios-native"], revision=2,
            nonce="fresh-v2-nonce-000001", schema_version=2,
        )
        old_auth = self.resolve([{"id": 1001, "user": {"login": TRUSTED_AUTHOR},
                                  "body": render_authorization_comment(old)}])
        fresh_auth = resolve_comments(
            [{"id": 1002, "user": {"login": TRUSTED_AUTHOR},
              "body": render_authorization_comment(fresh)}],
            trusted_author=TRUSTED_AUTHOR, expected_repository=REPOSITORY,
            expected_issue_number=ISSUE_NUMBER, expected_task_id="GH-179-P1",
            expected_revision=2,
        )
        self.assertEqual((old_auth.schema_version, fresh_auth.schema_version), (1, 2))
        self.assertNotEqual(old_auth.comment_id, fresh_auth.comment_id)
        self.assertNotEqual(old_auth.nonce, fresh_auth.nonce)
        self.assertNotEqual(old_auth.revision, fresh_auth.revision)
        self.assertNotEqual(old_auth.identity_sha256, fresh_auth.identity_sha256)
        self.assertEqual(fresh_auth.to_dict()["schema_version"], 2)

    def test_historical_authorization_plus_current_passes(self):
        resolved = self.resolve(
            [
                comment(1001, "GH-178-P1"),
                comment(1002, "GH-179-P1"),
            ]
        )

        self.assertEqual(
            resolved.task_id,
            "GH-179-P1",
        )
        self.assertEqual(
            resolved.comment_id,
            1002,
        )

    def test_zero_matching_authorizations_fails_closed(self):
        with self.assertRaises(
            AuthorizationError
        ) as context:
            self.resolve(
                [comment(1001, "GH-178-P1")]
            )

        self.assertEqual(
            context.exception.code,
            "AUTHORIZATION_MISSING",
        )

    def test_two_matching_authorizations_are_ambiguous(self):
        with self.assertRaises(
            AuthorizationError
        ) as context:
            self.resolve(
                [
                    comment(1001, "GH-179-P1"),
                    comment(1002, "GH-179-P1"),
                ]
            )

        self.assertEqual(
            context.exception.code,
            "AUTHORIZATION_AMBIGUOUS",
        )

    def test_untrusted_matching_authorization_is_rejected(self):
        with self.assertRaises(
            AuthorizationError
        ) as context:
            self.resolve(
                [
                    comment(
                        1001,
                        "GH-179-P1",
                        author="UntrustedUser",
                    )
                ]
            )

        self.assertEqual(
            context.exception.code,
            "AUTHORIZATION_AUTHOR_UNTRUSTED",
        )

    def test_malformed_matching_payload_is_rejected(self):
        valid = payload(
            "GH-179-P1",
            nonce="malformed-payload-0001",
        )
        malformed = copy.deepcopy(valid)
        malformed["payload_sha256"] = "0" * 64

        bad_comment = {
            "id": 1001,
            "user": {"login": TRUSTED_AUTHOR},
            "body": (
                f"{AUTHORIZATION_MARKER}\n"
                "```json\n"
                + json.dumps(
                    malformed,
                    indent=2,
                    sort_keys=True,
                )
                + "\n```\n"
            ),
        }

        with self.assertRaises(
            AuthorizationError
        ) as context:
            self.resolve([bad_comment])

        self.assertEqual(
            context.exception.code,
            "AUTHORIZATION_DIGEST_MISMATCH",
        )


class RequiredProfilesForPathsTests(unittest.TestCase):
    def test_profile_floors_use_component_boundaries_and_compose(self):
        cases = (
            (
                ["apps/backend/tests/test_task_controller.py"],
                {"backend"},
            ),
            (
                ["apps/backend/**"],
                {"backend"},
            ),
            (
                ["apps/mobile/**"],
                {"mobile"},
            ),
            (
                ["apps/mobile/src/runtime/session.ts"],
                {"mobile"},
            ),
            (
                ["apps/backend/app/migrations/versions/0034_example.py"],
                {"backend", "postgresql"},
            ),
            (
                ["apps/backend/app/models/food.py"],
                {"backend", "postgresql"},
            ),
            (
                ["apps/backend/app/repositories/food_repository.py"],
                {"backend", "postgresql"},
            ),
            (
                ["apps/backend/app/core/database.py"],
                {"backend", "postgresql"},
            ),
            (
                ["apps/backend/app/operators/current_runtime_authority.py"],
                {"backend", "postgresql"},
            ),
            (
                ["apps/backend/tests/test_phase5c4_roles_postgres.py"],
                {"backend", "postgresql"},
            ),
            (
                ["apps/backend/tests/postgres_test_support.py"],
                {"backend", "postgresql"},
            ),
            (
                ["apps/mobile/app.json"],
                {"ios-native", "mobile"},
            ),
            (
                ["scripts/lib/task_authorization.py"],
                {"repository", "ios-native"},
            ),
            (
                ["apps/backend/app/models/food.py", "apps/mobile/app.json"],
                {"backend", "ios-native", "mobile", "postgresql"},
            ),
            (
                ["docs/operations/testing.md"],
                set(),
            ),
            (
                ["apps/backendish/app/models/food.py"],
                set(),
            ),
            (
                ["apps/mobileish/app.json"],
                set(),
            ),
            (
                ["apps/backend/app/migrations_extra/versions/0034_example.py"],
                {"backend"},
            ),
            (
                ["apps/backend/app/repositories_extra/food_repository.py"],
                {"backend"},
            ),
            (
                ["apps/backend/tests/test_task_controller_postgresish.py"],
                {"backend"},
            ),
        )

        for paths, expected in cases:
            with self.subTest(paths=paths):
                self.assertEqual(
                    required_profiles_for_paths(paths),
                    expected,
                )


class RealGitAuthorizationMatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nutrition authorization paths-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "task/path-scope")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "src/nested").mkdir(parents=True)
        (self.repo / "src/top.txt").write_text("rename me\n")
        (self.repo / "src/change.txt").write_text("before\n")
        (self.repo / "src/nested/keep.txt").write_text("keep\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.auth = ResolvedAuthorization(
            task_id="GH-244", issue_number=244, repository="MitCaine/Nutrition-App",
            base_sha=self.base, allowed_paths=("src/*",), forbidden_paths=(),
            profiles=("repository",), revision=1, nonce="0123456789abcdef",
            comment_id=244, author_login="MitCaine", payload_sha256="a" * 64,
            identity_sha256="b" * 64,
        )

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def test_real_git_add_change_and_rename_keep_versioned_matcher(self):
        (self.repo / "src/change.txt").write_text("after\n")
        (self.repo / "src/new.txt").write_text("new\n")
        self.git("mv", "src/top.txt", "src/nested/top.txt")
        self.git("add", "-A")
        self.git("commit", "-qm", "add change and rename paths")
        candidate = self.git("rev-parse", "HEAD")

        changed = validate_candidate_scope(self.repo, self.auth, candidate_sha=candidate)
        self.assertEqual(changed, [
            "src/change.txt", "src/nested/top.txt", "src/new.txt", "src/top.txt",
        ])
        with self.assertRaisesRegex(AuthorizationError, "SCOPE_UNEXPECTED"):
            validate_candidate_scope(
                self.repo, dataclasses.replace(self.auth, schema_version=2),
                candidate_sha=candidate,
            )

    def test_real_git_overlapping_v2_forbidden_pattern_wins(self):
        self.git("switch", "-qc", "task/path-overlap", self.base)
        (self.repo / "src/new.txt").write_text("new\n")
        self.git("add", "src/new.txt")
        self.git("commit", "-qm", "add allowed and forbidden path")
        candidate = self.git("rev-parse", "HEAD")
        authorization = dataclasses.replace(
            self.auth, schema_version=2, forbidden_paths=("src/new.txt",),
        )
        with self.assertRaisesRegex(AuthorizationError, "SCOPE_FORBIDDEN"):
            validate_candidate_scope(self.repo, authorization, candidate_sha=candidate)

    def test_retained_v1_forbidden_wildcard_keeps_slash_crossing_reach(self):
        self.git("switch", "-qc", "task/v1-forbidden", self.base)
        (self.repo / "src/nested/new.txt").write_text("new\n")
        self.git("add", "src/nested/new.txt")
        self.git("commit", "-qm", "add nested path under retained v1 scope")
        candidate = self.git("rev-parse", "HEAD")
        authorization = dataclasses.replace(
            self.auth, allowed_paths=("src/*",), forbidden_paths=("src/*",),
        )
        self.assertEqual(authorization.schema_version, 1)
        with self.assertRaisesRegex(AuthorizationError, "SCOPE_FORBIDDEN"):
            validate_candidate_scope(self.repo, authorization, candidate_sha=candidate)


if __name__ == "__main__":
    unittest.main()


# Exercise real command/checkpoint/issue-lock paths with a synthetic transport.
# No GitHub publication, live assignment, or repository ref mutation occurs.
import argparse
import concurrent.futures
import threading
import pytest
import task


class PublicationTransport:
    def __init__(self, state_dir):
        self.state_dir = state_dir
        self.comments = []
        self.posts = 0
        self.failure = None
        self.hidden = False
        self.entered = None
        self.release = None

    def list_issue_comments(self, repository, issue):
        return [] if self.hidden else copy.deepcopy(self.comments)

    def create_issue_comment(self, repository, issue, body):
        persisted = task.load_state(self.state_dir, issue)
        assert persisted["phase"] == "PREPARED"
        assert persisted["authorization_publication"]["status"] == "pending"
        assert persisted["authorization_publication"]["identity"]["body_sha256"] == task.hashlib.sha256(body.encode()).hexdigest()
        self.posts += 1
        observed = {"id": 7001, "body": body, "user": {"login": TRUSTED_AUTHOR}}
        self.comments.append(observed)
        if self.entered is not None:
            self.entered.set()
            assert self.release.wait(5)
        if self.failure == "lost_reply":
            raise task.TaskControllerError("synthetic lost create reply")
        return copy.deepcopy(observed)

    def get_issue_comment(self, repository, comment_id):
        persisted = task.load_state(self.state_dir, 901)
        assert persisted["authorization_publication"]["comment_id"] == comment_id
        if self.failure == "refetch":
            raise task.TaskControllerError("synthetic refetch failure")
        return copy.deepcopy(self.comments[0])


def publication_case(tmp_path, monkeypatch):
    monkeypatch.setattr(task, "git", lambda *args: BASE_SHA)
    prepared = task.prepare_task(
        repo=ROOT, state_dir=tmp_path, issue_number=901, task_id="GH-901",
        trusted_author=TRUSTED_AUTHOR, repository=REPOSITORY, base_sha=BASE_SHA,
        allowed_paths=["scripts/task.py"], forbidden_paths=[], profiles=["repository"],
        revision=1, nonce="0123456789abcdef",
    )
    assert prepared["authorization_publication"] is None
    draft = Path(prepared["authorization"]["draft_path"])
    transport = PublicationTransport(tmp_path)
    monkeypatch.setattr(task, "GhIssueAuthorizationTransport", lambda: transport)
    monkeypatch.setattr(task, "git", lambda *args: "")
    monkeypatch.setattr(task, "require_trusted_main_controller", lambda *args, **kwargs: None)
    args = argparse.Namespace(state_dir=tmp_path, issue_number=901, repo_root=ROOT)
    return args, transport, draft


@pytest.mark.parametrize("failure", [None, "lost_reply", "refetch"])
def test_publication_recovers_without_duplicate_post(tmp_path, monkeypatch, failure):
    args, transport, _ = publication_case(tmp_path, monkeypatch)
    transport.failure = failure
    if failure:
        with pytest.raises(task.TaskControllerError):
            task.command_authorize(args)
        pending = task.load_state(tmp_path, 901)
        assert pending["phase"] == "PREPARED"
        assert pending["authorization_publication"]["status"] == "pending"
        # Invoke the command again from persisted state, as after a restart.
        transport.failure = None
    assert task.command_authorize(args) == 0
    complete = task.load_state(tmp_path, 901)
    assert complete["phase"] == "AUTHORIZED"
    assert complete["authorization"]["comment_id"] == 7001
    assert complete["workflow"]["authority"]["comment_id"] == 7001
    assert complete["authorization_publication"]["status"] == "complete"
    assert len(transport.comments) == transport.posts == 1
    with pytest.raises(task.TaskControllerError, match="REQUIRES_PREPARED"):
        task.command_authorize(args)
    assert transport.posts == 1


def test_empty_recovery_lookup_never_reposts(tmp_path, monkeypatch):
    args, transport, _ = publication_case(tmp_path, monkeypatch)
    transport.failure = "lost_reply"
    with pytest.raises(task.TaskControllerError):
        task.command_authorize(args)
    before = task.state_path(tmp_path, 901).read_bytes()
    transport.hidden = True
    for _ in range(3):
        with pytest.raises(task.TaskControllerError, match="PUBLICATION_UNRESOLVED"):
            task.command_authorize(args)
        assert task.state_path(tmp_path, 901).read_bytes() == before
    assert transport.posts == 1


@pytest.mark.parametrize("change", ["duplicate", "author", "nonce", "revision", "workflow", "malformed", "incomplete", "known-id", "draft"])
def test_uncertain_publication_refuses_mismatched_observations(tmp_path, monkeypatch, change):
    args, transport, draft = publication_case(tmp_path, monkeypatch)
    transport.failure = "refetch" if change == "known-id" else "lost_reply"
    with pytest.raises(task.TaskControllerError):
        task.command_authorize(args)
    original = copy.deepcopy(transport.comments[0])
    if change == "duplicate":
        transport.comments.append({**original, "id": 7002})
    elif change == "author":
        transport.comments[0]["user"]["login"] = "untrusted"
    elif change in {"nonce", "revision"}:
        payload_value = extract_payload(original["body"])
        payload_value[change] = "different-nonce-012345" if change == "nonce" else 2
        payload_value.pop("payload_sha256")
        changed = build_payload(**payload_value)
        transport.comments[0]["body"] = render_authorization_comment(changed) + task._render_workflow_selection(task._normalize_workflow_selection("standard", None))
    elif change == "workflow":
        transport.comments[0]["body"] = original["body"].replace('"standard"', '"compatibility"')
    elif change == "malformed":
        transport.comments[0]["body"] = AUTHORIZATION_MARKER + " malformed"
    elif change == "incomplete":
        transport.comments = [None]
    elif change == "known-id":
        transport.comments[0]["id"] = 7002
    elif change == "draft":
        draft.write_text(draft.read_text() + "changed draft")
    before = task.state_path(tmp_path, 901).read_bytes()
    with pytest.raises((task.TaskControllerError, AuthorizationError)):
        task.command_authorize(args)
    assert task.state_path(tmp_path, 901).read_bytes() == before
    assert transport.posts == 1


def test_legacy_prepared_unknown_empty_lookup_does_not_publish(tmp_path, monkeypatch):
    args, transport, _ = publication_case(tmp_path, monkeypatch)
    state = task.load_state(tmp_path, 901)
    del state["authorization_publication"]
    task.atomic_write_json(task.state_path(tmp_path, 901), state)
    with pytest.raises(task.TaskControllerError, match="PUBLICATION_UNRESOLVED"):
        task.command_authorize(args)
    assert transport.posts == 0


def test_concurrent_retry_rereads_pending_publication_under_issue_lock(tmp_path, monkeypatch):
    args, transport, _ = publication_case(tmp_path, monkeypatch)
    transport.failure = "lost_reply"
    transport.entered, transport.release = threading.Event(), threading.Event()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(task.command_authorize, args)
        assert transport.entered.wait(5)
        second = workers.submit(task.command_authorize, args)
        transport.release.set()
        with pytest.raises(task.TaskControllerError, match="lost create reply"):
            first.result(timeout=10)
        assert second.result(timeout=10) == 0
    assert transport.posts == len(transport.comments) == 1
    assert task.load_state(tmp_path, 901)["phase"] == "AUTHORIZED"


def test_pending_persistence_failure_prevents_external_post(tmp_path, monkeypatch):
    args, transport, _ = publication_case(tmp_path, monkeypatch)
    def fail_write(*args):
        raise OSError("synthetic fsync failure")
    monkeypatch.setattr(task, "atomic_write_json", fail_write)
    with pytest.raises(OSError, match="fsync failure"):
        task.command_authorize(args)
    assert transport.posts == 0


@pytest.mark.parametrize("legacy", [False, True])
def test_existing_exact_comment_recovers_without_post(tmp_path, monkeypatch, legacy):
    args, transport, draft = publication_case(tmp_path, monkeypatch)
    if legacy:
        state = task.load_state(tmp_path, 901)
        del state["authorization_publication"]
        task.atomic_write_json(task.state_path(tmp_path, 901), state)
    transport.comments = [{"id": 7001, "body": draft.read_text(), "user": {"login": TRUSTED_AUTHOR}}]
    assert task.command_authorize(args) == 0
    assert transport.posts == 0
    state = task.load_state(tmp_path, 901)
    assert state["authorization"]["nonce"] == "0123456789abcdef"
    assert state["authorization"]["revision"] == 1
    assert state["phase"] == "AUTHORIZED"


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("body", [None, 42, {"unavailable": True}, "missing"])
def test_incomplete_comment_content_cannot_prove_absence_or_uniqueness(tmp_path, monkeypatch, pending, body):
    args, transport, _ = publication_case(tmp_path, monkeypatch)
    if pending:
        transport.failure = "lost_reply"
        with pytest.raises(task.TaskControllerError):
            task.command_authorize(args)
    incomplete = {"id": 7002, "user": {"login": TRUSTED_AUTHOR}}
    if body != "missing":
        incomplete["body"] = body
    transport.comments.append(incomplete)
    before = task.state_path(tmp_path, 901).read_bytes()
    with pytest.raises(task.TaskControllerError, match="ISSUE_COMMENTS_RESPONSE_INVALID"):
        task.command_authorize(args)
    assert task.state_path(tmp_path, 901).read_bytes() == before
    assert transport.posts == (1 if pending else 0)
