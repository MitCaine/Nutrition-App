from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "project-audit.py"
SESSION_END = ROOT / "scripts" / "session-end.sh"

SPEC = importlib.util.spec_from_file_location("nutrition_project_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_session_json_reports_current_migration_heads() -> None:
    result = _run("session", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["migration_heads"]["application"] == ["0024_recipe_log_current_provenance"]
    assert payload["migration_heads"]["control"] == [
        "ops_0011_phase5c4_recovery_audit"
    ]
    assert payload["latest_phase_document"].endswith(
        "docs/historical/releases/production-hardening-phase5c4.9.md"
    )


def test_inventory_is_deterministic() -> None:
    first = _run("inventory", "--json")
    second = _run("inventory", "--json")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["application_heads"] == ["0024_recipe_log_current_provenance"]
    assert payload["control_heads"] == ["ops_0011_phase5c4_recovery_audit"]
    assert len(payload["inventory_sha256"]) == 64


def test_boundaries_accepts_completed_cutback_vector() -> None:
    result = _run("boundaries", "--json")
    assert result.returncode == 0
    findings = json.loads(result.stdout)
    assert all(finding["code"] != "PLACEHOLDER" for finding in findings)


def _placeholder_config(*excludes: str) -> dict[str, object]:
    return {
        "forbidden_placeholders": ["REPLACE_SIGNING_MESSAGE_DIGEST"],
        "placeholder_scan_excludes": list(excludes),
    }


def test_configured_placeholder_exclusion_is_exact(tmp_path: Path) -> None:
    excluded = tmp_path / "excluded.py"
    excluded.write_text("REPLACE_SIGNING_MESSAGE_DIGEST\n", encoding="utf-8")
    visible = tmp_path / "visible.py"
    visible.write_text("safe\n", encoding="utf-8")

    findings = AUDIT.placeholder_findings(
        _placeholder_config("excluded.py"),
        root=tmp_path,
    )

    assert findings == []


def test_real_placeholder_is_detected(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "unfinished.py"
    target.parent.mkdir()
    target.write_text(
        "value = 'REPLACE_SIGNING_MESSAGE_DIGEST'\n",
        encoding="utf-8",
    )

    findings = AUDIT.placeholder_findings(_placeholder_config(), root=tmp_path)

    assert [(finding.level, finding.code, finding.message) for finding in findings] == [
        (
            "ERROR",
            "PLACEHOLDER",
            "tests/unfinished.py contains REPLACE_SIGNING_MESSAGE_DIGEST",
        )
    ]


def test_audit_implementation_config_and_fixture_are_self_excluded(
    tmp_path: Path,
) -> None:
    excluded_paths = (
        "scripts/project-audit.py",
        "scripts/project-audit.json",
        "apps/backend/tests/test_project_audit.py",
    )
    for relative in excluded_paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("REPLACE_SIGNING_MESSAGE_DIGEST\n", encoding="utf-8")

    findings = AUDIT.placeholder_findings(
        _placeholder_config(*excluded_paths),
        root=tmp_path,
    )

    assert findings == []


def test_operator_document_contract_detects_missing_and_stale_statements(
    tmp_path: Path,
) -> None:
    document = tmp_path / "docs" / "operator.md"
    document.parent.mkdir()
    document.write_text("old control head\n", encoding="utf-8")
    config = {
        "operator_document_contracts": {
            "docs/operator.md": {
                "required": ["current control head"],
                "forbidden": ["old control head"],
            }
        }
    }

    findings = AUDIT.operator_document_contract_findings(config, root=tmp_path)

    assert [(finding.code, finding.message) for finding in findings] == [
        (
            "OPERATOR_DOCUMENT_CONTRACT_MISSING",
            "docs/operator.md does not contain 'current control head'",
        ),
        (
            "OPERATOR_DOCUMENT_CONTRACT_STALE",
            "docs/operator.md contains stale statement 'old control head'",
        ),
    ]


@pytest.mark.parametrize(
    ("findings", "warnings_are_blocking", "expected"),
    [
        ([AUDIT.Finding("WARN", "EXPECTED", "warning")], False, 0),
        ([AUDIT.Finding("ERROR", "EXPECTED", "error")], False, 1),
        ([AUDIT.Finding("WARN", "EXPECTED", "warning")], True, 1),
    ],
)
def test_finding_severity_controls_exit_status(
    findings: list[object],
    warnings_are_blocking: bool,
    expected: int,
) -> None:
    assert (
        AUDIT.findings_exit_code(
            findings,
            warnings_are_blocking=warnings_are_blocking,
        )
        == expected
    )


def test_multiple_pre_commit_failures_are_all_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    called: list[str] = []

    def outcome(name: str, result: int):
        def operation() -> int:
            called.append(name)
            return result

        return operation

    result = AUDIT.run_independent_checks(
        [
            ("first", outcome("first", 1)),
            ("second", outcome("second", 0)),
            ("third", outcome("third", 1)),
        ]
    )

    assert result == 1
    assert called == ["first", "second", "third"]
    output = capsys.readouterr().out
    assert "BLOCKED: first, third" in output


def test_migration_head_validation_checks_count_and_configured_identity() -> None:
    matching = AUDIT.migration_head_findings(
        {
            "expected_application_heads": ["app_head"],
            "expected_control_heads": ["control_head"],
        },
        application_heads=["app_head"],
        control_heads=["control_head"],
    )
    assert matching == []

    mismatched = AUDIT.migration_head_findings(
        {
            "expected_application_heads": ["expected_app"],
            "expected_control_heads": ["expected_control"],
        },
        application_heads=["actual_app"],
        control_heads=["actual_control", "second_control"],
    )
    assert {finding.code for finding in mismatched} == {
        "APP_HEAD_MISMATCH",
        "CONTROL_HEAD_COUNT",
        "CONTROL_HEAD_MISMATCH",
    }


def test_changed_paths_preserve_both_sides_of_a_rename() -> None:
    assert AUDIT.changed_paths(
        [
            " M docs/example.md",
            "R  docs/old.md -> apps/mobile/new.tsx",
        ]
    ) == [
        "docs/example.md",
        "docs/old.md",
        "apps/mobile/new.tsx",
    ]


def test_inventory_artifact_generation_is_deterministic_and_detects_tracked_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "evidence" / "control-plane-inventory.json"
    document = b'{"inventory_sha256":"abc"}\n'
    monkeypatch.setattr(AUDIT, "ROOT", tmp_path)
    monkeypatch.setattr(AUDIT, "render_control_inventory", lambda: document)
    monkeypatch.setattr(
        AUDIT,
        "build_control_inventory",
        lambda: {"inventory_sha256": "abc"},
    )
    monkeypatch.setattr(AUDIT, "git_report", lambda: {"available": True})

    tracked = False

    def fake_run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0 if tracked else 1, "", "")

    monkeypatch.setattr(AUDIT, "run", fake_run)
    config = {"generated_control_inventory": "evidence/control-plane-inventory.json"}

    assert AUDIT.verify_control_inventory(config) == 0
    assert output.read_bytes() == document
    assert AUDIT.verify_control_inventory(config) == 0

    tracked = True
    output.write_bytes(b"stale\n")
    assert AUDIT.verify_control_inventory(config) == 1
    assert output.read_bytes() == document


def test_pre_commit_orchestrates_every_required_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    def record(name: str, result: int = 0):
        def operation(*_args: object, **_kwargs: object) -> int:
            called.append(name)
            return result

        return operation

    monkeypatch.setattr(AUDIT, "load_config", lambda: {})
    monkeypatch.setattr(AUDIT, "session_report", record("session"))
    monkeypatch.setattr(AUDIT, "boundaries", record("boundaries", 1))
    monkeypatch.setattr(AUDIT, "verify_control_inventory", record("inventory"))
    monkeypatch.setattr(AUDIT, "git_diff_check", record("git"))
    monkeypatch.setattr(AUDIT, "focused_audit_tests", record("tests"))
    monkeypatch.setattr(AUDIT, "report_opt_in_suites", record("opt-in"))

    assert AUDIT.pre_commit() == 1
    assert called == [
        "session",
        "boundaries",
        "inventory",
        "git",
        "tests",
        "opt-in",
    ]


def test_session_end_executes_pre_commit_for_exact_exit_propagation() -> None:
    source = SESSION_END.read_text(encoding="utf-8")
    assert 'exec "$ROOT/scripts/project-audit.sh" pre-commit "$@"' in source
    assert "status=" not in source
