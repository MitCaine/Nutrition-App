"""Canonical backend checks, loaded from installed trusted source for qualification."""
from __future__ import annotations

import argparse
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
    parser.add_argument("mode", choices=("baseline", "postgresql", "version", "cleanup"))
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
