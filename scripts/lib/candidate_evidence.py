"""Exact capsule/candidate evidence; all durable state is controller-owned."""
from __future__ import annotations

import copy
import fnmatch
import hashlib
import hmac
import json
import re
import secrets
import subprocess
from pathlib import Path

from lib import ri_consumer, ri_delta
from lib.capsule_execution import capsule_metadata, source_snapshot, verify_planning_bytes
from lib.task_authorization import ResolvedAuthorization, canonical_json, validate_candidate_scope


class EvidenceError(RuntimeError):
    pass


GOVERNING_ISSUE_REPLAN_REQUIRED = "GOVERNING_ISSUE_REPLAN_REQUIRED"
GOVERNING_ISSUE_REVALIDATION_UNAVAILABLE = "GOVERNING_ISSUE_REVALIDATION_UNAVAILABLE"
GOVERNING_ISSUE_REVALIDATION_INVALID = "GOVERNING_ISSUE_REVALIDATION_INVALID"


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def governing_issue_material(issue: object, expected_number: int) -> dict:
    """Project the governing issue onto its four material authority fields."""
    if not isinstance(issue, dict):
        raise EvidenceError(GOVERNING_ISSUE_REVALIDATION_INVALID)

    number = issue.get("number")
    title = issue.get("title")
    body = issue.get("body")
    state = issue.get("state")
    if (type(expected_number) is not int or type(number) is not int
            or number != expected_number or not isinstance(title, str)
            or (body is not None and not isinstance(body, str))
            or not isinstance(state, str) or state not in {"open", "closed"}):
        raise EvidenceError(GOVERNING_ISSUE_REVALIDATION_INVALID)

    return {"number": number, "title": title, "body": body, "open": state == "open"}


def governing_issue_fingerprint(issue: object, expected_number: int) -> str:
    return digest(governing_issue_material(issue, expected_number))


def revalidate_governing_issue(binding: dict, issue: object) -> None:
    """Require an attached material issue fingerprint to match a live issue GET."""
    authorization = binding.get("authorization")
    expected_fingerprint = binding.get("issue_fingerprint")
    if (not isinstance(authorization, dict)
            or type(authorization.get("issue_number")) is not int
            or not isinstance(expected_fingerprint, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint)):
        raise EvidenceError(GOVERNING_ISSUE_REPLAN_REQUIRED)

    material = governing_issue_material(issue, authorization["issue_number"])
    if not material["open"] or digest(material) != expected_fingerprint:
        raise EvidenceError(GOVERNING_ISSUE_REPLAN_REQUIRED)


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode:
        raise EvidenceError("EVIDENCE_GIT_ERROR: " + result.stderr.decode(errors="replace"))
    return result.stdout


def git_text(repo: Path, *args: str) -> str:
    return git(repo, *args).decode().strip()


def read_blob(repo: Path, commit: str, path: str, *, max_bytes: int | None = None) -> bytes:
    if (not re.fullmatch(r"[0-9a-f]{40}", commit) or path.startswith("/")
            or any(x in {"", ".", ".."} for x in path.split("/")) or "\\" in path):
        raise EvidenceError("SOURCE_LOCATOR_INVALID")
    tree = git(repo, "ls-tree", "-z", commit, "--", path).split(b"\0")
    if len(tree) != 2 or not tree[0]:
        raise EvidenceError("SOURCE_PATH_NOT_COMMITTED")
    header, observed = tree[0].split(b"\t", 1)
    mode, kind, oid = header.split()
    if observed.decode() != path or kind != b"blob" or mode not in {b"100644", b"100755"}:
        raise EvidenceError("SOURCE_NOT_REGULAR")
    size = int(git_text(repo, "cat-file", "-s", oid.decode()))
    if size > ri_consumer.MAX_FILE_BYTES:
        raise EvidenceError("SOURCE_READ_LIMIT")
    if max_bytes is not None and size > max_bytes:
        raise EvidenceError("REVIEW_SOURCE_WORK_LIMIT")
    return git(repo, "cat-file", "blob", oid.decode())


def frozen_contract(raw: bytes) -> dict:
    metadata = capsule_metadata(raw)
    for key in ("state", "updated", "blocked", "blocked_reason", "blocked_since"):
        metadata.pop(key, None)
    body = raw.decode().split("+++", 2)[2]
    parts = re.split(r"(?m)^## (.+)\n", body)
    sections = {"preamble": parts[0]}
    for name, text in zip(parts[1::2], parts[2::2]):
        if name in sections:
            raise EvidenceError("CAPSULE_DUPLICATE_SECTION")
        if name not in {"State history", "Completion record"}:
            sections[name] = re.sub(r"(?m)^- \[[ xX]\] (AC-)", r"- [ ] \1", text).strip()
    return {"metadata": metadata, "sections": sections}


