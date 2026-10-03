"""Canonical backend checks, loaded from installed trusted source for qualification."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

BASELINE_MARKER_EXPRESSION = (
    "not postgres_concurrency and not phase5c_performance_t0 and "
    "not phase5c4_control_postgres and not phase5c4_minio and "
    "not phase5c4_docker_integration"
)
POSTGRES_TEST_FILES = (
    "tests/test_postgres_test_support.py",
    "tests/test_log_concurrency_postgres.py",
    "tests/test_graph_restart_idempotency_postgres.py",
    "tests/test_food_nutrient_integrity_postgres.py",
    "tests/test_food_nutrient_integrity_migration_postgres.py",
    "tests/test_e4_01_complete_persistence_postgres.py",
    "tests/test_e4_02_complete_mutation_postgres.py",
    "tests/test_e4_03_complete_invalidation_postgres.py",
    "tests/test_e4_04_history_range_postgres.py",
    "tests/test_recipe_duplication_postgres.py",
    "tests/test_e4_16_history_parity_postgres.py",
)
SCHEMA_PREFIXES = (
    "test_pg_support_", "test_phase3n_", "test_graph_restart_idem_",
    "test_food_nutrient_integrity_", "e4_02_complete_", "e4_03_",
    "e4_04_history_range_", "test_recipe_duplicate_", "e4_16_history_parity_",
)
DATABASE_PREFIXES = ("test_e4_01_complete_persistence_", "test_food_nutrient_migration_")
MARKERS = (
    "postgres_concurrency: requires a reachable PostgreSQL database",
    "phase5c_performance_t0: explicitly runs the full T0 performance fixture",
    "phase5c4_control_postgres: requires an isolated PostgreSQL 16 control database",
    "phase5c4_minio: requires a disposable object-lock-enabled MinIO server",
    "phase5c4_docker_integration: requires Docker control-plane infrastructure",
)


def candidate_backend(root: Path, sha: str | None) -> Path:
    root = root.resolve(strict=True)
    backend = root / "apps/backend"
    if not backend.is_dir():
        raise ValueError("BACKEND_CANDIDATE_ROOT_INVALID")
    if sha is not None:
        if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
            raise ValueError("BACKEND_CANDIDATE_SHA_INVALID")
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
            env={key: value for key, value in os.environ.items()
                 if key in {"PATH", "HOME", "SYSTEMROOT", "TMPDIR"}}
                 | {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
        )
        if result.stdout.strip() != sha:
            raise ValueError("BACKEND_CANDIDATE_SHA_MISMATCH")
    return backend


def pytest_environment(postgresql: bool) -> dict[str, str]:
    allowed = {"PATH", "HOME", "SYSTEMROOT", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
    if postgresql:
        env["REQUIRE_POSTGRES_TESTS"] = "1"
        env["NUTRITION_TEST_POSTGRES_URL"] = os.environ["NUTRITION_TEST_POSTGRES_URL"]
    return env


def isolated_account():
    """Only trusted jobs request this account; candidate tests cannot choose it."""
    requested = os.environ.get("NUTRITION_BACKEND_TEST_USER")
    if requested is None:
        return None
    if sys.platform != "linux" or requested != "nutrition-candidate":
        raise ValueError("BACKEND_TEST_IDENTITY_UNSUPPORTED")
    import pwd

    account = pwd.getpwnam(requested)
    if account.pw_uid in {0, os.getuid()}:
        raise ValueError("BACKEND_TEST_IDENTITY_NOT_ISOLATED")
    temporary = Path(os.environ["NUTRITION_BACKEND_TEST_TMPDIR"]).resolve(strict=True)
    info = temporary.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid
            or info.st_mode & 0o077):
        raise ValueError("BACKEND_TEST_TEMP_NOT_PRIVATE")
    return account, temporary


def runtime_paths() -> list[Path]:
    """Exact selected executable/import tree, aliases and replacement ancestors."""
    prefix = Path(sys.base_prefix).resolve(strict=True)
    if sys.platform != "linux" or prefix == Path("/") or sys.prefix != sys.base_prefix:
        raise ValueError("BACKEND_RUNTIME_LAYOUT_UNSUPPORTED")
    def literal_path(raw):
        logical = Path(raw)
        if (not logical.is_absolute() or ".." in logical.parts
                or not logical.is_relative_to(prefix)):
            raise ValueError("BACKEND_RUNTIME_LITERAL_OUTSIDE_PREFIX")
        return logical
    # Validate the literal launcher before trusting another executable probe.
    literal_path(sys.executable)
    imported = subprocess.run([sys.executable, "-I", "-B", "-c", "import json,sys; print(json.dumps(sys.path))"], check=True, capture_output=True, text=True)
    import_paths = json.loads(imported.stdout)
    if not isinstance(import_paths, list) or any(not isinstance(path, str) for path in import_paths):
        raise ValueError("BACKEND_RUNTIME_IMPORT_PATHS_INVALID")
    for raw in [sys.executable, *import_paths]:
        target = literal_path(raw).resolve(strict=False)
        if not target.is_relative_to(prefix):
            raise ValueError("BACKEND_RUNTIME_IMPORT_OUTSIDE_PREFIX")
    paths = {prefix, *prefix.parents}
    def inaccessible(error):
        raise error
    for directory, directories, files in os.walk(prefix, followlinks=False, onerror=inaccessible):
        for raw in [directory, *[str(Path(directory) / name) for name in directories + files]]:
            logical = Path(raw)
            target = logical.resolve(strict=True)
            if not target.is_relative_to(prefix):
                raise ValueError("BACKEND_RUNTIME_ALIAS_OUTSIDE_PREFIX")
            if not (target.is_dir() or target.is_file()):
                raise ValueError("BACKEND_RUNTIME_SPECIAL_FILE")
            # Hardlinks can name an inode outside the selected runtime boundary.
            if target.is_file() and target.stat().st_nlink != 1:
                raise ValueError("BACKEND_RUNTIME_HARDLINK_UNSUPPORTED")
            paths.update((logical, target, *logical.parents, *target.parents))
    return sorted(paths)


def runtime_access(account, paths: list[Path]) -> list[list[bool]]:
    # Trusted script/data only; candidate code is not imported by this probe.
    code = ("import json,os,sys; paths=json.load(sys.stdin); "
            "json.dump([[os.access(p,m) for m in (os.R_OK,os.W_OK,os.X_OK)] "
            "for p in paths],sys.stdout)")
    command = ["/usr/bin/sudo", "-n", "-u", account.pw_name, "--", "/usr/bin/env", "-i",
               sys.executable, "-I", "-B", "-c", code]
    completed = subprocess.run(command, input=json.dumps([str(path) for path in paths]),
                               capture_output=True, text=True, check=True)
    permissions = json.loads(completed.stdout)
    if (not isinstance(permissions, list) or len(permissions) != len(paths)
            or any(not isinstance(row, list) or len(row) != 3
                   or any(type(value) is not bool for value in row) for row in permissions)):
        raise ValueError("BACKEND_RUNTIME_PROBE_INVALID")
    return permissions


def assert_runtime_confined(account) -> None:
    paths = runtime_paths()
    if any(path.stat().st_uid == account.pw_uid for path in paths):
        raise ValueError("BACKEND_RUNTIME_CHILD_OWNED")
    if any(row[1] for row in runtime_access(account, paths)):
        raise ValueError("BACKEND_RUNTIME_WRITABLE")


def default_runtime_acl(directory: Path, account) -> str | None:
    """Preserve this child's effective inherited R/X; never expand an ACL mask."""
    output = subprocess.run(["/usr/bin/getfacl", "-cpn", "--", str(directory)],
                            check=True, capture_output=True, text=True).stdout
    entries = {}
    for line in output.splitlines():
        if not line.startswith("default:"):
            continue
        fields = line.split("#", 1)[0].strip().split(":")
        if len(fields) != 4 or fields[1] not in {"user", "group", "mask", "other"}:
            raise ValueError("BACKEND_RUNTIME_DEFAULT_ACL_INVALID")
        kind, qualifier, text = fields[1:]
        if qualifier and (kind not in {"user", "group"} or not qualifier.isdecimal()):
            raise ValueError("BACKEND_RUNTIME_DEFAULT_ACL_INVALID")
        if re.fullmatch(r"[r-][w-][x-]", text) is None or (kind, qualifier) in entries:
            raise ValueError("BACKEND_RUNTIME_DEFAULT_ACL_INVALID")
        entries[kind, qualifier] = (4 if text[0] == "r" else 0) | (2 if text[1] == "w" else 0) | (1 if text[2] == "x" else 0)
    if not entries:
        return None
    if not {("user", ""), ("group", ""), ("other", "")} <= entries.keys():
        raise ValueError("BACKEND_RUNTIME_DEFAULT_ACL_INVALID")
    if any(qualifier for kind, qualifier in entries if kind in {"user", "group"}) and ("mask", "") not in entries:
        raise ValueError("BACKEND_RUNTIME_DEFAULT_ACL_INVALID")
    mask = entries.get(("mask", ""), entries["group", ""])
    named = entries.get(("user", str(account.pw_uid)))
    if named is not None:
        # Retain raw R/X as well as effective bits for every inherited creation mode.
        inherited = named & 5
    else:
        # Runtime files are materialized by this trusted caller, never the child.
        if account.pw_uid == os.getuid():
            raise ValueError("BACKEND_RUNTIME_DEFAULT_OWNER_UNSUPPORTED")
        groups = set(os.getgrouplist(account.pw_name, account.pw_gid))
        info = directory.stat()
        future_gid = info.st_gid if info.st_mode & stat.S_ISGID else os.getgid()
        matches = [entries["group", ""]] if future_gid in groups else []
        matches.extend(bits for (kind, gid), bits in entries.items()
                       if kind == "group" and gid and int(gid) in groups)
        effective = 0
        if matches:
            for bits in matches:
                effective |= bits
            effective &= mask
        else:
            effective = entries["other", ""]
        inherited = effective & 5
        if inherited & ~mask:
            # Adding a named entry cannot preserve other-class rights without
            # expanding a mask and potentially granting other principals rights.
            raise ValueError("BACKEND_RUNTIME_DEFAULT_MASK_UNSUPPORTED")
    return ("r" if inherited & 4 else "-") + "-" + ("x" if inherited & 1 else "-")


