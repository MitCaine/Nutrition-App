"""Durable identity and output ledger for dependency-lock refreshes."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import subprocess


class TransactionError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state_path(root: Path) -> Path:
    return root.with_name(f".{root.name}.update-dependencies-transaction.json")


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
              inputs: dict[str, dict[str, str | None]]) -> "UpdateTransaction":
        path = state_path(root)
        identity = checkout_identity(root)
        if path.exists():
            state = _read(path)
            if state.get("status") == "complete" and not changed_paths(root):
                path.unlink()
            else:
                if state.get("identity") != identity:
                    raise TransactionError("Checkout branch, HEAD or worktree changed since the update began.")
                if state.get("area") != area or state.get("packages") != packages:
                    raise TransactionError("A different dependency update is pending; resume the recorded command first.")
                transaction = cls(root, state, path)
                transaction.recover_publication()
                transaction.verify(inputs)
                return transaction
        if changed_paths(root):
            raise TransactionError("Checkout has existing changes; use a clean worktree to protect them.")
        state = {"schema_version": 1, "identity": identity, "area": area,
                 "packages": packages, "areas": list(areas), "inputs": inputs,
                 "outputs": {}, "outcomes": {}, "status": "running"}
        _save(path, state)
        return cls(root, state, path)

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
        raw = Path(os.fsdecode(_git(self.root, "rev-parse", "--git-path", "index.lock")))
        lock = raw if raw.is_absolute() else self.root / raw
        self.assert_identity()
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError as exc:
            raise TransactionError("Git checkout is busy; retry dependency publication.") from exc
        try:
            owned = os.fstat(descriptor)
            self.assert_identity()
            yield
        finally:
            os.close(descriptor)
            try:
                current = lock.stat()
            except FileNotFoundError:
                current = None
            if current and (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                lock.unlink()

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
