"""Nutrition's native-record mapping; fixture controls are not host proof."""
import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import native_dispatch as consumer  # noqa: E402


def case(operation="launch"):
    selection = dict(assignment="GH-412/reviewer", attempt="native_unique_412", operation=operation)
    worker = "/root/previous_worker" if operation == "resume" else "/root/" + selection["attempt"]
    if operation == "resume":
        selection["worker"] = worker
    args = dict(message=consumer.message_prefix(selection) + "Bounded original assignment")
    args.update(target=worker) if operation == "resume" else args.update(task_name=selection["attempt"])
    checkpoint = dict(task_id="GH-412", execution=dict(native_dispatch=selection))
    record = dict(selection=selection, action=dict(tool="collaboration.followup_task" if operation == "resume" else "collaboration.spawn_agent",
                  arguments=args, reply=dict(task_name=worker)), before=dict(agents=[dict(agent_name=worker, agent_status=dict(completed="Attempt: previous_attempt"))]) if operation == "resume" else None,
                  snapshot=None)
    return checkpoint, record, worker


def mapped(checkpoint, record):
    return consumer.project(checkpoint, record, "/retained/original-native-record.json")[1]


@pytest.mark.parametrize("operation", ["launch", "resume"])
def test_native_success_accepts_only_this_action_without_claiming_running(operation):
    checkpoint, record, worker = case(operation)
    before = copy.deepcopy((checkpoint, record))
    observed = mapped(checkpoint, record)
    assert observed["state"] == "accepted" and observed["accepted"] is True and observed["worker"] == worker
    assert (checkpoint, record) == before


@pytest.mark.parametrize("operation", ["launch", "resume"])
def test_planned_and_missing_reply_cannot_become_active(operation):
    checkpoint, record, _ = case(operation)
    record["action"] = None
    assert mapped(checkpoint, record)["state"] == "planned"
    _, record, _ = case(operation)
    record["action"]["reply"] = None
    assert mapped(checkpoint, record)["state"] == "unknown"


@pytest.mark.parametrize("key,value", [("assignment", "GH-412/other"), ("attempt", "previous_attempt"), ("operation", "resume"), ("worker", "/root/other")])
def test_stale_record_refuses(key, value):
    checkpoint, record, _ = case()
    record = copy.deepcopy(record)
    record["selection"][key] = value
    with pytest.raises(ValueError, match="Stale or mismatched"):
        mapped(checkpoint, record)


def test_wrong_native_message_or_task_or_worker_cannot_claim_acceptance():
    for change in ("message", "task_name", "reply"):
        checkpoint, record, _ = case()
        if change == "reply":
            record["action"]["reply"] = {"task_name": "/root/unrelated"}
        else:
            record["action"]["arguments"][change] = "old action"
        with pytest.raises(ValueError):
            mapped(checkpoint, record)


def test_running_and_terminal_are_derived_from_native_status():
    checkpoint, record, worker = case()
    record["snapshot"] = dict(agents=[dict(agent_name=worker, agent_status="running")])
    assert mapped(checkpoint, record)["state"] == "active"
    record["snapshot"]["agents"][0]["agent_status"] = dict(completed="Attempt: native_unique_412\nResult")
    assert mapped(checkpoint, record)["state"] == "terminal"
    record["snapshot"]["agents"][0]["agent_status"] = dict(completed="Attempt: native_unique_412_old\nOld result")
    assert mapped(checkpoint, record)["state"] == "unknown"


def test_lost_fresh_reply_reconciles_current_actor_without_retry():
    checkpoint, record, worker = case()
    record["action"]["reply"] = None
    record["snapshot"] = dict(agents=[dict(agent_name=worker, agent_status="running")])
    assert mapped(checkpoint, record)["state"] == "active"
    record["snapshot"] = {"agents": []}
    assert mapped(checkpoint, record)["state"] == "unknown"  # incomplete inventory is not absence


def test_resume_cannot_reuse_old_terminal_or_queued_activity():
    checkpoint, record, worker = case("resume")
    record["snapshot"] = record["before"]
    assert mapped(checkpoint, record)["state"] == "unknown"
    record["action"]["reply"] = None
    record["snapshot"] = dict(agents=[dict(agent_name=worker, agent_status="running")])
    assert mapped(checkpoint, record)["state"] == "unknown"
    record["before"]["agents"][0]["agent_status"] = "running"
    with pytest.raises(ValueError, match="terminal/idle"):
        mapped(checkpoint, record)


def test_rejection_and_ambiguous_inventory_do_not_become_wait():
    checkpoint, record, worker = case()
    record["action"]["reply"] = {"error": "native rejected launch"}
    assert mapped(checkpoint, record)["state"] == "rejected"
    record["action"]["reply"] = None
    row = dict(agent_name=worker, agent_status="running")
    record["snapshot"] = dict(agents=[row, row])
    with pytest.raises(ValueError, match="Ambiguous"):
        mapped(checkpoint, record)


def test_selected_guard_consumes_consumer_projection_when_private_source_available():
    import re
    selection = (ROOT / "docs/local_project_map.md").read_text()
    location = re.search(r"Native dispatch guard source checkout: `([^`]+)`", selection).group(1)
    if not Path(location).is_dir():
        pytest.skip("Selected private guard source is not provisioned on this host")
    guard = consumer.selected_guard()  # Present source drift is a failure, not a skip.
    checkpoint, record, worker = case()
    selection, observation = consumer.project(checkpoint, record, "/original/native.json")
    assert guard.decide(selection, observation)["may_wait"] is True
    assert guard.decide(selection, observation)["may_mark_running"] is False
    record["action"] = None
    decision = guard.decide(*consumer.project(checkpoint, record, "/original/native.json"))
    assert decision["action"] == "reconcile" and not decision["may_wait"] and not decision["may_dispatch"]
    checkpoint, record, worker = case("resume")
    record["snapshot"] = dict(agents=[dict(agent_name=worker, agent_status=dict(completed="Attempt: native_unique_412\nResult"))])
    decision = guard.decide(*consumer.project(checkpoint, record, "/original/native.json"))
    assert decision["action"] == "consume" and not decision["may_wait"] and not decision["may_dispatch"]


def test_actual_empty_followup_success_is_distinct_from_lost_reply():
    checkpoint, record, worker = case("resume")
    record["action"]["reply"] = ""
    assert mapped(checkpoint, record)["state"] == "accepted"
    record["snapshot"] = dict(agents=[dict(agent_name=worker, agent_status="running")])
    assert mapped(checkpoint, record)["state"] == "active"
    record["snapshot"] = record["before"]
    assert mapped(checkpoint, record)["state"] == "unknown"
    record["snapshot"] = dict(agents=[dict(agent_name=worker, agent_status=dict(completed="Attempt: native_unique_412\nNew result"))])
    assert mapped(checkpoint, record)["state"] == "terminal"
    record["action"]["reply"] = None
    assert mapped(checkpoint, record)["state"] == "unknown"


def test_empty_body_is_not_a_successful_spawn_reply():
    checkpoint, record, _ = case()
    record["action"]["reply"] = ""
    with pytest.raises(ValueError, match="Incomplete native reply"):
        mapped(checkpoint, record)