def protect_runtime(account) -> None:
    """Trusted installed provisioning only; remove this child's writes, never add reads."""
    if not all(Path(path).is_file() for path in ("/usr/bin/setfacl", "/usr/bin/getfacl")):
        raise ValueError("BACKEND_RUNTIME_ACL_TOOL_MISSING")
    paths = runtime_paths()
    if any(path.stat().st_uid == account.pw_uid for path in paths):
        raise ValueError("BACKEND_RUNTIME_CHILD_OWNED")
    def identity(path):
        info = path.lstat()
        return (str(path.resolve(strict=True)), info.st_dev, info.st_ino, info.st_mode,
                info.st_uid, info.st_gid, info.st_nlink)
    snapshot = [identity(path) for path in paths]
    before = runtime_access(account, paths)
    if runtime_paths() != paths or [identity(path) for path in paths] != snapshot:
        raise ValueError("BACKEND_RUNTIME_SETUP_CHANGED")
    directories = sorted({path.resolve(strict=True) for path in paths if path.is_dir() and path.is_relative_to(Path(sys.base_prefix).resolve(strict=True))})
    defaults = {}
    for directory in directories:
        permission = default_runtime_acl(directory, account)
        if permission is not None:
            defaults.setdefault(permission, []).append(str(directory))
    if runtime_paths() != paths or [identity(path) for path in paths] != snapshot:
        raise ValueError("BACKEND_RUNTIME_SETUP_CHANGED")
    groups = {}
    for path, (read, _write, execute) in zip(paths, before):
        # Physical targets only; modifying a symlink ACL would follow it implicitly.
        target = path.resolve(strict=True)
        permission = ("r" if read else "-") + "-" + ("x" if execute else "-")
        groups.setdefault(permission, set()).add(str(target))
    for permission, targets in groups.items():
        ordered = sorted(targets)
        for start in range(0, len(ordered), 128):
            # -n preserves existing masks, preventing expansion of other principals.
            subprocess.run(["/usr/bin/sudo", "-n", "--", "/usr/bin/setfacl", "-n", "-m",
                            f"u:{account.pw_uid}:{permission}", "--", *ordered[start:start + 128]], check=True)
    # Only existing default policies change; masks and other entries stay intact.
    for permission, directories in defaults.items():
        for start in range(0, len(directories), 128):
            subprocess.run(["/usr/bin/sudo", "-n", "--", "/usr/bin/setfacl", "-n", "-m",
                            f"d:u:{account.pw_uid}:{permission}", "--", *directories[start:start + 128]], check=True)
    after = runtime_access(account, paths)
    if after != [[read, False, execute] for read, _write, execute in before]:
        raise ValueError("BACKEND_RUNTIME_ACL_NOT_CONFINED")
    assert_runtime_confined(account)


