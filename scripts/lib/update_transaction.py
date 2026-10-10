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
            transaction.recover_publication()
            if state.get("status") == "complete" and not changed_paths(root):
                path.unlink()
            else:
                if state.get("area") != area or state.get("packages") != packages:
                    raise TransactionError("A different dependency update is pending; resume the recorded command first.")
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

    def _artifact_records(self, area: str) -> tuple[dict[str, dict], dict]:
        output = self.state.get("outputs", {}).get(area)
        if not isinstance(output, dict):
            raise TransactionError("Dependency transaction output is missing during artifact recovery.")
        artifacts = output.get("artifacts")
        if artifacts is None:
            return {}, output
        if not isinstance(artifacts, dict):
            raise TransactionError("Updater artifact ownership record is invalid; inspect it manually.")
        nonce = self.state.get("index_lock_nonce")
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise TransactionError("Updater artifact transaction identity is invalid; inspect it manually.")
        files = output.get("files")
        if not isinstance(files, dict) or len(files) != 1:
            raise TransactionError("Updater artifact target inventory is invalid; inspect it manually.")
        expected_paths = set()
        for target_relpath, hashes in files.items():
            if (not isinstance(target_relpath, str) or Path(target_relpath).is_absolute()
                    or ".." in Path(target_relpath).parts or Path(target_relpath).as_posix() != target_relpath
                    or not isinstance(hashes, dict)):
                raise TransactionError("Updater artifact target escapes the checkout; inspect it manually.")
            expected_paths.update({target_relpath + ".update-tmp", target_relpath + ".update-recovery"})
        if set(artifacts) != expected_paths:
            raise TransactionError("Updater artifact ownership inventory does not match its transaction.")
        by_role = {}
        for relpath, record in artifacts.items():
            if not isinstance(relpath, str) or Path(relpath).is_absolute() or ".." in Path(relpath).parts:
                raise TransactionError("Updater artifact path escapes the checkout; inspect it manually.")
            if not isinstance(record, dict) or record.get("owner_nonce") != nonce:
                raise TransactionError("Updater artifact belongs to another transaction; inspect it manually.")
            role = record.get("role")
            if role not in {"staged", "recovery"} or role in by_role:
                raise TransactionError("Updater artifact role is invalid; inspect it manually.")
            target_relpath = record.get("target")
            if not isinstance(target_relpath, str) or target_relpath not in files:
                raise TransactionError("Updater artifact target is not recorded by this transaction.")
            suffix = ".update-tmp" if role == "staged" else ".update-recovery"
            target_path = Path(target_relpath)
            if relpath != target_path.with_name(target_path.name + suffix).as_posix():
                raise TransactionError("Updater artifact path does not match its recorded target.")
            expected_hash = files[target_relpath].get("after" if role == "staged" else "before")
            if record.get("sha256") != expected_hash:
                raise TransactionError("Updater artifact digest does not match its transaction proposal.")
            mode = record.get("mode")
            size = record.get("size")
            device = record.get("device")
            inode = record.get("inode")
            if (isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777
                    or isinstance(size, bool) or not isinstance(size, int) or size < 0
                    or (device is None) != (inode is None)
                    or (device is not None and (isinstance(device, bool) or not isinstance(device, int)
                                                or isinstance(inode, bool) or not isinstance(inode, int)))):
                raise TransactionError("Updater artifact identity or mode record is invalid; inspect it manually.")
            by_role[role] = (self.root / relpath, record)
        if set(by_role) != {"staged", "recovery"}:
            raise TransactionError("Updater artifact roles are incomplete; inspect it manually.")
        cleanup = output.get("artifact_cleanup", "active")
        if cleanup not in {"active", "rollback_pending", "cleanup_pending", "cleaned"}:
            raise TransactionError("Updater artifact cleanup state is invalid; inspect it manually.")
        return by_role, output

    def _assert_checkout_path(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise TransactionError("Updater publication path escapes the checkout; inspect it manually.") from exc
        if ".." in relative.parts:
            raise TransactionError("Updater publication path escapes the checkout; inspect it manually.")
        current = self.root
        try:
            root_info = os.lstat(current)
        except OSError as exc:
            raise TransactionError("Updater checkout path cannot be authenticated.") from exc
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise TransactionError("Updater checkout root is not a regular directory.")
        for part in relative.parts[:-1]:
            current = current / part
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                return
            except OSError as exc:
                raise TransactionError("Updater publication parent cannot be authenticated.") from exc
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise TransactionError("Updater publication parent is not a checkout directory.")

    def _read_nofollow(self, path: Path, description: str) -> tuple[os.stat_result, bytes] | None:
        self._assert_checkout_path(path)
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise TransactionError(f"Cannot authenticate {description}; inspect it manually.") from exc
        try:
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                data = stream.read()
            current = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise TransactionError(f"Cannot authenticate {description}; inspect it manually.") from exc
        if (not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)):
            raise TransactionError(f"{description.capitalize()} changed while being authenticated; inspect it manually.")
        return opened, data

    def _assert_artifact_file(self, path: Path, record: dict) -> None:
        actual = self._read_nofollow(path, "updater publication artifact")
        if actual is None:
            raise TransactionError("Updater publication artifact disappeared; inspect it manually.")
        info, data = actual
        if (record.get("device") is None or record.get("inode") is None
                or (info.st_dev, info.st_ino) != (record["device"], record["inode"])
                or stat.S_IMODE(info.st_mode) != record["mode"]
                or info.st_size != record["size"] or digest(data) != record["sha256"]):
            raise TransactionError("Updater publication artifact changed or was replaced; inspect it manually.")

    def _artifact_at_target(self, target: Path, record: dict) -> bool:
        actual = self._read_nofollow(target, "lockfile publication target")
        if actual is None:
            return False
        info, data = actual
        if digest(data) != record["sha256"]:
            return False
        if (record.get("device") is None or record.get("inode") is None
                or (info.st_dev, info.st_ino) != (record["device"], record["inode"])
                or stat.S_IMODE(info.st_mode) != record["mode"]
                or info.st_size != record["size"]):
            raise TransactionError("Lockfile publication artifact was replaced or changed; inspect it manually.")
        return True

    def _artifact_locations(self, area: str) -> dict[str, str]:
        records, output = self._artifact_records(area)
        if not records:
            return {}
        cleanup = output.get("artifact_cleanup", "active")
        locations = {}
        output_status = output.get("status")
        recovery_at_target = False
        if (output_status == "publishing"
                and cleanup in {"rollback_pending", "cleanup_pending", "cleaned"}):
            _, recovery_record = records["recovery"]
            recovery_at_target = self._artifact_at_target(
                self.root / recovery_record["target"], recovery_record
            )
        for role, (path, record) in records.items():
            self._assert_checkout_path(path)
            if cleanup == "cleaned" and (path.exists() or path.is_symlink()):
                raise TransactionError("Unexpected updater artifact exists after recorded cleanup; inspect it manually.")
            sidecar = self._read_nofollow(path, "updater publication artifact")
            target = self.root / record["target"]
            if sidecar is not None:
                self._assert_artifact_file(path, record)
                if role == "staged" and self._artifact_at_target(target, record):
                    raise TransactionError("Updater staging artifact is linked to the lockfile target.")
                locations[role] = "sidecar"
                continue
            if role == "staged":
                target_is_expected = self._artifact_at_target(target, record)
            else:
                target_is_expected = recovery_at_target
            if target_is_expected:
                locations[role] = "target"
            elif (role == "staged" and cleanup in {"rollback_pending", "cleanup_pending", "cleaned"}
                  and recovery_at_target and output_status == "publishing"):
                locations[role] = "consumed"
            elif record.get("device") is None and cleanup == "active":
                locations[role] = "uncreated"
            elif cleanup in {"cleanup_pending", "cleaned"}:
                locations[role] = "missing"
            else:
                raise TransactionError("Updater publication artifact is missing or outside its recorded location.")
        return locations

    def write_artifact(self, area: str, path: Path, data: bytes) -> None:
        records, _ = self._artifact_records(area)
        matching = [(record) for _, (artifact_path, record) in records.items()
                    if artifact_path == path and record.get("sha256") == digest(data)
                    and record.get("size") == len(data)]
        if len(matching) != 1:
            raise TransactionError("Updater publication artifact was not durably registered.")
        record = matching[0]
        self._assert_checkout_path(path)
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                                 record["mode"])
        except OSError as exc:
            raise TransactionError("Updater publication artifact path is occupied; inspect it manually.") from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), record["mode"])
            stream.flush()
            os.fsync(stream.fileno())
            owned = os.fstat(stream.fileno())
        if not stat.S_ISREG(owned.st_mode) or stat.S_IMODE(owned.st_mode) != record["mode"]:
            raise TransactionError("Updater publication artifact mode could not be established.")
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        record["device"] = owned.st_dev
        record["inode"] = owned.st_ino
        _save(self.path, self.state)

    def prepare_artifact_rollback(self, area: str) -> None:
        if checkout_identity(self.root) == self.state["identity"]:
            raise TransactionError("Artifact rollback requires confirmed checkout identity drift.")
        locations = self._artifact_locations(area)
        if locations.get("staged") != "target" or locations.get("recovery") != "sidecar":
            raise TransactionError("Cannot authenticate updater bytes for rollback; preserve recovery artifacts.")
        self.state["outputs"][area]["artifact_cleanup"] = "rollback_pending"
        _save(self.path, self.state)
        locations = self._artifact_locations(area)
        if locations.get("staged") != "target" or locations.get("recovery") != "sidecar":
            raise TransactionError("Updater artifacts changed during rollback preparation; preserve recovery bytes.")

    def cleanup_artifacts(self, area: str, *, guarded: bool = False) -> None:
        records, _ = self._artifact_records(area)
        if not records:
            return
        if not guarded:
            with self.publication_guard():
                self.cleanup_artifacts(area, guarded=True)
            return
        records, output = self._artifact_records(area)
        cleanup_state = output.get("artifact_cleanup", "active")
        identity_matches = checkout_identity(self.root) == self.state["identity"]
        locations = self._artifact_locations(area)
        rollback_after_identity_drift = cleanup_state == "rollback_pending" and not identity_matches
        if not identity_matches and not rollback_after_identity_drift:
            raise TransactionError("Checkout branch, HEAD or worktree changed before artifact cleanup.")
        if output.get("artifact_cleanup") == "cleaned":
            return
        if rollback_after_identity_drift and any(location == "sidecar" for location in locations.values()):
            raise TransactionError("Checkout changed; preserve remaining updater recovery artifacts for inspection.")
        if identity_matches:
            self.assert_identity()
        output["artifact_cleanup"] = "cleanup_pending"
        _save(self.path, self.state)
        for role, (path, record) in records.items():
            if locations[role] == "sidecar":
                if not identity_matches:
                    raise TransactionError("Checkout changed; preserve remaining updater recovery artifacts for inspection.")
                self.assert_identity()
                self._assert_checkout_path(path)
                self._assert_artifact_file(path, record)
                path.unlink()
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        if identity_matches:
            self.assert_identity()
        for path, _ in records.values():
            if path.exists() or path.is_symlink():
                raise TransactionError("Updater publication artifact appeared during cleanup; inspect it manually.")
        output["artifact_cleanup"] = "cleaned"
        _save(self.path, self.state)

    def recover_publication(self) -> None:
        if checkout_identity(self.root) != self.state["identity"]:
            raise TransactionError("Checkout branch, HEAD or worktree changed since the update began.")
        for area, output in list(self.state["outputs"].items()):
            if output["status"] not in {"publishing", "applied"}:
                continue
            self._artifact_locations(area)
            if output["status"] == "publishing":
                matches = []
                for relpath, hashes in output["files"].items():
                    path = self.root / relpath
                    actual_file = self._read_nofollow(path, "lockfile publication target")
                    actual = digest(actual_file[1]) if actual_file is not None else None
                    if actual not in {hashes["before"], hashes["after"]}:
                        raise TransactionError("Interrupted publication has unrecognized lock bytes.")
                    matches.append("after" if actual == hashes["after"] else "before")
                if all(match == "after" for match in matches):
                    output["status"] = "applied"
                    self.state["outcomes"][area] = "applied"
                    _save(self.path, self.state)
                elif all(match == "before" for match in matches):
                    self.cleanup_artifacts(area)
                    previous = output.get("previous")
                    if previous is None:
                        del self.state["outputs"][area]
                    else:
                        self.state["outputs"][area] = previous
                    self.state["outcomes"][area] = "pending"
                    _save(self.path, self.state)
                    continue
                else:
                    raise TransactionError("Interrupted multi-file publication is partial; inspect recovery artifacts.")
            if output["status"] == "applied":
                self.cleanup_artifacts(area)

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

    def assert_publication_boundary(self, area: str, target: Path, before: bytes,
                                    expected_target: os.stat_result) -> None:
        """Authenticate registered artifacts and the original lock immediately before replacement."""
        try:
            target_relpath = target.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise TransactionError("Updater publication path escapes the checkout; inspect it manually.") from exc
        artifacts, output = self._artifact_records(area)
        hashes = output.get("files", {}).get(target_relpath)
        if (output.get("status") != "publishing" or set(output.get("files", {})) != {target_relpath}
                or not hashes or hashes.get("before") != digest(before)):
            raise TransactionError("Updater publication record does not match the lockfile boundary.")
        if any(record["mode"] != stat.S_IMODE(expected_target.st_mode)
               for _, record in artifacts.values()):
            raise TransactionError("Updater artifact mode does not match the original lockfile mode.")
        locations = self._artifact_locations(area)
        if locations != {"staged": "sidecar", "recovery": "sidecar"}:
            raise TransactionError("Updater publication artifacts changed location before lock replacement.")
        actual = self._read_nofollow(target, "lockfile publication target")
        if actual is None:
            raise TransactionError("Lockfile disappeared at publication boundary; refusing replacement.")
        info, data = actual
        if (not stat.S_ISREG(info.st_mode)
                or (info.st_dev, info.st_ino) != (expected_target.st_dev, expected_target.st_ino)
                or stat.S_IMODE(info.st_mode) != stat.S_IMODE(expected_target.st_mode)
                or info.st_size != len(before) or data != before):
            raise TransactionError("Lockfile changed at publication boundary; refusing to overwrite it.")

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

    def publishing(self, area: str, proposals: list[tuple[Path, bytes, bytes]], *,
                   artifacts: list[tuple[Path, Path, str, bytes, int]] | None = None) -> None:
        files = {}
        for path, before, after in proposals:
            actual = self._read_nofollow(path, "lockfile publication target")
            if actual is None or actual[1] != before:
                raise TransactionError("Lockfile changed before publication.")
            relpath = path.relative_to(self.root).as_posix()
            files[relpath] = {"before": digest(before), "after": digest(after)}
        artifact_records = None
        if artifacts is not None:
            if len(files) != 1:
                raise TransactionError("Single-lock artifact registration requires one lock target.")
            nonce = self.state.get("index_lock_nonce")
            if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
                raise TransactionError("Transaction has no identity for publication artifacts.")
            artifact_records = {}
            for artifact_path, target_path, role, data, mode in artifacts:
                if role not in {"staged", "recovery"} or target_path not in (proposal[0] for proposal in proposals):
                    raise TransactionError("Invalid single-lock publication artifact specification.")
                suffix = ".update-tmp" if role == "staged" else ".update-recovery"
                if artifact_path != target_path.with_name(target_path.name + suffix):
                    raise TransactionError("Updater artifact path does not match its lock target.")
                if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
                    raise TransactionError("Updater artifact mode is invalid.")
                target_relpath = target_path.relative_to(self.root).as_posix()
                expected_hash = files[target_relpath]["after" if role == "staged" else "before"]
                if digest(data) != expected_hash:
                    raise TransactionError("Updater artifact bytes do not match the validated proposal.")
                artifact_relpath = artifact_path.relative_to(self.root).as_posix()
                if artifact_relpath in artifact_records:
                    raise TransactionError("Duplicate updater artifact path.")
                artifact_records[artifact_relpath] = {
                    "owner_nonce": nonce,
                    "role": role,
                    "target": target_relpath,
                    "sha256": expected_hash,
                    "size": len(data),
                    "mode": mode,
                    "device": None,
                    "inode": None,
                }
            if {record["role"] for record in artifact_records.values()} != {"staged", "recovery"}:
                raise TransactionError("Single-lock publication requires staged and recovery artifacts.")
        previous = self.state["outputs"].get(area)
        output = {"status": "publishing", "files": files}
        if artifact_records is not None:
            output["artifacts"] = artifact_records
            output["artifact_cleanup"] = "active"
        if previous is not None:
            output["previous"] = previous
        self.state["outputs"][area] = output
        _save(self.path, self.state)

    def applied(self, area: str) -> None:
        self.assert_identity()
        output = self.state["outputs"][area]
        for relpath, hashes in output["files"].items():
            actual = self._read_nofollow(self.root / relpath, "lockfile publication target")
            if actual is None or digest(actual[1]) != hashes["after"]:
                raise TransactionError("Published lock bytes do not match transaction proposal.")
        artifacts, _ = self._artifact_records(area)
        if artifacts:
            locations = self._artifact_locations(area)
            if locations.get("staged") != "target" or locations.get("recovery") != "sidecar":
                raise TransactionError("Published lock artifacts do not match transaction ownership.")
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
