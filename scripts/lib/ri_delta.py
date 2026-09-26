"""Trusted Nutrition P/C materialization and structural-review evidence.

The installed RI package supplies inventories and comparisons. This consumer owns
Git membership, coverage policy, stability and reviewer attachment, not acceptance.
"""
from __future__ import annotations

import json
import re
import shutil
import stat
from pathlib import Path

from lib import ri_consumer as ri

POLICY = {"schema_version": 1, "scope": "changed-files-v1"}
MAX_CHANGED = 200
MAX_PACKET = 1_000_000


def configuration(capsule: str) -> dict | None:
    markers = re.findall(r"(?m)^```nutrition-ri-v1\s*$", capsule)
    blocks = re.findall(r"```nutrition-ri-v1\s*\n(.*?)\n```", capsule, re.S)
    if not markers and not blocks:
        return None
    if len(markers) != 1 or len(blocks) != 1 or json.loads(blocks[0]) != POLICY:
        raise ri.RIError("RI_CAPSULE_POLICY_INVALID")
    return dict(POLICY)


def changed_paths(repo: Path, planning: str, candidate: str) -> list[str]:
    return sorted(x for x in ri.git(repo, "diff", "--no-renames", "--name-only", "-z", planning, candidate).decode().split("\0") if x)


def tree(repo: Path, revision: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ri.RIError("RI_EXACT_COMMIT_REQUIRED")
    ri.git(repo, "cat-file", "-e", revision + "^{commit}")
    raw = ri.git(repo, "ls-tree", "-r", "-z", revision)
    if len(raw) > 8_000_000:
        raise ri.RIError("RI_TREE_BUDGET_EXCEEDED")
    records = {}
    for entry in raw.split(b"\0"):
        if entry:
            header, name = entry.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            records[name.decode()] = {"mode": mode, "kind": kind, "git_blob": oid}
    return records


def classification(path: str, record: dict | None) -> str:
    if record is None:
        return "absent"
    if any(part.startswith(".") or part in ri.EXCLUDED_DIRECTORIES for part in Path(path).parts):
        return "excluded"
    if Path(path).suffix.lower() not in ri.SUPPORTED:
        return "unsupported"
    if record["kind"] != "blob" or record["mode"] not in {"100644", "100755"}:
        raise ri.RIError("RI_NON_REGULAR_SUPPORTED_SOURCE: " + path)
    return "supported"


def file_changes(repo: Path, planning: str, candidate: str) -> list[dict]:
    fields = ri.git(repo, "diff", "--name-status", "-z", "--find-renames", planning, candidate).decode().split("\0")
    changes = []
    while fields and fields[0]:
        status = fields.pop(0)
        path = fields.pop(0)
        if status.startswith(("R", "C")):
            changes.append({"status": status, "planning_path": path, "candidate_path": fields.pop(0)})
        else:
            changes.append({"status": status, "planning_path": None if status == "A" else path,
                            "candidate_path": None if status == "D" else path})
    return changes


def check_transitions(changes: list[dict], trees: dict) -> None:
    for change in changes:
        before, after = change["planning_path"], change["candidate_path"]
        if before and after:
            old = classification(before, trees["planning"].get(before))
            new = classification(after, trees["candidate"].get(after))
            if {old, new} == {"supported", "excluded"}:
                raise ri.RIError("RI_INCLUSION_EXCLUSION_TRANSITION: " + before + " -> " + after)


def selection(repo: Path, records: dict, paths: list[str]) -> tuple[dict, dict]:
    selected, coverage = {}, {}
    total = 0
    for path in paths:
        record = records.get(path)
        disposition = classification(path, record)
        coverage[path] = {"classification": disposition, "git": record}
        if disposition != "supported":
            continue
        size = int(ri.git(repo, "cat-file", "-s", record["git_blob"]))
        total += size
        if size > ri.MAX_FILE_BYTES or total > ri.MAX_TOTAL_BYTES or len(selected) >= ri.MAX_FILES:
            raise ri.RIError("RI_SOURCE_BUDGET_EXCEEDED")
        raw = ri.git(repo, "cat-file", "blob", record["git_blob"])
        selected[path] = {"bytes": raw, "sha256": ri.sha256(raw), "git_blob": record["git_blob"], "mode": record["mode"]}
    return selected, coverage


def freeze(directory: Path) -> None:
    for path in directory.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    directory.chmod(0o555)


def stability(directory: Path, selected: dict) -> dict:
    ri.verify_materialization(directory, selected)
    result = {}
    for path in (directory, *sorted(directory.rglob("*"))):
        info = path.lstat()
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ri.RIError("RI_MATERIALIZATION_NON_REGULAR")
        result[path.relative_to(directory).as_posix()] = [info.st_dev, info.st_ino, info.st_mode,
                                                        info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    return result


def discard_materialization(directory: Path) -> None:
    if directory.exists():
        directory.chmod(0o700)
        for path in directory.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o700)
        shutil.rmtree(directory)


WORKER = """
import json,sys
from pathlib import Path
from repository_intelligence.inventory import inventory_tree,compare_inventories,compact_delta
p=inventory_tree(Path(sys.argv[1]),stable=True,logical_root="nutrition-changed-files-v1")
c=inventory_tree(Path(sys.argv[2]),stable=True,logical_root="nutrition-changed-files-v1")
d=compare_inventories(p,c)
print(json.dumps({"planning":p,"candidate":c,"comparison":d,"compact":compact_delta(d)}))
"""


def validate_inventory(value: dict, selected: dict, lock: dict) -> None:
    if (value.get("inventory_schema_version") != lock["contracts"]["inventory"]
            or value.get("navigation_schema_version") != lock["contracts"]["navigation"]
            or value.get("mapping_contract") != lock["contracts"]["mapping"]):
        raise ri.RIError("RI_INVENTORY_CONTRACT_CHANGED")
    if value.get("status") != "complete" or value.get("failures") or value.get("incomplete_reasons"):
        raise ri.RIError("RI_SUPPORTED_INVENTORY_INCOMPLETE")
    if value.get("materialization") != "caller_asserted_stable" or value.get("observed_exclusions") or value.get("observed_unsupported_paths"):
        raise ri.RIError("RI_UNEXPECTED_SCAN_COVERAGE")
    scope = value.get("scope", {})
    if (scope.get("logical_root") != "nutrition-changed-files-v1" or scope.get("language_choices") != {}
            or scope.get("excluded_directories") != [] or scope.get("configuration") is not None):
        raise ri.RIError("RI_COMPARISON_POLICY_CHANGED")
    files = value.get("files", [])
    if sorted(x.get("path", "") for x in files) != sorted(selected):
        raise ri.RIError("RI_INVENTORY_MEMBERSHIP_MISMATCH")
    for item in files:
        path = item["path"]
        data = selected[path]["bytes"]
        identity = item.get("source_identity", {})
        if (identity.get("relative_path") != path or identity.get("raw_sha256") != ri.sha256(data)
                or identity.get("byte_count") != len(data) or item.get("mapping_status") != "navigation_only"):
            raise ri.RIError("RI_INVENTORY_SOURCE_MISMATCH")
        coverage = item.get("adapter_coverage", {})
        structural = item.get("structural", {})
        declarations = item.get("declarations", [])
        if (not isinstance(declarations, list)
                or coverage.get("unhandled_node_count") != 0
                or coverage.get("mapped_node_count") != coverage.get("promised_node_count")
                or coverage.get("mapped_node_count") != len(declarations)
                or structural.get("error_count") != 0
                or structural.get("missing_count") != 0
                or structural.get("diagnostic_count") != 0
                or structural.get("declaration_count") != len(declarations)):
            raise ri.RIError("RI_SUPPORTED_INVENTORY_INCOMPLETE")
        parser = item.get("parser", {})
        suffix = Path(path).suffix.lower()
        grammar, package = (("Python", "tree-sitter-python") if suffix == ".py" else
                            ("TSX", "tree-sitter-typescript") if suffix == ".tsx" else
                            ("TypeScript", "tree-sitter-typescript") if suffix in {".ts", ".mts", ".cts"} else
                            ("JavaScript", "tree-sitter-javascript"))
        versions = {wheel["name"]: wheel["version"] for wheel in lock["wheels"]}
        if (parser.get("adapter_version") != lock["contracts"]["adapter"]
                or parser.get("runtime_version") != versions["tree-sitter"]
                or parser.get("grammar") != grammar or parser.get("grammar_version") != versions[package]):
            raise ri.RIError("RI_PARSER_CONTRACT_CHANGED")
        for declaration in declarations:
            span = declaration["byte_range"]
            start, end = span["start"], span["end"]
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(data)
                    or ri.sha256(data[start:end]) != declaration["declaration_sha256"]):
                raise ri.RIError("RI_DECLARATION_SOURCE_MISMATCH")


