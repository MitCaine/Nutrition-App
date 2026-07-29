#!/usr/bin/env python3
"""Deterministic repository session, boundary, inventory, and privilege checks.

The tool intentionally uses only the Python standard library. PostgreSQL privilege
checks invoke psql so they use the same connection behavior as operator workflows.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps" / "backend"
CONFIG = ROOT / "scripts" / "project-audit.json"


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=check)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_config() -> dict[str, Any]:
    if not CONFIG.exists():
        return {}
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def module_path(module: str) -> Path | None:
    candidate = BACKEND / (module.replace(".", "/") + ".py")
    return candidate if candidate.exists() else None


def literal_assignments(path: Path) -> dict[str, str | None]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, str | None] = {}
    for node in tree.body:
        target_name: str | None = None
        value_node: ast.expr | None = None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target_name = node.targets[0].id
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value_node = node.value
        if (
            target_name
            and isinstance(value_node, ast.Constant)
            and (isinstance(value_node.value, str) or value_node.value is None)
        ):
            values[target_name] = value_node.value
    return values


def imported_constants(path: Path) -> dict[str, str | None]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, str | None] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        imported_path = module_path(node.module)
        if imported_path is None:
            continue
        source_values = literal_assignments(imported_path)
        for alias in node.names:
            if alias.name in source_values:
                values[alias.asname or alias.name] = source_values[alias.name]
    return values


def migration_revision(path: Path) -> tuple[str | None, str | None]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = {**imported_constants(path), **literal_assignments(path)}
    resolved: dict[str, str | None] = {}
    for node in tree.body:
        target_name: str | None = None
        value_node: ast.expr | None = None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target_name = node.targets[0].id
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value_node = node.value
        if target_name not in {"revision", "down_revision"} or value_node is None:
            continue
        if isinstance(value_node, ast.Constant) and (
            isinstance(value_node.value, str) or value_node.value is None
        ):
            resolved[target_name] = value_node.value
        elif isinstance(value_node, ast.Name):
            resolved[target_name] = values.get(value_node.id)
    return resolved.get("revision"), resolved.get("down_revision")


def migration_heads(directory: Path) -> list[str]:
    revisions: dict[str, str | None] = {}
    referenced: set[str] = set()
    for path in sorted(directory.glob("*.py")):
        if path.name == "__init__.py":
            continue
        revision, down = migration_revision(path)
        if revision:
            revisions[revision] = down
            if down:
                referenced.add(down)
    return sorted(set(revisions) - referenced)


def git_report() -> dict[str, Any]:
    inside = run(["git", "rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0:
        return {"available": False, "reason": "archive has no .git metadata"}
    branch = run(["git", "branch", "--show-current"]).stdout.strip() or "DETACHED"
    head = run(["git", "rev-parse", "--short=12", "HEAD"]).stdout.strip()
    status = run(["git", "status", "--porcelain=v1", "-uall"]).stdout.splitlines()
    return {"available": True, "branch": branch, "head": head, "status": status}


def changed_paths(status: Sequence[str]) -> list[str]:
    paths: list[str] = []
    for line in status:
        if len(line) < 4:
            continue
        value = line[3:]
        paths.extend(value.split(" -> ", 1) if " -> " in value else [value])
    return paths


def latest_phase_document() -> str | None:
    docs = list(ROOT.glob("docs/production-hardening-phase*.md"))
    if not docs:
        return None

    def key(path: Path) -> tuple[int, ...]:
        suffix = path.stem.removeprefix("production-hardening-phase")
        numbers = [int(part) for part in re.findall(r"\d+", suffix)]
        return tuple(numbers)

    return rel(max(docs, key=key))


def session_report(as_json: bool) -> int:
    app_heads = migration_heads(BACKEND / "app" / "migrations" / "versions")
    control_heads = migration_heads(BACKEND / "app" / "control_migrations" / "versions")
    git = git_report()
    payload = {
        "repository": str(ROOT),
        "git": git,
        "migration_heads": {"application": app_heads, "control": control_heads},
        "latest_phase_document": latest_phase_document(),
        "phase5c4_files": len(list(BACKEND.glob("**/*phase5c4*"))),
        "mobile_changed": bool(
            git.get("available")
            and any(
                path.startswith("apps/mobile/")
                for path in changed_paths(git.get("status", []))
            )
        ),
        "opt_in_test_markers": parse_pytest_markers(),
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("Nutrition App authoritative session report")
    print(f"repository: {ROOT}")
    if git["available"]:
        print(f"git: {git['branch']} @ {git['head']}")
        print(f"working tree entries: {len(git['status'])}")
        for line in git["status"]:
            print(f"  {line}")
    else:
        print(f"git: unavailable ({git['reason']})")
    print(f"application migration head(s): {', '.join(app_heads) or 'NONE'}")
    print(f"control migration head(s): {', '.join(control_heads) or 'NONE'}")
    print(f"latest phase document: {payload['latest_phase_document'] or 'NONE'}")
    print(f"mobile files changed: {payload['mobile_changed']}")
    print("opt-in test markers:")
    for marker in payload["opt_in_test_markers"]:
        print(f"  - {marker}")
    return 0


def parse_pytest_markers() -> list[str]:
    text = (BACKEND / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"markers\s*=\s*\[(.*?)\]", text, re.S)
    if not block:
        return []
    return re.findall(r'"([^"\n]+)"', block.group(1))


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str


def findings_exit_code(
    findings: Sequence[Finding],
    *,
    warnings_are_blocking: bool = False,
) -> int:
    blocking_levels = {"ERROR"}
    if warnings_are_blocking:
        blocking_levels.add("WARN")
    return 1 if any(finding.level in blocking_levels for finding in findings) else 0


def _configured_relative_paths(
    values: Any,
    *,
    setting: str,
) -> tuple[set[str], list[Finding]]:
    findings: list[Finding] = []
    paths: set[str] = set()
    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in values
    ):
        return paths, [
            Finding(
                "ERROR",
                "CONFIG_INVALID",
                f"{setting} must be a list of repository-relative paths",
            )
        ]
    for value in values:
        normalized = Path(value).as_posix()
        parts = Path(normalized).parts
        if (
            not normalized
            or Path(normalized).is_absolute()
            or ".." in parts
            or normalized.endswith("/")
            or any(character in normalized for character in "*?[]")
        ):
            findings.append(
                Finding(
                    "ERROR",
                    "CONFIG_INVALID",
                    f"{setting} contains invalid path {value!r}",
                )
            )
            continue
        paths.add(normalized)
    return paths, findings


def migration_head_findings(
    config: dict[str, Any],
    *,
    application_heads: Sequence[str],
    control_heads: Sequence[str],
) -> list[Finding]:
    findings: list[Finding] = []
    if len(application_heads) != 1:
        findings.append(
            Finding(
                "ERROR",
                "APP_HEAD_COUNT",
                f"expected one application head, found {list(application_heads)}",
            )
        )
    if len(control_heads) != 1:
        findings.append(
            Finding(
                "ERROR",
                "CONTROL_HEAD_COUNT",
                f"expected one control head, found {list(control_heads)}",
            )
        )
    expected_application = config.get("expected_application_heads", [])
    expected_control = config.get("expected_control_heads", [])
    if expected_application and list(application_heads) != expected_application:
        findings.append(
            Finding(
                "ERROR",
                "APP_HEAD_MISMATCH",
                f"expected {expected_application}, found {list(application_heads)}",
            )
        )
    if expected_control and list(control_heads) != expected_control:
        findings.append(
            Finding(
                "ERROR",
                "CONTROL_HEAD_MISMATCH",
                f"expected {expected_control}, found {list(control_heads)}",
            )
        )
    return findings


def placeholder_findings(
    config: dict[str, Any],
    *,
    root: Path = ROOT,
) -> list[Finding]:
    placeholders = config.get(
        "forbidden_placeholders",
        ["REPLACE_SIGNING_MESSAGE_DIGEST"],
    )
    excludes, findings = _configured_relative_paths(
        config.get("placeholder_scan_excludes", []),
        setting="placeholder_scan_excludes",
    )
    if not isinstance(placeholders, list) or not all(
        isinstance(value, str) and value for value in placeholders
    ):
        return [
            *findings,
            Finding(
                "ERROR",
                "CONFIG_INVALID",
                "forbidden_placeholders must be a list of nonempty strings",
            ),
        ]

    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(
            part in {".git", ".venv", "node_modules"} for part in path.parts
        ):
            continue
        relative = path.relative_to(root).as_posix()
        if relative in excludes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for placeholder in placeholders:
            if placeholder in text:
                findings.append(
                    Finding(
                        "ERROR",
                        "PLACEHOLDER",
                        f"{relative} contains {placeholder}",
                    )
                )
    return findings


def operator_document_contract_findings(
    config: dict[str, Any],
    *,
    root: Path = ROOT,
) -> list[Finding]:
    contracts = config.get("operator_document_contracts", {})
    if not isinstance(contracts, dict):
        return [
            Finding(
                "ERROR",
                "CONFIG_INVALID",
                "operator_document_contracts must be an object",
            )
        ]

    findings: list[Finding] = []
    for relative, contract in sorted(contracts.items()):
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(contract, dict)
        ):
            findings.append(
                Finding(
                    "ERROR",
                    "CONFIG_INVALID",
                    "operator document contract path or value is invalid",
                )
            )
            continue
        required = contract.get("required", [])
        forbidden = contract.get("forbidden", [])
        if not all(
            isinstance(values, list)
            and all(isinstance(value, str) and value for value in values)
            for values in (required, forbidden)
        ):
            findings.append(
                Finding(
                    "ERROR",
                    "CONFIG_INVALID",
                    f"operator document contract for {relative} is invalid",
                )
            )
            continue
        path = root / relative
        if not path.is_file():
            findings.append(
                Finding(
                    "ERROR",
                    "OPERATOR_DOCUMENT_MISSING",
                    relative,
                )
            )
            continue
        text_value = path.read_text(encoding="utf-8")
        for value in required:
            if value not in text_value:
                findings.append(
                    Finding(
                        "ERROR",
                        "OPERATOR_DOCUMENT_CONTRACT_MISSING",
                        f"{relative} does not contain {value!r}",
                    )
                )
        for value in forbidden:
            if value in text_value:
                findings.append(
                    Finding(
                        "ERROR",
                        "OPERATOR_DOCUMENT_CONTRACT_STALE",
                        f"{relative} contains stale statement {value!r}",
                    )
                )
    return findings


def check_boundaries(config: dict[str, Any] | None = None) -> list[Finding]:
    config = load_config() if config is None else config
    findings: list[Finding] = []
    app_heads = migration_heads(BACKEND / "app" / "migrations" / "versions")
    control_heads = migration_heads(BACKEND / "app" / "control_migrations" / "versions")
    findings.extend(
        migration_head_findings(
            config,
            application_heads=app_heads,
            control_heads=control_heads,
        )
    )

    widths = config.get("control_revision_max_length", 32)
    for path in sorted(
        (BACKEND / "app" / "control_migrations" / "versions").glob("*.py")
    ):
        revision, _ = migration_revision(path)
        if revision and len(revision) > widths:
            findings.append(
                Finding(
                    "ERROR",
                    "CONTROL_REVISION_WIDTH",
                    f"{revision!r} is {len(revision)} chars; max {widths}",
                )
            )

    git = git_report()
    forbidden = config.get("forbidden_change_prefixes", ["apps/mobile/"])
    if git.get("available"):
        for path in changed_paths(git["status"]):
            for prefix in forbidden:
                if path.startswith(prefix):
                    findings.append(Finding("ERROR", "FORBIDDEN_CHANGE", path))

    operational_patterns = config.get("operational_migration_forbidden_tokens", [])
    for directory in [
        BACKEND / "app" / "control_migrations" / "versions",
        BACKEND / "app" / "migrations" / "versions",
    ]:
        for path in sorted(directory.glob("*.py")):
            name = path.name.lower()
            if not any(
                token in name
                for token in ("phase5c4", "activation", "cutback", "recovery")
            ):
                continue
            text = path.read_text(encoding="utf-8").lower()
            for token in operational_patterns:
                if token.lower() in text:
                    findings.append(
                        Finding(
                            "WARN",
                            "DOMAIN_TOKEN_IN_OPS_MIGRATION",
                            f"{rel(path)} contains {token!r}",
                        )
                    )

    findings.extend(placeholder_findings(config))
    findings.extend(operator_document_contract_findings(config))
    return findings


def _print_findings(findings: Sequence[Finding]) -> None:
    if not findings:
        print("PASS: no violations found")
    for finding in findings:
        print(f"{finding.level} {finding.code}: {finding.message}")


def boundaries(as_json: bool) -> int:
    config = load_config()
    findings = check_boundaries(config)
    if as_json:
        print(
            json.dumps(
                [finding.__dict__ for finding in findings], indent=2, sort_keys=True
            )
        )
    else:
        print("Nutrition App phase-boundary validation")
        _print_findings(findings)
    return findings_exit_code(
        findings,
        warnings_are_blocking=bool(config.get("warnings_are_blocking", False)),
    )


def extract_constants(path: Path, names: Iterable[str]) -> dict[str, str]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for name in names:
        match = re.search(
            rf'^{re.escape(name)}\s*(?::[^=]+)?=\s*["\']([^"\']+)', text, re.M
        )
        if match:
            result[name] = match.group(1)
    return result


def build_control_inventory() -> dict[str, Any]:
    operators = BACKEND / "app" / "operators"
    migrations = BACKEND / "app" / "control_migrations" / "versions"
    purposes: list[dict[str, str]] = []
    roles: set[str] = set()
    sql_functions: set[str] = set()
    sql_tables: set[str] = set()
    transitions: set[str] = set()

    for path in sorted(operators.glob("phase5c4*.py")):
        text = path.read_text(encoding="utf-8")
        for name, value in literal_assignments(path).items():
            if isinstance(value, str) and re.fullmatch(
                r"[A-Z][A-Z0-9_]*(?:PURPOSE|VERSION)", name
            ):
                purposes.append({"file": rel(path), "constant": name, "value": value})
        roles.update(re.findall(r'["\'](nutrition_[a-z0-9_]+)["\']', text))
        transitions.update(re.findall(r'["\']([A-Z][A-Z0-9_]{4,})["\']', text))

    for path in sorted(migrations.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        sql_functions.update(
            re.findall(
                r"CREATE(?: OR REPLACE)? FUNCTION\s+([a-zA-Z0-9_.]+)", text, re.I
            )
        )
        sql_tables.update(
            re.findall(
                r"CREATE TABLE(?: IF NOT EXISTS)?\s+([a-zA-Z0-9_.]+)", text, re.I
            )
        )
        roles.update(
            re.findall(
                r"\b(?:GRANT|REVOKE).*?\b(?:TO|FROM)\s+([a-zA-Z0-9_]+)", text, re.I
            )
        )

    payload = {
        "application_heads": migration_heads(
            BACKEND / "app" / "migrations" / "versions"
        ),
        "control_heads": migration_heads(migrations),
        "authorization_contract_constants": sorted(
            purposes,
            key=lambda item: (item["file"], item["constant"]),
        ),
        "roles": sorted(role for role in roles if role.startswith("nutrition_")),
        "sql_functions": sorted(sql_functions),
        "sql_tables": sorted(sql_tables),
        "state_tokens": sorted(
            token
            for token in transitions
            if any(
                key in token
                for key in (
                    "ACTIVE",
                    "CUTBACK",
                    "CLOSE",
                    "PROMOTION",
                    "VERIFIED",
                    "INTERVENTION",
                    "MIGRATION",
                )
            )
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["inventory_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


def render_control_inventory() -> bytes:
    return (
        json.dumps(build_control_inventory(), indent=2, sort_keys=True) + "\n"
    ).encode()


def _write_bytes_if_changed(path: Path, document: bytes) -> bool:
    before = path.read_bytes() if path.exists() else None
    if before == document:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(document)
    os.replace(temporary, path)
    return True


def control_inventory(as_json: bool, output: Path | None) -> int:
    rendered = render_control_inventory()
    if output:
        changed = _write_bytes_if_changed(output, rendered)
        action = "wrote" if changed else "verified"
        print(f"{action} {output}")
    else:
        del as_json
        sys.stdout.buffer.write(rendered)
    return 0


def _configured_inventory_path(
    config: dict[str, Any],
) -> tuple[Path | None, list[Finding]]:
    configured = config.get("generated_control_inventory")
    if not isinstance(configured, str):
        return None, [
            Finding(
                "ERROR",
                "CONFIG_INVALID",
                "generated_control_inventory must be a repository-relative path",
            )
        ]
    paths, findings = _configured_relative_paths(
        [configured],
        setting="generated_control_inventory",
    )
    if findings or len(paths) != 1:
        return None, findings
    relative = next(iter(paths))
    return ROOT / relative, []


def verify_control_inventory(config: dict[str, Any] | None = None) -> int:
    config = load_config() if config is None else config
    output, findings = _configured_inventory_path(config)
    if output is None:
        _print_findings(findings)
        return 1
    expected = render_control_inventory()
    changed = _write_bytes_if_changed(output, expected)
    git = git_report()
    tracked = False
    if git.get("available"):
        tracked = (
            run(
                ["git", "ls-files", "--error-unmatch", "--", rel(output)],
            ).returncode
            == 0
        )
    if changed and (tracked or not git.get("available")):
        print(
            "ERROR GENERATED_INVENTORY_DRIFT: "
            f"regenerated stale committed artifact {rel(output)}"
        )
        return 1
    if changed:
        print(f"GENERATED: {rel(output)} (new committed evidence artifact)")
    else:
        print(f"PASS: {rel(output)} is deterministic and current")
    inventory_digest = json.loads(expected)["inventory_sha256"]
    print(f"inventory sha256: {inventory_digest}")
    return 0


PRIVILEGE_QUERY = r"""
WITH role_rows AS (
  SELECT jsonb_build_object(
    'name', rolname,
    'superuser', rolsuper,
    'inherit', rolinherit,
    'createrole', rolcreaterole,
    'createdb', rolcreatedb,
    'canlogin', rolcanlogin,
    'replication', rolreplication,
    'bypassrls', rolbypassrls
  ) AS item
  FROM pg_roles
  WHERE rolname LIKE 'nutrition_%'
  ORDER BY rolname
), membership_rows AS (
  SELECT jsonb_build_object('role', parent.rolname, 'member', child.rolname) AS item
  FROM pg_auth_members m
  JOIN pg_roles parent ON parent.oid = m.roleid
  JOIN pg_roles child ON child.oid = m.member
  WHERE parent.rolname LIKE 'nutrition_%' OR child.rolname LIKE 'nutrition_%'
  ORDER BY parent.rolname, child.rolname
), function_rows AS (
  SELECT jsonb_build_object(
    'schema', n.nspname,
    'name', p.proname,
    'identity_args', pg_get_function_identity_arguments(p.oid),
    'owner', owner.rolname,
    'acl', COALESCE(p.proacl::text, '')
  ) AS item
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
  JOIN pg_roles owner ON owner.oid = p.proowner
  WHERE n.nspname LIKE 'phase5c4%'
  ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
)
SELECT jsonb_build_object(
  'roles', COALESCE((SELECT jsonb_agg(item) FROM role_rows), '[]'::jsonb),
  'memberships', COALESCE((SELECT jsonb_agg(item) FROM membership_rows), '[]'::jsonb),
  'functions', COALESCE((SELECT jsonb_agg(item) FROM function_rows), '[]'::jsonb)
)::text;
"""


def collect_privileges(database_url: str) -> dict[str, Any]:
    result = run(
        [
            "psql",
            database_url,
            "-X",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            PRIVILEGE_QUERY,
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "psql privilege query failed")
    return json.loads(result.stdout.strip())


def privilege_diff(
    database_url: str, expected: Path | None, write_expected: Path | None
) -> int:
    actual = collect_privileges(database_url)
    if write_expected:
        write_expected.parent.mkdir(parents=True, exist_ok=True)
        write_expected.write_text(
            json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote privilege manifest {write_expected}")
        return 0
    if expected is None:
        print(json.dumps(actual, indent=2, sort_keys=True))
        return 0
    wanted = json.loads(expected.read_text(encoding="utf-8"))
    if actual == wanted:
        print("PASS: PostgreSQL role/function privilege manifest matches")
        return 0
    print("FAIL: PostgreSQL privilege manifest drift", file=sys.stderr)
    print(json.dumps({"expected": wanted, "actual": actual}, indent=2, sort_keys=True))
    return 1


Check = tuple[str, Callable[[], int]]


def run_independent_checks(checks: Sequence[Check]) -> int:
    """Run every independent check and return one final blocking status."""

    failed: list[str] = []
    for label, operation in checks:
        print(f"=== {label} ===")
        try:
            result = operation()
        except Exception as exc:  # pragma: no cover - defensive orchestration guard.
            print(f"ERROR TOOLING_EXCEPTION: {type(exc).__name__}: {exc}")
            result = 1
        if result:
            failed.append(label)
    print("=== Pre-commit summary ===")
    if failed:
        print(f"BLOCKED: {', '.join(failed)}")
        return 1
    print("PASS: all repository-owned mechanical checks completed")
    return 0


def git_diff_check() -> int:
    git = git_report()
    if not git.get("available"):
        print("WARN GIT_UNAVAILABLE: git diff --check not run")
        return 0
    result = run(["git", "diff", "--check"])
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        print("ERROR GIT_DIFF_CHECK: git diff --check failed")
        return 1
    print("PASS: git diff --check")
    return 0


def focused_audit_tests(config: dict[str, Any] | None = None) -> int:
    config = load_config() if config is None else config
    configured, findings = _configured_relative_paths(
        config.get("focused_audit_tests", []),
        setting="focused_audit_tests",
    )
    if findings or not configured:
        _print_findings(
            findings
            or [
                Finding(
                    "ERROR",
                    "CONFIG_INVALID",
                    "focused_audit_tests must contain at least one test path",
                )
            ]
        )
        return 1
    missing = [path for path in sorted(configured) if not (ROOT / path).is_file()]
    if missing:
        for path in missing:
            print(f"ERROR FOCUSED_TEST_MISSING: {path}")
        return 1
    backend_tests = [
        (ROOT / path).relative_to(BACKEND).as_posix()
        for path in sorted(configured)
        if (ROOT / path).is_relative_to(BACKEND)
    ]
    if len(backend_tests) != len(configured):
        print("ERROR CONFIG_INVALID: focused audit tests must be backend test paths")
        return 1
    result = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--noconftest",
            "-q",
            *backend_tests,
        ],
        cwd=BACKEND,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        print("ERROR FOCUSED_AUDIT_TESTS: focused tooling tests failed")
        return 1
    print("PASS: focused audit-tooling tests")
    return 0


def report_opt_in_suites(config: dict[str, Any] | None = None) -> int:
    config = load_config() if config is None else config
    suites = config.get("pre_commit_opt_in_suites", [])
    if not isinstance(suites, list) or not all(
        isinstance(item, str) and item for item in suites
    ):
        print("ERROR CONFIG_INVALID: pre_commit_opt_in_suites must be a list of names")
        return 1
    if not suites:
        print("NOT RUN: no opt-in suites configured")
        return 0
    for suite in suites:
        print(f"NOT RUN (opt-in): {suite}")
    return 0


def pre_commit() -> int:
    config = load_config()
    return run_independent_checks(
        [
            ("Authoritative session state", lambda: session_report(False)),
            ("Repository boundaries and migration heads", lambda: boundaries(False)),
            (
                "Deterministic control-plane inventory",
                lambda: verify_control_inventory(config),
            ),
            ("Git whitespace check", git_diff_check),
            ("Focused audit-tooling tests", lambda: focused_audit_tests(config)),
            ("Expensive suite status", lambda: report_opt_in_suites(config)),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    session = sub.add_parser(
        "session", help="print deterministic session/handoff state"
    )
    session.add_argument("--json", action="store_true")
    boundary = sub.add_parser("boundaries", help="validate mechanical phase boundaries")
    boundary.add_argument("--json", action="store_true")
    inventory = sub.add_parser(
        "inventory", help="generate static control-plane inventory"
    )
    inventory.add_argument("--json", action="store_true")
    inventory.add_argument("--output", type=Path)
    privileges = sub.add_parser(
        "privileges", help="collect or diff PostgreSQL role/function privileges"
    )
    privileges.add_argument(
        "--database-url", default=os.environ.get("CONTROL_DATABASE_URL")
    )
    privileges.add_argument("--expected", type=Path)
    privileges.add_argument("--write-expected", type=Path)
    sub.add_parser(
        "pre-commit",
        help="run repository-owned mechanical checks and aggregate failures",
    )
    args = parser.parse_args()

    if args.command == "session":
        return session_report(args.json)
    if args.command == "boundaries":
        return boundaries(args.json)
    if args.command == "inventory":
        return control_inventory(args.json, args.output)
    if args.command == "privileges":
        if not args.database_url:
            parser.error("privileges requires --database-url or CONTROL_DATABASE_URL")
        try:
            return privilege_diff(args.database_url, args.expected, args.write_expected)
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    if args.command == "pre-commit":
        return pre_commit()
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
