"""Durable identity and output ledger for dependency-lock refreshes."""
from __future__ import annotations

import hashlib
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
import re
import secrets
import stat
import subprocess


class TransactionError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state_path(root: Path) -> Path:
    return root.with_name(f".{root.name}.update-dependencies-transaction.json")


def index_lock_path(identity: dict[str, str]) -> Path:
    return Path(identity["git_dir"]) / "index.lock"


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False, timeout=15)
    if result.returncode:
        raise TransactionError(f"Cannot verify Git checkout identity ({' '.join(args)}).")
    return result.stdout.strip()


def checkout_identity(root: Path) -> dict[str, str]:
    try:
        identity = {
            "root": str(root.resolve(strict=True)),
            "git_dir": str(Path(os.fsdecode(_git(root, "rev-parse", "--absolute-git-dir"))).resolve(strict=True)),
            "branch": os.fsdecode(_git(root, "symbolic-ref", "--quiet", "HEAD")),
            "head": os.fsdecode(_git(root, "rev-parse", "HEAD")),
        }
        if Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel"))).resolve(strict=True) != root.resolve(strict=True):
            raise TransactionError("Updater root is not the checked-out Git worktree.")
        return identity
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TransactionError("Cannot verify Git checkout identity.") from exc


def changed_paths(root: Path) -> set[str]:
    try:
        result = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
                                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TransactionError("Cannot inspect checkout changes.") from exc
    if result.returncode:
        raise TransactionError("Cannot inspect checkout changes.")
    entries = result.stdout.split(b"\0")
    changes: set[str] = set()
    for entry in entries:
        if not entry:
            continue
        if len(entry) < 4 or entry[:2] != b" M" or entry[2:3] != b" ":
            raise TransactionError("Checkout contains staged, untracked, renamed or non-updater changes.")
        changes.add(os.fsdecode(entry[3:]))
    return changes


def _save(path: Path, state: dict) -> None:
    if path.is_symlink():
        raise TransactionError("Transaction path is a symlink; refusing to use it.")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    data = (json.dumps(state, sort_keys=True, indent=2) + "\n").encode()
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path: Path) -> dict:
    if path.is_symlink():
        raise TransactionError("Transaction path is a symlink; refusing to use it.")
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise TransactionError("Cannot authenticate dependency update transaction; inspect it manually.") from exc
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise TransactionError("Unknown dependency update transaction schema.")
    return state