def run_pytest(backend: Path, postgresql: bool, extra: list[str]) -> int:
    # /dev/null prevents candidate configuration selecting/deselecting the gate.
    argv = [sys.executable, "-I", "-m", "pytest", "-c", os.devnull,
            "--rootdir", str(backend), "--confcutdir", str(backend),
            "--strict-markers", "-o", "addopts=", "-o", f"pythonpath={backend}",
            "-o", "markers=" + "\n".join(MARKERS), "-p", "no:cacheprovider"]
    if postgresql:
        argv.extend(["-q", *POSTGRES_TEST_FILES])
    else:
        argv.extend(["-m", BASELINE_MARKER_EXPRESSION, "tests", *extra])
    env = pytest_environment(postgresql)
    isolation = isolated_account()
    if isolation is not None:
        account, temporary = isolation
        assert_runtime_confined(account)
        env.update(HOME=account.pw_dir, TMPDIR=str(temporary),
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="safe.directory",
                   GIT_CONFIG_VALUE_0=str(backend.parent.parent))
        # Runner-owned source/runtime and step files remain outside this UID's writes.
        argv = ["/usr/bin/sudo", "-n", "-u", account.pw_name, "--", "/usr/bin/env", "-i",
                *[f"{key}={value}" for key, value in sorted(env.items())], *argv]
    return subprocess.run(argv, cwd=backend, env=env).returncode


