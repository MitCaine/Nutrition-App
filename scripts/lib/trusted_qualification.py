from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Protocol

SCRIPT_ROOT = Path(__file__).resolve().parents[1]

if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(SCRIPT_ROOT),
    )

from lib.qualification_profiles import (  # noqa: E402
    required_checks_for_profiles,
)
from lib.task_authorization import (  # noqa: E402
    AuthorizationError,
    ResolvedAuthorization,
    canonical_json,
    resolve_comment,
    validate_candidate_scope,
)

CHECK_NAME = "Main qualification"


class TrustedQualificationError(RuntimeError):
    pass


class CheckPublisher(Protocol):
    def publish(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        ...


def _digest(
    value: dict[str, Any],
) -> str:
    return hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def build_plan(
    repo: Path,
    authorization: ResolvedAuthorization,
    *,
    candidate_sha: str,
    candidate_ref: str,
) -> dict[str, Any]:
    if not isinstance(candidate_ref, str) or not candidate_ref:
        raise TrustedQualificationError(
            "candidate_ref is required"
        )

    overlay = validate_candidate_scope(
        repo,
        authorization,
        candidate_sha=candidate_sha,
    )

    profiles = list(
        authorization.profiles
    )

    checks = required_checks_for_profiles(
        profiles
    )

    core: dict[str, Any] = {
        "schema_version": 1,
        "task_id": authorization.task_id,
        "issue_number": authorization.issue_number,
        "repository": authorization.repository,
        "authorization_comment_id": (
            authorization.comment_id
        ),
        "authorization_author": (
            authorization.author_login
        ),
        "authorization_payload_sha256": (
            authorization.payload_sha256
        ),
        "authorization_identity_sha256": (
            authorization.identity_sha256
        ),
        "authorization_revision": (
            authorization.revision
        ),
        "authorization_nonce": (
            authorization.nonce
        ),
        "base_sha": authorization.base_sha,
        "candidate_sha": candidate_sha,
        "candidate_ref": candidate_ref,
        "profiles": profiles,
        "profile_checks": {
            profile: list(names)
            for profile, names in checks.items()
        },
        "changed_paths": overlay,
    }

    return {
        **core,
        "plan_sha256": _digest(core),
    }


def revalidate_plan_authorization(
    plan: dict[str, Any],
    comment: dict[str, Any],
    *,
    trusted_author: str,
) -> ResolvedAuthorization:
    authorization = resolve_comment(
        comment,
        trusted_author=trusted_author,
        expected_repository=plan[
            "repository"
        ],
        expected_issue_number=plan[
            "issue_number"
        ],
        expected_task_id=plan["task_id"],
        expected_revision=plan[
            "authorization_revision"
        ],
        expected_comment_id=plan[
            "authorization_comment_id"
        ],
        expected_payload_sha256=plan[
            "authorization_payload_sha256"
        ],
    )

    expected = {
        "authorization_author": (
            authorization.author_login
        ),
        "authorization_identity_sha256": (
            authorization.identity_sha256
        ),
        "authorization_nonce": (
            authorization.nonce
        ),
        "base_sha": authorization.base_sha,
        "profiles": list(
            authorization.profiles
        ),
    }

    for key, value in expected.items():
        if plan.get(key) != value:
            raise TrustedQualificationError(
                (
                    "AUTHORIZATION_PLAN_DRIFT: "
                    f"{key}: expected={value} "
                    f"observed={plan.get(key)}"
                )
            )

    core = {
        key: value
        for key, value in plan.items()
        if key != "plan_sha256"
    }

    if plan.get("plan_sha256") != _digest(core):
        raise TrustedQualificationError(
            "PLAN_DIGEST_MISMATCH"
        )

    return authorization


def normalize_profile_results(
    plan: dict[str, Any],
    results: Mapping[str, str],
) -> dict[str, str]:
    selected = list(
        plan.get("profiles") or []
    )

    if set(results) != set(selected):
        raise TrustedQualificationError(
            (
                "PROFILE_RESULT_SET_MISMATCH: "
                f"selected={selected} "
                f"observed={sorted(results)}"
            )
        )

    normalized: dict[str, str] = {}

    for profile in selected:
        result = results[profile]

        if result not in {
            "success",
            "failure",
            "cancelled",
            "timed_out",
        }:
            raise TrustedQualificationError(
                (
                    "PROFILE_RESULT_INVALID: "
                    f"{profile}={result}"
                )
            )

        normalized[profile] = result

    return normalized


def build_check_request(
    plan: dict[str, Any],
    *,
    workflow_run_id: str,
    profile_results: Mapping[str, str],
) -> dict[str, Any]:
    if not workflow_run_id:
        raise TrustedQualificationError(
            "workflow_run_id is required"
        )

    results = normalize_profile_results(
        plan,
        profile_results,
    )

    success = all(
        value == "success"
        for value in results.values()
    )

    conclusion = (
        "success"
        if success
        else "failure"
    )

    summary = {
        "task_id": plan["task_id"],
        "issue_number": plan["issue_number"],
        "candidate_sha": plan[
            "candidate_sha"
        ],
        "authorization_comment_id": plan[
            "authorization_comment_id"
        ],
        "authorization_payload_sha256": plan[
            "authorization_payload_sha256"
        ],
        "authorization_identity_sha256": plan[
            "authorization_identity_sha256"
        ],
        "plan_sha256": plan["plan_sha256"],
        "workflow_run_id": workflow_run_id,
        "profile_results": results,
    }

    return {
        "name": CHECK_NAME,
        "head_sha": plan["candidate_sha"],
        "status": "completed",
        "conclusion": conclusion,
        "external_id": (
            "nutrition-task:"
            f"{plan['issue_number']}:"
            f"{plan['authorization_identity_sha256']}:"
            f"{plan['candidate_sha']}"
        ),
        "details_url": (
            "https://github.com/"
            f"{plan['repository']}/actions/runs/"
            f"{workflow_run_id}"
        ),
        "output": {
            "title": (
                "Trusted qualification "
                + (
                    "passed"
                    if success
                    else "failed"
                )
            ),
            "summary": (
                "Candidate-independent authorization "
                "and trusted qualification result."
            ),
            "text": (
                "```json\n"
                + json.dumps(
                    summary,
                    indent=2,
                    sort_keys=True,
                )
                + "\n```"
            ),
        },
    }


class HttpCheckPublisher:
    def __init__(
        self,
        *,
        repository: str,
        token: str,
    ) -> None:
        if not token:
            raise TrustedQualificationError(
                "dedicated App token is required"
            )

        self.repository = repository
        self.token = token

    def publish(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        url = (
            "https://api.github.com/repos/"
            f"{self.repository}/check-runs"
        )

        body = json.dumps(
            request
        ).encode("utf-8")

        http_request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": (
                    "application/vnd.github+json"
                ),
                "Authorization": (
                    f"Bearer {self.token}"
                ),
                "Content-Type": (
                    "application/json"
                ),
                "X-GitHub-Api-Version": (
                    "2022-11-28"
                ),
                "User-Agent": (
                    "nutrition-app-trusted-qualification"
                ),
            },
        )

        try:
            with urllib.request.urlopen(
                http_request,
                timeout=30,
            ) as response:
                document = json.loads(
                    response.read().decode(
                        "utf-8"
                    )
                )
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ) as exc:
            raise TrustedQualificationError(
                (
                    "CHECK_PUBLISH_FAILED: "
                    f"{exc}"
                )
            ) from exc

        if not isinstance(document, dict):
            raise TrustedQualificationError(
                "CHECK_PUBLISH_RESPONSE_INVALID"
            )

        return document


