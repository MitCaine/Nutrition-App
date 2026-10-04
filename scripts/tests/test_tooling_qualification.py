from __future__ import annotations
import hashlib
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import tooling_qualification as tooling
from lib.task_authorization import required_profiles_for_paths


def plan_for(sha):
    core = {'candidate_sha': sha, 'profiles': ['repository'], 'tooling_paths': ['scripts/**'], 'tooling_tests': True}
    return {**core, 'plan_sha256': hashlib.sha256(json.dumps(core, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()}


class ToolingQualificationTests(unittest.TestCase):
    def test_component_and_pattern_floor(self):
        for path in ('scripts', 'scripts/task.py', 'scripts/lib/a.py', 'scripts/**', 'engineering/tooling', 'engineering/tooling/ri/a', '.python-version', '.github/workflows/trusted-qualification.yml', '.github/workflows/trusted-qualification-execute.yml', '**', '*/x', 's*/x', 'engineering/*/x', 'engineering/tool*', 'engineering/toolin?', '.github/workflows/trusted-qualificatio?.yml'):
            with self.subTest(path=path):
                self.assertTrue(tooling.selected([path]))
                self.assertIn('repository', required_profiles_for_paths([path]))
        for path in ('scripts-extra/a', 'engineering/tooling-extra/a', 'apps/backend/app/a.py', 'docs/a.md'):
            self.assertFalse(tooling.selected([path]))
        self.assertEqual(required_profiles_for_paths(['scripts/lib/task_authorization.py']), {'repository', 'ios-native'})
        self.assertEqual(required_profiles_for_paths(['apps/mobile/app.json']), {'mobile', 'ios-native'})

    def test_real_git_planned_and_deleted_path_floor_cannot_be_omitted(self):
        from lib.task_authorization import ResolvedAuthorization, AuthorizationError, validate_candidate_scope
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            selected = repo / "scripts/tests/test_selected.py"
            selected.parent.mkdir(parents=True)
            selected.write_text("# tracked controller test\n")
            def git(*args):
                return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
            git("init", "-q"); git("config", "user.email", "fixture@example.invalid"); git("config", "user.name", "Fixture")
            git("add", "."); git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD"); git("update-ref", "refs/remotes/origin/main", base)
            authorization = ResolvedAuthorization(task_id="GH-245", issue_number=245, repository="MitCaine/Nutrition-App", base_sha=base, allowed_paths=("scripts/**",), forbidden_paths=(), profiles=("backend",), revision=4, nonce="0123456789abcdef", comment_id=245, author_login="MitCaine", payload_sha256="a" * 64, identity_sha256="b" * 64)
            with self.assertRaisesRegex(AuthorizationError, "QUALIFICATION_PROFILE_REQUIRED"):
                validate_candidate_scope(repo, authorization, candidate_sha=base)
            allowed = dataclasses.replace(authorization, profiles=("repository",))
            self.assertEqual(validate_candidate_scope(repo, allowed, candidate_sha=base), [])
            selected.unlink(); git("add", "-A"); git("commit", "-qm", "delete controller test")
            candidate = git("rev-parse", "HEAD")
            with self.assertRaisesRegex(AuthorizationError, "QUALIFICATION_PROFILE_REQUIRED"):
                validate_candidate_scope(repo, authorization, candidate_sha=candidate)
            self.assertEqual(validate_candidate_scope(repo, allowed, candidate_sha=candidate), ["scripts/tests/test_selected.py"])

    def test_trusted_plan_revalidation_and_failed_check(self):
        from lib import trusted_qualification as trusted
        from lib.task_authorization import build_payload, render_authorization_comment, resolve_comment
        payload = build_payload(task_id="GH-245", issue_number=245, repository="MitCaine/Nutrition-App", base_sha="b" * 40, allowed_paths=["scripts/tests/test_task_launcher.py"], forbidden_paths=[], profiles=["repository"], revision=1, nonce="0123456789abcdef")
        comment = {"id": 123, "user": {"login": "MitCaine"}, "body": render_authorization_comment(payload)}
        authorization = resolve_comment(comment, trusted_author="MitCaine", expected_repository="MitCaine/Nutrition-App", expected_issue_number=245, expected_task_id="GH-245", expected_revision=1, expected_comment_id=123)
        with patch.object(trusted, "validate_candidate_scope", return_value=["scripts/tests/test_task_launcher.py"]):
            plan = trusted.build_plan(ROOT, authorization, candidate_sha="a" * 40, candidate_ref="candidate")
        self.assertTrue(plan["tooling_tests"])
        trusted.revalidate_plan_authorization(plan, comment, trusted_author="MitCaine")
        changed = dict(plan, tooling_tests=False)
        changed["plan_sha256"] = trusted._digest({key: value for key, value in changed.items() if key != "plan_sha256"})
        with self.assertRaises(trusted.TrustedQualificationError):
            trusted.revalidate_plan_authorization(changed, comment, trusted_author="MitCaine")
        request = trusted.build_check_request(plan, workflow_run_id="1234", profile_results={"repository": "failure"})
        self.assertEqual(request["conclusion"], "failure")
        self.assertEqual(request["head_sha"], "a" * 40)

    def test_malformed_and_mismatched_plan(self):
        plan = plan_for('a' * 40)
        self.assertTrue(tooling.validate_plan(plan, 'a' * 40))
        for field, value in [('candidate_sha', 'b' * 40), ('tooling_tests', False), ('tooling_paths', ['docs/a'])]:
            altered = dict(plan, **{field: value})
            with self.assertRaises(ValueError):
                tooling.validate_plan(altered, 'a' * 40)
        core = dict(plan); core.pop('plan_sha256'); core['tooling_tests'] = 'true'
        core['plan_sha256'] = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        with self.assertRaises(ValueError): tooling.validate_plan(core, 'a' * 40)

    def test_real_trusted_runner_failure_and_success_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / 'candidate'; candidate.mkdir()
            for name in tooling.TEST_FILES:
                path = candidate / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('')
            # Candidate selection/workflow/config cannot replace the trusted command.
            malicious = candidate / 'scripts/lib/tooling_qualification.py'
            malicious.parent.mkdir(parents=True); malicious.write_text('raise SystemExit(0)')
            (candidate / 'pytest.ini').write_text('[pytest]\naddopts = --ignore=scripts/tests/test_task_launcher.py\n')
            selected = candidate / 'scripts/tests/test_task_launcher.py'
            body = '''import os\ndef test_selected_control():\n    assert 'GH_TOKEN' not in os.environ\n    assert 'PYTEST_ADDOPTS' not in os.environ\n    assert 'PYTHONPATH' not in os.environ\n    assert 'NUTRITION_REQUIRE_EVIDENCE_SANDBOX' not in os.environ\n    assert CONTROL\n'''
            selected.write_text(body.replace('CONTROL', 'False'))
            def git(*args):
                return subprocess.check_output(['git', '-C', str(candidate), *args], text=True).strip()
            git('init', '-q'); git('config', 'user.email', 'fixture@example.invalid'); git('config', 'user.name', 'Fixture'); git('add', '.'); git('commit', '-qm', 'negative')
            def invoke():
                sha = git('rev-parse', 'HEAD'); plan = Path(directory) / 'plan.json'; plan.write_text(json.dumps(plan_for(sha)))
                env = dict(os.environ, GH_TOKEN='fixture-secret', PYTEST_ADDOPTS='--ignore=scripts', PYTHONPATH='/invalid', NUTRITION_REQUIRE_EVIDENCE_SANDBOX='1')
                return subprocess.run([sys.executable, str(ROOT / 'scripts/lib/tooling_qualification.py'), '--candidate-root', str(candidate), '--candidate-sha', sha, '--plan', str(plan)], env=env, text=True, capture_output=True)
            negative = invoke()
            self.assertEqual(negative.returncode, 1, negative.stdout + negative.stderr)
            self.assertIn('FAILED', negative.stdout)
            selected.write_text(body.replace('CONTROL', 'True')); git('add', '.'); git('commit', '-qm', 'positive')
            positive = invoke()
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertIn('PASSED', positive.stdout)

    def test_workflow_privilege_and_trusted_selection(self):
        source = (ROOT / '.github/workflows/trusted-qualification-execute.yml').read_text()
        job = source.split('  repository:\n', 1)[1].split('\n  backend:', 1)[0]
        self.assertIn('contents: read', job)
        self.assertNotIn('secrets.', job)
        self.assertNotIn('cache:', job)
        self.assertIn('trusted/scripts/lib/tooling_qualification.py', job)
        self.assertIn('trusted/.python-version', job)
        self.assertIn('trusted/apps/backend/requirements-dev.lock', job)
        self.assertIn('persist-credentials: false', job)
        self.assertLess(job.index('Trusted fast controller suite'), job.index('Validate docs'))
        self.assertTrue({"scripts/tests/test_task_authorization.py", "scripts/tests/test_path_scope.py",
                         "scripts/tests/test_task_closeout.py", "apps/backend/tests/test_task_controller.py"}.issubset(tooling.TEST_FILES))
        self.assertNotIn("scripts/tests/test_independent_review.py", tooling.TEST_FILES)
        self.assertIn("scripts/tests/test_backend_qualification.py", tooling.TEST_FILES)