def requirements(raw: bytes) -> list[dict]:
    text = raw.decode()
    markers = re.findall(r"(?m)^```nutrition-evidence-v1[^\r\n]*$", text)
    blocks = re.findall(
        r"(?m)^```nutrition-evidence-v1[ \t]*\r?\n(.*?)\r?\n```[ \t]*$", text, re.S)
    if not markers:
        raise EvidenceError("CAPSULE_EVIDENCE_REQUIREMENTS_MISSING")
    if len(markers) != 1 or len(blocks) != 1:
        raise EvidenceError("CAPSULE_EVIDENCE_REQUIREMENTS_INVALID")
    try:
        values = json.loads(blocks[0])
    except ValueError as exc:
        raise EvidenceError("CAPSULE_EVIDENCE_REQUIREMENTS_INVALID") from exc
    if not isinstance(values, list) or not values:
        raise EvidenceError("CAPSULE_EVIDENCE_REQUIREMENTS_INVALID")
    kinds = {"focused", "baseline", "sqlite", "postgresql", "infrastructure", "native", "manual"}
    seen = set()
    for item in values:
        if (not isinstance(item, dict) or not {"id", "kind", "required", "argv"}.issubset(item)
                or set(item) - {"id", "kind", "required", "argv", "prepare"}
                or not isinstance(item["id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]*", item["id"])
                or item["id"] in seen or not isinstance(item["kind"], str)
                or item["kind"] not in kinds or type(item["required"]) is not bool):
            raise EvidenceError("CAPSULE_EVIDENCE_REQUIREMENT_INVALID")
        if "prepare" in item and (item["prepare"] != "mobile-npm-ci-offline-v1"
                                  or item["kind"] == "manual"):
            raise EvidenceError("CAPSULE_EVIDENCE_PREPARATION_INVALID")
        argv = item["argv"]
        if item["kind"] == "manual":
            if argv is not None:
                raise EvidenceError("MANUAL_EVIDENCE_COMMAND_FORBIDDEN")
        elif (not isinstance(argv, list) or not argv
              or any(not isinstance(x, str) or not x or "\0" in x for x in argv)):
            raise EvidenceError("EVIDENCE_COMMAND_INVALID")
        seen.add(item["id"])
    if not {"focused", "baseline"}.issubset({x["kind"] for x in values if x["required"]}):
        raise EvidenceError("REQUIRED_FOCUSED_AND_BASELINE_EVIDENCE_MISSING")
    return values


def review_obligations(repo: Path, raw: bytes, authorization: ResolvedAuthorization,
                       issue: dict, criteria: dict[str, str], required_checks: list[dict], *,
                       allow_unavailable_issue_text: bool = False) -> dict:
    """Bind a small, frozen issue/standards checklist to exact source bytes."""
    text = raw.decode()
    markers = re.findall(r"(?m)^```nutrition-review-obligations-v1[^\r\n]*$", text)
    blocks = re.findall(
        r"(?m)^```nutrition-review-obligations-v1[ \t]*\r?\n(.*?)\r?\n```[ \t]*$", text, re.S)
    if not markers:
        raise EvidenceError("REVIEW_OBLIGATIONS_MISSING")
    if len(markers) != 1 or len(blocks) != 1:
        raise EvidenceError("REVIEW_OBLIGATIONS_INVALID")
    try:
        value = json.loads(blocks[0])
    except ValueError as exc:
        raise EvidenceError("REVIEW_OBLIGATIONS_INVALID") from exc
    if (not isinstance(value, dict) or set(value) != {"schema_version", "outcomes", "standards"}
            or value["schema_version"] != 1 or not isinstance(value["outcomes"], list)
            or not isinstance(value["standards"], list)
            or not 1 <= len(value["outcomes"]) <= 16 or not 1 <= len(value["standards"]) <= 16):
        raise EvidenceError("REVIEW_OBLIGATIONS_INVALID")
    outcomes, standards = [], []
    checks = {item["id"]: item for item in required_checks}
    seen = set()
    for item in value["outcomes"]:
        if (not isinstance(item, dict) or set(item) != {"id", "quote", "mapping"}
                or not isinstance(item["id"], str) or not re.fullmatch(r"OUT-[1-9][0-9]*", item["id"])
                or item["id"] in seen or not isinstance(item["quote"], str)
                or not 8 <= len(item["quote"]) <= 1000
                or (not isinstance(issue.get("body"), str) and not allow_unavailable_issue_text)
                or (isinstance(issue.get("body"), str) and item["quote"] not in issue["body"])
                or not isinstance(item["mapping"], dict)):
            raise EvidenceError("REVIEW_OUTCOME_INVALID")
        seen.add(item["id"])
        mapping = item["mapping"]
        kind = mapping.get("type")
        if kind == "criteria":
            ids = mapping.get("ids")
            if (set(mapping) != {"type", "ids"} or not isinstance(ids, list) or not ids
                    or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids)
                    or any(x not in criteria for x in ids)):
                raise EvidenceError("REVIEW_OUTCOME_MAPPING_INVALID")
        elif kind == "unresolved":
            if (set(mapping) != {"type", "reason"} or not isinstance(mapping["reason"], str)
                    or not 1 <= len(mapping["reason"].strip()) <= 500):
                raise EvidenceError("REVIEW_OUTCOME_MAPPING_INVALID")
        elif kind == "deferred":
            check = mapping.get("manual_check")
            if (set(mapping) != {"type", "manual_check", "comment_id", "reason"}
                    or not isinstance(check, str) or checks.get(check, {}).get("kind") != "manual"
                    or checks[check]["required"] is not True or type(mapping.get("comment_id")) is not int
                    or mapping["comment_id"] < 1 or not isinstance(mapping.get("reason"), str)
                    or not 1 <= len(mapping["reason"].strip()) <= 500):
                raise EvidenceError("REVIEW_DEFERRAL_AUTHORITY_INVALID")
        else:
            raise EvidenceError("REVIEW_OUTCOME_MAPPING_INVALID")
        outcomes.append(item)
    seen.clear()
    for item in value["standards"]:
        if (not isinstance(item, dict) or set(item) != {"id", "path", "start_line", "end_line", "reason"}
                or not isinstance(item["id"], str) or not re.fullmatch(r"STD-[1-9][0-9]*", item["id"])
                or item["id"] in seen or not isinstance(item["path"], str)
                or type(item["start_line"]) is not int or type(item["end_line"]) is not int
                or not 1 <= item["start_line"] <= item["end_line"] <= item["start_line"] + 39
                or not isinstance(item["reason"], str) or not 1 <= len(item["reason"].strip()) <= 500):
            raise EvidenceError("REVIEW_STANDARD_INVALID")
        seen.add(item["id"])
        source = read_blob(repo, authorization.base_sha, item["path"])
        lines = source.decode().splitlines()
        if item["end_line"] > len(lines):
            raise EvidenceError("REVIEW_STANDARD_SOURCE_RANGE_INVALID")
        excerpt = "\n".join(lines[item["start_line"] - 1:item["end_line"]])
        if len(excerpt.encode()) > 8_000:
            raise EvidenceError("REVIEW_STANDARD_EXCERPT_LIMIT")
        standards.append({**item, "revision": authorization.base_sha,
                          "source_sha256": hashlib.sha256(source).hexdigest(),
                          "excerpt": excerpt})
    return {"schema_version": 1, "outcomes": outcomes, "standards": standards}


PLANNING_CONTEXT_SCHEMA_VERSION = 1
PLANNING_CONTEXT_FIELDS = {"schema_version", "workflow_mode", "authorization", "issue"}
AUTHORIZATION_CONTEXT_FIELDS = {
    "task_id", "issue_number", "repository", "base_sha", "allowed_paths",
    "forbidden_paths", "profiles", "revision", "nonce", "comment_id",
    "author_login", "payload_sha256", "identity_sha256",
}
PLANNING_BLOCK_TAGS = (
    "nutrition-review-obligations-v1",
    "nutrition-evidence-v1",
    "nutrition-ri-v1",
)


def planning_context_document(authorization: ResolvedAuthorization, workflow_mode: str,
                              issue: dict | None) -> dict:
    """Build the narrow, trusted input used by strict READY planning validation."""
    if workflow_mode not in {"attached", "compatibility"}:
        raise EvidenceError("PLANNING_WORKFLOW_MODE_INVALID")
    issue_context = None
    if issue is not None:
        if type(issue.get("number")) is not int or issue["number"] != authorization.issue_number:
            raise EvidenceError("PLANNING_ISSUE_CONTEXT_INVALID")
        body = issue.get("body")
        if body is not None and not isinstance(body, str):
            raise EvidenceError("PLANNING_ISSUE_CONTEXT_INVALID")
        issue_context = {"number": issue["number"], "body": body}
    return {"schema_version": PLANNING_CONTEXT_SCHEMA_VERSION,
            "workflow_mode": workflow_mode, "authorization": authorization.to_dict(),
            "issue": issue_context}


