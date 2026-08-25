from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from lib.qualification_profiles import (
    QualificationProfileError,
    required_checks_for_profiles,
)

AUTHORIZATION_MARKER = "<!-- nutrition-task-authorization:v1 -->"
SCHEMA_VERSION = 1

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
)
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{16,128}$")

IOS_NATIVE_PROFILE = "ios-native"

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
    "scripts/ios-native-qualification.sh",
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

    def to_dict(self) -> dict[str, Any]:
        return {
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

        if item.startswith("/") or "\\" in item:
            raise AuthorizationError(
                "AUTHORIZATION_PATH_INVALID",
                f"{field} path must be repository-relative POSIX syntax: {item}",
            )

        pieces = item.split("/")

        if any(piece in {"", ".", ".."} for piece in pieces):
            raise AuthorizationError(
                "AUTHORIZATION_PATH_INVALID",
                f"{field} path contains an invalid segment: {item}",
            )

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

    if core["schema_version"] != SCHEMA_VERSION:
        raise AuthorizationError(
            "AUTHORIZATION_SCHEMA_UNSUPPORTED",
            (
                "schema_version must equal "
                f"{SCHEMA_VERSION}"
            ),
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
    )

    forbidden_paths = _normalize_paths(
        core["forbidden_paths"],
        field="forbidden_paths",
        allow_empty=True,
    )

    profiles = _normalize_profiles(
        core["profiles"]
    )

    return {
        "schema_version": SCHEMA_VERSION,
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
) -> dict[str, Any]:
    core = _normalize_core(
        {
            "schema_version": SCHEMA_VERSION,
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

    return (
        f"{AUTHORIZATION_MARKER}\n"
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
    if body.count(AUTHORIZATION_MARKER) != 1:
        raise AuthorizationError(
            "AUTHORIZATION_MARKER_INVALID",
            "authorization marker must occur exactly once",
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
        and AUTHORIZATION_MARKER
        in comment["body"]
    ]

    if not marked:
        raise AuthorizationError(
            "AUTHORIZATION_MISSING",
            "no authorization comment was found",
        )

    if len(marked) != 1:
        raise AuthorizationError(
            "AUTHORIZATION_AMBIGUOUS",
            (
                "expected exactly one authorization "
                f"comment; found {len(marked)}"
            ),
        )

    return resolve_comment(
        marked[0],
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
    return (
        path == pattern
        or fnmatch.fnmatchcase(
            path,
            pattern,
        )
    )


def required_profiles_for_paths(
    paths: Iterable[str],
) -> set[str]:
    observed = tuple(paths)

    if any(
        _path_matches(path, pattern)
        for path in observed
        for pattern in IOS_NATIVE_PATH_PATTERNS
    ):
        return {IOS_NATIVE_PROFILE}

    return set()


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
            _path_matches(path, pattern)
            for pattern
            in authorization.forbidden_paths
        ):
            raise AuthorizationError(
                "SCOPE_FORBIDDEN",
                path,
            )

        if not any(
            _path_matches(path, pattern)
            for pattern
            in authorization.allowed_paths
        ):
            raise AuthorizationError(
                "SCOPE_UNEXPECTED",
                path,
            )

    required_profiles = (
        required_profiles_for_paths(
            overlay
        )
    )

    missing_profiles = sorted(
        required_profiles
        - set(authorization.profiles)
    )

    if missing_profiles:
        raise AuthorizationError(
            "QUALIFICATION_PROFILE_REQUIRED",
            (
                "changed paths require qualification "
                "profile(s): "
                + ", ".join(missing_profiles)
            ),
        )

    return overlay