def publish_check(
    publisher: CheckPublisher,
    request: dict[str, Any],
    *,
    expected_app_id: int,
) -> dict[str, Any]:
    if (
        type(expected_app_id) is not int
        or expected_app_id < 1
    ):
        raise TrustedQualificationError(
            "CHECK_APP_ID_INVALID"
        )

    response = publisher.publish(
        request
    )

    if response.get("name") != CHECK_NAME:
        raise TrustedQualificationError(
            "CHECK_RESPONSE_NAME_MISMATCH"
        )

    if (
        response.get("head_sha")
        != request["head_sha"]
    ):
        raise TrustedQualificationError(
            "CHECK_RESPONSE_SHA_MISMATCH"
        )

    if (
        response.get("external_id")
        != request.get("external_id")
    ):
        raise TrustedQualificationError(
            "CHECK_RESPONSE_EXTERNAL_ID_MISMATCH"
        )

    if (
        response.get("conclusion")
        != request.get("conclusion")
    ):
        raise TrustedQualificationError(
            "CHECK_RESPONSE_CONCLUSION_MISMATCH"
        )

    app = response.get("app")

    if not isinstance(app, dict):
        raise TrustedQualificationError(
            "CHECK_RESPONSE_APP_MISSING"
        )

    if app.get("id") != expected_app_id:
        raise TrustedQualificationError(
            (
                "CHECK_RESPONSE_APP_MISMATCH: "
                f"expected={expected_app_id} "
                f"observed={app.get('id')}"
            )
        )

    return response


def resolved_authorization_from_comment(
    comment: dict[str, Any],
    *,
    trusted_author: str,
    repository: str,
    issue_number: int,
    task_id: str,
    revision: int,
    comment_id: int,
    payload_sha256: str,
) -> ResolvedAuthorization:
    try:
        return resolve_comment(
            comment,
            trusted_author=trusted_author,
            expected_repository=repository,
            expected_issue_number=issue_number,
            expected_task_id=task_id,
            expected_revision=revision,
            expected_comment_id=comment_id,
            expected_payload_sha256=(
                payload_sha256
            ),
        )
    except AuthorizationError as exc:
        raise TrustedQualificationError(
            str(exc)
        ) from exc