def parse_planning_context(value: object) -> dict:
    """Validate the controller-supplied planning context's exact shape."""
    if (not isinstance(value, dict) or set(value) != PLANNING_CONTEXT_FIELDS
            or type(value.get("schema_version")) is not int
            or value["schema_version"] != PLANNING_CONTEXT_SCHEMA_VERSION
            or value.get("workflow_mode") not in {"attached", "compatibility"}):
        raise EvidenceError("PLANNING_CONTEXT_INVALID")
    source = value.get("authorization")
    if not isinstance(source, dict) or set(source) != AUTHORIZATION_CONTEXT_FIELDS:
        raise EvidenceError("PLANNING_AUTHORIZATION_CONTEXT_INVALID")
    try:
        authorization = ResolvedAuthorization(
            task_id=source["task_id"], issue_number=source["issue_number"],
            repository=source["repository"], base_sha=source["base_sha"],
            allowed_paths=tuple(source["allowed_paths"]),
            forbidden_paths=tuple(source["forbidden_paths"]), profiles=tuple(source["profiles"]),
            revision=source["revision"], nonce=source["nonce"], comment_id=source["comment_id"],
            author_login=source["author_login"], payload_sha256=source["payload_sha256"],
            identity_sha256=source["identity_sha256"],
        )
    except (KeyError, TypeError) as exc:
        raise EvidenceError("PLANNING_AUTHORIZATION_CONTEXT_INVALID") from exc
    if authorization.to_dict() != source:
        raise EvidenceError("PLANNING_AUTHORIZATION_CONTEXT_INVALID")
    issue = value.get("issue")
    if issue is not None:
        if (not isinstance(issue, dict) or set(issue) != {"number", "body"}
                or type(issue.get("number")) is not int
                or issue["number"] != authorization.issue_number
                or (issue.get("body") is not None and not isinstance(issue["body"], str))):
            raise EvidenceError("PLANNING_ISSUE_CONTEXT_INVALID")
    return {"schema_version": PLANNING_CONTEXT_SCHEMA_VERSION,
            "workflow_mode": value["workflow_mode"], "authorization": authorization,
            "issue": issue}


def _planning_criteria(raw: bytes) -> dict[str, str]:
    sections = frozen_contract(raw)["sections"]
    section = sections.get("Acceptance criteria", "")
    matches = re.findall(r"(?m)^- \[[ xX]\] (AC-[A-Za-z0-9-]+):?\s+(.+)$", section)
    if not matches or len({identifier for identifier, _ in matches}) != len(matches):
        raise EvidenceError("CAPSULE_ACCEPTANCE_IDS_INVALID")
    return dict(matches)


def _has_planning_block_marker(raw: bytes) -> bool:
    text = raw.decode()
    return any(re.search(rf"(?m)^```{re.escape(tag)}(?:[ \t].*)?$", text)
               for tag in PLANNING_BLOCK_TAGS)


def validate_ready_planning(repo: Path, raw: bytes, context: dict | None) -> dict:
    """Apply attachment parsers early when trusted controller context is present."""
    if context is None:
        if _has_planning_block_marker(raw):
            raise EvidenceError("PLANNING_CONTEXT_REQUIRED")
        # The generic offline validator also serves compatibility work. It has no
        # authority to infer attached mode or fabricate its required context.
        return {"workflow_mode": "unspecified", "attached_blocks_checked": False,
                "issue_text_checked": False}
    parsed_context = parse_planning_context(context)
    authorization = parsed_context["authorization"]
    mode = parsed_context["workflow_mode"]
    metadata = capsule_metadata(raw)
    expected = {"id": authorization.task_id, "capsule_revision": authorization.revision,
                "base_commit": authorization.base_sha,
                "source_issue": f"https://github.com/{authorization.repository}/issues/{authorization.issue_number}"}
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise EvidenceError("PLANNING_AUTHORIZATION_MISMATCH")

    text = raw.decode()
    has_obligations = bool(re.search(r"(?m)^```nutrition-review-obligations-v1(?:[ \t].*)?$", text))
    has_requirements = bool(re.search(r"(?m)^```nutrition-evidence-v1(?:[ \t].*)?$", text))
    has_ri = bool(re.search(r"(?m)^```nutrition-ri-v1(?:[ \t].*)?$", text))
    if mode == "attached" or has_obligations or has_requirements or has_ri:
        planned = requirements(raw) if mode == "attached" or has_requirements else []
        criteria = _planning_criteria(raw)
        obligations = None
        if mode == "attached" or has_obligations:
            issue = parsed_context["issue"]
            obligations = review_obligations(
                repo, raw, authorization, issue or {"body": None}, criteria, planned,
                allow_unavailable_issue_text=issue is None or issue.get("body") is None)
        structural = ri_delta.configuration(text)
        if mode == "attached" or has_ri:
            # configuration() returns None for an absent optional block and raises
            # for malformed or duplicate selected policies.
            if has_ri and structural is None:
                raise EvidenceError("RI_CAPSULE_POLICY_INVALID")
        declared = {item["id"] for item in planned if item["required"]}
        specialized = metadata.get("specialized_qualification", [])
        if not isinstance(specialized, list):
            raise EvidenceError("SPECIALIST_REQUIREMENT_NOT_MACHINE_BOUND")
        for entry in specialized:
            if not isinstance(entry, str) or not entry.startswith(("profile:", "evidence:")):
                raise EvidenceError("SPECIALIST_REQUIREMENT_NOT_MACHINE_BOUND")
            if entry.startswith("evidence:") and entry[9:] not in declared:
                raise EvidenceError("SPECIALIST_REQUIREMENT_MISSING")
        profiles = sorted(entry[8:] for entry in specialized
                          if isinstance(entry, str) and entry.startswith("profile:"))
        if profiles != sorted(authorization.profiles):
            raise EvidenceError("CAPSULE_PROFILES_CHANGED")
        issue = parsed_context["issue"]
        return {"workflow_mode": mode, "attached_blocks_checked": True,
                "issue_text_checked": issue is not None and issue.get("body") is not None,
                "requirements": [item["id"] for item in planned],
                "outcomes": [item["id"] for item in obligations["outcomes"]] if obligations else [],
                "standards": [item["id"] for item in obligations["standards"]] if obligations else [],
                "ri_selected": structural is not None}
    return {"workflow_mode": mode, "attached_blocks_checked": False,
            "issue_text_checked": parsed_context["issue"] is not None
            and parsed_context["issue"].get("body") is not None}


