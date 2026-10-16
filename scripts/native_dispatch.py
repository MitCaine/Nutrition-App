"""Read-only bridge from retained native collaboration records to RI decisions.

The controller owns record authenticity, freshness, checkpoint writes and tool
calls. This bridge never launches, resumes, waits, authenticates a host or grants
retry authority. Original native replies remain evidence, not invented flags.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

from lib import review_commands as native

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    path = Path(path)
    native._no_symlink_components(path)
    require(path.is_file() and path.stat().st_size <= 1_000_000, "Expected bounded regular JSON evidence")
    value = native._parse_json(path.read_bytes())
    require(isinstance(value, dict), "Expected JSON object")
    return value


def message_prefix(selection):
    return "".join(f"{label}: {selection[key]}\n" for label, key in
                   (("Assignment", "assignment"), ("Attempt", "attempt"), ("Operation", "operation")))


def selected_guard():
    text = (ROOT / "docs/local_project_map.md").read_text()
    revision = re.search(r"Native dispatch guard source revision: `([0-9a-f]{40})`", text)
    location = re.search(r"Native dispatch guard source checkout: `([^`]+)`", text)
    require(revision is not None and location is not None, "Native dispatch guard is not selected")
    source = native._canonical_root(location.group(1))
    require(native._git(source, "rev-parse", "HEAD").decode().strip() == revision.group(1), "Guard source HEAD differs")
    require(not native._git(source, "status", "--porcelain").strip(), "Guard source is dirty")
    path = source / "src/repository_intelligence/dispatch_guard.py"
    native._no_symlink_components(path)
    require(path.read_bytes() == native._git(source, "show", revision.group(1) + ":src/repository_intelligence/dispatch_guard.py"),
            "Guard module differs from selected Git object")
    spec = importlib.util.spec_from_file_location("nutrition_selected_dispatch_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worker_row(snapshot, worker=None, attempt=None):
    if snapshot is None:
        return None
    require(isinstance(snapshot, dict) and set(snapshot) == {"agents"} and isinstance(snapshot["agents"], list),
            "Expected original collaboration.list_agents result")
    rows = snapshot["agents"]
    require(all(isinstance(row, dict) and isinstance(row.get("agent_name"), str) for row in rows), "Incomplete native inventory")
    matches = [row for row in rows if row["agent_name"] == worker] if worker else [
        row for row in rows if row["agent_name"].rsplit("/", 1)[-1] == attempt]
    require(len(matches) <= 1, "Ambiguous native worker inventory")
    return matches[0] if matches else None


def completed(row):
    status = row.get("agent_status") if row else None
    return status.get("completed") if isinstance(status, dict) and isinstance(status.get("completed"), str) else None


def project(checkpoint, record, evidence):
    """Map THIS selected action, never an arbitrary caller-provided accepted flag."""
    selection = checkpoint.get("execution", {}).get("native_dispatch")
    require(isinstance(selection, dict) and set(selection) <= {"assignment", "attempt", "operation", "worker"}, "No selected native assignment")
    require(all(isinstance(selection.get(key), str) and selection[key].strip() for key in ("assignment", "attempt", "operation")),
            "Incomplete native assignment")
    require(isinstance(checkpoint.get("task_id"), str) and selection["assignment"].startswith(checkpoint["task_id"] + "/"),
            "Assignment differs from checkpoint task")
    require(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", selection["attempt"]) is not None, "Attempt must be the unique native task/action name")
    require(selection["operation"] in ("launch", "resume"), "Unsupported native operation")
    require(set(record) == {"selection", "action", "before", "snapshot"} and record["selection"] == selection,
            "Stale or mismatched native assignment/attempt/operation/worker")
    observation = dict(selection, state="planned", evidence=evidence)
    action = record["action"]
    if action is None:
        return selection, observation
    require(isinstance(action, dict) and set(action) == {"tool", "arguments", "reply"}, "Expected retained native call and reply")
    args = action["arguments"]
    require(isinstance(args, dict) and isinstance(args.get("message"), str) and args["message"].startswith(message_prefix(selection)),
            "Native action message is not bound to current assignment/attempt/operation")
    operation = selection["operation"]
    if operation == "launch":
        require(action["tool"] == "collaboration.spawn_agent" and args.get("task_name") == selection["attempt"], "Launch action identity mismatch")
    else:
        require(isinstance(selection.get("worker"), str) and selection["worker"].strip(), "Resume requires existing worker identity")
        require(action["tool"] == "collaboration.followup_task" and args.get("target") == selection["worker"], "Resume action identity mismatch")
        require(completed(worker_row(record["before"], worker=selection["worker"])) is not None,
                "Resumption requires the existing terminal/idle worker record; queued followup is not a new active attempt")
    reply = action["reply"]
    require(reply is None or isinstance(reply, dict), "Incomplete native reply")
    if reply and isinstance(reply.get("error"), str) and reply["error"].strip():
        return selection, dict(observation, state="rejected")
    worker = reply.get("task_name") if reply else None
    accepted = isinstance(worker, str) and bool(worker.strip())
    if accepted:
        require(worker.rsplit("/", 1)[-1] == selection["attempt"] if operation == "launch" else worker == selection["worker"],
                "Native reply worker differs from selected action")
    row = worker_row(record["snapshot"], worker=worker if accepted else selection.get("worker"),
                     attempt=selection["attempt"] if operation == "launch" else None)
    # A fresh launch's globally unique task name permits bounded lost-reply
    # reconciliation. A resumed actor alone cannot identify a new resume attempt.
    if not accepted and operation == "launch" and row:
        worker, accepted = row["agent_name"], True
    if not accepted:
        return selection, dict(observation, state="unknown")
    result = dict(observation, worker=worker, accepted=True, state="accepted")
    if row:
        terminal = completed(row)
        if terminal is not None:
            # Native inventories retain prior completed actors. Do not consume
            # an old terminal result as the completion of a new followup action.
            if f"Attempt: {selection['attempt']}" not in terminal.splitlines():
                return selection, dict(observation, state="unknown")
            result["state"] = "terminal"
        elif row.get("agent_status") == "running":
            result["state"] = "active"
        else:
            return selection, dict(observation, state="unknown")
    return selection, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        selection, observation = project(read(args.checkpoint), read(args.record), str(args.record))
        decision = selected_guard().decide(selection, observation)
        print(json.dumps(decision, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
        print(json.dumps(dict(action="refused", may_wait=False, may_mark_running=False, may_dispatch=False, reason=str(error))))
        return 1


if __name__ == "__main__":
    sys.exit(main())
