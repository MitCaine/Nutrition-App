"""Trusted Nutrition P/C materialization and structural-review evidence.

The installed RI package supplies inventories and comparisons. This consumer owns
Git membership, coverage policy, stability and reviewer attachment, not acceptance.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

from lib import ri_consumer as ri

POLICY = {"schema_version": 1, "scope": "changed-files-v1"}
MAX_CHANGED = 200
MAX_PACKET = 1_000_000
MAX_REVIEW_ARTIFACT_BYTES = 4_000_000
MAX_REVIEW_ARTIFACT_FILE_BYTES = 32_000_000
REVIEW_ARTIFACT_NAMES = frozenset({
    "membership", "planning-source-manifest", "candidate-source-manifest",
    "stability-before", "stability-after", "raw", "planning", "candidate",
    "comparison", "compact", "packet",
})


def configuration(capsule: str) -> dict | None:
    markers = re.findall(r"(?m)^```nutrition-ri-v1\s*$", capsule)
    blocks = re.findall(r"```nutrition-ri-v1\s*\n(.*?)\n```", capsule, re.S)
    if not markers and not blocks:
        return None
    try:
        value = json.loads(blocks[0]) if len(blocks) == 1 else None
    except (TypeError, ValueError) as exc:
        raise ri.RIError("RI_CAPSULE_POLICY_INVALID") from exc
    if len(markers) != 1 or len(blocks) != 1 or value != POLICY:
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
    disposition = ri.source_classification(path)
    if disposition != "supported":
        return disposition
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


def artifact_stat(path: Path):
    try:
        info = path.lstat()
    except OSError as exc:
        raise ri.RIError("RI_ARTIFACT_NOT_REGULAR") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ri.RIError("RI_ARTIFACT_NOT_REGULAR")
    if info.st_size > MAX_REVIEW_ARTIFACT_FILE_BYTES:
        raise ri.RIError("RI_STRUCTURAL_REVIEW_BUDGET_EXCEEDED")
    return info


def artifact_bytes(path: Path, *, expected_size: int | None = None) -> bytes:
    before = artifact_stat(path)
    if expected_size is not None and before.st_size != expected_size:
        raise ri.RIError("RI_STRUCTURAL_ARTIFACT_CHANGED")
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ri.RIError("RI_STRUCTURAL_ARTIFACT_CHANGED")
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    if len(raw) != before.st_size or identity(after) != identity(before) or identity(path.lstat()) != identity(before):
        raise ri.RIError("RI_STRUCTURAL_ARTIFACT_CHANGED")
    return raw


def artifact(path: Path, *, expected_size: int | None = None) -> dict:
    raw = artifact_bytes(path, expected_size=expected_size)
    return {"path": str(path.resolve()), "sha256": ri.sha256(raw), "bytes": len(raw)}


def artifact_metadata(entries: dict) -> None:
    """Check the complete physical inventory and budgets before any content read."""
    if not isinstance(entries, dict) or set(entries) != REVIEW_ARTIFACT_NAMES:
        raise ri.RIError("RI_STRUCTURAL_ARTIFACT_INVENTORY")
    parents = set()
    declared_total = physical_total = 0
    for name, entry in entries.items():
        if (not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}
                or not isinstance(entry["path"], str)
                or not isinstance(entry["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
                or type(entry["bytes"]) is not int or entry["bytes"] < 0):
            raise ri.RIError("RI_STRUCTURAL_ARTIFACT_METADATA")
        path = Path(entry["path"])
        if not path.is_absolute() or path.name != name + ".json" or str(path.resolve()) != entry["path"]:
            raise ri.RIError("RI_STRUCTURAL_ARTIFACT_METADATA")
        info = artifact_stat(path)
        declared_total += entry["bytes"]
        physical_total += info.st_size
        if (entry["bytes"] > MAX_REVIEW_ARTIFACT_FILE_BYTES
                or (name == "packet" and max(entry["bytes"], info.st_size) > MAX_PACKET)):
            raise ri.RIError("RI_STRUCTURAL_REVIEW_BUDGET_EXCEEDED")
        parents.add(path.parent)
    if declared_total > MAX_REVIEW_ARTIFACT_BYTES or physical_total > MAX_REVIEW_ARTIFACT_BYTES:
        raise ri.RIError("RI_STRUCTURAL_REVIEW_BUDGET_EXCEEDED")
    if len(parents) != 1:
        raise ri.RIError("RI_STRUCTURAL_ARTIFACT_INVENTORY")
    directory = next(iter(parents))
    if {p.stem for p in directory.glob("*.json")} - {"record"} != REVIEW_ARTIFACT_NAMES:
        raise ri.RIError("RI_STRUCTURAL_ARTIFACT_INVENTORY")
    for entry in entries.values():
        if Path(entry["path"]).lstat().st_size != entry["bytes"]:
            raise ri.RIError("RI_STRUCTURAL_ARTIFACT_CHANGED")


def review_artifacts(directory: Path) -> dict:
    """Authenticate complete retained plain artifacts after physical preflight."""
    paths = {p.stem: p for p in directory.glob("*.json")}
    if set(paths) != REVIEW_ARTIFACT_NAMES:
        raise ri.RIError("RI_STRUCTURAL_ARTIFACT_INVENTORY")
    sizes = {name: artifact_stat(path).st_size for name, path in paths.items()}
    if sum(sizes.values()) > MAX_REVIEW_ARTIFACT_BYTES or sizes["packet"] > MAX_PACKET:
        raise ri.RIError("RI_STRUCTURAL_REVIEW_BUDGET_EXCEEDED")
    entries = {name: artifact(path, expected_size=sizes[name]) for name, path in sorted(paths.items())}
    artifact_metadata(entries)
    return entries


def validate_record(binding: dict, record: dict) -> None:
    if (not isinstance(record, dict) or set(record) != {"binding_sha256", "planning", "candidate",
            "status", "selection_status", "packet", "artifacts", "record_sha256"}):
        raise ri.RIError("RI_STRUCTURAL_RECORD_MISMATCH")
    artifact_metadata(record.get("artifacts"))
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    packet = record.get("packet")
    if (not isinstance(packet, dict) or ri.digest(body) != record.get("record_sha256")
            or binding.get("structural") != POLICY
            or type(binding["structural"]["schema_version"]) is not int
            or record.get("binding_sha256") != binding["binding_sha256"]
            or record.get("planning") != binding["planning"] or record.get("candidate") != binding["candidate"]
            or record.get("status") not in {"comparable", "unsupported-only", "excluded-only", "mixed"}
            or record.get("selection_status") not in {"supported-only", "unsupported-only", "excluded-only", "mixed"}
            or record.get("selection_status") != packet.get("selection_status")
            or record.get("status") != packet.get("status")
            or type(packet.get("schema_version")) is not int or packet.get("schema_version") != 1
            or packet.get("policy") != POLICY or type(packet["policy"]["schema_version"]) is not int
            or packet.get("binding_sha256") != binding["binding_sha256"]
            or packet.get("planning") != binding["planning"] or packet.get("candidate") != binding["candidate"]
            or packet.get("paths") != binding["structural_paths"]):
        raise ri.RIError("RI_STRUCTURAL_RECORD_MISMATCH")
    packet_bytes = None
    for name, entry in record["artifacts"].items():
        path = Path(entry["path"])
        raw = artifact_bytes(path, expected_size=entry["bytes"])
        if {"path": str(path.resolve()), "sha256": ri.sha256(raw), "bytes": len(raw)} != entry:
            raise ri.RIError("RI_STRUCTURAL_ARTIFACT_CHANGED")
        if name == "packet":
            packet_bytes = raw
    if json.loads(packet_bytes) != packet:
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