def observe(repo: Path, candidate: str) -> dict:
    if git_text(repo, "rev-parse", "HEAD") != candidate:
        raise EvidenceError("CANDIDATE_HEAD_CHANGED")
    if git_text(repo, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
        raise EvidenceError("CANDIDATE_NOT_CLEAN")
    snapshot = source_snapshot(repo)
    verify_planning_bytes(repo, candidate, snapshot)
    index = Path(git_text(repo, "rev-parse", "--git-path", "index"))
    if not index.is_absolute():
        index = repo / index
    refs_raw = git(repo, "show-ref")
    refs = {name.decode(): sha.decode() for sha, name in
            (line.split(b" ", 1) for line in refs_raw.splitlines())}
    return {"candidate": candidate, "branch": git_text(repo, "branch", "--show-current"),
            "source_sha256": digest(snapshot),
            "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            "refs_sha256": hashlib.sha256(refs_raw).hexdigest(), "refs": refs}


def source_matches(expected: dict, observed: dict, *, main_transition: tuple[str, str] | None = None,
                   added_refs: dict[str, str] | None = None) -> bool:
    """Keep sealed source identity across receipted main and terminal ref moves."""
    if any(expected.get(key) != observed.get(key) for key in
           ("candidate", "branch", "source_sha256", "index_sha256")):
        return False
    if expected.get("refs_sha256") == observed.get("refs_sha256"):
        return "refs" not in expected or expected["refs"] == observed.get("refs")
    if main_transition is None or not isinstance(expected.get("refs"), dict) or not isinstance(observed.get("refs"), dict):
        return False
    before, after = main_transition
    main_refs = {"refs/remotes/origin/main", "refs/heads/main"}
    alias = "refs/remotes/origin/HEAD"
    additions = added_refs or {}
    if (not isinstance(additions, dict)
            or any(not isinstance(name, str) or not isinstance(sha, str)
                   or not re.fullmatch(r"[0-9a-f]{40}", sha)
                   or name in main_refs | {alias}
                   for name, sha in additions.items())):
        return False
    permitted = main_refs | {alias} | additions.keys()
    changed = {name for name in expected["refs"].keys() | observed["refs"].keys()
               if expected["refs"].get(name) != observed["refs"].get(name)}
    if not changed & main_refs or not changed <= permitted:
        return False
    if alias in changed and ("refs/remotes/origin/main" not in changed
                             or expected["refs"].get(alias) != expected["refs"].get("refs/remotes/origin/main")
                             or observed["refs"].get(alias) != observed["refs"].get("refs/remotes/origin/main")):
        return False
    return all(
        (expected["refs"].get(name) == before and observed["refs"].get(name) == after)
        if name in main_refs | {alias} else
        (name not in expected["refs"] and observed["refs"].get(name) == additions[name])
        for name in changed)


def attach(repo: Path, authorization: ResolvedAuthorization, *, planning: str,
           candidate: str, issue: dict, correction_limit: int = 1) -> dict:
    if type(correction_limit) is not int or correction_limit not in (0, 1):
        raise EvidenceError("CORRECTION_LIMIT_INVALID")
    issue_material = governing_issue_material(issue, authorization.issue_number)
    if not issue_material["open"]:
        raise EvidenceError(GOVERNING_ISSUE_REPLAN_REQUIRED)
    for sha in (planning, candidate):
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise EvidenceError("EXACT_COMMIT_REQUIRED")
    capsule_path = f"engineering/capsules/active/{authorization.task_id}.md"
    parents = git_text(repo, "rev-list", "--parents", "-n", "1", planning).split()
    if parents != [planning, authorization.base_sha]:
        raise EvidenceError("CAPSULE_PLANNING_BASE_MISMATCH")
    if git_text(repo, "diff", "--name-only", authorization.base_sha, planning).splitlines() != [capsule_path]:
        raise EvidenceError("CAPSULE_PLANNING_OVERLAY_INVALID")
    git(repo, "merge-base", "--is-ancestor", planning, candidate)
    original = read_blob(repo, planning, capsule_path)
    current = read_blob(repo, candidate, capsule_path)
    metadata = capsule_metadata(original)
    expected = {"id": authorization.task_id, "capsule_revision": authorization.revision,
                "base_commit": authorization.base_sha, "state": "READY", "blocked": False,
                "source_issue": f"https://github.com/{authorization.repository}/issues/{authorization.issue_number}"}
    if any(metadata.get(k) != v for k, v in expected.items()):
        raise EvidenceError("CAPSULE_AUTHORIZATION_MISMATCH")
    if sorted(x[8:] for x in metadata["specialized_qualification"] if x.startswith("profile:")) != sorted(authorization.profiles):
        raise EvidenceError("CAPSULE_PROFILES_CHANGED")
    planned = requirements(original)
    declared = {x["id"] for x in planned if x["required"]}
    for entry in metadata["specialized_qualification"]:
        if not entry.startswith(("profile:", "evidence:")):
            raise EvidenceError("SPECIALIST_REQUIREMENT_NOT_MACHINE_BOUND")
        if entry.startswith("evidence:") and entry[9:] not in declared:
            raise EvidenceError("SPECIALIST_REQUIREMENT_MISSING")
    allowed = metadata["owned_paths"] + metadata["allowed_paths"]
    for pattern in allowed:
        if pattern not in authorization.allowed_paths and (any(x in pattern for x in "*?[")
                or not any(fnmatch.fnmatchcase(pattern, x) for x in authorization.allowed_paths)):
            raise EvidenceError("CAPSULE_SCOPE_EXPANDS_AUTHORITY")
    changed = validate_candidate_scope(repo, authorization, candidate_sha=candidate,
                                       observed_main_sha=authorization.base_sha)
    forbidden = list(authorization.forbidden_paths) + metadata["forbidden_paths"]
    for path in changed:
        if (not any(fnmatch.fnmatchcase(path, x) for x in allowed)
                or any(fnmatch.fnmatchcase(path, x) for x in forbidden)):
            raise EvidenceError("CANDIDATE_CAPSULE_SCOPE_MISMATCH")
    if frozen_contract(original) != frozen_contract(current):
        raise EvidenceError("CAPSULE_SEMANTIC_CHANGE_REQUIRES_REPLAN")
    current_meta = capsule_metadata(current)
    if current_meta["state"] not in {"IMPLEMENTED", "VERIFIED", "REVIEWED"} or current_meta["blocked"]:
        raise EvidenceError("CANDIDATE_NOT_IMPLEMENTED")
    observed = observe(repo, candidate)
    if observed["branch"] != metadata["branch"]:
        raise EvidenceError("CANDIDATE_BRANCH_MISMATCH")
    ac_section = frozen_contract(original)["sections"].get("Acceptance criteria", "")
    criteria = re.findall(r"(?m)^- \[[ xX]\] (AC-[A-Za-z0-9-]+):?\s+(.+)$", ac_section)
    if not criteria or len({x[0] for x in criteria}) != len(criteria):
        raise EvidenceError("CAPSULE_ACCEPTANCE_IDS_INVALID")
    obligations = review_obligations(repo, original, authorization, issue, dict(criteria), planned)
    result = {"schema_version": 1, "authorization": authorization.to_dict(),
              "planning": planning, "candidate": candidate, "capsule_path": capsule_path,
              "capsule_sha256": hashlib.sha256(original).hexdigest(),
              "candidate_capsule_sha256": hashlib.sha256(current).hexdigest(),
              "capsule_text": original.decode(), "contract_sha256": digest(frozen_contract(original)),
              "branch": metadata["branch"], "criteria": dict(criteria), "requirements": planned,
              "review_obligations": obligations,
              "issue": issue, "issue_sha256": digest(issue),
              "issue_fingerprint": digest(issue_material), "source": observed,
              "changed_paths": changed, "correction_limit": correction_limit}
    structural = ri_delta.configuration(original.decode())
    if structural is not None:
        result["structural"] = structural
        result["structural_paths"] = ri_delta.changed_paths(repo, planning, candidate)
    return {**result, "binding_sha256": digest(result)}


def authenticate_binding(binding: dict, authorization: ResolvedAuthorization, candidate: str) -> None:
    value = dict(binding)
    signature = value.pop("binding_sha256", None)
    if digest(value) != signature:
        raise EvidenceError("ATTACHMENT_DIGEST_MISMATCH")
    if binding["authorization"] != authorization.to_dict() or binding["candidate"] != candidate:
        raise EvidenceError("ATTACHMENT_AUTHORITY_OR_CANDIDATE_CHANGED")


def qualify(binding: dict, qualification: dict, check: dict, expected_app: int) -> dict:
    auth = binding["authorization"]
    expected_external = f"nutrition-task:{auth['issue_number']}:{auth['identity_sha256']}:{binding['candidate']}"
    if (type(expected_app) is not int or expected_app < 1 or expected_app == 15368
            or qualification.get("result") != "PASS"
            or qualification.get("candidate_sha") != binding["candidate"]
            or qualification.get("check_app_id") != expected_app
            or qualification.get("candidate_ref_removed") is not True
            or check.get("id") != qualification.get("check_id")
            or check.get("app", {}).get("id") != expected_app
            or check.get("name") != "Main qualification"
            or check.get("head_sha") != binding["candidate"]
            or check.get("status") != "completed" or check.get("conclusion") != "success"
            or check.get("external_id") != expected_external):
        raise EvidenceError("EXACT_TRUSTED_QUALIFICATION_REQUIRED")
    return {"binding_sha256": binding["binding_sha256"], "profiles": auth["profiles"],
            "qualification": qualification, "check": check}


def validate_commands(binding: dict, observations: dict) -> None:
    for requirement in binding["requirements"]:
        item = observations.get(requirement["id"])
        if item is None:
            if requirement["required"]:
                raise EvidenceError("REQUIRED_EVIDENCE_MISSING: " + requirement["id"])
            continue
        if (item.get("binding_sha256") != binding["binding_sha256"]
                or item.get("kind") != requirement["kind"]
                or item.get("status") not in {"passed", "failed", "skipped", "unavailable"}):
            raise EvidenceError("COMMAND_EVIDENCE_MISMATCH")
        if requirement["required"] and item["status"] != "passed":
            raise EvidenceError("REQUIRED_EVIDENCE_NOT_PASSED: " + requirement["id"])


def validate_verdict(binding: dict, value: dict) -> str:
    obligations = binding.get("review_obligations")
    if not isinstance(obligations, dict):
        raise EvidenceError("REVIEW_OBLIGATIONS_MISSING")
    expected_fields = {"candidate", "binding_sha256", "disposition", "matrix", "findings", "summary",
                       "outcome_review", "standards_review"}
    if binding.get("structural"):
        expected_fields.add("structural_review")
    if (not isinstance(value, dict) or set(value) != expected_fields
            or value["candidate"] != binding["candidate"]
            or value["binding_sha256"] != binding["binding_sha256"]
            or value["disposition"] not in {"approved", "bounded-correction", "stop-replan"}
            or not isinstance(value["summary"], str) or not value["summary"].strip()
            or not isinstance(value["findings"], list) or not isinstance(value["matrix"], list)
            or not isinstance(value["outcome_review"], list) or not isinstance(value["standards_review"], list)):
        raise EvidenceError("REVIEW_VERDICT_INVALID")
    rows = value["matrix"]
    if len(rows) != len(binding["criteria"]):
        raise EvidenceError("REVIEW_ACCEPTANCE_MATRIX_INCOMPLETE")
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"id", "result", "evidence"}
                or row["id"] not in binding["criteria"] or row["id"] in seen
                or row["result"] not in {"PASS", "FAIL"}
                or not isinstance(row["evidence"], str) or not row["evidence"].strip()):
            raise EvidenceError("REVIEW_ACCEPTANCE_MATRIX_INVALID")
        seen.add(row["id"])
    for finding in value["findings"]:
        if (not isinstance(finding, dict) or set(finding) != {"priority", "path", "line", "description"}
                or type(finding["priority"]) is not int or finding["priority"] not in range(4)
                or type(finding["line"]) is not int or finding["line"] < 1
                or not isinstance(finding["path"], str) or not finding["path"]
                or not isinstance(finding["description"], str) or not finding["description"].strip()):
            raise EvidenceError("REVIEW_FINDING_INVALID")
    outcome_ids = {item["id"] for item in obligations["outcomes"]}
    standard_ids = {item["id"] for item in obligations["standards"]}
    for name, expected, permitted in (("outcome_review", outcome_ids, {"PASS", "FAIL", "UNRESOLVED", "DEFERRED"}),
                                      ("standards_review", standard_ids, {"PASS", "FAIL", "UNRESOLVED"})):
        found = set()
        for row in value[name]:
            if (not isinstance(row, dict) or set(row) != {"id", "result", "evidence"}
                    or row["id"] not in expected or row["id"] in found
                    or row["result"] not in permitted or not isinstance(row["evidence"], str)
                    or not row["evidence"].strip()):
                raise EvidenceError("REVIEW_OBLIGATION_MATRIX_INVALID")
            found.add(row["id"])
        if found != expected:
            raise EvidenceError("REVIEW_OBLIGATION_MATRIX_INCOMPLETE")
    structural_rows = value.get("structural_review", [])
    if binding.get("structural"):
        if (not isinstance(structural_rows, list)
                or sorted(row.get("path", "") for row in structural_rows) != binding["structural_paths"]):
            raise EvidenceError("REVIEW_STRUCTURAL_MATRIX_INCOMPLETE")
        for row in structural_rows:
            if (set(row) != {"path", "result", "evidence"} or row["result"] not in {"PASS", "FAIL"}
                    or not isinstance(row["evidence"], str) or not row["evidence"].strip()):
                raise EvidenceError("REVIEW_STRUCTURAL_MATRIX_INVALID")
    if value["disposition"] == "approved":
        outcome_mapping = {item["id"]: item["mapping"]["type"] for item in obligations["outcomes"]}
        outcome_bad = any(row["result"] != ("DEFERRED" if outcome_mapping[row["id"]] == "deferred" else "PASS")
                          or outcome_mapping[row["id"]] == "unresolved" for row in value["outcome_review"])
        if (value["findings"] or any(x["result"] != "PASS" for x in rows + structural_rows + value["standards_review"])
                or outcome_bad):
            raise EvidenceError("REVIEW_APPROVAL_CONTRADICTS_FINDINGS")
    return value["disposition"]