class UpdateTransaction:
    def __init__(self, root: Path, state: dict, path: Path):
        self.root, self.state, self.path = root, state, path

    @classmethod
    def begin(cls, root: Path, area: str, packages: list[str], areas: tuple[str, ...],
              inputs: dict[str, dict[str, str | None]], *,
              process_lock_fd: int | None = None) -> "UpdateTransaction":
        path = state_path(root)
        identity = checkout_identity(root)
        if path.exists():
            state = _read(path)
            if state.get("identity") != identity:
                raise TransactionError("Checkout branch, HEAD or worktree changed since the update began.")
            if "index_lock_nonce" not in state:
                if index_lock_path(identity).exists() or index_lock_path(identity).is_symlink():
                    raise TransactionError("Unknown Git index lock exists; inspect it manually.")
                state["index_lock_nonce"] = secrets.token_hex(16)
                _save(path, state)
            if state.get("status") != "complete" and (state.get("area") != area or state.get("packages") != packages):
                raise TransactionError("A different dependency update is pending; resume the recorded command first.")
            transaction = cls(root, state, path)
            transaction.recover_stale_index_lock(process_lock_fd)
            if state.get("status") == "complete" and not changed_paths(root):
                path.unlink()
            else:
                if state.get("area") != area or state.get("packages") != packages:
                    raise TransactionError("A different dependency update is pending; resume the recorded command first.")
                transaction.recover_publication()
                transaction.verify(inputs)
                return transaction
        elif index_lock_path(identity).exists() or index_lock_path(identity).is_symlink():
            raise TransactionError("Unknown Git index lock exists; inspect it manually.")
        if changed_paths(root):
            raise TransactionError("Checkout has existing changes; use a clean worktree to protect them.")
        state = {"schema_version": 1, "identity": identity, "area": area,
                 "packages": packages, "areas": list(areas), "inputs": inputs,
                 "outputs": {}, "outcomes": {}, "status": "running",
                 "index_lock_nonce": secrets.token_hex(16)}
        _save(path, state)
        return cls(root, state, path)

    def _index_lock(self) -> Path:
        return index_lock_path(self.state["identity"])

    def _index_lock_token(self) -> bytes:
        nonce = self.state.get("index_lock_nonce")
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise TransactionError("Transaction has no authenticated Git index lock owner.")
        identity = json.dumps(self.state["identity"], sort_keys=True, separators=(",", ":")).encode()
        record = {"kind": "nutrition-updater-index-lock-v1", "nonce": nonce,
                  "identity_sha256": digest(identity)}
        return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()

    def _index_lock_stage(self) -> Path:
        self._index_lock_token()
        return self._index_lock().with_name("index.lock.nutrition-" + self.state["index_lock_nonce"]
                                           + "-" + secrets.token_hex(8) + ".tmp")

    def _index_lock_stages(self) -> list[Path]:
        self._index_lock_token()
        return list(self._index_lock().parent.glob("index.lock.nutrition-" + self.state["index_lock_nonce"]
                                                   + "-*.tmp"))

    def _assert_process_lock(self, descriptor: int | None) -> None:
        if descriptor is None:
            raise TransactionError("Stale Git lock recovery requires the updater process lock.")
        path = self.root.with_name(f".{self.root.name}.update-dependencies.lock")
        try:
            owned, current = os.fstat(descriptor), path.stat()
            if (owned.st_dev, owned.st_ino) != (current.st_dev, current.st_ino):
                raise TransactionError("Updater process lock identity changed.")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            raise TransactionError("Updater process lock is not held for stale Git lock recovery.") from exc

    def recover_stale_index_lock(self, process_lock_fd: int | None) -> None:
        lock = self._index_lock()
        stages = self._index_lock_stages()
        if not (lock.exists() or lock.is_symlink() or stages):
            return
        self._assert_process_lock(process_lock_fd)
        token = self._index_lock_token()
        validated = []
        for path in (lock, *stages):
            if not (path.exists() or path.is_symlink()):
                continue
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    owned = os.fstat(descriptor)
                    raw = os.read(descriptor, len(token) + 1)
                finally:
                    os.close(descriptor)
                current = path.stat()
            except OSError as exc:
                raise TransactionError("Cannot authenticate existing Git index lock; inspect it manually.") from exc
            if (not stat.S_ISREG(owned.st_mode) or raw != token or owned.st_size != len(token)
                    or (owned.st_dev, owned.st_ino) != (current.st_dev, current.st_ino)):
                if path == lock:
                    raise TransactionError("Unknown Git index lock exists; inspect it manually.")
                continue
            validated.append((path, owned.st_dev, owned.st_ino))
        for path, device, inode in validated:
            current = path.stat(follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (device, inode):
                raise TransactionError("Git index lock changed during recovery; inspect it manually.")
            path.unlink()
        directory = os.open(lock.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _expected_inputs(self, inputs: dict[str, dict[str, str | None]]) -> dict[str, dict[str, str | None]]:
        expected = {area: values.copy() for area, values in self.state["inputs"].items()}
        for output in self.state["outputs"].values():
            if output["status"] == "applied":
                for relpath, hashes in output["files"].items():
                    for values in expected.values():
                        if relpath in values:
                            values[relpath] = hashes["after"]
        if inputs != expected:
            raise TransactionError("Dependency authority inputs changed since the update began.")
        return expected

    def recover_publication(self) -> None:
        if checkout_identity(self.root) != self.state["identity"]:
            raise TransactionError("Checkout branch, HEAD or worktree changed since the update began.")
        for area, output in list(self.state["outputs"].items()):
            if output["status"] != "publishing":
                continue
            matches = []
            for relpath, hashes in output["files"].items():
                path = self.root / relpath
                actual = digest(path.read_bytes()) if path.is_file() else None
                if actual not in {hashes["before"], hashes["after"]}:
                    raise TransactionError("Interrupted publication has unrecognized lock bytes.")
                matches.append("after" if actual == hashes["after"] else "before")
            if all(match == "after" for match in matches):
                output["status"] = "applied"
                self.state["outcomes"][area] = "applied"
            elif all(match == "before" for match in matches):
                previous = output.get("previous")
                if previous is None:
                    del self.state["outputs"][area]
                else:
                    self.state["outputs"][area] = previous
                self.state["outcomes"][area] = "pending"
            else:
                raise TransactionError("Interrupted multi-file publication is partial; inspect recovery artifacts.")
            _save(self.path, self.state)

    def verify(self, inputs: dict[str, dict[str, str | None]]) -> None:
        self.assert_identity()
        self._expected_inputs(inputs)
        expected_paths = set()
        for output in self.state["outputs"].values():
            if output["status"] == "applied":
                for relpath, hashes in output["files"].items():
                    actual = self.root / relpath
                    if not actual.is_file() or digest(actual.read_bytes()) != hashes["after"]:
                        raise TransactionError("Previously published updater output changed; refusing resume.")
                    original = next((values[relpath] for values in self.state["inputs"].values()
                                     if relpath in values), hashes["before"])
                    if hashes["after"] != original:
                        expected_paths.add(relpath)
        if changed_paths(self.root) != expected_paths:
            raise TransactionError("Checkout includes changes outside recorded updater output; refusing resume.")

    def assert_identity(self) -> None:
        if checkout_identity(self.root) != self.state["identity"]:
            raise TransactionError("Checkout branch, HEAD or worktree changed during dependency update.")

    @contextmanager
    def publication_guard(self):
        """Hold Git's index lock across a single-file replacement.

        Ordinary Git checkout/switch takes this same lock. A post-write identity
        check still catches ref updates that do not use the index.
        """
        lock = self._index_lock()
        stage = self._index_lock_stage()
        token = self._index_lock_token()
        self.assert_identity()
        if stage.exists() or stage.is_symlink():
            raise TransactionError("Updater Git lock staging file exists; resume the recorded transaction.")
        descriptor = os.open(stage, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        owned_stage = os.fstat(descriptor)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(stage, lock, follow_symlinks=False)
            except FileExistsError as exc:
                raise TransactionError("Git checkout is busy; retry dependency publication.") from exc
            directory = os.open(lock.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            owned = lock.stat()
            try:
                self.assert_identity()
                yield
            finally:
                try:
                    current = lock.stat()
                except FileNotFoundError:
                    current = None
                if current and (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                    lock.unlink()
        finally:
            try:
                current_stage = stage.stat()
            except FileNotFoundError:
                current_stage = None
            if current_stage and (current_stage.st_dev, current_stage.st_ino) == (owned_stage.st_dev, owned_stage.st_ino):
                stage.unlink()

    def done(self, area: str) -> bool:
        return self.state["outcomes"].get(area) in {"applied", "current"}

    def publishing(self, area: str, proposals: list[tuple[Path, bytes, bytes]]) -> None:
        files = {}
        for path, before, after in proposals:
            if not path.is_file() or path.read_bytes() != before:
                raise TransactionError("Lockfile changed before publication.")
            relpath = path.relative_to(self.root).as_posix()
            files[relpath] = {"before": digest(before), "after": digest(after)}
        previous = self.state["outputs"].get(area)
        self.state["outputs"][area] = {"status": "publishing", "files": files}
        if previous is not None:
            self.state["outputs"][area]["previous"] = previous
        _save(self.path, self.state)

    def applied(self, area: str) -> None:
        self.assert_identity()
        output = self.state["outputs"][area]
        for relpath, hashes in output["files"].items():
            if digest((self.root / relpath).read_bytes()) != hashes["after"]:
                raise TransactionError("Published lock bytes do not match transaction proposal.")
        output["status"] = "applied"
        self.state["outcomes"][area] = "applied"
        _save(self.path, self.state)

    def current(self, area: str) -> None:
        self.state["outcomes"][area] = "current"
        _save(self.path, self.state)

    def failed(self, area: str) -> None:
        self.state["outcomes"][area] = "failed"
        _save(self.path, self.state)

    def finish(self) -> None:
        if all(self.done(area) for area in self.state["areas"]):
            self.state["status"] = "complete"
            _save(self.path, self.state)
