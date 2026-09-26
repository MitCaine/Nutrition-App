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

from lib.capsule_execution import capsule_metadata, source_snapshot, verify_planning_bytes
from lib.task_authorization import ResolvedAuthorization, canonical_json, validate_candidate_scope


class EvidenceError(RuntimeError):
    pass


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode:
        raise EvidenceError("EVIDENCE_GIT_ERROR: " + result.stderr.decode(errors="replace"))
    return result.stdout


def git_text(repo: Path, *args: str) -> str:
    return git(repo, *args).decode().strip()


def read_blob(repo: Path, commit: str, path: str) -> bytes:
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
    if size > 2_000_000:
        raise EvidenceError("SOURCE_READ_LIMIT")
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
    blocks = re.findall(r"```nutrition-evidence-v1\s*\n(.*?)\n```", raw.decode(), re.S)
    if len(blocks) != 1:
        raise EvidenceError("CAPSULE_EVIDENCE_REQUIREMENTS_MISSING")
    try:
        values = json.loads(blocks[0])
    except ValueError as exc:
        raise EvidenceError("CAPSULE_EVIDENCE_REQUIREMENTS_INVALID") from exc
    if not isinstance(values, list) or not values:
        raise EvidenceError("CAPSULE_EVIDENCE_REQUIREMENTS_INVALID")
    kinds = {"focused", "baseline", "sqlite", "postgresql", "infrastructure", "native", "manual"}
    seen = set()
    for item in values:
        if (not isinstance(item, dict) or set(item) != {"id", "kind", "required", "argv"}
                or not isinstance(item["id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]*", item["id"])
                or item["id"] in seen or item["kind"] not in kinds or type(item["required"]) is not bool):
            raise EvidenceError("CAPSULE_EVIDENCE_REQUIREMENT_INVALID")
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
    return {"candidate": candidate, "branch": git_text(repo, "branch", "--show-current"),
            "source_sha256": digest(snapshot),
            "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            "refs_sha256": hashlib.sha256(git(repo, "show-ref")).hexdigest()}


def attach(repo: Path, authorization: ResolvedAuthorization, *, planning: str,
           candidate: str, issue: dict, correction_limit: int = 1) -> dict:
    if type(correction_limit) is not int or correction_limit not in (0, 1):
        raise EvidenceError("CORRECTION_LIMIT_INVALID")
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
    result = {"schema_version": 1, "authorization": authorization.to_dict(),
              "planning": planning, "candidate": candidate, "capsule_path": capsule_path,
              "capsule_sha256": hashlib.sha256(original).hexdigest(),
              "candidate_capsule_sha256": hashlib.sha256(current).hexdigest(),
              "capsule_text": original.decode(), "contract_sha256": digest(frozen_contract(original)),
              "branch": metadata["branch"], "criteria": dict(criteria), "requirements": planned,
              "issue": issue, "issue_sha256": digest(issue), "source": observed,
              "changed_paths": changed, "correction_limit": correction_limit}
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
    if (not isinstance(value, dict) or set(value) != {"candidate", "binding_sha256", "disposition", "matrix", "findings", "summary"}
            or value["candidate"] != binding["candidate"]
            or value["binding_sha256"] != binding["binding_sha256"]
            or value["disposition"] not in {"approved", "bounded-correction", "stop-replan"}
            or not isinstance(value["summary"], str) or not value["summary"].strip()
            or not isinstance(value["findings"], list) or not isinstance(value["matrix"], list)):
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
    if value["disposition"] == "approved" and (value["findings"] or any(x["result"] != "PASS" for x in rows)):
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
              "source_before": before, "source_after": None, "argv": None, "exit_code": None}
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
                  "python_prefix": sys.prefix, "python_base_prefix": sys.base_prefix})
    reads = ["/System", "/usr", "/bin", "/sbin", "/Library", "/opt/homebrew",
             "/private/var/select", "/var/select", "/Applications/Xcode.app", str(scratch), str(python.parent.parent),
             str(python.resolve().parent.parent)]
    profile = "\n".join([
        "(version 1)", "(deny default)", "(allow process*)", "(allow sysctl-read)", "(allow mach-lookup)",
        '(allow file-read* (literal "/") (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))',
        "(allow file-read* " + " ".join("(subpath " + json.dumps(x) + ")" for x in reads) + ")",
        '(allow file-write* (literal "/dev/null") (subpath ' + json.dumps(str(scratch)) + '))',
        "(deny network*)",
    ])
    (directory / "sandbox.sb").write_text(profile)
    (scratch / "home").mkdir()
    (scratch / "tmp").mkdir()
    developer = next((p for p in (Path("/Applications/Xcode.app/Contents/Developer"),
                                  Path("/Library/Developer/CommandLineTools")) if (p / "usr/bin/git").is_file()), None)
    tool_path = str(developer / "usr/bin") + ":" if developer else ""
    env = {"HOME": str(scratch / "home"), "TMPDIR": str(scratch / "tmp"),
           "PATH": str(python.parent) + ":" + tool_path + "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "NUTRITION_REVIEW_OUTPUT_DIR": str(scratch / "output")}
    if developer:
        env["DEVELOPER_DIR"] = str(developer)
    record["environment"] = env
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
    record["artifacts"] = {name: artifact(directory / name) for name in ("stdout.log", "stderr.log", "sandbox.sb")}
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
    qualified = attached.get("qualified")
    if not qualified or qualified.get("binding_sha256") != binding["binding_sha256"]:
        raise EvidenceError("BOUND_QUALIFICATION_MISSING")
    return {"qualification": qualified, "commands": commands}


def gate(state: dict, candidate: str, *, review_required: bool = False) -> None:
    """Compatibility tasks are unchanged; attached tasks cannot use assertion-only gates."""
    if "capsule_evidence" not in state:
        return
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