def validate_comparison(raw: dict, selected: dict, lock: dict) -> None:
    for side in ("planning", "candidate"):
        validate_inventory(raw[side], selected[side], lock)
    for key in ("scope", "parser_contract", "mapping_contract", "inventory_schema_version", "navigation_schema_version"):
        if raw["planning"].get(key) != raw["candidate"].get(key):
            raise ri.RIError("RI_COMPARISON_POLICY_CHANGED")
    if (raw["comparison"].get("status") != "comparable_candidate_delta"
            or raw["compact"].get("status") != "comparable_candidate_delta"):
        raise ri.RIError("RI_COMPARISON_NOT_COMPARABLE")
    expected = {key: [] for key in ("added", "removed", "modified", "unchanged")}
    for path in sorted(selected["planning"].keys() | selected["candidate"].keys()):
        before, after = selected["planning"].get(path), selected["candidate"].get(path)
        kind = ("added" if before is None else "removed" if after is None else
                "unchanged" if before["sha256"] == after["sha256"] else "modified")
        expected[kind].append(path)
    if raw["compact"].get("file_changes") != expected:
        raise ri.RIError("RI_GIT_DELTA_NOT_RECONCILED")


def artifact(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ri.RIError("RI_ARTIFACT_NOT_REGULAR")
    return {"path": str(path.resolve()), "sha256": ri.sha256(path.read_bytes()), "bytes": path.stat().st_size}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def capture(repo: Path, binding: dict, runtime: Path, directory: Path) -> dict:
    if binding.get("structural") != POLICY:
        raise ri.RIError("RI_FROZEN_POLICY_REQUIRED")
    planning, candidate = binding["planning"], binding["candidate"]
    ri.git(repo, "merge-base", "--is-ancestor", planning, candidate)
    lock = ri.read_lock()
    manifest, environment = ri.verify_runtime(runtime, lock=lock)
    directory = ri.external(directory, repo)
    if directory.exists() or directory.is_relative_to(runtime.resolve().parent):
        raise ri.RIError("RI_EVIDENCE_DIRECTORY_INVALID")
    paths = changed_paths(repo, planning, candidate)
    if paths != binding["structural_paths"] or not paths or len(paths) > MAX_CHANGED:
        raise ri.RIError("RI_CHANGED_SCOPE_MISMATCH_OR_LIMIT")
    trees = {side: tree(repo, sha) for side, sha in (("planning", planning), ("candidate", candidate))}
    changes = file_changes(repo, planning, candidate)
    check_transitions(changes, trees)
    selected, coverage = {}, {}
    for side in trees:
        selected[side], coverage[side] = selection(repo, trees[side], paths)
    directory.mkdir(parents=True)
    write_json(directory / "membership.json", {"trees": trees, "coverage": coverage, "changes": changes})
    roots = {side: directory / (side + "-source") for side in trees}
    try:
        for side in roots:
            source_manifest = ri.materialize(selected[side], roots[side])
            write_json(directory / (side + "-source-manifest.json"), source_manifest)
            freeze(roots[side])
        before = {side: stability(roots[side], selected[side]) for side in roots}
        write_json(directory / "stability-before.json", before)
        ri.offline_run([str(environment / "bin/python"), "-I", "-B", "-c", WORKER,
                        str(roots["planning"]), str(roots["candidate"])], cwd=directory,
                       log=directory / "raw.json", readonly_roots=list(roots.values()))
        after = {side: stability(roots[side], selected[side]) for side in roots}
        write_json(directory / "stability-after.json", after)
        if before != after:
            raise ri.RIError("RI_SOURCE_CHANGED_DURING_SCAN")
        ri.verify_runtime(runtime, lock=lock)
        raw = json.loads((directory / "raw.json").read_text())
        for name in ("planning", "candidate", "comparison", "compact"):
            write_json(directory / (name + ".json"), raw[name])
        validate_comparison(raw, selected, lock)
        has_supported = any(classification(p, trees[s].get(p)) == "supported" for p in paths for s in trees)
        packet = {"schema_version": 1, "binding_sha256": binding["binding_sha256"],
                  "planning": planning, "candidate": candidate, "policy": POLICY,
                  "ri_revision": lock["revision"], "contracts": lock["contracts"],
                  "runtime_manifest_sha256": manifest["manifest_sha256"],
                  "status": "comparable" if has_supported else "unsupported-only",
                  "paths": paths, "file_changes": changes, "coverage": coverage,
                  "compact_delta": raw["compact"], "worker_source_writes_denied": True,
                  "source_stability_verified": True,
                  "limitations": ["Complete changed-file callable inventories only; not whole-repository or semantic coverage.",
                                  "All changed files and the full Git diff require direct review, even with no callable delta.",
                                  "Unsupported-only is a coverage disposition, never structural proof or a native-check waiver."]}
        if len(json.dumps(packet, indent=2).encode()) > MAX_PACKET:
            raise ri.RIError("RI_STRUCTURAL_PACKET_LIMIT")
        write_json(directory / "packet.json", packet)
        record = {"binding_sha256": binding["binding_sha256"], "planning": planning, "candidate": candidate,
                  "status": packet["status"], "packet": packet,
                  "artifacts": {p.stem: artifact(p) for p in sorted(directory.glob("*.json"))}}
        record["record_sha256"] = ri.digest(record)
        write_json(directory / "record.json", record)
        return record
    except (OSError, ValueError, KeyError, TypeError, ri.RIError) as exc:
        write_json(directory / "failure.json", {"error": str(exc), "planning": planning, "candidate": candidate})
        raise
    finally:
        for root in roots.values():
            discard_materialization(root)


def validate_record(binding: dict, record: dict) -> None:
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    if (ri.digest(body) != record.get("record_sha256") or record.get("binding_sha256") != binding["binding_sha256"]
            or record.get("planning") != binding["planning"] or record.get("candidate") != binding["candidate"]
            or record.get("status") not in {"comparable", "unsupported-only"}
            or record.get("packet", {}).get("paths") != binding["structural_paths"]):
        raise ri.RIError("RI_STRUCTURAL_RECORD_MISMATCH")
    for entry in record["artifacts"].values():
        if artifact(Path(entry["path"])) != entry:
            raise ri.RIError("RI_STRUCTURAL_ARTIFACT_CHANGED")
    if json.loads(Path(record["artifacts"]["packet"]["path"]).read_text()) != record["packet"]:
        raise ri.RIError("RI_STRUCTURAL_PACKET_CHANGED")


def disposition(binding: dict, record: dict, value: dict) -> dict:
    validate_record(binding, record)
    if (set(value) != {"binding_sha256", "record_sha256", "paths"}
            or value["binding_sha256"] != binding["binding_sha256"]
            or value["record_sha256"] != record["record_sha256"] or not isinstance(value["paths"], list)):
        raise ri.RIError("RI_CONTROLLER_DISPOSITION_IDENTITY")
    if sorted(row.get("path", "") for row in value["paths"]) != binding["structural_paths"]:
        raise ri.RIError("RI_CONTROLLER_DISPOSITION_INCOMPLETE")
    for row in value["paths"]:
        if (set(row) != {"path", "decision", "authority", "qualification"} or row["decision"] != "expected"
                or not isinstance(row["authority"], str) or not row["authority"].strip()
                or not isinstance(row["qualification"], str) or not row["qualification"].strip()):
            raise ri.RIError("RI_UNEXPECTED_CHANGE_OR_MISSING_DISPOSITION")
    return value
