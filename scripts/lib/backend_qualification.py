"""Canonical backend checks, loaded from installed trusted source for qualification."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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


def checkout_candidate(root: Path, sha: str) -> None:
    """Deliver this public repository without checkout-action credential metadata."""
    if os.environ.get("GITHUB_REPOSITORY") != "MitCaine/Nutrition-App":
        raise ValueError("BACKEND_CHECKOUT_REPOSITORY_INVALID")
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("BACKEND_CANDIDATE_SHA_INVALID")
    workspace = Path(os.environ["GITHUB_WORKSPACE"])
    if not workspace.is_absolute() or workspace.resolve(strict=True) != workspace:
        raise ValueError("BACKEND_CHECKOUT_WORKSPACE_INVALID")
    root = root.absolute()
    if root != workspace / "candidate" or root.exists() or root.is_symlink():
        raise ValueError("BACKEND_CHECKOUT_DESTINATION_INVALID")
    # Anonymous access is intentional: this fixed repository is public. No token,
    # credential helper, header, proxy, include, template or inherited Git option.
    env = {"PATH": os.defpath, "LANG": "C", "HOME": os.devnull,
           "XDG_CONFIG_HOME": os.devnull,
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1",
           "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "https"}
    command = ["/usr/bin/git", "-c", "core.hooksPath=" + os.devnull,
               "-c", "core.fsmonitor=false", "-c", "core.attributesFile=" + os.devnull,
               "-c", "credential.helper=", "-c", "http.followRedirects=false"]

    def run(arguments, timeout=30):
        try:
            return subprocess.run(command + arguments, cwd=workspace, env=env,
                                  capture_output=True, check=True, timeout=timeout).stdout
        except (OSError, subprocess.SubprocessError):
            # Never echo transport output, ambient diagnostics or credentials.
            raise ValueError("BACKEND_CHECKOUT_COMMAND_FAILED") from None

    run(["init", "--template=", str(root)])
    run(["-C", str(root), "fetch", "--no-tags", "--no-recurse-submodules",
         "https://github.com/MitCaine/Nutrition-App.git", sha], timeout=120)
    if run(["-C", str(root), "rev-parse", "FETCH_HEAD"]).decode().strip() != sha:
        raise ValueError("BACKEND_CANDIDATE_SHA_MISMATCH")
    # Empty templates disable hooks; no candidate or submodule code is executed.
    run(["-C", str(root), "checkout", "--detach", sha])
    if (root / ".git/shallow").exists():
        raise ValueError("BACKEND_CHECKOUT_SHALLOW_UNSUPPORTED")
    _validate_source_git_nodes(root)
    inventory = source_inventory(root, sha, restricted=True)
    if run(["-C", str(root), "status", "--porcelain", "--untracked-files=all"]):
        raise ValueError("BACKEND_CHECKOUT_DIRTY")
    print(f"BACKEND_CHECKOUT_IDENTITY sha={sha} tree={inventory['tree']}", flush=True)


def candidate_backend(root: Path, sha: str | None) -> Path:
    original_root = root.absolute()
    root = root.resolve(strict=True)
    backend = root / "apps/backend"
    if not backend.is_dir():
        raise ValueError("BACKEND_CANDIDATE_ROOT_INVALID")
    if sha is not None:
        if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
            raise ValueError("BACKEND_CANDIDATE_SHA_INVALID")
        _validate_source_git_nodes(root)
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
            env={key: value for key, value in os.environ.items()
                 if key in {"PATH", "HOME", "SYSTEMROOT", "TMPDIR"}}
                 | {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
        )
        if result.stdout.strip() != sha:
            raise ValueError("BACKEND_CANDIDATE_SHA_MISMATCH")
    if sha is not None:
        inventory = source_inventory(root, sha)
        print(f"BACKEND_SOURCE_IDENTITY original={original_root} resolved={root} sha={sha} "
              f"tree={inventory['tree']} files={len(inventory['entries'])}", flush=True)
    return backend


# Source limits bound both parent object reads and trusted child probe input.
SOURCE_MAX_FILES = 100000
SOURCE_MAX_BYTES = 512 * 1024 * 1024
SOURCE_MAX_OBJECT = 64 * 1024 * 1024
SOURCE_MAX_CONFIG = 64 * 1024
SOURCE_MAX_CONFIG_LINE = 4096
SOURCE_MAX_CONFIG_LINES = 4096


def source_git(root: Path, *arguments: str) -> bytes:
    env = {"PATH": os.defpath, "LANG": "C", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1",
           "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"}
    return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                           "-c", "core.fsmonitor=false", "-c", "core.attributesFile=" + os.devnull,
                           "-c", "safe.directory=" + str(root), "-C", str(root), *arguments],
                          env=env, check=True, capture_output=True).stdout


def _validate_source_git_nodes(root):
    gitdir = root / ".git"
    if not gitdir.is_dir() or gitdir.is_symlink():
        raise ValueError("BACKEND_SOURCE_GIT_LAYOUT_UNSUPPORTED")
    if (gitdir / "objects/info/alternates").exists() or (gitdir / "objects/info/http-alternates").exists():
        raise ValueError("BACKEND_SOURCE_ALTERNATES_UNSUPPORTED")
    count = 0
    git_total = 0
    for directory, directories, files in os.walk(gitdir, followlinks=False):
        for name in directories + files:
            info = (Path(directory) / name).lstat()
            count += 1
            git_total += info.st_size if stat.S_ISREG(info.st_mode) else 0
            if info.st_size > SOURCE_MAX_OBJECT or git_total > SOURCE_MAX_BYTES:
                raise ValueError("BACKEND_SOURCE_GIT_BOUNDS_EXCEEDED")
            if count > SOURCE_MAX_FILES:
                raise ValueError("BACKEND_SOURCE_GIT_BOUNDS_EXCEEDED")
            if (not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                raise ValueError("BACKEND_SOURCE_GIT_ALIAS_UNSUPPORTED")

    # Parse bounded local bytes with includes disabled, outside every checkout.
    # Ordinary Git reads must never encounter an external include/worktree source.
    if ((gitdir / "config.worktree").exists() or (gitdir / "commondir").exists()
            or any((gitdir / "objects/pack").glob("*.promisor"))):
        raise ValueError("BACKEND_SOURCE_GIT_OBJECT_BOUNDARY_UNSUPPORTED")
    config_path = gitdir / "config"
    config = config_path.read_bytes() if config_path.exists() else b""
    lines = config.split(b"\n")
    if (len(config) > SOURCE_MAX_CONFIG or len(lines) > SOURCE_MAX_CONFIG_LINES
            or any(len(line) > SOURCE_MAX_CONFIG_LINE or line.rstrip().endswith(b"\\") for line in lines)):
        # Limit native parser key expansion before it can allocate output; folded
        # lines are unsupported rather than following unbounded continuation keys.
        raise ValueError("BACKEND_SOURCE_GIT_CONFIG_BOUNDS_UNSUPPORTED")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0"}
    parsed = subprocess.run(["git", "config", "--no-includes", "--file", "-", "--null", "--name-only", "--list"],
                            cwd="/", env=env, input=config, check=True, capture_output=True).stdout
    if len(parsed) > SOURCE_MAX_OBJECT:
        raise ValueError("BACKEND_SOURCE_GIT_BOUNDS_EXCEEDED")
    keys = [record.decode("utf-8", "strict").lower()
            for record in parsed.split(b"\0") if record]
    if any(key.startswith(("include.", "includeif."))
           or key in {"extensions.partialclone", "extensions.worktreeconfig", "core.worktree"}
           or key.endswith(".promisor") for key in keys):
        raise ValueError("BACKEND_SOURCE_GIT_OBJECT_BOUNDARY_UNSUPPORTED")


def source_inventory(root: Path, sha: str, *, restricted: bool = False):
    """Authenticate live tracked bytes; committed bytes never repair live drift."""
    import hashlib
    import unicodedata

    _validate_source_git_nodes(root)
    if source_git(root, "rev-parse", "HEAD").decode().strip() != sha:
        raise ValueError("BACKEND_CANDIDATE_SHA_MISMATCH")
    entries, names, total = [], set(), 0
    for record in source_git(root, "ls-tree", "-rz", sha).split(b"\0"):
        if not record:
            continue
        metadata, raw = record.split(b"\t", 1)
        mode, kind, blob = metadata.decode("ascii").split()
        name = raw.decode("utf-8", "strict")
        parts = name.split("/")
        normalized = unicodedata.normalize("NFC", name).casefold()
        if (any(part in {"", ".", ".."} or part.casefold() == ".git" for part in parts)
                or name.startswith("/") or "\\" in name or normalized in names):
            raise ValueError("BACKEND_SOURCE_PATH_UNSUPPORTED")
        names.add(normalized)
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ValueError("BACKEND_SOURCE_TYPE_UNSUPPORTED")
        if restricted and mode == "120000":
            raise ValueError("BACKEND_SOURCE_SYMLINK_UNSUPPORTED")
        size = int(source_git(root, "cat-file", "-s", blob))
        total += size
        if size > SOURCE_MAX_OBJECT or total > SOURCE_MAX_BYTES or len(entries) >= SOURCE_MAX_FILES:
            raise ValueError("BACKEND_SOURCE_BOUNDS_EXCEEDED")
        data = source_git(root, "cat-file", "blob", blob)
        path = root / name
        for parent in [path.parent, *path.parent.parents]:
            if parent == root.parent:
                break
            if parent.is_symlink():
                raise ValueError("BACKEND_SOURCE_ALIAS_UNSUPPORTED")
        info = path.lstat()
        if restricted and (info.st_nlink != 1 or info.st_mode & 0o7000):
            raise ValueError("BACKEND_SOURCE_HARDLINK_OR_MODE_UNSUPPORTED")
        if mode == "120000":
            actual = os.readlink(path).encode()
        elif stat.S_ISREG(info.st_mode):
            actual = path.read_bytes()
            if bool(info.st_mode & 0o111) != (mode == "100755"):
                raise ValueError("BACKEND_SOURCE_MODE_CHANGED")
        else:
            raise ValueError("BACKEND_SOURCE_TYPE_CHANGED")
        if actual != data:
            raise ValueError("BACKEND_SOURCE_CONTENT_CHANGED")
        entries.append({"path": name, "mode": mode, "blob": blob,
                        "bytes": size, "sha256": hashlib.sha256(data).hexdigest()})
    expected_index = b"".join((entry["mode"] + " " + entry["blob"] + " 0\t" + entry["path"]).encode() + b"\0"
                              for entry in sorted(entries, key=lambda entry: entry["path"].encode()))
    if source_git(root, "ls-files", "--stage", "-z") != expected_index:
        raise ValueError("BACKEND_SOURCE_INDEX_CHANGED")
    return {"sha": sha, "tree": source_git(root, "rev-parse", sha + "^{tree}").decode().strip(),
            "entries": entries}


# This literal runs only standard-library code under the selected isolated runtime.
SOURCE_PROBE = r'''
import errno, hashlib, json, os, stat, subprocess, sys
payload = json.load(sys.stdin)
result = {"uid": os.getuid(), "errno": 0, "error": ""}
try:
    root = payload["root"]
    for path in payload["controls"]:
        info = os.lstat(path)
        if info.st_uid == os.getuid() or stat.S_ISLNK(info.st_mode):
            raise ValueError("OWNED_OR_ALIAS")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("HARDLINK")
        # Sticky root-owned /tmp cannot replace another owner's child.
        sticky = path == "/tmp" and stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
        if os.access(path, os.W_OK) and not sticky:
            raise ValueError("WRITABLE")
    for entry in payload["inventory"]["entries"]:
        path = os.path.join(root, entry["path"])
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("TYPE_OR_HARDLINK")
        if bool(info.st_mode & 0o111) != (entry["mode"] == "100755"):
            raise ValueError("MODE")
        with open(path, "rb") as stream:
            data = stream.read(entry["bytes"] + 1)
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("CONTENT")
    for path, digest in payload["git_files"]:
        with open(path, "rb") as stream:
            if hashlib.sha256(stream.read()).hexdigest() != digest:
                raise ValueError("GIT_CONTENT")
    git_env = {"PATH": os.defpath, "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1"}
    git_command = ["/usr/bin/git", "-c", "core.hooksPath=" + os.devnull,
                   "-c", "core.fsmonitor=false", "-c", "safe.directory=" + root, "-C", root]
    for arguments, expected in [(["rev-parse", "HEAD"], payload["inventory"]["sha"]),
                                (["rev-parse", "HEAD^{tree}"], payload["inventory"]["tree"]),
                                (["ls-files", "--stage", "-z"], payload["index"])]:
        checked = subprocess.run(git_command + arguments, env=git_env, capture_output=True, text=True)
        if checked.returncode or checked.stdout.rstrip("\n") != expected:
            raise ValueError("GIT_IDENTITY_OR_STATUS")
except OSError as error:
    result["errno"] = error.errno
    result["error"] = "ACCESS"
except ValueError as error:
    result["error"] = str(error)
json.dump(result, sys.stdout)
'''


def source_probe(root, inventory, account, *, private_receipt=None):
    import hashlib

    controls = {root, *root.parents}
    git_files = []
    if private_receipt is not None:
        info = private_receipt.lstat()
        if (private_receipt.parent != root / ".git" or info.st_uid != os.getuid()
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError("BACKEND_SOURCE_RETENTION_RECEIPT_UNSAFE")
    for base in (root / ".git",):
        for directory, directories, files in os.walk(base, followlinks=False):
            controls.add(Path(directory))
            for name in directories + files:
                path = Path(directory) / name
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                    raise ValueError("BACKEND_SOURCE_GIT_ALIAS_UNSUPPORTED")
                controls.add(path)
                if stat.S_ISREG(info.st_mode) and path != private_receipt:
                    # Only this context-owned private receipt omits child content
                    # reads; ownership/write checks and trusted snapshots cover it.
                    git_files.append((str(path), hashlib.sha256(path.read_bytes()).hexdigest()))
    for entry in inventory["entries"]:
        path = root / entry["path"]
        controls.update((path, *path.parents))
    for path in controls:
        info = path.lstat()
        if info.st_uid == account.pw_uid:
            raise ValueError("BACKEND_SOURCE_CHILD_OWNED")
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("BACKEND_SOURCE_ALIAS_UNSUPPORTED")
    payload = {"root": str(root), "inventory": inventory,
               "controls": [str(path) for path in sorted(controls)], "git_files": git_files,
               "index": source_git(root, "ls-files", "--stage", "-z").decode()}
    completed = subprocess.run(["/usr/bin/sudo", "-n", "-u", account.pw_name, "--",
                                "/usr/bin/env", "-i", sys.executable, "-I", "-B", "-c", SOURCE_PROBE],
                               input=json.dumps(payload), text=True, capture_output=True, check=True)
    result = json.loads(completed.stdout)
    if (not isinstance(result, dict) or set(result) != {"uid", "errno", "error"}
            or type(result["uid"]) is not int or result["uid"] != account.pw_uid
            or type(result["errno"]) is not int or not isinstance(result["error"], str)
            or result["errno"] < 0 or (result["errno"] != 0 and result["error"] != "ACCESS")):
        raise ValueError("BACKEND_SOURCE_PROBE_INVALID")
    return result


def source_snapshot(root, inventory):
    import hashlib

    paths = {root, *root.parents}
    for entry in inventory["entries"]:
        path = root / entry["path"]
        paths.update((path, *path.parents))
    paths.update((root / ".git").rglob("*"))
    paths.add(root / ".git")
    snapshot = []
    for path in sorted(paths):
        info = path.lstat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_relative_to(root / ".git") and stat.S_ISREG(info.st_mode) else None
        external = not path.is_relative_to(root)
        acl = subprocess.run(["/usr/bin/getfacl", "-cpn", "--", str(path)],
                             check=True, capture_output=True).stdout
        snapshot.append((str(path), info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                         info.st_gid, 0 if external else info.st_nlink,
                         0 if external else info.st_mtime_ns, 0 if external else info.st_ctime_ns, digest, acl))
    return snapshot


def materialize_source(root, inventory, account):
    """Write only the exact C object closure, with no candidate Git configuration."""
    import tempfile
    import zlib

    temporary = Path("/tmp")
    info = temporary.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or not info.st_mode & stat.S_ISVTX or not info.st_mode & stat.S_IXOTH):
        raise ValueError("BACKEND_SOURCE_TMP_UNSAFE")
    stage = Path(tempfile.mkdtemp(prefix="nutrition-source-", dir="/tmp"))
    identity = stage.lstat()
    try:
        if (not stat.S_ISDIR(identity.st_mode) or identity.st_uid != os.getuid()
                or identity.st_mode & 0o077):
            raise ValueError("BACKEND_SOURCE_STAGE_CREATION_UNSAFE")
        gitdir = stage / ".git"
        (gitdir / "objects").mkdir(parents=True)
        (gitdir / "refs").mkdir()
        (gitdir / "HEAD").write_text(inventory["sha"] + "\n")
        (gitdir / "shallow").write_text(inventory["sha"] + "\n")
        (gitdir / "config").write_text("[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tlogallrefupdates = false\n")
        objects = {inventory["sha"]: "commit", inventory["tree"]: "tree"}
        for record in source_git(root, "ls-tree", "-rtz", inventory["sha"]).split(b"\0"):
            if record:
                mode, kind, oid = record.split(b"\t", 1)[0].decode().split()
                objects[oid] = kind
        object_total = 0
        if len(objects) > SOURCE_MAX_FILES * 2:
            raise ValueError("BACKEND_SOURCE_OBJECT_BOUNDS")
        for oid, kind in objects.items():
            size = int(source_git(root, "cat-file", "-s", oid))
            object_total += size
            if size > SOURCE_MAX_OBJECT or object_total > SOURCE_MAX_BYTES:
                raise ValueError("BACKEND_SOURCE_OBJECT_BOUNDS")
            data = source_git(root, "cat-file", kind, oid)
            import hashlib
            raw_object = kind.encode() + b" " + str(len(data)).encode() + b"\0" + data
            if hashlib.sha1(raw_object).hexdigest() != oid:
                raise ValueError("BACKEND_SOURCE_OBJECT_IDENTITY_CHANGED")
            destination = gitdir / "objects" / oid[:2] / oid[2:]
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(zlib.compress(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data))
        for entry in inventory["entries"]:
            destination = stage / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source_git(root, "cat-file", "blob", entry["blob"]))
            destination.chmod(0o700 if entry["mode"] == "100755" else 0o600)
        source_git(stage, "read-tree", inventory["sha"])
        paths = [stage, *stage.rglob("*")]
        # Keep the root closed until EVERY descendant loses inherited writes.
        modes = {}
        for path in paths:
            info = path.lstat()
            if (info.st_uid != os.getuid() or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                raise ValueError("BACKEND_SOURCE_STAGE_SEAL_IDENTITY_INVALID")
            subprocess.run(["/usr/bin/setfacl", "-b", "-k", "--", str(path)], check=True, capture_output=True)
            mode = 0o700 if stat.S_ISDIR(info.st_mode) or info.st_mode & 0o111 else 0o600
            path.chmod(mode)
            modes[path] = mode
        for path, mode in modes.items():
            if stat.S_IMODE(path.lstat().st_mode) != mode:
                raise ValueError("BACKEND_SOURCE_STAGE_SEAL_MODE_INVALID")
            acl = subprocess.run(["/usr/bin/getfacl", "-cpn", "--", str(path)],
                                 check=True, capture_output=True, text=True).stdout
            expected = {"user::rwx" if mode == 0o700 else "user::rw-", "group::---", "other::---"}
            if set(acl.split()) != expected:
                raise ValueError("BACKEND_SOURCE_STAGE_SEAL_ACL_INVALID")
        # Descendants receive final read/search permissions first; root opens LAST.
        for path in [*paths[1:], stage]:
            permission = "r-x" if modes[path] == 0o700 else "r--"
            subprocess.run(["/usr/bin/setfacl", "-m", f"u:{account.pw_uid}:{permission}",
                            "--", str(path)], check=True, capture_output=True)
        if source_inventory(stage, inventory["sha"], restricted=True) != inventory:
            raise ValueError("BACKEND_SOURCE_STAGE_IDENTITY_CHANGED")
        if source_git(stage, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("BACKEND_SOURCE_STAGE_DIRTY")
        return stage, (identity.st_dev, identity.st_ino)
    except BaseException:
        remove_source_stage(stage, (identity.st_dev, identity.st_ino))
        raise


def remove_source_stage(stage, identity):
    import shutil

    info = stage.lstat()
    if (info.st_dev, info.st_ino) != identity or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("BACKEND_SOURCE_CLEANUP_IDENTITY_CHANGED")
    if not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError("BACKEND_SOURCE_CLEANUP_UNSUPPORTED")
    shutil.rmtree(stage)


@contextmanager
def _prepared_source(backend, sha, isolation):
    if isolation is None:
        yield backend
        return
    import errno

    account, _temporary = isolation
    root = backend.parent.parent
    # Reject unsafe source metadata before the broader runtime inventory. This
    # boundary cannot require runtime access or invoke checkout-aware Git.
    _validate_source_git_nodes(root)
    assert_runtime_confined(account)
    authenticated = sha is not None
    if sha is None:
        sha = source_git(root, "rev-parse", "HEAD").decode().strip()
    inventory = source_inventory(root, sha, restricted=True)
    original_snapshot = source_snapshot(root, inventory)
    stage = None
    retained = False
    result = source_probe(root, inventory, account)
    try:
        if result["errno"] == errno.EACCES:
            if not authenticated:
                raise ValueError("BACKEND_SOURCE_INACCESSIBLE_SHA_REQUIRED")
            print(f"BACKEND_SOURCE_ACCESS EACCES sha={sha} tree={inventory['tree']} uid={account.pw_uid}", flush=True)
            stage, identity = materialize_source(root, inventory, account)
            selected = stage
            # Bind exact owned identity privately BEFORE yielding any possible launch.
            import tempfile

            descriptor, receipt = tempfile.mkstemp(prefix=".launch-state-", suffix=".json", dir=stage / ".git")
            with os.fdopen(descriptor, "w") as output:
                json.dump({"version": 1, "sha": sha, "tree": inventory["tree"],
                           "runner_uid": os.getuid(), "candidate_uid": account.pw_uid,
                           "stage": str(stage), "identity": identity,
                           "launch_budget": 1, "quiescence": "unproved",
                           "cleanup": "ephemeral job teardown; persistent cleanup requires exact identity and verified quiescence"},
                          output, sort_keys=True)
            info = Path(receipt).lstat()
            if (info.st_uid != os.getuid() or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != 0o600 or not stat.S_ISREG(info.st_mode)):
                raise ValueError("BACKEND_SOURCE_RETENTION_RECEIPT_UNSAFE")
        elif result["error"]:
            raise ValueError("BACKEND_SOURCE_PREFLIGHT_FAILED:" + str(result))
        else:
            selected = root
        selected_snapshot = source_snapshot(selected, inventory)
        def recheck():
            if source_snapshot(root, inventory) != original_snapshot or source_snapshot(selected, inventory) != selected_snapshot:
                raise ValueError("BACKEND_SOURCE_IDENTITY_CHANGED")
            if source_inventory(root, sha, restricted=True) != inventory:
                raise ValueError("BACKEND_SOURCE_ORIGINAL_CHANGED")
            result = source_probe(selected, inventory, account,
                                  private_receipt=Path(receipt) if stage is not None else None)
            if result["error"] or result["errno"]:
                raise ValueError("BACKEND_SOURCE_PREFLIGHT_FAILED:" + str(result))
            if source_snapshot(root, inventory) != original_snapshot or source_snapshot(selected, inventory) != selected_snapshot:
                raise ValueError("BACKEND_SOURCE_CHANGED_DURING_PROBE")
        recheck()
        print(f"BACKEND_SOURCE_READY root={selected} sha={sha} tree={inventory['tree']} uid={account.pw_uid}", flush=True)
        if stage is not None:
            retained = True
            print(f"BACKEND_SOURCE_RETAINED root={stage} receipt={receipt} launch_budget=1 quiescence=unproved", flush=True)
        try:
            yield selected / "apps/backend"
        finally:
            recheck()
    finally:
        # A yielded context permits launch, even when spawn/cancellation is unknown.
        # Leader exit never proves descendants quiescent. Only prelaunch setup cleans.
        if stage is not None and not retained:
            remove_source_stage(stage, identity)



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
    parser.add_argument("mode", choices=("baseline", "postgresql", "version", "cleanup", "protect-runtime", "checkout"))
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--print-marker-expression", action="store_true")
    args, extra = parser.parse_known_args(argv)
    if extra and extra[0] == "--":
        extra = extra[1:]
    if args.mode == "checkout":
        if extra or args.candidate_root is None or args.candidate_sha is None or args.print_marker_expression:
            parser.error("checkout requires only exact candidate root and SHA")
        checkout_candidate(args.candidate_root, args.candidate_sha)
        return 0
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
        with _prepared_source(backend, args.candidate_sha, isolated_account()) as selected:
            return run_pytest(selected, args.mode == "postgresql", extra)
    check_database(args.mode)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as error:
        print(f"BACKEND_QUALIFICATION_FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error