def sign_receipt(receipt: dict, key: bytes) -> dict:
    if len(key) != 32:
        raise EvidenceError("CONTROLLER_KEY_INVALID")
    return {**receipt, "signature": hmac.new(key, canonical_json(receipt).encode(), hashlib.sha256).hexdigest()}


def authenticate_receipt(receipt: dict, key: bytes, binding: dict) -> None:
    value = dict(receipt)
    signature = value.pop("signature", None)
    expected = sign_receipt(value, key)["signature"]
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise EvidenceError("REVIEW_CONTROLLER_PROVENANCE_INVALID")
    if receipt.get("binding_sha256") != binding["binding_sha256"]:
        raise EvidenceError("REVIEW_CANDIDATE_REPLAY")
    session = receipt.get("session", {})
    if (not session.get("thread_id") or not session.get("turn_id") or not session.get("nonce")
            or session.get("fresh") is not True or session.get("completed") is not True
            or session.get("environment_access") is not False or session.get("mcp_disabled") is not True):
        raise EvidenceError("REVIEW_SESSION_PROVENANCE_INVALID")
    validate_verdict(binding, receipt["verdict"])


def correction(state: dict) -> dict:
    evidence = state.get("capsule_evidence", {})
    receipt = evidence.get("review", {})
    if (receipt.get("verdict", {}).get("disposition") != "bounded-correction"
            or state.get("phase") != "REVIEWED_CHANGES_REQUESTED"):
        raise EvidenceError("BOUNDED_CORRECTION_NOT_AUTHORIZED")
    used = evidence.get("corrections_used", 0)
    if used >= evidence["binding"]["correction_limit"]:
        raise EvidenceError("CORRECTION_BUDGET_EXHAUSTED")
    updated = copy.deepcopy(state)
    updated.setdefault("evidence_history", []).append(copy.deepcopy(evidence))
    updated["capsule_evidence"] = {"planning": evidence["binding"]["planning"],
                                   "prior_binding": evidence["binding"]["binding_sha256"],
                                   "corrections_used": used + 1, "requires_fresh_candidate": True}
    updated.update(phase="AUTHORIZED", qualification=None, verification=None, review=None, integration=None)
    return updated