def check_database(mode: str) -> None:
    # This module itself is invoked with -I; candidate app/gate modules are never imported.
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["NUTRITION_TEST_POSTGRES_URL"])
    try:
        with engine.connect() as connection:
            if mode == "version":
                version = connection.execute(text("SHOW server_version")).scalar_one()
                if version.split(".")[0] != "16":
                    raise ValueError(f"expected PostgreSQL 16, found {version}")
                print(f"PostgreSQL 16 verified: {version}")
                return
            # Literal prefix comparisons avoid SQL LIKE underscore wildcard overreach.
            schemas = connection.execute(text(
                "SELECT schema_name FROM information_schema.schemata WHERE "
                + " OR ".join(f"starts_with(schema_name, :p{i})"
                              for i in range(len(SCHEMA_PREFIXES)))
            ), {f"p{i}": prefix for i, prefix in enumerate(SCHEMA_PREFIXES)}).scalars().all()
            databases = connection.execute(text(
                "SELECT datname FROM pg_catalog.pg_database WHERE "
                + " OR ".join(f"starts_with(datname, :p{i})"
                              for i in range(len(DATABASE_PREFIXES)))
            ), {f"p{i}": prefix for i, prefix in enumerate(DATABASE_PREFIXES)}).scalars().all()
            if schemas or databases:
                raise ValueError(f"residual PostgreSQL test schemas: {schemas}; "
                                 f"residual PostgreSQL test databases: {databases}")
            print("Isolated PostgreSQL schema/database cleanup verified")
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline", "postgresql", "version", "cleanup", "protect-runtime"))
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--print-marker-expression", action="store_true")
    args, extra = parser.parse_known_args(argv)
    if extra and extra[0] == "--":
        extra = extra[1:]
    if args.print_marker_expression:
        if args.mode != "baseline" or extra or args.candidate_sha:
            parser.error("marker printing only supports baseline without extra arguments")
        print(BASELINE_MARKER_EXPRESSION)
        return 0
    if args.mode == "protect-runtime":
        if extra or args.candidate_root is not None or args.candidate_sha is not None:
            parser.error("runtime protection accepts no candidate or extra arguments")
        isolation = isolated_account()
        if isolation is None:
            raise ValueError("BACKEND_RUNTIME_ISOLATED_ACCOUNT_REQUIRED")
        protect_runtime(isolation[0])
        return 0
    if args.candidate_root is None:
        parser.error("--candidate-root is required")
    if extra and (args.mode != "baseline" or args.candidate_sha):
        parser.error("additional pytest arguments are only supported by the local baseline")
    backend = candidate_backend(args.candidate_root, args.candidate_sha)
    if args.mode in {"baseline", "postgresql"}:
        return run_pytest(backend, args.mode == "postgresql", extra)
    check_database(args.mode)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as error:
        print(f"BACKEND_QUALIFICATION_FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error
