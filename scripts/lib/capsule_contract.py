"""Small shared capsule contract primitives; no transport or receipt machinery."""
from __future__ import annotations
import hashlib
import re
import tomllib

from lib.task_authorization import canonical_json


class EvidenceError(RuntimeError):
    pass


class ExecutionError(RuntimeError):
    pass


GOVERNING_ISSUE_REPLAN_REQUIRED = "GOVERNING_ISSUE_REPLAN_REQUIRED"
GOVERNING_ISSUE_REVALIDATION_UNAVAILABLE = "GOVERNING_ISSUE_REVALIDATION_UNAVAILABLE"
GOVERNING_ISSUE_REVALIDATION_INVALID = "GOVERNING_ISSUE_REVALIDATION_INVALID"


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def capsule_metadata(data: bytes) -> dict:
    try:
        parts = data.decode().split("+++", 2)
        if parts[0].strip() or len(parts) != 3:
            raise ValueError("missing front matter")
        return tomllib.loads(parts[1])
    except (ValueError, UnicodeError) as exc:
        raise ExecutionError("CAPSULE_PARSE_INVALID") from exc


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