def _read_json_object(
    path: Path,
) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise TrustedQualificationError(
            f"JSON_INPUT_INVALID: {path}"
        ) from exc

    if not isinstance(document, dict):
        raise TrustedQualificationError(
            f"JSON_INPUT_INVALID: {path}"
        )

    return document


def _write_json_object(
    path: Path,
    document: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            document,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def command_plan(
    args: argparse.Namespace,
) -> int:
    comment = _read_json_object(
        args.comment
    )

    authorization = (
        resolved_authorization_from_comment(
            comment,
            trusted_author=args.trusted_author,
            repository=args.repository,
            issue_number=args.issue_number,
            task_id=args.task_id,
            revision=args.authorization_revision,
            comment_id=args.authorization_comment_id,
            payload_sha256=(
                args.authorization_payload_sha256
            ),
        )
    )

    plan = build_plan(
        args.repo_root.resolve(),
        authorization,
        candidate_sha=args.candidate_sha,
        candidate_ref=args.candidate_ref,
    )

    _write_json_object(
        args.output,
        plan,
    )

    print(
        json.dumps(
            {
                "result": "PASS",
                "plan_sha256": plan[
                    "plan_sha256"
                ],
                "candidate_sha": plan[
                    "candidate_sha"
                ],
                "profiles": plan["profiles"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    return 0


def command_finalize(
    args: argparse.Namespace,
) -> int:
    plan = _read_json_object(
        args.plan
    )

    comment = _read_json_object(
        args.comment
    )

    results = _read_json_object(
        args.profile_results
    )

    revalidate_plan_authorization(
        plan,
        comment,
        trusted_author=args.trusted_author,
    )

    request = build_check_request(
        plan,
        workflow_run_id=args.workflow_run_id,
        profile_results=results,
    )

    _write_json_object(
        args.output,
        request,
    )

    print(
        json.dumps(
            {
                "result": "PASS",
                "candidate_sha": request[
                    "head_sha"
                ],
                "conclusion": request[
                    "conclusion"
                ],
                "external_id": request[
                    "external_id"
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    return 0


def command_publish(
    args: argparse.Namespace,
) -> int:
    request = _read_json_object(
        args.request
    )

    token = os.environ.get(
        "NUTRITION_QUALIFICATION_APP_TOKEN",
        "",
    )

    publisher = HttpCheckPublisher(
        repository=args.repository,
        token=token,
    )

    response = publish_check(
        publisher,
        request,
        expected_app_id=args.expected_app_id,
    )

    _write_json_object(
        args.output,
        response,
    )

    print(
        json.dumps(
            {
                "result": "PASS",
                "check_id": response.get("id"),
                "head_sha": response[
                    "head_sha"
                ],
                "conclusion": response[
                    "conclusion"
                ],
                "app_id": response[
                    "app"
                ]["id"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    return 0


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Trusted candidate-independent "
            "qualification helper."
        )
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    plan = commands.add_parser(
        "plan"
    )

    plan.add_argument(
        "--repo-root",
        type=Path,
        required=True,
    )
    plan.add_argument(
        "--repository",
        required=True,
    )
    plan.add_argument(
        "--issue-number",
        type=int,
        required=True,
    )
    plan.add_argument(
        "--task-id",
        required=True,
    )
    plan.add_argument(
        "--authorization-revision",
        type=int,
        required=True,
    )
    plan.add_argument(
        "--authorization-comment-id",
        type=int,
        required=True,
    )
    plan.add_argument(
        "--authorization-payload-sha256",
        required=True,
    )
    plan.add_argument(
        "--trusted-author",
        required=True,
    )
    plan.add_argument(
        "--candidate-sha",
        required=True,
    )
    plan.add_argument(
        "--candidate-ref",
        required=True,
    )
    plan.add_argument(
        "--comment",
        type=Path,
        required=True,
    )
    plan.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    plan.set_defaults(
        handler=command_plan
    )

    finalize = commands.add_parser(
        "finalize"
    )

    finalize.add_argument(
        "--plan",
        type=Path,
        required=True,
    )
    finalize.add_argument(
        "--comment",
        type=Path,
        required=True,
    )
    finalize.add_argument(
        "--profile-results",
        type=Path,
        required=True,
    )
    finalize.add_argument(
        "--trusted-author",
        required=True,
    )
    finalize.add_argument(
        "--workflow-run-id",
        required=True,
    )
    finalize.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    finalize.set_defaults(
        handler=command_finalize
    )

    publish = commands.add_parser(
        "publish"
    )

    publish.add_argument(
        "--repository",
        required=True,
    )
    publish.add_argument(
        "--expected-app-id",
        type=int,
        required=True,
    )
    publish.add_argument(
        "--request",
        type=Path,
        required=True,
    )
    publish.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    publish.set_defaults(
        handler=command_publish
    )

    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    try:
        return args.handler(args)
    except (
        AuthorizationError,
        TrustedQualificationError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "error": str(exc),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
