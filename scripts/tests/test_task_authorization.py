from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

from lib.task_authorization import (  # noqa: E402
    AUTHORIZATION_MARKER,
    AuthorizationError,
    build_payload,
    render_authorization_comment,
    resolve_comments,
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


if __name__ == "__main__":
    unittest.main()