def create_key(path: Path) -> bytes:
    if path.is_symlink():
        raise EvidenceError("CONTROLLER_KEY_LINK_FORBIDDEN")
    if path.exists():
        if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_mode & 0o077:
            raise EvidenceError("CONTROLLER_KEY_PERMISSIONS_INVALID")
        key = path.read_bytes()
    else:
        key = secrets.token_bytes(32)
        with path.open("xb") as handle:
            path.chmod(0o600)
            handle.write(key)
    if len(key) != 32:
        raise EvidenceError("CONTROLLER_KEY_INVALID")
    return key


def artifact(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise EvidenceError("EVIDENCE_ARTIFACT_NOT_REGULAR")
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size}


def validate_artifacts(record: dict) -> None:
    for entry in record.get("artifacts", {}).values():
        if artifact(Path(entry["path"])) != entry:
            raise EvidenceError("EVIDENCE_ARTIFACT_CHANGED")


def run_check(repo: Path, binding: dict, identifier: str, directory: Path,
              *, timeout: float = 900) -> dict:
    """Run frozen argv in an offline disposable clone, never the authority checkout."""
    import os
    import platform
    import signal
    import sys
    import time
    import shutil
    import stat

    def tested_source(clone: Path) -> dict:
        """Bind the bytes the command can read to every regular blob in C."""
        candidate = binding["candidate"]
        if git_text(clone, "rev-parse", "HEAD") != candidate:
            raise EvidenceError("EVIDENCE_TESTED_HEAD_CHANGED")
        algorithm = git_text(clone, "rev-parse", "--show-object-format")
        if algorithm not in {"sha1", "sha256"}:
            raise EvidenceError("EVIDENCE_TESTED_OBJECT_FORMAT")
        records = {}
        total = 0
        for entry in git(clone, "ls-tree", "-r", "-z", candidate).split(b"\0"):
            if not entry:
                continue
            header, name = entry.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise EvidenceError("EVIDENCE_TESTED_NON_REGULAR_SOURCE")
            path = clone / name.decode()
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise EvidenceError("EVIDENCE_TESTED_NON_REGULAR_SOURCE")
            raw = path.read_bytes()
            observed = hashlib.new(algorithm, b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if observed != oid or bool(info.st_mode & 0o111) != (mode == "100755"):
                raise EvidenceError("EVIDENCE_TESTED_SOURCE_CHANGED: " + name.decode())
            records[name.decode()] = {"sha256": hashlib.sha256(raw).hexdigest(), "mode": mode}
            total += len(raw)
        return {"candidate": candidate, "source_sha256": digest(records),
                "tracked_files": len(records), "tracked_bytes": total}

    requirement = next((x for x in binding["requirements"] if x["id"] == identifier), None)
    if requirement is None or requirement["kind"] == "manual":
        raise EvidenceError("EXECUTABLE_REQUIREMENT_REQUIRED")
    if not 0 < timeout <= 3600:
        raise EvidenceError("EVIDENCE_TIMEOUT_INVALID")
    directory = directory.resolve()
    if directory == repo.resolve() or directory.is_relative_to(repo.resolve()):
        raise EvidenceError("EVIDENCE_STATE_INSIDE_CANDIDATE")
    before = observe(repo, binding["candidate"])
    if before != binding["source"]:
        raise EvidenceError("EVIDENCE_SOURCE_CHANGED")
    directory.mkdir(parents=True, exist_ok=False)
    record = {"binding_sha256": binding["binding_sha256"], "id": identifier,
              "kind": requirement["kind"], "status": "unavailable", "artifacts": {},
              "source_before": before, "source_after": None,
              "tested_source_before": None, "tested_source_after": None,
              "argv": None, "exit_code": None}
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        record["reason"] = "Local command transport is qualified only on macOS; no substitute result."
        return record
    scratch = directory / "scratch"
    scratch.mkdir()
    clone = scratch / "repository"
    result = subprocess.run(["git", "clone", "--no-hardlinks", "--no-checkout", str(repo), str(clone)],
                            capture_output=True)
    if result.returncode:
        raise EvidenceError("EVIDENCE_CLONE_FAILED")
    git(clone, "checkout", "--detach", binding["candidate"])
    record["tested_source_before"] = tested_source(clone)
    preparation = requirement.get("prepare")
    cache = None
    if preparation == "mobile-npm-ci-offline-v1":
        mobile = clone / "apps/mobile"
        lock = mobile / "package-lock.json"
        manifest = mobile / "package.json"
        cache_value = os.environ.get("NUTRITION_EVIDENCE_NPM_CACHE", "")
        cache = Path(cache_value).expanduser().absolute() if cache_value else None
        trusted_cache = (Path.home() / ".npm").absolute()
        if (not lock.is_file() or lock.is_symlink() or not manifest.is_file()
                or manifest.is_symlink()):
            record["reason"] = "Mobile manifest or lock unavailable in exact candidate"
            return record
        if (cache is None or cache != trusted_cache or cache.resolve() != cache
                or not cache.is_dir()):
            record["reason"] = "Trusted local npm cache unavailable"
            return record
        record["preparation"] = {"contract": preparation,
                                  "package_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
                                  "package_json_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                                  "cache": str(cache)}
    python = Path(sys.executable).absolute()
    replacements = {"{python}": str(python), "{repository}": str(clone), "{evidence}": str(scratch / "output")}
    argv = [replacements.get(x, x) for x in requirement["argv"]]
    executable = Path(argv[0]) if "/" in argv[0] else Path(shutil.which(argv[0]) or "/missing")
    if not executable.is_absolute():
        executable = clone / executable
    executable = executable.absolute()
    if not executable.is_file():
        record["reason"] = "Declared executable unavailable"
        return record
    argv[0] = str(executable)
    record.update(argv=argv, runtime={"executable": str(executable),
                  "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                  "python_prefix": sys.prefix, "python_base_prefix": sys.base_prefix,
                  "python_version": sys.version})
    reads = ["/System", "/usr", "/bin", "/sbin", "/Library", "/opt/homebrew",
             "/private/var/select", "/var/select", "/Applications/Xcode.app", str(scratch), str(python.parent.parent),
             str(python.resolve().parent.parent)]
    def sandbox_policy(read_paths: list[str], write_paths: list[Path]) -> str:
        metadata_paths = sorted({str(p) for root in read_paths for p in Path(root).parents}
                                | {str(p) for p in scratch.parents}
                                | {str(directory / name) for name in
                                   ("stdout.log", "stderr.log", "prepare-stdout.log", "prepare-stderr.log")})
        return "\n".join([
            "(version 1)", "(deny default)", "(allow process*)", "(allow sysctl-read)", "(allow mach-lookup)",
            '(allow file-read* (literal "/") (subpath "/dev/fd") (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))',
            "(allow file-read* " + " ".join("(subpath " + json.dumps(x) + ")" for x in read_paths) + ")",
            "(allow file-read-metadata " + " ".join("(literal " + json.dumps(x) + ")" for x in metadata_paths) + ")",
            "(allow file-write* (literal \"/dev/null\") "
            + " ".join("(subpath " + json.dumps(str(path)) + ")" for path in write_paths) + ")",
            "(deny network*)",
        ])
    (scratch / "home").mkdir()
    (scratch / "tmp").mkdir()
    (scratch / "output").mkdir()
    profile = sandbox_policy(reads, [scratch / "home", scratch / "tmp", scratch / "output"])
    (directory / "sandbox.sb").write_text(profile)
    developer = next((p for p in (Path("/Applications/Xcode.app/Contents/Developer"),
                                  Path("/Library/Developer/CommandLineTools")) if (p / "usr/bin/git").is_file()), None)
    tool_path = str(developer / "usr/bin") + ":" if developer else ""
    mobile_node_bin = os.environ.get("NUTRITION_EVIDENCE_NODE_BIN", "") if preparation == "mobile-npm-ci-offline-v1" else ""
    mobile_node_path = str(Path(mobile_node_bin).absolute()) + ":" if mobile_node_bin else ""
    env = {"HOME": str(scratch / "home"), "TMPDIR": str(scratch / "tmp"),
           "PATH": mobile_node_path + str(python.parent) + ":" + tool_path + "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "NUTRITION_REVIEW_OUTPUT_DIR": str(scratch / "output")}
    if developer:
        env["DEVELOPER_DIR"] = str(developer)
    record["environment"] = env
    if preparation == "mobile-npm-ci-offline-v1":
        node_bin = Path(mobile_node_bin).absolute() if mobile_node_bin else None
        if (node_bin is None or not node_bin.is_dir()
                or not node_bin.resolve().is_relative_to(Path("/opt/homebrew"))):
            record["reason"] = "Explicit supported Node toolchain unavailable"
            return record
        npm = Path(shutil.which("npm", path=env["PATH"]) or "/missing").absolute()
        node = Path(shutil.which("node", path=env["PATH"]) or "/missing").absolute()
        if not npm.is_file() or not node.is_file():
            record["reason"] = "npm or Node executable unavailable"
            return record
        if (node.parent != node_bin or npm.parent != node_bin
                or not node.resolve().is_relative_to(Path("/opt/homebrew"))
                or not npm.resolve().is_relative_to(Path("/opt/homebrew"))):
            record["reason"] = "Explicit Node/npm toolchain unavailable"
            return record
        node_version = subprocess.run([str(node), "--version"], capture_output=True, env=env, timeout=10)
        if node_version.returncode or not re.fullmatch(rb"v\d+\.\d+\.\d+\s*", node_version.stdout):
            record["reason"] = "Node runtime unavailable"
            return record
        prepare_argv = [str(npm), "ci", "--offline", "--ignore-scripts", "--engine-strict", "--no-audit",
                        "--no-fund", "--cache", str(cache)]
        record["preparation"].update(argv=prepare_argv,
            npm_sha256=hashlib.sha256(npm.read_bytes()).hexdigest(),
            node_path=str(node), node_sha256=hashlib.sha256(node.read_bytes()).hexdigest(),
            node_version=node_version.stdout.decode().strip())
        prepare_profile = sandbox_policy([*reads, str(cache)], [scratch])
        (directory / "prepare-sandbox.sb").write_text(prepare_profile)
        with (directory / "prepare-stdout.log").open("wb") as stdout, (directory / "prepare-stderr.log").open("wb") as stderr:
            process = subprocess.Popen(["/usr/bin/sandbox-exec", "-p", prepare_profile, *prepare_argv],
                                       cwd=clone / "apps/mobile", env=env, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                prepare_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                prepare_code = None
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=10)
        record["preparation"].update(exit_code=prepare_code,
            stdout=artifact(directory / "prepare-stdout.log"),
            stderr=artifact(directory / "prepare-stderr.log"))
        record["artifacts"].update({"prepare-stdout.log": record["preparation"]["stdout"],
                                    "prepare-stderr.log": record["preparation"]["stderr"],
                                    "prepare-sandbox.sb": artifact(directory / "prepare-sandbox.sb"),
                                    "sandbox.sb": artifact(directory / "sandbox.sb")})
        if prepare_code != 0:
            record.update(status="failed" if prepare_code is not None else "unavailable",
                          reason="Offline npm preparation did not pass", source_after=observe(repo, binding["candidate"]))
            record["record_sha256"] = digest(record)
            return record
    if tested_source(clone) != record["tested_source_before"]:
        raise EvidenceError("EVIDENCE_TESTED_SOURCE_CHANGED_DURING_PREPARATION")
    started = time.monotonic()
    with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(["/usr/bin/sandbox-exec", "-p", profile, *argv], cwd=clone,
                                   env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
            record.update(exit_code=code, status="passed" if code == 0 else "failed")
        except subprocess.TimeoutExpired:
            record.update(status="unavailable", reason="Required command timed out")
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    record["source_after"] = observe(repo, binding["candidate"])
    if record["source_after"] != before:
        raise EvidenceError("EVIDENCE_AUTHORITY_MUTATED")
    record["tested_source_after"] = tested_source(clone)
    if record["tested_source_after"] != record["tested_source_before"]:
        raise EvidenceError("EVIDENCE_TESTED_SOURCE_CHANGED")
    record["artifacts"].update({name: artifact(directory / name) for name in ("stdout.log", "stderr.log", "sandbox.sb")})
    # Preserve the canonical runner's actual output files, including fingerprints.
    output = scratch / "output"
    if output.exists():
        for path in sorted(output.rglob("*")):
            if path.is_file():
                record["artifacts"]["bundle/" + str(path.relative_to(output))] = artifact(path)
    record["record_sha256"] = digest(record)
    return record


def evidence_packet(attached: dict) -> dict:
    binding = attached["binding"]
    commands = attached.get("commands", {})
    validate_commands(binding, commands)
    for item in commands.values():
        validate_artifacts(item)
    for outcome in binding["review_obligations"]["outcomes"]:
        mapping = outcome["mapping"]
        if mapping["type"] == "deferred":
            manual = commands.get(mapping["manual_check"], {})
            comment = manual.get("comment", {})
            if (manual.get("status") != "passed" or comment.get("id") != mapping["comment_id"]
                    or outcome["id"] not in manual.get("evidence", "")
                    or mapping["reason"] not in manual.get("evidence", "")):
                raise EvidenceError("REVIEW_DEFERRAL_AUTHORITY_MISSING")
    qualified = attached.get("qualified")
    if not qualified or qualified.get("binding_sha256") != binding["binding_sha256"]:
        raise EvidenceError("BOUND_QUALIFICATION_MISSING")
    packet = {"qualification": qualified, "commands": commands}
    if binding.get("structural"):
        record = attached.get("structural")
        if not record:
            raise EvidenceError("REQUIRED_STRUCTURAL_EVIDENCE_MISSING")
        ri_delta.validate_record(binding, record)
        decision = ri_delta.disposition(binding, record, attached.get("structural_disposition", {}))
        packet["structural"] = {"record": record, "controller_disposition": decision}
    return packet


def _workflow_mode(state: dict) -> str:
    workflow = state.get("workflow")
    authorization = state.get("authorization")
    authorization = authorization if isinstance(authorization, dict) else {}
    if workflow is None:
        if "workflow_selection_sha256" in authorization:
            raise EvidenceError("WORKFLOW_MODE_STATE_INCOMPLETE")
        return "attached" if "capsule_evidence" in state else "compatibility"

    if not isinstance(workflow, dict) or set(workflow) != {
        "mode", "reason", "selection_sha256", "authority"
    }:
        raise EvidenceError("WORKFLOW_MODE_STATE_INVALID")
    mode = workflow["mode"]
    reason = workflow["reason"]
    if mode == "attached":
        if reason is not None:
            raise EvidenceError("WORKFLOW_MODE_STATE_INVALID")
    elif mode == "compatibility":
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500 or reason != reason.strip():
            raise EvidenceError("WORKFLOW_MODE_STATE_INVALID")
    else:
        raise EvidenceError("WORKFLOW_MODE_STATE_INVALID")

    selection = {"schema_version": 1, "mode": mode, "reason": reason}
    selection_sha256 = hashlib.sha256(canonical_json(selection).encode()).hexdigest()
    authority = workflow["authority"]
    if (
        workflow["selection_sha256"] != selection_sha256
        or authorization.get("workflow_selection_sha256") != selection_sha256
        or not isinstance(authority, dict)
        or set(authority) != {
            "comment_id", "author_login", "authorization_identity_sha256", "selection_sha256"
        }
        or type(authority["comment_id"]) is not int
        or authority["comment_id"] < 1
        or not isinstance(authority["author_login"], str)
        or not authority["author_login"]
        or not isinstance(authority["authorization_identity_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", authority["authorization_identity_sha256"])
        or authority["selection_sha256"] != selection_sha256
        or authority["comment_id"] != authorization.get("comment_id")
        or authority["author_login"] != authorization.get("author_login")
        or authority["authorization_identity_sha256"] != authorization.get("identity_sha256")
    ):
        raise EvidenceError("WORKFLOW_AUTHORITY_INVALID")
    return mode


def gate(state: dict, candidate: str, *, review_required: bool = False) -> None:
    """Enforce attached evidence while preserving authorized legacy compatibility."""
    mode = _workflow_mode(state)
    if mode == "compatibility" and "capsule_evidence" not in state:
        return
    if mode == "attached" and "capsule_evidence" not in state:
        raise EvidenceError("CANDIDATE_ATTACHMENT_REQUIRED")
    attached = state["capsule_evidence"]
    binding = attached.get("binding")
    if not binding or binding["candidate"] != candidate or attached.get("requires_fresh_candidate"):
        raise EvidenceError("FRESH_CANDIDATE_ATTACHMENT_REQUIRED")
    packet = evidence_packet(attached)
    if review_required:
        receipt = attached.get("review", {})
        authenticate_receipt(receipt, create_key(Path(attached["key_path"])), binding)
        if receipt.get("evidence_sha256") != digest(packet):
            raise EvidenceError("REVIEW_EVIDENCE_CHANGED")
        if receipt["verdict"]["disposition"] != "approved":
            raise EvidenceError("INDEPENDENT_APPROVAL_REQUIRED")


def public_handoff(attached: dict) -> str:
    binding = attached["binding"]
    receipt = attached.get("review", {})
    commands = attached.get("commands", {})
    public = {"candidate": binding["candidate"], "planning": binding["planning"],
              "binding_sha256": binding["binding_sha256"], "capsule_sha256": binding["capsule_sha256"],
              "authorization": binding["authorization"], "issue_sha256": binding["issue_sha256"],
              "qualification": attached.get("qualified"), "review": receipt.get("verdict"),
              "session": receipt.get("session"), "runtime": {k: v for k, v in receipt.get("runtime", {}).items() if k != "executable"},
              "trace_sha256": receipt.get("trace_sha256"),
              "commands": {name: {"kind": item["kind"], "status": item["status"], "exit_code": item.get("exit_code"),
                            "record_sha256": item.get("record_sha256"),
                            "manual_locator": item.get("comment", {}).get("html_url"), "artifacts": {
                                label: {"sha256": entry["sha256"], "bytes": entry["bytes"],
                                        "locator": "controller-local:" + entry["sha256"]}
                                for label, entry in item.get("artifacts", {}).items()}}
                           for name, item in commands.items()}}
    if binding.get("structural"):
        record = attached["structural"]
        public["structural"] = {"record_sha256": record["record_sha256"], "status": record["status"],
                                "planning": record["planning"], "candidate": record["candidate"],
                                "controller_disposition": attached["structural_disposition"],
                                "artifacts": {name: {"sha256": entry["sha256"], "bytes": entry["bytes"],
                                              "locator": "controller-local:" + entry["sha256"]}
                                              for name, entry in record["artifacts"].items()}}
    body = "## Capsule candidate evidence\n\nRaw local logs remain controller-owned; digests are locators, not remote availability claims. "
    body += "The exact qualification is retrievable from GitHub; the observed review decision and matrix are recorded below.\n\n```json\n"
    body += json.dumps(public, indent=2) + "\n```\n"
    if len(body.encode()) > 60_000:
        raise EvidenceError("PUBLIC_HANDOFF_TOO_LARGE")
    return body


def manual_observation(binding: dict, identifier: str, comment: dict) -> dict:
    requirement = next((x for x in binding["requirements"] if x["id"] == identifier), None)
    if requirement is None or requirement["kind"] != "manual":
        raise EvidenceError("MANUAL_REQUIREMENT_REQUIRED")
    auth = binding["authorization"]
    if (comment.get("user", {}).get("login") != auth["author_login"]
            or comment.get("user", {}).get("type") != "User"
            or comment.get("performed_via_github_app") is not None):
        raise EvidenceError("MANUAL_TRUSTED_OWNER_REQUIRED")
    blocks = re.findall(r"```nutrition-manual-v1\s*\n(.*?)\n```", comment.get("body", ""), re.S)
    if len(blocks) != 1:
        raise EvidenceError("MANUAL_ATTESTATION_MISSING")
    try:
        value = json.loads(blocks[0])
    except ValueError as exc:
        raise EvidenceError("MANUAL_ATTESTATION_INVALID") from exc
    if (not isinstance(value, dict) or set(value) != {"candidate", "binding_sha256", "check", "status", "evidence"}
            or value["candidate"] != binding["candidate"] or value["binding_sha256"] != binding["binding_sha256"]
            or value["check"] != identifier or value["status"] not in {"passed", "failed", "skipped", "unavailable"}
            or not isinstance(value["evidence"], str) or not value["evidence"].strip()
            or not comment.get("html_url", "").startswith(f"https://github.com/{auth['repository']}/issues/{auth['issue_number']}#issuecomment-")):
        raise EvidenceError("MANUAL_ATTESTATION_IDENTITY_INVALID")
    record = {"binding_sha256": binding["binding_sha256"], "id": identifier, "kind": "manual",
              "status": value["status"], "artifacts": {}, "comment": comment,
              "comment_sha256": digest(comment), "evidence": value["evidence"]}
    return {**record, "record_sha256": digest(record)}


def revalidate_manual(attached: dict, transport) -> None:
    for identifier, item in attached.get("commands", {}).items():
        if item["kind"] == "manual":
            comment = transport.get_issue_comment(attached["binding"]["authorization"]["repository"], item["comment"]["id"])
            if manual_observation(attached["binding"], identifier, comment) != item:
                raise EvidenceError("MANUAL_ATTESTATION_CHANGED")
