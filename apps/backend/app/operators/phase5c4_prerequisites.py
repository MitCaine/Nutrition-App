"""Strict Stage 5C4.2b target-identity and local-fence admission.

The database emits typed observations; this module is the only Python verifier.
All digest preimages delegate to the existing Phase 5C canonical serializer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Literal, Mapping
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.operators import phase5c_contracts as canonical
from app.operators.phase5c4_contracts import (
    QUALIFIER_VERSION,
    TARGET_SCHEMA_REVISION,
)


# Compatibility seam for existing test callers without importing application
# settings into independent control-plane commands at module import time.
settings: Any | None = None


ADVISORY_LOCK_KEY = 5_542_018
TARGET_IDENTITY_VERSION = "phase5c_promotion_target_identity_v1"
FENCE_EVENT_VERSION = "phase5c_write_fence_event_v1"

FenceMode = Literal[
    "closed_prequalification",
    "closed_cutover",
    "open_production",
    "closed_incident",
    "retired",
]

FENCE_MODES = frozenset(
    {
        "closed_prequalification",
        "closed_cutover",
        "open_production",
        "closed_incident",
        "retired",
    }
)
CANARY_FENCE_MODES = frozenset({"closed_prequalification", "closed_cutover"})
_ALLOWED_EVENT_TRANSITIONS = frozenset(
    {
        ("closed_prequalification", "closed_cutover"),
        ("closed_prequalification", "closed_incident"),
        ("closed_prequalification", "retired"),
        ("closed_cutover", "open_production"),
        ("closed_cutover", "closed_incident"),
        ("closed_cutover", "retired"),
        ("open_production", "closed_incident"),
        ("open_production", "retired"),
        ("closed_incident", "retired"),
    }
)

READINESS_REASONS = frozenset(
    {
        "database_unavailable",
        "schema_revision_mismatch",
        "target_identity_missing",
        "target_identity_invalid",
        "fence_state_missing",
        "fence_state_invalid",
        "fence_event_chain_invalid",
        "write_fence_closed_prequalification",
        "write_fence_closed_cutover",
        "write_fence_closed_incident",
        "write_fence_retired",
        "runtime_role_mismatch",
        "role_topology_invalid",
    }
)

QUALIFICATION_FAILURE_CODES = frozenset(
    {
        "qualification_schema_revision_unsupported",
        "qualification_target_identity_missing",
        "qualification_target_identity_invalid",
        "qualification_fence_state_invalid",
        "qualification_fence_event_chain_invalid",
        "qualification_gate_trigger_coverage_invalid",
        "qualification_role_topology_invalid",
        "qualification_immutability_invalid",
        "qualification_concurrent_fence_change",
    }
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_IDENTITY_KEYS = frozenset(
    {
        "archive_identity",
        "clone_marker_digest",
        "conversion_clone_identity_digest",
        "conversion_run_id",
        "identity_digest",
        "identity_version",
        "initialized_at",
        "target_instance_id",
        "target_nonce",
    }
)
_IDENTITY_PREIMAGE_KEYS = _IDENTITY_KEYS - {"identity_digest"}
_EVENT_PREIMAGE_KEYS = frozenset(
    {
        "artifact_set_digest",
        "attempt_id",
        "authorization_digest",
        "command_id",
        "contract_version",
        "epoch",
        "event_id",
        "from_mode",
        "occurred_at",
        "previous_event_digest",
        "target_instance_id",
        "to_mode",
    }
)
_EVENT_KEYS = _EVENT_PREIMAGE_KEYS | {"event_digest"}
_STATE_KEYS = frozenset(
    {
        "artifact_set_digest",
        "attempt_id",
        "authorization_digest",
        "epoch",
        "last_event_digest",
        "mode",
        "target_instance_id",
        "updated_at",
    }
)
_OBSERVATION_KEYS = frozenset(
    {
        "bindings_valid",
        "events",
        "gate_trigger_coverage_valid",
        "identity",
        "immutability_valid",
        "role_topology_valid",
        "schema_revision",
        "session_role",
        "state",
    }
)
LOCAL_ADMISSION_KEYS = frozenset(
    {
        "composite_bindings_valid",
        "event_chain_valid",
        "fence_mode",
        "fence_state_present",
        "fence_state_valid",
        "gate_trigger_coverage_valid",
        "identity_present",
        "identity_valid",
        "immutability_valid",
        "role_topology_valid",
        "schema_revision",
        "session_role_valid",
    }
)
_PROJECTION_KEYS = frozenset(
    {
        "target_identity_digest",
        "fence_mode",
        "fence_epoch",
        "event_chain_digest",
        "schema_revision",
        "trigger_coverage_digest",
        "role_qualification_digest",
        "immutability_qualification_digest",
    }
)


class Phase5C4PrerequisiteError(RuntimeError):
    """A stable fail-closed prerequisite classification."""

    def __init__(self, reason_code: str):
        if reason_code not in READINESS_REASONS | QUALIFICATION_FAILURE_CODES:
            reason_code = "database_unavailable"
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class PromotionPrerequisiteState:
    identity: dict[str, Any]
    state: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    gate_trigger_coverage_valid: bool
    role_topology_valid: bool
    immutability_valid: bool
    session_role: str

    @property
    def event_chain_digest(self) -> str:
        return str(self.state["last_event_digest"])

    def qualifier_projection(self) -> dict[str, Any]:
        projection = {
            "target_identity_digest": self.identity["identity_digest"],
            "fence_mode": self.state["mode"],
            "fence_epoch": self.state["epoch"],
            "event_chain_digest": self.event_chain_digest,
            "schema_revision": TARGET_SCHEMA_REVISION,
            "trigger_coverage_digest": canonical.canonical_digest(
                {"gate_trigger_coverage_valid": self.gate_trigger_coverage_valid}
            ),
            "role_qualification_digest": canonical.canonical_digest(
                {
                    "qualifier_version": QUALIFIER_VERSION,
                    "role_topology_valid": self.role_topology_valid,
                    "session_role": self.session_role,
                }
            ),
            "immutability_qualification_digest": canonical.canonical_digest(
                {"immutability_valid": self.immutability_valid}
            ),
        }
        assert set(projection) == _PROJECTION_KEYS
        return projection


def admit_qualification_prerequisites(
    prerequisites: PromotionPrerequisiteState,
) -> None:
    """Apply the single qualifier-v2 prerequisite admission policy.

    Both independent qualification and Stage 5C4.4 evidence collection call this function so a
    false topology/trigger/immutability observation or a non-initial fence can never be accepted by
    one path and rejected by the other.
    """

    if prerequisites.session_role != "nutrition_qualifier":
        raise Phase5C4PrerequisiteError("qualification_role_topology_invalid")
    if not prerequisites.role_topology_valid:
        raise Phase5C4PrerequisiteError("qualification_role_topology_invalid")
    if not prerequisites.gate_trigger_coverage_valid:
        raise Phase5C4PrerequisiteError("qualification_gate_trigger_coverage_invalid")
    if not prerequisites.immutability_valid:
        raise Phase5C4PrerequisiteError("qualification_immutability_invalid")
    if (
        prerequisites.state["mode"] != "closed_prequalification"
        or prerequisites.state["epoch"] != 1
    ):
        raise Phase5C4PrerequisiteError("qualification_fence_state_invalid")


@dataclass(frozen=True)
class LocalReadiness:
    ready: bool
    reason_code: str | None = None


@dataclass(frozen=True)
class LocalAdmission:
    schema_revision: str | None
    identity_present: bool
    identity_valid: bool
    composite_bindings_valid: bool
    fence_state_present: bool
    fence_state_valid: bool
    event_chain_valid: bool
    fence_mode: str | None
    session_role_valid: bool
    role_topology_valid: bool
    gate_trigger_coverage_valid: bool
    immutability_valid: bool


def validate_local_admission(payload: Any) -> LocalAdmission:
    admission = _require_mapping(payload, LOCAL_ADMISSION_KEYS, "database_unavailable")
    schema_revision = admission["schema_revision"]
    if schema_revision is not None and not isinstance(schema_revision, str):
        raise Phase5C4PrerequisiteError("database_unavailable")
    fence_mode = admission["fence_mode"]
    if fence_mode is not None and not isinstance(fence_mode, str):
        raise Phase5C4PrerequisiteError("database_unavailable")
    boolean_fields = LOCAL_ADMISSION_KEYS - {"fence_mode", "schema_revision"}
    if any(not isinstance(admission[field], bool) for field in boolean_fields):
        raise Phase5C4PrerequisiteError("database_unavailable")
    return LocalAdmission(**admission)


def classify_local_admission(admission: LocalAdmission) -> LocalReadiness:
    if admission.schema_revision != TARGET_SCHEMA_REVISION:
        return LocalReadiness(False, "schema_revision_mismatch")
    if not admission.identity_present:
        return LocalReadiness(False, "target_identity_missing")
    if not admission.identity_valid or not admission.composite_bindings_valid:
        return LocalReadiness(False, "target_identity_invalid")
    if not admission.fence_state_present:
        return LocalReadiness(False, "fence_state_missing")
    if not admission.fence_state_valid:
        return LocalReadiness(False, "fence_state_invalid")
    if not admission.event_chain_valid:
        return LocalReadiness(False, "fence_event_chain_invalid")
    if not admission.session_role_valid:
        return LocalReadiness(False, "runtime_role_mismatch")
    if not admission.role_topology_valid:
        return LocalReadiness(False, "role_topology_invalid")
    if not admission.gate_trigger_coverage_valid:
        return LocalReadiness(False, "role_topology_invalid")
    if not admission.immutability_valid:
        return LocalReadiness(False, "role_topology_invalid")
    if admission.fence_mode == "open_production":
        return LocalReadiness(True)
    reason = {
        "closed_prequalification": "write_fence_closed_prequalification",
        "closed_cutover": "write_fence_closed_cutover",
        "closed_incident": "write_fence_closed_incident",
        "retired": "write_fence_retired",
    }.get(admission.fence_mode, "fence_state_invalid")
    return LocalReadiness(False, reason)


def format_contract_timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise Phase5C4PrerequisiteError("target_identity_invalid")
        rendered = value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    elif isinstance(value, str):
        rendered = value
    else:
        raise Phase5C4PrerequisiteError("target_identity_invalid")
    if not _TIMESTAMP.fullmatch(rendered):
        raise Phase5C4PrerequisiteError("target_identity_invalid")
    try:
        parsed = datetime.strptime(rendered, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise Phase5C4PrerequisiteError("target_identity_invalid") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != rendered:
        raise Phase5C4PrerequisiteError("target_identity_invalid")
    return rendered


def target_identity_preimage(payload: Mapping[str, Any]) -> dict[str, Any]:
    identity = _require_mapping(payload, _IDENTITY_KEYS, "target_identity_invalid")
    for field in (
        "archive_identity",
        "clone_marker_digest",
        "conversion_clone_identity_digest",
        "identity_digest",
    ):
        _require_digest(identity.get(field), "target_identity_invalid")
    if identity.get("identity_version") != TARGET_IDENTITY_VERSION:
        raise Phase5C4PrerequisiteError("target_identity_invalid")
    for field in ("conversion_run_id", "target_instance_id", "target_nonce"):
        identity[field] = _canonical_uuid(identity.get(field), "target_identity_invalid")
    identity["initialized_at"] = format_contract_timestamp(identity.get("initialized_at"))
    preimage = {key: identity[key] for key in _IDENTITY_PREIMAGE_KEYS}
    if canonical.canonical_digest(preimage) != identity["identity_digest"]:
        raise Phase5C4PrerequisiteError("target_identity_invalid")
    return preimage


def fence_event_preimage(payload: Mapping[str, Any]) -> dict[str, Any]:
    event = _require_mapping(payload, _EVENT_KEYS, "fence_event_chain_invalid")
    if event.get("contract_version") != FENCE_EVENT_VERSION:
        raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
    if isinstance(event.get("epoch"), bool) or not isinstance(event.get("epoch"), int):
        raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
    if event["epoch"] < 1:
        raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
    for field in ("command_id", "event_id", "target_instance_id"):
        event[field] = _canonical_uuid(event.get(field), "fence_event_chain_invalid")
    event["attempt_id"] = _optional_uuid(event.get("attempt_id"), "fence_event_chain_invalid")
    event["occurred_at"] = _event_timestamp(event.get("occurred_at"))
    for field in (
        "artifact_set_digest",
        "authorization_digest",
        "previous_event_digest",
    ):
        _optional_digest(event.get(field), "fence_event_chain_invalid")
    _require_digest(event.get("event_digest"), "fence_event_chain_invalid")
    from_mode = event.get("from_mode")
    if from_mode is not None and from_mode not in FENCE_MODES:
        raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
    if event.get("to_mode") not in FENCE_MODES:
        raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
    preimage = {key: event[key] for key in _EVENT_PREIMAGE_KEYS}
    if canonical.canonical_digest(preimage) != event["event_digest"]:
        raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
    return preimage


def validate_prerequisite_observation(payload: Any) -> PromotionPrerequisiteState:
    observation = _require_mapping(payload, _OBSERVATION_KEYS, "target_identity_invalid")
    if observation.get("schema_revision") != TARGET_SCHEMA_REVISION:
        raise Phase5C4PrerequisiteError("schema_revision_mismatch")
    if observation["identity"] is None:
        raise Phase5C4PrerequisiteError("target_identity_missing")
    identity = dict(observation["identity"])
    target_identity_preimage(identity)
    if observation.get("bindings_valid") is not True:
        raise Phase5C4PrerequisiteError("target_identity_invalid")
    if observation["state"] is None:
        raise Phase5C4PrerequisiteError("fence_state_missing")
    state = _require_mapping(observation["state"], _STATE_KEYS, "fence_state_invalid")
    _validate_state_shape(state, identity)
    events_payload = observation.get("events")
    if not isinstance(events_payload, list) or not events_payload:
        raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
    events = tuple(dict(event) for event in events_payload)
    _validate_event_chain(events, identity, state)
    for field in (
        "gate_trigger_coverage_valid",
        "immutability_valid",
        "role_topology_valid",
    ):
        if not isinstance(observation.get(field), bool):
            raise Phase5C4PrerequisiteError("role_topology_invalid")
    if not isinstance(observation.get("session_role"), str):
        raise Phase5C4PrerequisiteError("runtime_role_mismatch")
    return PromotionPrerequisiteState(
        identity=identity,
        state=state,
        events=events,
        gate_trigger_coverage_valid=observation["gate_trigger_coverage_valid"],
        role_topology_valid=observation["role_topology_valid"],
        immutability_valid=observation["immutability_valid"],
        session_role=observation["session_role"],
    )


def evaluate_local_readiness(
    db: Session | Connection,
    *,
    expected_role: str = "nutrition_runtime",
) -> LocalReadiness:
    bind = db.get_bind() if isinstance(db, Session) else db
    dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect_name != "postgresql":
        from app.core.config import DeploymentMode, settings as application_settings

        configured_settings = settings or application_settings
        if configured_settings.deployment_mode is not DeploymentMode.TEST:
            return LocalReadiness(False, "schema_revision_mismatch")
        try:
            db.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return LocalReadiness(False, "database_unavailable")
        return LocalReadiness(True)
    try:
        reader_available = db.execute(
            text("SELECT pg_catalog.to_regprocedure('public.phase5c_local_admission_v1()')")
        ).scalar_one()
        if reader_available is None:
            return LocalReadiness(False, "schema_revision_mismatch")
        session_role, current_role = db.execute(text("SELECT session_user, current_user")).one()
        if (str(session_role), str(current_role)) != (expected_role, expected_role):
            return LocalReadiness(False, "runtime_role_mismatch")
        raw = db.execute(text("SELECT * FROM public.phase5c_local_admission_v1()")).mappings().one()
        return classify_local_admission(validate_local_admission(dict(raw)))
    except Phase5C4PrerequisiteError as exc:
        reason = exc.reason_code
        if reason in READINESS_REASONS:
            return LocalReadiness(False, reason)
        return LocalReadiness(False, "database_unavailable")
    except SQLAlchemyError:
        return LocalReadiness(False, "database_unavailable")
    except (KeyError, TypeError, ValueError):
        return LocalReadiness(False, "database_unavailable")


def qualification_reason(reason_code: str) -> str:
    mapping = {
        "schema_revision_mismatch": "qualification_schema_revision_unsupported",
        "target_identity_missing": "qualification_target_identity_missing",
        "target_identity_invalid": "qualification_target_identity_invalid",
        "fence_state_missing": "qualification_fence_state_invalid",
        "fence_state_invalid": "qualification_fence_state_invalid",
        "fence_event_chain_invalid": "qualification_fence_event_chain_invalid",
        "runtime_role_mismatch": "qualification_role_topology_invalid",
        "role_topology_invalid": "qualification_role_topology_invalid",
    }
    return mapping.get(reason_code, "qualification_concurrent_fence_change")


def _validate_state_shape(state: dict[str, Any], identity: Mapping[str, Any]) -> None:
    state["target_instance_id"] = _canonical_uuid(
        state.get("target_instance_id"), "fence_state_invalid"
    )
    if state["target_instance_id"] != identity["target_instance_id"]:
        raise Phase5C4PrerequisiteError("fence_state_invalid")
    epoch = state.get("epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
        raise Phase5C4PrerequisiteError("fence_state_invalid")
    if state.get("mode") not in FENCE_MODES:
        raise Phase5C4PrerequisiteError("fence_state_invalid")
    state["attempt_id"] = _optional_uuid(state.get("attempt_id"), "fence_state_invalid")
    for field in ("authorization_digest", "artifact_set_digest"):
        _optional_digest(state.get(field), "fence_state_invalid")
    _require_digest(state.get("last_event_digest"), "fence_state_invalid")
    state["updated_at"] = _state_timestamp(state.get("updated_at"))
    if state["mode"] == "open_production" and any(
        state[field] is None
        for field in ("attempt_id", "authorization_digest", "artifact_set_digest")
    ):
        raise Phase5C4PrerequisiteError("fence_state_invalid")
    if state["epoch"] == 1 and (
        state["mode"] != "closed_prequalification"
        or any(
            state[field] is not None
            for field in ("attempt_id", "authorization_digest", "artifact_set_digest")
        )
    ):
        raise Phase5C4PrerequisiteError("fence_state_invalid")


def _validate_event_chain(
    events: tuple[dict[str, Any], ...],
    identity: Mapping[str, Any],
    state: Mapping[str, Any],
) -> None:
    previous: dict[str, Any] | None = None
    for expected_epoch, event in enumerate(events, start=1):
        fence_event_preimage(event)
        if event["epoch"] != expected_epoch:
            raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
        if event["target_instance_id"] != identity["target_instance_id"]:
            raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
        if previous is None:
            if (
                event["from_mode"] is not None
                or event["to_mode"] != "closed_prequalification"
                or event["previous_event_digest"] is not None
                or any(
                    event[field] is not None
                    for field in (
                        "attempt_id",
                        "authorization_digest",
                        "artifact_set_digest",
                    )
                )
            ):
                raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
        elif (
            event["from_mode"] != previous["to_mode"]
            or event["previous_event_digest"] != previous["event_digest"]
            or (event["from_mode"], event["to_mode"]) not in _ALLOWED_EVENT_TRANSITIONS
        ):
            raise Phase5C4PrerequisiteError("fence_event_chain_invalid")
        previous = event
    assert previous is not None
    if len(events) != state["epoch"] or any(
        state[state_field] != previous[event_field]
        for state_field, event_field in (
            ("mode", "to_mode"),
            ("attempt_id", "attempt_id"),
            ("authorization_digest", "authorization_digest"),
            ("artifact_set_digest", "artifact_set_digest"),
            ("last_event_digest", "event_digest"),
            ("updated_at", "occurred_at"),
        )
    ):
        raise Phase5C4PrerequisiteError("fence_event_chain_invalid")


def _require_mapping(payload: Any, keys: frozenset[str], reason: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != keys:
        raise Phase5C4PrerequisiteError(reason)
    return dict(payload)


def _canonical_uuid(value: Any, reason: str) -> str:
    if not isinstance(value, (str, UUID)):
        raise Phase5C4PrerequisiteError(reason)
    rendered = str(value)
    try:
        parsed = UUID(rendered)
    except (ValueError, TypeError, AttributeError):
        raise Phase5C4PrerequisiteError(reason) from None
    if str(parsed) != rendered:
        raise Phase5C4PrerequisiteError(reason)
    return rendered


def _optional_uuid(value: Any, reason: str) -> str | None:
    return None if value is None else _canonical_uuid(value, reason)


def _require_digest(value: Any, reason: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise Phase5C4PrerequisiteError(reason)
    return value


def _optional_digest(value: Any, reason: str) -> str | None:
    return None if value is None else _require_digest(value, reason)


def _event_timestamp(value: Any) -> str:
    try:
        return format_contract_timestamp(value)
    except Phase5C4PrerequisiteError:
        raise Phase5C4PrerequisiteError("fence_event_chain_invalid") from None


def _state_timestamp(value: Any) -> str:
    try:
        return format_contract_timestamp(value)
    except Phase5C4PrerequisiteError:
        raise Phase5C4PrerequisiteError("fence_state_invalid") from None
