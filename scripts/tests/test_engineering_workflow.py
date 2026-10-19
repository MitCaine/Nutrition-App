"""Public record/prepare barriers for the explicitly selected engineering route."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import task  # noqa: E402
import worker_execution  # noqa: E402


def record():
    return (ROOT / 'engineering/tasks/ENGINEERING_TEMPLATE.md').read_text()


def _inspector_fixture(tmp_path, history='existing', owner_profiles=None):
    repo = tmp_path / 'repo'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    git('init', '-q')
    git('config', 'user.name', 'Fixture owner')
    git('config', 'user.email', 'owner@example.invalid')
    specification_path = repo / 'engineering/tasks/GH-422-ENGINEERING.md'
    specification_path.parent.mkdir(parents=True)
    has_starting_specification = history != 'first_add_then_modify'
    if has_starting_specification:
        specification_path.write_text('## Prior plan\n\nAccepted starting text.\n')
    source_path = repo / 'scripts/worker_execution.py'
    source_path.parent.mkdir(parents=True)
    source_path.write_text('pass\n')
    git('add', 'scripts/worker_execution.py')
    if has_starting_specification:
        git('add', 'engineering/tasks/GH-422-ENGINEERING.md')
    git('commit', '-qm', 'integration base')
    integration_base = git('rev-parse', 'HEAD')
    initial_branch = git('branch', '--show-current')
    predecessor = integration_base
    accepted_plan = '## Accepted plan\n\nExact reviewed planning text.\n'
    if history == 'first_add_then_modify':
        specification_path.write_text('## Initial approved plan\n\nFirst reviewed addition.\n')
        git('add', 'engineering/tasks/GH-422-ENGINEERING.md')
        git('commit', '-qm', 'add accepted plan')
        specification_path.write_text(accepted_plan)
        git('add', 'engineering/tasks/GH-422-ENGINEERING.md')
        git('commit', '-qm', 'refine accepted plan')
    elif history == 'delete_readd':
        git('rm', 'engineering/tasks/GH-422-ENGINEERING.md')
        git('commit', '-qm', 'delete accepted specification')
        specification_path.parent.mkdir(parents=True, exist_ok=True)
        specification_path.write_text(accepted_plan)
        git('add', 'engineering/tasks/GH-422-ENGINEERING.md')
        git('commit', '-qm', 'reintroduce accepted specification')
    elif history == 'rename':
        git('mv', 'engineering/tasks/GH-422-ENGINEERING.md', 'engineering/tasks/GH-422-RENAMED.md')
        git('commit', '-qm', 'rename accepted specification')
        git('mv', 'engineering/tasks/GH-422-RENAMED.md', 'engineering/tasks/GH-422-ENGINEERING.md')
        specification_path.write_text(accepted_plan)
        git('add', 'engineering/tasks/GH-422-ENGINEERING.md')
        git('commit', '-qm', 'rename accepted specification back')
    elif history == 'unrelated':
        specification_path.write_text(accepted_plan)
        (repo / 'unrelated.txt').write_text('Unauthorized history change.\n')
        git('add', 'engineering/tasks/GH-422-ENGINEERING.md', 'unrelated.txt')
        git('commit', '-qm', 'change plan and unrelated path')
    elif history == 'reverted_source':
        specification_path.write_text(accepted_plan)
        git('add', 'engineering/tasks/GH-422-ENGINEERING.md')
        git('commit', '-qm', 'publish accepted plan')
        source_path.write_text('source change that is later reverted\n')
        git('add', 'scripts/worker_execution.py')
        git('commit', '-qm', 'introduce unrelated source change')
        source_path.write_text('pass\n')
        git('add', 'scripts/worker_execution.py')
        git('commit', '-qm', 'revert unrelated source change')
    elif history == 'nonlinear':
        git('switch', '-c', 'side-plan', '-q')
        specification_path.write_text('## Side plan\n\nNonlinear planning branch.\n')
        git('add', 'engineering/tasks/GH-422-ENGINEERING.md')
        git('commit', '-qm', 'side specification change')
        git('switch', initial_branch, '-q')
        specification_path.write_text(accepted_plan)
        git('add', 'engineering/tasks/GH-422-ENGINEERING.md')
        git('commit', '-qm', 'main specification change')
        git('merge', '-q', '--no-ff', '-s', 'ours', 'side-plan', '-m', 'nonlinear specification history')
    elif history == 'existing':
        specification_path.write_text(accepted_plan)
        git('add', 'engineering/tasks/GH-422-ENGINEERING.md')
        git('commit', '-qm', 'publish accepted plan')
    else:
        raise AssertionError(f'unknown fixture history: {history}')
    base = git('rev-parse', 'HEAD')

    history_rows = []
    for commit in git('rev-list', '--reverse', f'{predecessor}..{base}').splitlines():
        parent = git('rev-list', '--parents', '-n', '1', commit).split()[1]
        rows = git('diff-tree', '--no-commit-id', '--name-status', '-r', '--find-renames',
                   parent, commit).splitlines()
        history_rows.append([row.split('\t') for row in rows])

    def reference(path):
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    specification = reference(specification_path)
    report_path = tmp_path / 'planning-review.md'
    report_path.write_text('Independent planning review report.\n')
    planning_report = reference(report_path)
    predecessor_report_path = tmp_path / 'predecessor-review.md'
    predecessor_report_path.write_text('Accepted predecessor review.\n')
    predecessor_report = reference(predecessor_report_path)
    due_paths = [tmp_path / 'c2-runner.stdout.log', tmp_path / 'c2-source-review.md']
    for path in due_paths:
        path.write_text('Original retained predecessor evidence.\n')
    due_evidence = [reference(path) for path in due_paths]
    selection_sha256 = 'a' * 64
    approval_value = {
        'decision': 'approved', 'specification': specification,
        'selection_sha256': selection_sha256, 'reviewer': 'Independent plan reviewer',
        'reviewer_report': planning_report,
    }
    approval_path = tmp_path / 'planning-approval.json'
    approval_path.write_text(json.dumps(approval_value, sort_keys=True) + '\n')
    approval = reference(approval_path)
    allowed_changes = ['scripts/worker_execution.py', 'scripts/lib/review_commands.py']
    profiles = ['repository']
    authorized_profiles = owner_profiles or profiles
    assignment = {
        'assignment': 'GH-422/implementation-a1', 'attempt': 'GH-422-implementation-a1',
        'base': base, 'integration_base': integration_base,
        'allowed_changes': allowed_changes, 'profiles': profiles,
        'specification': specification, 'selection_sha256': selection_sha256,
        'planning_review': {
            'decision': 'approved', 'reviewer': 'Independent plan reviewer',
            'report': planning_report, 'approval': approval, 'specification': specification,
            'selection_sha256': selection_sha256,
        },
        'predecessor': {
            'candidate': predecessor, 'decision': 'accepted',
            'review': {'decision': 'approved', 'reviewed_candidate': predecessor,
                       'report': predecessor_report},
            'due_evidence': due_evidence,
        },
    }
    payload = task.build_payload(
        task_id='GH-422', issue_number=422, repository='owner/repo', base_sha=integration_base,
        allowed_paths=['scripts/**', 'engineering/**'], forbidden_paths=['engineering/private/**'],
        profiles=authorized_profiles, revision=1, nonce='fixture-owner-nonce',
    )
    selection = task._normalize_workflow_selection('standard', None)
    selection_sha = task._workflow_selection_digest(selection)
    comment = {
        'id': 77, 'user': {'login': 'fixture-owner'},
        'body': task.render_authorization_comment(payload).rstrip() + '\n\n'
                + task._render_workflow_selection(selection),
    }
    resolved = task.resolve_comments(
        [comment], trusted_author='fixture-owner', expected_repository='owner/repo',
        expected_issue_number=422, expected_task_id='GH-422', expected_revision=1,
    )
    state = {
        'schema_version': 1, 'phase': 'AUTHORIZED', 'issue_number': 422, 'task_id': 'GH-422',
        'repository': 'owner/repo', 'trusted_author': 'fixture-owner',
        'authorization': {
            'revision': resolved.revision, 'nonce': resolved.nonce,
            'base_sha': resolved.base_sha, 'payload_sha256': resolved.payload_sha256,
            'comment_id': resolved.comment_id, 'identity_sha256': resolved.identity_sha256,
            'author_login': resolved.author_login, 'workflow_selection_sha256': selection_sha,
        },
        'workflow': {
            'mode': 'standard', 'reason': None, 'selection_sha256': selection_sha,
            'authority': {
                'comment_id': resolved.comment_id, 'author_login': resolved.author_login,
                'authorization_identity_sha256': resolved.identity_sha256,
                'selection_sha256': selection_sha,
            },
        },
        'execution': {'engineering_assignment': assignment},
    }
    request = {
        'task_id': 'GH-422', 'issue_number': 422,
        'authorization_identity_sha256': resolved.identity_sha256,
        'engineering_assignment': assignment, 'assignment': assignment['assignment'],
        'attempt': assignment['attempt'], 'base': base, 'integration_base': integration_base,
        'allowed_changes': allowed_changes, 'profiles': profiles, 'workspace': str(repo),
        'accepted_engineering': {
            'path': specification['path'], 'sha256': specification['sha256'],
            'phase': 'implementation', 'route': 'engineering', 'selection': ['engineering'],
            'approval': approval,
        },
    }

    class FixtureTransport:
        def __init__(self):
            self.predecessor_decisions = []

        def list_issue_comments(self, repository, issue_number):
            assert (repository, issue_number) == ('owner/repo', 422)
            return [comment]

        def withhold_predecessor_acceptance(self, return_reference, *, result_reference=None,
                                             native_references=()):
            report_path = Path(return_reference['path'])
            report = json.loads(report_path.read_text())
            observed_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
            assert observed_hash == return_reference['sha256']
            evidence = None
            if result_reference is not None:
                result_path = Path(result_reference['path'])
                result = json.loads(result_path.read_text())
                assert hashlib.sha256(result_path.read_bytes()).hexdigest() == result_reference['sha256']
                assert result['candidate'] == report['candidate']
                assert result['attempt'] == report['attempt']
                assert result['ready'] is False
                observed_native = []
                for reference in native_references:
                    native_path = Path(reference['path'])
                    record = json.loads(native_path.read_text())
                    native_case = record['native_case']
                    assert hashlib.sha256(native_path.read_bytes()).hexdigest() == reference['sha256']
                    assert native_case['candidate'] == report['candidate']
                    assert native_case['attempt'] == report['attempt']
                    observed_native.append({
                        'reference': reference,
                        'case': native_case['case'],
                        'status': native_case['status'],
                        'request_sha256': native_case['request_sha256'],
                    })
                evidence = {
                    'result': result_reference,
                    'native_cases': observed_native,
                    'review_ready': report.get('review_ready'),
                    'completeness_ready': report.get('completeness', {}).get('ready'),
                }
            if report.get('review_ready') is False and report.get('completeness', {}).get('ready') is False:
                decision = 'interrupted'
            else:
                decision = 'accepted'
            observed = {
                'candidate': report.get('candidate'), 'return': return_reference,
                'decision': decision,
            }
            if evidence is not None:
                observed['evidence'] = evidence
            self.predecessor_decisions.append(observed)
            return decision

    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    checkpoint = state_dir / 'issue-422.json'
    checkpoint.write_text(json.dumps(state, sort_keys=True) + '\n')
    request_path = tmp_path / 'request.json'
    request_path.write_text(json.dumps(request, sort_keys=True) + '\n')
    return {
        'repo': repo, 'git': git, 'state': state, 'request': request,
        'checkpoint': checkpoint, 'request_path': request_path, 'state_dir': state_dir,
        'transport': FixtureTransport(), 'due_paths': due_paths, 'history_rows': history_rows,
    }


def _run_assignment_inspector(fixture, monkeypatch):
    monkeypatch.setattr(task, 'GhQualificationTransport', lambda: fixture['transport'])
    return task.main([
        '--repo-root', str(fixture['repo']), '--state-dir', str(fixture['state_dir']),
        'inspect-engineering-assignment', '422', '--request', str(fixture['request_path']),
    ])


def _save_assignment(fixture, assignment):
    fixture['state']['execution']['engineering_assignment'] = assignment
    fixture['request']['engineering_assignment'] = assignment
    for key in ('assignment', 'attempt', 'base', 'integration_base', 'allowed_changes', 'profiles'):
        fixture['request'][key] = assignment[key]
    fixture['checkpoint'].write_text(json.dumps(fixture['state'], sort_keys=True) + '\n')
    fixture['request_path'].write_text(json.dumps(fixture['request'], sort_keys=True) + '\n')


def _state_snapshot(fixture):
    state_dir = fixture['state_dir']
    return {
        path.relative_to(state_dir).as_posix(): ('directory' if path.is_dir() else path.read_bytes())
        for path in sorted(state_dir.rglob('*'))
    }


def _worker_test_helpers():
    path = ROOT / 'scripts/tests/test_worker_execution.py'
    spec = importlib.util.spec_from_file_location('nutrition_worker_execution_test_support', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_partial_public_return_keeps_predecessor_unaccepted_through_fixture_transport(
        tmp_path, monkeypatch, capsys):
    public_root = tmp_path / 'public-route'
    public_root.mkdir()
    worker_tests = _worker_test_helpers()
    case = worker_tests._write_generated_fixture(worker_execution, public_root)
    attempt, result_path, terminal_path, result, terminal = worker_tests._run_generated_fixture_to_terminal(
        case, second_case_failure='raise SystemExit(13)', expected_run=1)
    assert result['ready'] is False
    assert terminal['review_ready'] is False
    assert terminal['completeness']['ready'] is False
    facts = {row['id']: row for row in result['facts']['outcomes']}
    assert facts['P1']['status'] == 'passed'
    assert facts['P1b']['status'] == 'failed'
    assert facts['R1']['status'] == 'failed'
    original_return = terminal_path.read_bytes()

    inspector_root = tmp_path / 'inspector'
    inspector_root.mkdir()
    fixture = _inspector_fixture(inspector_root)
    return_reference = {
        'path': str(terminal_path),
        'sha256': hashlib.sha256(original_return).hexdigest(),
    }
    # This deterministic test transport models the controller boundary only.
    # The product inspector still reads the controller's saved decision mechanically.
    decision = fixture['transport'].withhold_predecessor_acceptance(return_reference)
    assert decision == 'interrupted'
    assert fixture['transport'].predecessor_decisions == [{
        'candidate': terminal['candidate'], 'return': return_reference, 'decision': 'interrupted',
    }]
    assignment = json.loads(json.dumps(fixture['state']['execution']['engineering_assignment']))
    assignment['predecessor']['decision'] = decision
    assignment['predecessor']['review']['report'] = return_reference
    assignment['predecessor']['due_evidence'] = [
        return_reference,
        {'path': str(result_path), 'sha256': hashlib.sha256(result_path.read_bytes()).hexdigest()},
    ]
    _save_assignment(fixture, assignment)
    checkpoint_before = fixture['checkpoint'].read_bytes()
    state_before = _state_snapshot(fixture)

    assert _run_assignment_inspector(fixture, monkeypatch) == 1
    refused = json.loads(capsys.readouterr().out)
    assert refused['result'] == 'FAIL'
    assert refused['error'] == 'ENGINEERING_PREDECESSOR_NOT_ACCEPTED'
    assert fixture['checkpoint'].read_bytes() == checkpoint_before
    assert _state_snapshot(fixture) == state_before
    assert not (fixture['state_dir'] / assignment['attempt']).exists()
    assert terminal_path.read_bytes() == original_return


def test_combined_public_interaction_failure_withholds_predecessor_acceptance(
        tmp_path, monkeypatch, capsys):
    worker_tests = _worker_test_helpers()

    def run_individual(label, case_id, attempt_name, expected):
        root = tmp_path / label
        root.mkdir()
        case = worker_tests._write_generated_fixture(worker_execution, root)
        output = root / 'scratch' / 'OUTPUT.txt'
        worker_tests._configure_generated_output_portion_fixture(
            case, attempt=attempt_name, case_id=case_id, output_path=output)
        attempt, result_path, return_path, result, returned = (
            worker_tests._run_generated_fixture_to_terminal(case))
        proof_id = 'P1' if case_id == 'case_a' else 'P1b'
        outcomes = {row['id']: row for row in result['facts']['outcomes']}
        assert result['ready'] is True and returned['review_ready'] is True
        assert returned['completeness']['ready'] is True
        assert outcomes[proof_id]['status'] == 'passed'
        assert output.read_text() == expected
        run_dir = attempt / 'native/runs' / attempt_name
        native_request = run_dir / 'request.json'
        record_path = run_dir / 'commands' / case_id / 'result.json'
        record = json.loads(record_path.read_text())
        native_case = record['native_case']
        request_sha = hashlib.sha256(native_request.read_bytes()).hexdigest()
        assert native_case['case'] == case_id
        assert native_case['candidate'] == returned['candidate']
        assert native_case['attempt'] == attempt_name
        assert native_case['request_sha256'] == request_sha
        assert native_case['status'] == 'passed'
        reference = {'path': str(record_path),
                     'sha256': hashlib.sha256(record_path.read_bytes()).hexdigest()}
        return {
            'candidate': returned['candidate'], 'attempt': attempt_name,
            'request_sha256': request_sha, 'native_reference': reference,
            'native_bytes': record_path.read_bytes(), 'return_bytes': return_path.read_bytes(),
            'result_bytes': result_path.read_bytes(), 'case': case,
            'attempt_path': attempt, 'native_case': native_case,
        }

    individual_a = run_individual(
        'individual-a', 'case_a', 'GH-422-interaction-portion-a', 'portion-a')
    individual_b = run_individual(
        'individual-b', 'case_b', 'GH-422-interaction-portion-b', 'portion-b')

    collision_root = tmp_path / 'combined-collision'
    collision_root.mkdir()
    collision_case = worker_tests._write_generated_fixture(worker_execution, collision_root)
    shared_output = collision_root / 'scratch' / 'OUTPUT.txt'
    worker_tests._configure_generated_interaction_fixture(
        collision_case, attempt='GH-422-interaction-collision',
        output_a=shared_output, output_b=shared_output)
    combined_attempt, combined_result_path, combined_return_path, combined_result, combined_return = (
        worker_tests._run_generated_fixture_to_terminal(collision_case, expected_run=1))
    assert combined_result['ready'] is False
    assert combined_return['review_ready'] is False
    assert combined_return['completeness']['ready'] is False
    assert shared_output.read_text() == 'portion-b'
    combined_outcomes = {row['id']: row for row in combined_result['facts']['outcomes']}
    assert combined_outcomes['P1']['status'] == 'passed'
    assert combined_outcomes['P1b']['status'] == 'passed'
    assert combined_outcomes['P1c']['status'] == 'failed'
    assert combined_outcomes['R1']['status'] == 'failed'

    run_dir = combined_attempt / 'native/runs' / collision_case['seed']['attempt']
    native_request = run_dir / 'request.json'
    request_sha = hashlib.sha256(native_request.read_bytes()).hexdigest()
    combined_records = {}
    for case_id, expected_status in (
            ('case_a', 'passed'), ('case_b', 'passed'), ('case_interaction', 'failed')):
        record_path = run_dir / 'commands' / case_id / 'result.json'
        record_bytes = record_path.read_bytes()
        record = json.loads(record_bytes)
        native_case = record['native_case']
        assert native_case['case'] == case_id
        assert native_case['candidate'] == combined_return['candidate']
        assert native_case['attempt'] == collision_case['seed']['attempt']
        assert native_case['request_sha256'] == request_sha
        assert native_case['status'] == expected_status
        assert record['status'] == expected_status
        if case_id == 'case_interaction':
            assert record['exit_code'] == 1 and record['child_return_code'] == 1
            stderr_binding = native_case['artifacts']['stderr']
            stderr_path = Path(stderr_binding['path'])
            stderr_bytes = stderr_path.read_bytes()
            assert hashlib.sha256(stderr_bytes).hexdigest() == stderr_binding['sha256']
            assert (b"AssertionError: interaction outputs were overwritten: "
                    b"first='portion-b', second='portion-b'") in stderr_bytes
            interaction_stderr = stderr_bytes
        else:
            assert record['exit_code'] == 0 and record['child_return_code'] == 0
        combined_records[case_id] = {
            'reference': {'path': str(record_path),
                          'sha256': hashlib.sha256(record_bytes).hexdigest()},
            'bytes': record_bytes,
        }

    distinct_root = tmp_path / 'combined-distinct'
    distinct_root.mkdir()
    distinct_case = worker_tests._write_generated_fixture(worker_execution, distinct_root)
    distinct_a = distinct_root / 'scratch' / 'OUTPUT-A.txt'
    distinct_b = distinct_root / 'scratch' / 'OUTPUT-B.txt'
    worker_tests._configure_generated_interaction_fixture(
        distinct_case, attempt='GH-422-interaction-distinct',
        output_a=distinct_a, output_b=distinct_b)
    distinct_attempt, distinct_result_path, distinct_return_path, distinct_result, distinct_return = (
        worker_tests._run_generated_fixture_to_terminal(distinct_case))
    distinct_outcomes = {row['id']: row for row in distinct_result['facts']['outcomes']}
    assert distinct_result['ready'] is True
    assert distinct_return['review_ready'] is True
    assert distinct_return['completeness']['ready'] is True
    assert all(distinct_outcomes[key]['status'] == 'passed' for key in ('P1', 'P1b', 'P1c'))
    assert distinct_a.read_text() == 'portion-a' and distinct_b.read_text() == 'portion-b'
    distinct_run_dir = distinct_attempt / 'native/runs' / distinct_case['seed']['attempt']
    distinct_request_sha = hashlib.sha256((distinct_run_dir / 'request.json').read_bytes()).hexdigest()
    for case_id in ('case_a', 'case_b', 'case_interaction'):
        record_path = distinct_run_dir / 'commands' / case_id / 'result.json'
        record = json.loads(record_path.read_text())
        native_case = record['native_case']
        assert native_case['case'] == case_id
        assert native_case['candidate'] == distinct_return['candidate']
        assert native_case['attempt'] == distinct_case['seed']['attempt']
        assert native_case['request_sha256'] == distinct_request_sha
        assert native_case['status'] == record['status'] == 'passed'
        assert record['exit_code'] == record['child_return_code'] == 0

    combined_return_bytes = combined_return_path.read_bytes()
    combined_result_bytes = combined_result_path.read_bytes()
    inspector_root = tmp_path / 'inspector'
    inspector_root.mkdir()
    fixture = _inspector_fixture(inspector_root)
    return_reference = {
        'path': str(combined_return_path),
        'sha256': hashlib.sha256(combined_return_bytes).hexdigest(),
    }
    result_reference = {
        'path': str(combined_result_path),
        'sha256': hashlib.sha256(combined_result_bytes).hexdigest(),
    }
    native_references = [combined_records[case_id]['reference'] for case_id in
                         ('case_a', 'case_b', 'case_interaction')]
    decision = fixture['transport'].withhold_predecessor_acceptance(
        return_reference, result_reference=result_reference,
        native_references=native_references)
    assert decision == 'interrupted'
    transport_observation = fixture['transport'].predecessor_decisions
    assert len(transport_observation) == 1
    observed = transport_observation[0]
    assert observed['candidate'] == combined_return['candidate']
    assert observed['return'] == return_reference and observed['decision'] == 'interrupted'
    assert observed['evidence']['result'] == result_reference
    assert observed['evidence']['review_ready'] is False
    assert observed['evidence']['completeness_ready'] is False
    observed_native = observed['evidence']['native_cases']
    assert [(row['case'], row['status'], row['request_sha256']) for row in observed_native] == [
        ('case_a', 'passed', request_sha), ('case_b', 'passed', request_sha),
        ('case_interaction', 'failed', request_sha),
    ]

    assignment = json.loads(json.dumps(fixture['state']['execution']['engineering_assignment']))
    assignment['predecessor']['decision'] = decision
    assignment['predecessor']['review']['report'] = return_reference
    assignment['predecessor']['due_evidence'] = [return_reference, result_reference, *native_references]
    _save_assignment(fixture, assignment)
    checkpoint_before = fixture['checkpoint'].read_bytes()
    state_before = _state_snapshot(fixture)
    assert _run_assignment_inspector(fixture, monkeypatch) == 1
    refused = json.loads(capsys.readouterr().out)
    assert refused['result'] == 'FAIL'
    assert refused['error'] == 'ENGINEERING_PREDECESSOR_NOT_ACCEPTED'
    assert fixture['checkpoint'].read_bytes() == checkpoint_before
    assert _state_snapshot(fixture) == state_before
    assert not (fixture['state_dir'] / assignment['attempt']).exists()
    assert combined_return_path.read_bytes() == combined_return_bytes
    assert combined_result_path.read_bytes() == combined_result_bytes
    assert Path(combined_records['case_a']['reference']['path']).read_bytes() == combined_records['case_a']['bytes']
    assert Path(combined_records['case_b']['reference']['path']).read_bytes() == combined_records['case_b']['bytes']
    assert Path(combined_records['case_interaction']['reference']['path']).read_bytes() == combined_records['case_interaction']['bytes']
    assert interaction_stderr == Path(
        json.loads(combined_records['case_interaction']['bytes'])['native_case']['artifacts']['stderr']['path']
    ).read_bytes()
    for retained in (individual_a, individual_b):
        record_path = Path(retained['native_reference']['path'])
        assert record_path.read_bytes() == retained['native_bytes']
        assert Path(retained['case']['evidence'] / retained['case']['seed']['attempt'] / 'RETURN.json').read_bytes() == retained['return_bytes']
        assert Path(retained['case']['evidence'] / retained['case']['seed']['attempt'] / 'NUTRITION_RESULT.json').read_bytes() == retained['result_bytes']


def test_public_inspector_accepts_existing_specification_modification(tmp_path, monkeypatch, capsys):
    fixture = _inspector_fixture(tmp_path)
    before = _state_snapshot(fixture)
    assert fixture['history_rows'] == [[['M', 'engineering/tasks/GH-422-ENGINEERING.md']]]
    assert _run_assignment_inspector(fixture, monkeypatch) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['result'] == 'PASS'
    assert result['assignment'] == 'GH-422/implementation-a1'
    assert result['base'] == fixture['state']['execution']['engineering_assignment']['base']
    assert len(result['references']) == 6
    assert _state_snapshot(fixture) == before


def test_public_inspector_accepts_initial_specification_addition_then_modification(
        tmp_path, monkeypatch, capsys):
    fixture = _inspector_fixture(tmp_path, history='first_add_then_modify')
    before = _state_snapshot(fixture)
    assert fixture['history_rows'] == [
        [['A', 'engineering/tasks/GH-422-ENGINEERING.md']],
        [['M', 'engineering/tasks/GH-422-ENGINEERING.md']],
    ]
    assert _run_assignment_inspector(fixture, monkeypatch) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['result'] == 'PASS'
    assert result['base'] == fixture['state']['execution']['engineering_assignment']['base']
    assert _state_snapshot(fixture) == before


@pytest.mark.parametrize('history,error', [
    ('delete_readd', 'ENGINEERING_ASSIGNMENT_HISTORY_OUT_OF_SCOPE'),
    ('rename', 'ENGINEERING_ASSIGNMENT_HISTORY_OUT_OF_SCOPE'),
    ('unrelated', 'ENGINEERING_ASSIGNMENT_HISTORY_OUT_OF_SCOPE'),
    ('reverted_source', 'ENGINEERING_ASSIGNMENT_HISTORY_OUT_OF_SCOPE'),
    ('nonlinear', 'ENGINEERING_ASSIGNMENT_HISTORY_NOT_LINEAR'),
])
def test_public_inspector_refuses_unsafe_specification_history_without_checkpoint_or_attempt_changes(
        tmp_path, monkeypatch, capsys, history, error):
    fixture = _inspector_fixture(tmp_path, history=history)
    if history == 'delete_readd':
        assert fixture['history_rows'] == [
            [['D', 'engineering/tasks/GH-422-ENGINEERING.md']],
            [['A', 'engineering/tasks/GH-422-ENGINEERING.md']],
        ]
    elif history == 'rename':
        assert fixture['history_rows'][0][0][0].startswith('R')
    elif history == 'unrelated':
        assert fixture['history_rows'] == [[
            ['M', 'engineering/tasks/GH-422-ENGINEERING.md'],
            ['A', 'unrelated.txt'],
        ]]
    elif history == 'reverted_source':
        assert fixture['history_rows'] == [
            [['M', 'engineering/tasks/GH-422-ENGINEERING.md']],
            [['M', 'scripts/worker_execution.py']],
            [['M', 'scripts/worker_execution.py']],
        ]
    else:
        assert len(fixture['history_rows']) >= 3
    before = _state_snapshot(fixture)
    checkpoint_before = fixture['checkpoint'].read_bytes()
    assert _run_assignment_inspector(fixture, monkeypatch) == 1
    refused = json.loads(capsys.readouterr().out)
    assert refused['result'] == 'FAIL'
    assert refused['error'] == error
    assert fixture['checkpoint'].read_bytes() == checkpoint_before
    assert _state_snapshot(fixture) == before
    assert not (fixture['state_dir'] / fixture['request']['attempt']).exists()


@pytest.mark.parametrize('failure,error', [
    ('altered_plan', 'ENGINEERING_PLANNING_APPROVAL_BINDING_MISMATCH'),
    ('predecessor_absent', 'ENGINEERING_PREDECESSOR_INCOMPLETE'),
    ('predecessor_rejected', 'ENGINEERING_PREDECESSOR_NOT_ACCEPTED'),
    ('predecessor_interrupted', 'ENGINEERING_PREDECESSOR_NOT_ACCEPTED'),
    ('moved_review', 'ENGINEERING_PREDECESSOR_NOT_ACCEPTED'),
    ('missing_due_evidence', 'ENGINEERING_PREDECESSOR_DUE_EVIDENCE_REFERENCE_UNAVAILABLE'),
    ('planning_report_binding', 'ENGINEERING_PLANNING_REPORT_REFERENCE_CHANGED'),
    ('due_evidence_binding', 'ENGINEERING_PREDECESSOR_DUE_EVIDENCE_REFERENCE_CHANGED'),
    ('unauthorized_path', 'ENGINEERING_ASSIGNMENT_PATH_OUTSIDE_OWNER_SCOPE: engineering/private/secret.md'),
    ('profile_floor', 'ENGINEERING_ASSIGNMENT_PROFILE_FLOOR_REDUCED'),
    ('rename', 'ENGINEERING_ASSIGNMENT_HISTORY_OUT_OF_SCOPE'),
    ('moved_base', 'ENGINEERING_ASSIGNMENT_BASE_MOVED'),
])
def test_public_inspector_refuses_changed_assignment_and_preserves_checkpoint(
        tmp_path, monkeypatch, capsys, failure, error):
    owner_profiles = ['repository', 'backend'] if failure == 'profile_floor' else None
    fixture = _inspector_fixture(tmp_path, owner_profiles=owner_profiles)
    assignment = json.loads(json.dumps(fixture['state']['execution']['engineering_assignment']))
    if failure == 'altered_plan':
        assignment['selection_sha256'] = 'b' * 64
        assignment['planning_review']['selection_sha256'] = 'b' * 64
        _save_assignment(fixture, assignment)
    elif failure in ('predecessor_rejected', 'predecessor_interrupted'):
        assignment['predecessor']['decision'] = 'rejected' if failure == 'predecessor_rejected' else 'interrupted'
        _save_assignment(fixture, assignment)
    elif failure == 'predecessor_absent':
        assignment['predecessor'] = {}
        _save_assignment(fixture, assignment)
    elif failure == 'planning_report_binding':
        assignment['planning_review']['report']['sha256'] = '0' * 64
        _save_assignment(fixture, assignment)
    elif failure == 'due_evidence_binding':
        assignment['predecessor']['due_evidence'][0]['sha256'] = '0' * 64
        _save_assignment(fixture, assignment)
    elif failure == 'moved_review':
        assignment['predecessor']['review']['reviewed_candidate'] = 'f' * 40
        _save_assignment(fixture, assignment)
    elif failure == 'missing_due_evidence':
        fixture['due_paths'][0].unlink()
    elif failure == 'unauthorized_path':
        assignment['allowed_changes'] = ['engineering/private/secret.md']
        _save_assignment(fixture, assignment)
    elif failure == 'profile_floor':
        assignment['profiles'] = ['backend']
        _save_assignment(fixture, assignment)
    elif failure == 'rename':
        fixture['git']('mv', 'scripts/worker_execution.py', 'scripts/worker_execution-moved.py')
        fixture['git']('commit', '-qm', 'unauthorized source rename')
        assignment['base'] = fixture['git']('rev-parse', 'HEAD')
        _save_assignment(fixture, assignment)
    elif failure == 'moved_base':
        fixture['git']('commit', '--allow-empty', '-qm', 'base moved unexpectedly')

    before = fixture['checkpoint'].read_bytes()
    state_before = _state_snapshot(fixture)
    result = _run_assignment_inspector(fixture, monkeypatch)
    assert result == 1
    refused = json.loads(capsys.readouterr().out)
    assert refused['result'] == 'FAIL'
    assert refused['error'] == error
    assert fixture['checkpoint'].read_bytes() == before
    assert _state_snapshot(fixture) == state_before
    assert not (fixture['state_dir'] / assignment['attempt']).exists()


def test_engineering_record_is_explicit_and_not_capsule_alias(tmp_path, capsys):
    path = tmp_path / 'engineering.md'
    path.write_text(record())
    args = argparse.Namespace(task_record=path, route='engineering', repo_root=ROOT)
    assert task.command_validate_record(args) == 0
    assert '"route":"engineering"' in capsys.readouterr().out
    args.route = 'normal'
    with pytest.raises(task.TaskControllerError, match='TASK_RECORD_INVALID'):
        task.command_validate_record(args)


@pytest.mark.parametrize('section', ['Original requirements', 'Engineering decisions', 'Source boundaries',
                                     'Proof and sequencing', 'Closeout'])
def test_missing_commented_or_fenced_section_cannot_satisfy_plan(tmp_path, section):
    path = tmp_path / 'engineering.md'
    for replacement in ['', '<!-- ## ' + section + ' -->', '```\n## ' + section + '\n```']:
        path.write_text(record().replace('## ' + section, replacement))
        with pytest.raises(task.TaskControllerError, match='TASK_RECORD_INVALID'):
            task.command_validate_record(argparse.Namespace(task_record=path, route='engineering', repo_root=ROOT))


def test_engineering_prepare_refuses_before_git_without_real_record(monkeypatch, tmp_path):
    args = task.build_parser().parse_args(['--state-dir', str(tmp_path), 'prepare', '422',
        '--task-id', 'GH-422', '--route', 'engineering', '--allowed-path', 'x', '--profile', 'repository'])
    monkeypatch.setattr(task, 'git', lambda *a, **kw: pytest.fail('Invalid engineering preparation reached Git'))
    with pytest.raises(task.TaskControllerError, match='SELECTED_ROUTE_REQUIRES_TASK_RECORD'):
        task.command_prepare(args)
    assert not list(tmp_path.iterdir())


def test_engineering_duplicate_heading_refuses(tmp_path):
    path = tmp_path / 'engineering.md'
    path.write_text(record() + '\n## Engineering decisions\nContradictory second decision.\n')
    with pytest.raises(task.TaskControllerError, match='TASK_RECORD_INVALID'):
        task.command_validate_record(argparse.Namespace(task_record=path, route='engineering', repo_root=ROOT))


def test_engineering_prepare_persists_record_identity_and_preserves_existing_checkpoint(tmp_path, monkeypatch):
    import hashlib
    import json
    specification = tmp_path / 'plan.md'
    specification.write_text(record())
    args = task.build_parser().parse_args(['--repo-root', str(ROOT), '--state-dir', str(tmp_path / 'state'),
        'prepare', '422', '--task-id', 'GH-422', '--repository', 'MitCaine/Nutrition-App',
        '--route', 'engineering', '--task-record', str(specification), '--base-sha', 'a' * 40,
        '--allowed-path', 'scripts/worker_execution.py', '--profile', 'repository'])
    # Fixture transport supplies the authenticated main; the real preparation,
    # payload, lock, transaction and durable checkpoint code are exercised.
    monkeypatch.setattr(task, 'git', lambda *a, **kw: 'a' * 40)
    monkeypatch.setattr(task, 'require_trusted_main_controller', lambda *a, **kw: None)
    assert task.command_prepare(args) == 0
    checkpoint = tmp_path / 'state/issue-422.json'
    before = checkpoint.read_bytes()
    state = json.loads(before)
    assert state['phase'] == 'PREPARED' and state['authorization']['base_sha'] == 'a' * 40
    assert state['execution']['preparation_record'] == {
        'route': 'engineering', 'path': str(specification),
        'sha256': hashlib.sha256(specification.read_bytes()).hexdigest(),
    }
    with pytest.raises(task.TaskControllerError, match='TASK_STATE_EXISTS_PRESERVE_HISTORY'):
        task.command_prepare(args)
    assert checkpoint.read_bytes() == before
