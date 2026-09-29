from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import path_scope  # noqa: E402


class VersionedPathScopeTests(unittest.TestCase):
    def test_v2_component_matcher_table(self):
        cases = (
            ("src/file.py", "src/file.py", True),
            ("src/other.py", "src/file.py", False),
            ("src/file.py", "src/*", True),
            ("src/nested/file.py", "src/*", False),
            ("apps/backend", "apps/backend", True),
            ("apps/backend/api/routes.py", "apps/backend", False),
            ("apps/backend", "apps/backend/**", True),
            ("apps/backend/api/routes.py", "apps/backend/**", True),
            ("apps/backendish/api/routes.py", "apps/backend/**", False),
            ("src/file.py", "src/**/file.py", True),
            ("src/deep/file.py", "src/**/file.py", True),
            ("a/b/c", "**", True),
            ("file.py", "**", True),
        )
        for path, pattern, expected in cases:
            with self.subTest(path=path, pattern=pattern):
                self.assertEqual(path_scope.matches(path, pattern, path_scope.V2), expected)

    def test_v1_fnmatchcase_behavior_remains_frozen(self):
        cases = (
            ("src/nested/file.py", "src/*", True),
            ("root", "root/**", False),
            ("src/file.py", "src/**/file.py", False),
            ("src/deep/file.py", "src/**/file.py", True),
            ("src/a.py", "src/[ab].py", True),
        )
        for path, pattern, expected in cases:
            with self.subTest(path=path, pattern=pattern):
                self.assertEqual(path_scope.matches(path, pattern, path_scope.V1), expected)
        self.assertTrue(path_scope.matches("src/name\0part", "src/*", path_scope.V1))
        self.assertTrue(path_scope.matches("src\\name", "**", path_scope.V1))
        with self.assertRaises(path_scope.PathPatternError):
            path_scope.matches("src/name\0part", "src/*", path_scope.V2)

    def test_v2_rejects_malformed_or_unsupported_patterns(self):
        invalid = (
            "",
            "/root/file.py",
            "root/",
            "root//file.py",
            "root/./file.py",
            "root/../file.py",
            "root\\file.py",
            "src/foo*bar.py",
            "src/**bar/file.py",
            "src/file?.py",
            "src/[ab].py",
        )
        for pattern in invalid:
            with self.subTest(pattern=pattern):
                with self.assertRaises(path_scope.PathPatternError):
                    path_scope.validate_pattern(pattern, path_scope.V2)

    def test_invalid_version_or_path_fails_closed(self):
        for version in (0, 3, True, "2"):
            with self.subTest(version=version):
                with self.assertRaises(path_scope.PathPatternError):
                    path_scope.matches("src/file.py", "src/*", version)
        with self.assertRaises(path_scope.PathPatternError):
            path_scope.matches("src/../secret", "**", path_scope.V2)

    def test_forbidden_pattern_wins_even_when_allowed_also_matches(self):
        self.assertFalse(path_scope.permitted(
            "apps/backend/private/keys.py",
            ["apps/backend/**"],
            ["apps/backend/private/**"],
            path_scope.V2,
        ))
        self.assertTrue(path_scope.permitted(
            "apps/backend/models/food.py",
            ["apps/backend/**"],
            ["apps/backend/private/**"],
            path_scope.V2,
        ))


if __name__ == "__main__":
    unittest.main()
