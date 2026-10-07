from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from lib import path_scope
from lib.qualification_profiles import (
    QualificationProfileError,
    required_checks_for_profiles,
)

AUTHORIZATION_MARKER_V1 = "<!-- nutrition-task-authorization:v1 -->"
AUTHORIZATION_MARKER_V2 = "<!-- nutrition-task-authorization:v2 -->"
AUTHORIZATION_MARKERS = (AUTHORIZATION_MARKER_V1, AUTHORIZATION_MARKER_V2)
AUTHORIZATION_MARKER = AUTHORIZATION_MARKER_V2
SCHEMA_VERSION = path_scope.V2

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
)
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{16,128}$")

IOS_NATIVE_PROFILE = "ios-native"
BACKEND_PROFILE = "backend"
MOBILE_PROFILE = "mobile"
POSTGRESQL_PROFILE = "postgresql"

BACKEND_PATH_ROOT = "apps/backend"
MOBILE_PATH_ROOT = "apps/mobile"

POSTGRESQL_PATH_ROOTS = (
    "apps/backend/app/control_migrations",
    "apps/backend/app/db",
    "apps/backend/app/migrations",
    "apps/backend/app/models",
    "apps/backend/app/operators",
    "apps/backend/app/repositories",
)
POSTGRESQL_TEST_ROOT = "apps/backend/tests"

POSTGRESQL_EXACT_PATHS = frozenset(
    {
        "apps/backend/.env.example",
        "apps/backend/alembic-control.ini",
        "apps/backend/alembic.ini",
        "apps/backend/app/core/config.py",
        "apps/backend/app/core/database.py",
        "apps/backend/app/core/database_identity.py",
        "apps/backend/app/dependencies/database.py",
        "apps/backend/tests/postgres_test_support.py",
    }
)

IOS_NATIVE_PATH_PATTERNS = (
    ".github/workflows/ios-native.yml",
    ".github/workflows/trusted-qualification-execute.yml",
    ".nvmrc",
    "apps/mobile/app.json",
    "apps/mobile/package.json",
    "apps/mobile/package-lock.json",
    "apps/mobile/plugins/**",
    "apps/mobile/modules/**/expo-module.config.json",
    "apps/mobile/modules/**/ios/**",
    "apps/mobile/modules/**/ios-tests/**",
    "scripts/ios-native-qualification.sh",
    "scripts/ios-native-cache-key.sh",
    "scripts/lib/qualification_profiles.py",
    "scripts/lib/task_authorization.py",
)

CORE_FIELDS = {
    "schema_version",
    "task_id",
    "issue_number",
    "repository",
    "base_sha",
    "allowed_paths",
    "forbidden_paths",
    "profiles",
    "revision",
    "nonce",
}

PAYLOAD_FIELDS = CORE_FIELDS | {"payload_sha256"}

JSON_BLOCK_PATTERN = re.compile(
    r"```json[ \t]*\n(?P<body>\{.*?\})[ \t]*\n```",
    re.DOTALL,
)


class AuthorizationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class ResolvedAuthorization:
    task_id: str
    issue_number: int
    repository: str
    base_sha: str
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    profiles: tuple[str, ...]
    revision: int
    nonce: str
    comment_id: int
    author_login: str
    payload_sha256: str
    identity_sha256: str
    schema_version: int = path_scope.V1

    def to_dict(self) -> dict[str, Any]:
        value = {
            "task_id": self.task_id,
            "issue_number": self.issue_number,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "allowed_paths": list(self.allowed_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "profiles": list(self.profiles),
            "revision": self.revision,
            "nonce": self.nonce,
            "comment_id": self.comment_id,
            "author_login": self.author_login,
            "payload_sha256": self.payload_sha256,
            "identity_sha256": self.identity_sha256,
        }
        if self.schema_version == path_scope.V2:
            value["schema_version"] = path_scope.V2
        elif self.schema_version != path_scope.V1:
            raise ValueError("unsupported authorization schema version")
        return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def _require_int(
    value: Any,
    *,
    field: str,
    minimum: int,
) -> int:
    if type(value) is not int or value < minimum:
        raise AuthorizationError(
            "AUTHORIZATION_FIELD_INVALID",
            f"{field} must be an integer >= {minimum}",
        )

    return value


def _normalize_paths(
    value: Any,
    *,
    field: str,
    allow_empty: bool,
    schema_version: int,
) -> list[str]:
    if not isinstance(value, list):
        raise AuthorizationError(
            "AUTHORIZATION_FIELD_INVALID",
            f"{field} must be a list",
        )

    normalized: list[str] = []

    for item in value:
        if not isinstance(item, str) or not item:
            raise AuthorizationError(
                "AUTHORIZATION_PATH_INVALID",
                f"{field} contains a non-string or empty path",
            )

        try:
            path_scope.validate_pattern(item, schema_version)
        except path_scope.PathPatternError as exc:
            raise AuthorizationError(
                "AUTHORIZATION_PATH_INVALID",
                f"{field} path is invalid: {item}: {exc}",
            ) from exc

        normalized.append(item)

    if not allow_empty and not normalized:
        raise AuthorizationError(
            "AUTHORIZATION_PATH_INVALID",
            f"{field} must contain at least one path",
        )

    if len(set(normalized)) != len(normalized):
        raise AuthorizationError(
            "AUTHORIZATION_PATH_DUPLICATE",
            f"{field} contains duplicate paths",
        )

    return sorted(normalized)


def _normalize_profiles(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise AuthorizationError(
            "AUTHORIZATION_PROFILE_INVALID",
            "profiles must be a non-empty list",
        )

    profiles: list[str] = []

    for item in value:
        if not isinstance(item, str) or not item:
            raise AuthorizationError(
                "AUTHORIZATION_PROFILE_INVALID",
                "profiles must contain non-empty strings",
            )

        profiles.append(item)

    if len(set(profiles)) != len(profiles):
        raise AuthorizationError(
            "AUTHORIZATION_PROFILE_DUPLICATE",
            "profiles contain duplicates",
        )

    try:
        required_checks_for_profiles(profiles)
    except QualificationProfileError as exc:
        raise AuthorizationError(
            exc.code,
            str(exc),
        ) from exc

    return profiles


def _normalize_core(
    core: dict[str, Any],
) -> dict[str, Any]:
    if set(core) != CORE_FIELDS:
        missing = sorted(CORE_FIELDS - set(core))
        extra = sorted(set(core) - CORE_FIELDS)

        raise AuthorizationError(
            "AUTHORIZATION_FIELDS_INVALID",
            f"missing={missing} extra={extra}",
        )

    schema_version = core["schema_version"]
    if type(schema_version) is not int or schema_version not in path_scope.SUPPORTED_VERSIONS:
        raise AuthorizationError(
            "AUTHORIZATION_SCHEMA_UNSUPPORTED",
            "schema_version must equal 1 or 2",
        )

    task_id = core["task_id"]

    if (
        not isinstance(task_id, str)
        or not TASK_ID_PATTERN.fullmatch(task_id)
    ):
        raise AuthorizationError(
            "AUTHORIZATION_TASK_INVALID",
            "task_id is invalid",
        )

    issue_number = _require_int(
        core["issue_number"],
        field="issue_number",
        minimum=1,
    )

    repository = core["repository"]

    if (
        not isinstance(repository, str)
        or not REPOSITORY_PATTERN.fullmatch(repository)
    ):
        raise AuthorizationError(
            "AUTHORIZATION_REPOSITORY_INVALID",
            "repository must use owner/name syntax",
        )

    base_sha = core["base_sha"]

    if (
        not isinstance(base_sha, str)
        or not SHA_PATTERN.fullmatch(base_sha)
    ):
        raise AuthorizationError(
            "AUTHORIZATION_BASE_INVALID",
            "base_sha must be an exact lowercase 40-character SHA",
        )

    revision = _require_int(
        core["revision"],
        field="revision",
        minimum=1,
    )

    nonce = core["nonce"]

    if (
        not isinstance(nonce, str)
        or not NONCE_PATTERN.fullmatch(nonce)
    ):
        raise AuthorizationError(
            "AUTHORIZATION_NONCE_INVALID",
            (
                "nonce must be 16-128 characters using "
                "letters, digits, dot, underscore, or hyphen"
            ),
        )

    allowed_paths = _normalize_paths(
        core["allowed_paths"],
        field="allowed_paths",
        allow_empty=False,
        schema_version=schema_version,
    )

    forbidden_paths = _normalize_paths(
        core["forbidden_paths"],
        field="forbidden_paths",
        allow_empty=True,
        schema_version=schema_version,
    )

    profiles = _normalize_profiles(
        core["profiles"]
    )

    return {
        "schema_version": schema_version,
        "task_id": task_id,
        "issue_number": issue_number,
        "repository": repository,
        "base_sha": base_sha,
        "allowed_paths": allowed_paths,
        "forbidden_paths": forbidden_paths,
        "profiles": profiles,
        "revision": revision,
        "nonce": nonce,
    }


def payload_digest(
    core: dict[str, Any],
) -> str:
    normalized = _normalize_core(core)
    return sha256_text(
        canonical_json(normalized)
    )


def build_payload(
    *,
    task_id: str,
    issue_number: int,
    repository: str,
    base_sha: str,
    allowed_paths: Iterable[str],
    forbidden_paths: Iterable[str],
    profiles: Iterable[str],
    revision: int,
    nonce: str,
    schema_version: int = SCHEMA_VERSION,
) -> dict[str, Any]:
    core = _normalize_core(
        {
            "schema_version": schema_version,
            "task_id": task_id,
            "issue_number": issue_number,
            "repository": repository,
            "base_sha": base_sha,
            "allowed_paths": list(allowed_paths),
            "forbidden_paths": list(forbidden_paths),
            "profiles": list(profiles),
            "revision": revision,
            "nonce": nonce,
        }
    )

    return {
        **core,
        "payload_sha256": payload_digest(core),
    }


def validate_payload(
    payload: dict[str, Any],
    *,
    expected_repository: str | None = None,
    expected_issue_number: int | None = None,
    expected_task_id: str | None = None,
    expected_revision: int | None = None,
    expected_payload_sha256: str | None = None,
) -> dict[str, Any]:
    if set(payload) != PAYLOAD_FIELDS:
        missing = sorted(PAYLOAD_FIELDS - set(payload))
        extra = sorted(set(payload) - PAYLOAD_FIELDS)

        raise AuthorizationError(
            "AUTHORIZATION_FIELDS_INVALID",
            f"missing={missing} extra={extra}",
        )

    core = {
        key: payload[key]
        for key in CORE_FIELDS
    }

    normalized = _normalize_core(core)

    if core != normalized:
        raise AuthorizationError(
            "AUTHORIZATION_NOT_CANONICAL",
            (
                "authorization arrays and values must use "
                "their canonical normalized representation"
            ),
        )

    observed_digest = payload["payload_sha256"]

    if (
        not isinstance(observed_digest, str)
        or not DIGEST_PATTERN.fullmatch(
            observed_digest
        )
    ):
        raise AuthorizationError(
            "AUTHORIZATION_DIGEST_INVALID",
            "payload_sha256 is invalid",
        )

    expected_digest = payload_digest(normalized)

    if observed_digest != expected_digest:
        raise AuthorizationError(
            "AUTHORIZATION_DIGEST_MISMATCH",
            (
                f"recorded={observed_digest} "
                f"computed={expected_digest}"
            ),
        )

    if (
        expected_payload_sha256 is not None
        and observed_digest
        != expected_payload_sha256
    ):
        raise AuthorizationError(
            "AUTHORIZATION_DIGEST_DRIFT",
            (
                f"expected={expected_payload_sha256} "
                f"observed={observed_digest}"
            ),
        )

    expectations = (
        (
            "repository",
            expected_repository,
            normalized["repository"],
        ),
        (
            "issue_number",
            expected_issue_number,
            normalized["issue_number"],
        ),
        (
            "task_id",
            expected_task_id,
            normalized["task_id"],
        ),
        (
            "revision",
            expected_revision,
            normalized["revision"],
        ),
    )

    for field, expected, observed in expectations:
        if expected is not None and observed != expected:
            raise AuthorizationError(
                "AUTHORIZATION_IDENTITY_MISMATCH",
                (
                    f"{field}: expected={expected} "
                    f"observed={observed}"
                ),
            )

    return {
        **normalized,
        "payload_sha256": observed_digest,
    }


def render_authorization_comment(
    payload: dict[str, Any],
) -> str:
    validated = validate_payload(payload)

    marker = {
        path_scope.V1: AUTHORIZATION_MARKER_V1,
        path_scope.V2: AUTHORIZATION_MARKER_V2,
    }[validated["schema_version"]]
    return (
        f"{marker}\n"
        "```json\n"
        + json.dumps(
            validated,
            indent=2,
            sort_keys=True,
        )
        + "\n```\n"
    )


def extract_payload(
    body: str,
) -> dict[str, Any]:
    present = [marker for marker in AUTHORIZATION_MARKERS if marker in body]
    if len(present) != 1 or body.count(present[0]) != 1:
        raise AuthorizationError(
            "AUTHORIZATION_MARKER_INVALID",
            "exactly one recognized authorization marker must occur once",
        )

    matches = list(
        JSON_BLOCK_PATTERN.finditer(body)
    )

    if len(matches) != 1:
        raise AuthorizationError(
            "AUTHORIZATION_JSON_INVALID",
            "authorization comment must contain exactly one JSON block",
        )

    try:
        payload = json.loads(
            matches[0].group("body")
        )
    except json.JSONDecodeError as exc:
        raise AuthorizationError(
            "AUTHORIZATION_JSON_INVALID",
            str(exc),
        ) from exc

    if not isinstance(payload, dict):
        raise AuthorizationError(
            "AUTHORIZATION_JSON_INVALID",
            "authorization JSON must be an object",
        )

    marker_version = (path_scope.V1 if present[0] == AUTHORIZATION_MARKER_V1
                      else path_scope.V2)
    if payload.get("schema_version") != marker_version or type(payload.get("schema_version")) is not int:
        raise AuthorizationError(
            "AUTHORIZATION_MARKER_SCHEMA_MISMATCH",
            "authorization marker and schema_version must select the same matcher",
        )

    return payload


def resolve_comment(
    comment: dict[str, Any],
    *,
    trusted_author: str,
    expected_repository: str,
    expected_issue_number: int,
    expected_task_id: str,
    expected_revision: int,
    expected_comment_id: int | None = None,
    expected_payload_sha256: str | None = None,
) -> ResolvedAuthorization:
    comment_id = comment.get("id")

    if type(comment_id) is not int or comment_id < 1:
        raise AuthorizationError(
            "AUTHORIZATION_COMMENT_ID_INVALID",
            "comment id is invalid",
        )

    if (
        expected_comment_id is not None
        and comment_id != expected_comment_id
    ):
        raise AuthorizationError(
            "AUTHORIZATION_COMMENT_ID_MISMATCH",
            (
                f"expected={expected_comment_id} "
                f"observed={comment_id}"
            ),
        )

    user = comment.get("user")

    if not isinstance(user, dict):
        raise AuthorizationError(
            "AUTHORIZATION_AUTHOR_INVALID",
            "comment user is missing",
        )

    author = user.get("login")

    if author != trusted_author:
        raise AuthorizationError(
            "AUTHORIZATION_AUTHOR_UNTRUSTED",
            (
                f"expected={trusted_author} "
                f"observed={author}"
            ),
        )

    body = comment.get("body")

    if not isinstance(body, str):
        raise AuthorizationError(
            "AUTHORIZATION_BODY_INVALID",
            "comment body is missing",
        )

    payload = validate_payload(
        extract_payload(body),
        expected_repository=expected_repository,
        expected_issue_number=expected_issue_number,
        expected_task_id=expected_task_id,
        expected_revision=expected_revision,
        expected_payload_sha256=expected_payload_sha256,
    )

    identity = {
        "comment_id": comment_id,
        "author_login": author,
        "payload_sha256": payload[
            "payload_sha256"
        ],
    }

    return ResolvedAuthorization(
        task_id=payload["task_id"],
        issue_number=payload["issue_number"],
        repository=payload["repository"],
        base_sha=payload["base_sha"],
        allowed_paths=tuple(
            payload["allowed_paths"]
        ),
        forbidden_paths=tuple(
            payload["forbidden_paths"]
        ),
        profiles=tuple(
            payload["profiles"]
        ),
        revision=payload["revision"],
        nonce=payload["nonce"],
        comment_id=comment_id,
        author_login=author,
        payload_sha256=payload[
            "payload_sha256"
        ],
        identity_sha256=sha256_text(
            canonical_json(identity)
        ),
        schema_version=payload["schema_version"],
    )


def resolve_comments(
    comments: Iterable[dict[str, Any]],
    *,
    trusted_author: str,
    expected_repository: str,
    expected_issue_number: int,
    expected_task_id: str,
    expected_revision: int,
) -> ResolvedAuthorization:
    marked = [
        comment
        for comment in comments
        if isinstance(comment.get("body"), str)
        and any(marker in comment["body"] for marker in AUTHORIZATION_MARKERS)
    ]

    if not marked:
        raise AuthorizationError(
            "AUTHORIZATION_MISSING",
            "no authorization comment was found",
        )

    matching: list[dict[str, Any]] = []

    for comment in marked:
        body = comment.get("body")
        assert isinstance(body, str)

        try:
            payload = extract_payload(body)
        except AuthorizationError:
            continue

        if (
            payload.get("repository")
            == expected_repository
            and payload.get("issue_number")
            == expected_issue_number
            and payload.get("task_id")
            == expected_task_id
            and payload.get("revision")
            == expected_revision
        ):
            matching.append(comment)

    if not matching:
        raise AuthorizationError(
            "AUTHORIZATION_MISSING",
            (
                "no authorization comment matched "
                f"task={expected_task_id} "
                f"revision={expected_revision}"
            ),
        )

    if len(matching) != 1:
        raise AuthorizationError(
            "AUTHORIZATION_AMBIGUOUS",
            (
                "expected exactly one authorization "
                "comment matching "
                f"task={expected_task_id} "
                f"revision={expected_revision}; "
                f"found {len(matching)}"
            ),
        )

    return resolve_comment(
        matching[0],
        trusted_author=trusted_author,
        expected_repository=expected_repository,
        expected_issue_number=expected_issue_number,
        expected_task_id=expected_task_id,
        expected_revision=expected_revision,
    )


def _git(
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

    if completed.returncode:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
        )

        raise AuthorizationError(
            "GIT_AUTHORITY_ERROR",
            detail,
        )

    return completed.stdout.strip()


def _path_matches(
    path: str,
    pattern: str,
) -> bool:
    return path_scope.matches(path, pattern, path_scope.V1)


def _path_is_within_component_tree(
    path: str,
    root: str,
) -> bool:
    """Match profile roots by path component without changing scope globs."""
    return path == root or path.startswith(f"{root}/")


from lib.tooling_qualification import selected as tooling_selected


def required_profiles_for_paths(
    paths: Iterable[str],
) -> set[str]:
    observed = tuple(paths)
    required: set[str] = set()

    if tooling_selected(observed):
        required.add("repository")

    if any(
        _path_is_within_component_tree(
            path,
            BACKEND_PATH_ROOT,
        )
        for path in observed
    ):
        required.add(BACKEND_PROFILE)

    if any(
        _path_is_within_component_tree(
            path,
            MOBILE_PATH_ROOT,
        )
        for path in observed
    ):
        required.add(MOBILE_PROFILE)

    if any(
        path in POSTGRESQL_EXACT_PATHS
        or any(
            _path_is_within_component_tree(path, root)
            for root in POSTGRESQL_PATH_ROOTS
        )
        or (
            _path_is_within_component_tree(
                path,
                POSTGRESQL_TEST_ROOT,
            )
            and path.rsplit("/", maxsplit=1)[-1].endswith(
                "_postgres.py"
            )
        )
        for path in observed
    ):
        required.add(POSTGRESQL_PROFILE)

    if any(
        _path_matches(path, pattern)
        for path in observed
        for pattern in IOS_NATIVE_PATH_PATTERNS
    ):
        required.add(IOS_NATIVE_PROFILE)

    return required


def changed_paths(
    repo: Path,
    *,
    base_sha: str,
    candidate_sha: str,
) -> list[str]:
    lines = _git(
        repo,
        "diff",
        "--name-status",
        "-M",
        f"{base_sha}..{candidate_sha}",
    ).splitlines()

    paths: set[str] = set()

    for line in lines:
        if not line:
            continue

        pieces = line.split("\t")
        status = pieces[0]

        if status.startswith(("R", "C")):
            if len(pieces) != 3:
                raise AuthorizationError(
                    "SCOPE_DIFF_INVALID",
                    f"unexpected rename/copy record: {line}",
                )

            paths.add(pieces[1])
            paths.add(pieces[2])
            continue

        if len(pieces) != 2:
            raise AuthorizationError(
                "SCOPE_DIFF_INVALID",
                f"unexpected diff record: {line}",
            )

        paths.add(pieces[1])

    return sorted(paths)


def _introduced_commits(
    repo: Path,
    *,
    base_sha: str,
    candidate_sha: str,
) -> list[tuple[str, str]]:
    lines = _git(
        repo,
        "rev-list",
        "--reverse",
        "--topo-order",
        "--parents",
        f"{base_sha}..{candidate_sha}",
    ).splitlines()

    commits: list[tuple[str, str]] = []

    for line in lines:
        pieces = line.split()

        if len(pieces) > 2:
            raise AuthorizationError(
                "SCOPE_MERGE_UNSUPPORTED",
                pieces[0],
            )

        if len(pieces) != 2:
            raise AuthorizationError(
                "SCOPE_HISTORY_INVALID",
                line,
            )

        commits.append((pieces[0], pieces[1]))

    return commits


def validate_candidate_scope(
    repo: Path,
    authorization: ResolvedAuthorization,
    *,
    candidate_sha: str,
    observed_main_sha: str | None = None,
) -> list[str]:
    if not SHA_PATTERN.fullmatch(candidate_sha):
        raise AuthorizationError(
            "CANDIDATE_SHA_INVALID",
            "candidate SHA must be an exact lowercase 40-character SHA",
        )

    _git(
        repo,
        "cat-file",
        "-e",
        f"{candidate_sha}^{{commit}}",
    )

    main_sha = (
        observed_main_sha
        if observed_main_sha is not None
        else _git(
            repo,
            "rev-parse",
            "--verify",
            "refs/remotes/origin/main",
        )
    )

    if main_sha != authorization.base_sha:
        raise AuthorizationError(
            "BASE_AUTHORITY_STALE",
            (
                f"authorization={authorization.base_sha} "
                f"origin_main={main_sha}"
            ),
        )

    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "merge-base",
            "--is-ancestor",
            authorization.base_sha,
            candidate_sha,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    if ancestor.returncode:
        raise AuthorizationError(
            "BASE_NOT_ANCESTOR",
            (
                f"{authorization.base_sha} is not "
                f"an ancestor of {candidate_sha}"
            ),
        )

    overlay = changed_paths(
        repo,
        base_sha=authorization.base_sha,
        candidate_sha=candidate_sha,
    )

    for path in overlay:
        if any(
            path_scope.matches(path, pattern, authorization.schema_version)
            for pattern
            in authorization.forbidden_paths
        ):
            raise AuthorizationError(
                "SCOPE_FORBIDDEN",
                path,
            )

        if not any(
            path_scope.matches(path, pattern, authorization.schema_version)
            for pattern
            in authorization.allowed_paths
        ):
            raise AuthorizationError(
                "SCOPE_UNEXPECTED",
                path,
            )

    # A planning commit may change only its capsule; authorize floors for the
    # exact planned scope as well as the paths already present in the overlay.
    required_profiles = required_profiles_for_paths(
        (*overlay, *authorization.allowed_paths)
    )

    missing_profiles = sorted(
        required_profiles
        - set(authorization.profiles)
    )

    if missing_profiles:
        raise AuthorizationError(
            "QUALIFICATION_PROFILE_REQUIRED",
            (
                "planned or changed paths require qualification "
                "profile(s): "
                + ", ".join(missing_profiles)
            ),
        )

    for commit_sha, parent_sha in _introduced_commits(
        repo,
        base_sha=authorization.base_sha,
        candidate_sha=candidate_sha,
    ):
        commit_paths = changed_paths(
            repo,
            base_sha=parent_sha,
            candidate_sha=commit_sha,
        )

        for path in commit_paths:
            if any(
                path_scope.matches(path, pattern, authorization.schema_version)
                for pattern
                in authorization.forbidden_paths
            ):
                raise AuthorizationError(
                    "SCOPE_FORBIDDEN",
                    f"{path} in commit {commit_sha}",
                )

            if not any(
                path_scope.matches(path, pattern, authorization.schema_version)
                for pattern
                in authorization.allowed_paths
            ):
                raise AuthorizationError(
                    "SCOPE_UNEXPECTED",
                    f"{path} in commit {commit_sha}",
                )

    return overlay
