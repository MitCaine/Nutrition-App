from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import math
import re
import sys
import threading
import time
from typing import Any, Literal

from sqlalchemy import Engine, event

from app.operators.phase5c_performance_contracts import (
    PERFORMANCE_STAGES,
    SCAN_COUNT_KEYS,
)

_DAILY_LOG_TABLES = frozenset(
    {"daily_logs", "daily_log_nutrient_snapshots"}
)
_OCR_TABLES = frozenset(
    {
        "ocr_scans",
        "parse_results",
        "parser_corrections",
        "ocr_nutrition_confirmation_traces",
    }
)
_RECIPE_SOURCE_TABLES = frozenset({"recipes", "recipe_ingredients"})
_SUPPORTING_SOURCE_TABLES = frozenset(
    {
        "users",
        "food_items",
        "serving_definitions",
        "food_nutrients",
        "food_sources",
    }
)
_WRITE_PREFIXES = ("insert", "update", "delete", "merge")
_DDL_PREFIXES = ("alter", "comment", "create", "drop", "truncate")
_BOUNDING_CLAUSE = re.compile(r"\b(?:where|limit|offset|fetch)\b", re.IGNORECASE)
_RELATION = re.compile(
    r"\b(?:from|join)\s+"
    r"((?:\"(?:[^\"]|\"\")+\"|[A-Za-z_][A-Za-z0-9_$]*)"
    r"(?:\s*\.\s*(?:\"(?:[^\"]|\"\")+\"|[A-Za-z_][A-Za-z0-9_$]*))?)",
    re.IGNORECASE,
)
_OPERATION_LOCK_ACQUIRE = re.compile(r"\bpg_advisory_lock\s*\(", re.IGNORECASE)
_OPERATION_LOCK_RELEASE = re.compile(r"\bpg_advisory_unlock\s*\(", re.IGNORECASE)
_RECIPE_MARKER_FOOD_SCAN = re.compile(
    r"\bis_recipe\s*=\s*true\s+or\s+source_type\s*=\s*'recipe'(?:\s|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryClassification:
    """Aggregate-safe SQL classification; it intentionally retains no SQL or identifiers."""

    operation: Literal["select", "write", "ddl", "other"]
    logical_full_scan: bool
    global_source_pass: bool
    archive_support_relation_scan: bool
    daily_log_relation_scan: bool
    ocr_relation_scan: bool
    dependency_query: bool
    operation_lock_action: Literal["acquire", "release"] | None


@dataclass(frozen=True)
class _StageScope:
    owner: int
    name: str


@dataclass(frozen=True)
class _SubjectScope:
    owner: int
    ordinal: int
    stage: str
    started_at: float
    disposition: Literal["convert", "quarantine", "block"] | None


@dataclass(frozen=True)
class _ObserverStageScope:
    owner: int
    name: str
    previous: _StageScope | None
    started_wall: float
    started_cpu: float
    started_rss: int | None
    owns_stage: bool


@dataclass(frozen=True)
class _QueryStart:
    stage: str
    started_at: float
    subject_ordinal: int | None
    classification: QueryClassification


@dataclass(frozen=True)
class _TransactionStart:
    stage: str
    started_at: float
    subject_ordinal: int | None


@dataclass(frozen=True)
class _LockHoldStart:
    stage: str
    started_at: float


@dataclass
class _Aggregate:
    query_count: int = 0
    scan_counts: dict[str, int] = field(
        default_factory=lambda: {key: 0 for key in SCAN_COUNT_KEYS}
    )
    subject_ordinals: set[int] = field(default_factory=set)
    subject_query_counts: dict[int, int] = field(default_factory=dict)
    subject_seconds: list[float] = field(default_factory=list)
    transaction_seconds: list[float] = field(default_factory=list)
    operation_lock_hold_seconds: list[float] = field(default_factory=list)
    operation_lock_wait_seconds: list[float] = field(default_factory=list)
    retry_count: int = 0
    dependency_query_count: int = 0


@dataclass
class _StageAggregate(_Aggregate):
    status: Literal["not_run", "running", "completed", "failed"] = "not_run"
    wall_seconds: float = 0.0
    cpu_seconds: float = 0.0
    artifact_bytes: int | None = None
    nested_wall_seconds: float = 0.0
    nested_cpu_seconds: float = 0.0
    rss_high_water_growth_bytes: int = 0
    nested_rss_high_water_growth_bytes: int = 0


_CURRENT_STAGE: ContextVar[_StageScope | None] = ContextVar(
    "phase5c_performance_stage", default=None
)
_SUBJECT_STACK: ContextVar[tuple[_SubjectScope, ...]] = ContextVar(
    "phase5c_performance_subject_stack", default=()
)
_OBSERVER_STAGE_STACK: ContextVar[tuple[_ObserverStageScope, ...]] = ContextVar(
    "phase5c_performance_observer_stage_stack", default=()
)
_IGNORE_QUERIES: ContextVar[frozenset[int]] = ContextVar(
    "phase5c_performance_ignored_owners", default=frozenset()
)


def _unquote_identifier(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1].replace('""', '"')
    return value.casefold()


def _safe_relations(statement: str) -> tuple[tuple[str | None, str], ...]:
    relations: list[tuple[str | None, str]] = []
    for match in _RELATION.finditer(statement):
        parts = re.split(r"\s*\.\s*", match.group(1), maxsplit=1)
        if len(parts) == 1:
            relations.append((None, _unquote_identifier(parts[0])))
        else:
            relations.append(
                (_unquote_identifier(parts[0]), _unquote_identifier(parts[1]))
            )
    return tuple(relations)


def classify_sql(
    statement: str,
    *,
    archive_schema: str | None = None,
    subject_scoped: bool = False,
) -> QueryClassification:
    """Classify one statement without retaining SQL, parameters, or unknown relation names.

    A "full scan" here means an unbounded logical relation read. It does not claim that
    PostgreSQL selected a physical sequential-scan plan.
    """

    normalized = " ".join(statement.split())
    lowered = normalized.casefold()
    first = lowered.split(" ", 1)[0] if lowered else ""
    if first in {"select", "with"}:
        operation: Literal["select", "write", "ddl", "other"] = "select"
    elif first.startswith(_WRITE_PREFIXES):
        operation = "write"
    elif first.startswith(_DDL_PREFIXES):
        operation = "ddl"
    else:
        operation = "other"

    relations = _safe_relations(normalized) if operation == "select" else ()
    relation_tables = {table for _schema, table in relations}
    recipe_marker_food_scan = (
        "food_items" in relation_tables
        and _RECIPE_MARKER_FOOD_SCAN.search(normalized) is not None
    )
    logical_full_scan = bool(relations) and (
        _BOUNDING_CLAUSE.search(normalized) is None or recipe_marker_food_scan
    )
    recipe_relation = bool(relation_tables & _RECIPE_SOURCE_TABLES)
    recipe_root_relation = "recipes" in relation_tables
    supporting_relation = bool(relation_tables & _SUPPORTING_SOURCE_TABLES)
    archive_relation = False
    if archive_schema is not None:
        archive_key = archive_schema.casefold()
        archive_relation = any(
            schema == archive_key and table in _RECIPE_SOURCE_TABLES
            for schema, table in relations
        )

    daily_relation = bool(relation_tables & _DAILY_LOG_TABLES)
    ocr_relation = bool(relation_tables & _OCR_TABLES)
    source_relation = recipe_relation or supporting_relation or archive_relation
    bounded_dependency = operation == "select" and source_relation and not logical_full_scan

    lock_action: Literal["acquire", "release"] | None = None
    if _OPERATION_LOCK_ACQUIRE.search(normalized):
        lock_action = "acquire"
    elif _OPERATION_LOCK_RELEASE.search(normalized):
        lock_action = "release"

    return QueryClassification(
        operation=operation,
        logical_full_scan=logical_full_scan,
        # Each unbounded Recipe relation read is a stable proxy for one planning-source pass.
        global_source_pass=logical_full_scan and recipe_root_relation,
        archive_support_relation_scan=logical_full_scan and source_relation,
        daily_log_relation_scan=logical_full_scan and daily_relation,
        ocr_relation_scan=logical_full_scan and ocr_relation,
        dependency_query=subject_scoped and bounded_dependency,
        operation_lock_action=lock_action,
    )


def percentile(values: list[float] | tuple[float, ...], percentile_value: int) -> float:
    """Return a deterministic nearest-rank percentile for bounded measurement evidence."""

    if not 0 < percentile_value <= 100:
        raise ValueError("percentile must be in the range 1..100")
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if any(not math.isfinite(value) or value < 0 for value in ordered):
        raise ValueError("measurement values must be finite and non-negative")
    rank = max(0, math.ceil((percentile_value / 100) * len(ordered)) - 1)
    return ordered[rank]


def summarize_distribution(
    values: list[float] | tuple[float, ...] | list[int] | tuple[int, ...],
    *,
    integral: bool = False,
) -> dict[str, int | float | None]:
    if not values:
        return {
            "count": 0,
            "p50": None,
            "p95": None,
            "p99": None,
            "maximum": None,
        }
    if integral:
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("integral distribution values must be integers")
        return {
            "count": len(values),
            "p50": int(percentile(values, 50)),
            "p95": int(percentile(values, 95)),
            "p99": int(percentile(values, 99)),
            "maximum": max(values),
        }
    return {
        "count": len(values),
        "p50": _round_seconds(percentile(values, 50)),
        "p95": _round_seconds(percentile(values, 95)),
        "p99": _round_seconds(percentile(values, 99)),
        "maximum": _round_seconds(max(values)),
    }


def _round_seconds(value: float) -> float:
    return round(float(value), 9)


def _peak_rss() -> tuple[int | None, str]:
    try:
        import resource

        raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (ImportError, OSError, ValueError):
        return None, "unavailable"
    if sys.platform == "darwin":
        return raw, "resource_ru_maxrss"
    return raw * 1024, "resource_ru_maxrss"


class Phase5CPerformanceInstrumentation:
    """Temporary, aggregate-only instrumentation for the offline Phase 5C benchmark."""

    def __init__(self, *, archive_schema: str | None = None) -> None:
        self.archive_schema = archive_schema
        self._owner = id(self)
        self._mutex = threading.RLock()
        self._global = _Aggregate()
        self._stages = {name: _StageAggregate() for name in PERFORMANCE_STAGES}
        self._active_queries: dict[int, _QueryStart] = {}
        self._active_transactions: dict[int, list[_TransactionStart]] = {}
        self._active_lock_holds: dict[int, _LockHoldStart] = {}
        self._next_subject_ordinal = 0
        self._database_size_bytes: int | None = None
        self._installed = False
        rss, method = _peak_rss()
        self._peak_python_rss_bytes = rss
        self._memory_measurement_method = method

    @contextmanager
    def install(self) -> Iterator[Phase5CPerformanceInstrumentation]:
        """Install process-local Engine-class listeners and always remove them."""

        with self._mutex:
            if self._installed:
                raise RuntimeError("Phase 5C performance instrumentation is already installed")
            self._installed = True
        listeners = (
            ("before_cursor_execute", self._before_cursor_execute),
            ("after_cursor_execute", self._after_cursor_execute),
            ("begin", self._transaction_begin),
            ("commit", self._transaction_end),
            ("rollback", self._transaction_end),
        )
        for name, listener in listeners:
            event.listen(Engine, name, listener)
        try:
            yield self
        finally:
            for name, listener in reversed(listeners):
                event.remove(Engine, name, listener)
            with self._mutex:
                self._installed = False
                self._active_queries.clear()
                self._active_transactions.clear()
                self._active_lock_holds.clear()
                self._capture_rss()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if name not in self._stages:
            raise ValueError("Unsupported Phase 5C performance stage")
        token = _CURRENT_STAGE.set(_StageScope(self._owner, name))
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        started_rss, _ = _peak_rss()
        self._capture_rss()
        with self._mutex:
            aggregate = self._stages[name]
            nested_wall_at_start = aggregate.nested_wall_seconds
            nested_cpu_at_start = aggregate.nested_cpu_seconds
            nested_rss_at_start = aggregate.nested_rss_high_water_growth_bytes
            if aggregate.status != "failed":
                aggregate.status = "running"
        try:
            yield
        except BaseException:
            with self._mutex:
                aggregate.status = "failed"
            raise
        else:
            with self._mutex:
                if aggregate.status != "failed":
                    aggregate.status = "completed"
        finally:
            elapsed_wall = time.perf_counter() - started_wall
            elapsed_cpu = time.process_time() - started_cpu
            ended_rss, _ = _peak_rss()
            with self._mutex:
                nested_wall = aggregate.nested_wall_seconds - nested_wall_at_start
                nested_cpu = aggregate.nested_cpu_seconds - nested_cpu_at_start
                nested_rss = (
                    aggregate.nested_rss_high_water_growth_bytes
                    - nested_rss_at_start
                )
                aggregate.wall_seconds += max(0.0, elapsed_wall - nested_wall)
                aggregate.cpu_seconds += max(0.0, elapsed_cpu - nested_cpu)
                if started_rss is not None and ended_rss is not None:
                    interval_growth = max(0, ended_rss - started_rss)
                    aggregate.rss_high_water_growth_bytes += max(
                        0, interval_growth - nested_rss
                    )
            self._capture_rss()
            _CURRENT_STAGE.reset(token)

    @contextmanager
    def subject(
        self,
        *,
        disposition: Literal["convert", "quarantine", "block"] = "convert",
    ) -> Iterator[None]:
        self.observe_subject("subject_start", disposition=disposition)
        try:
            yield
        finally:
            self.observe_subject("subject_end")

    def observe_subject(
        self,
        event_name: str,
        _subject_identity: object | None = None,
        disposition: str | None = None,
        _attempt: int | None = None,
    ) -> None:
        """Converter callback. The supplied identity is deliberately ignored and never retained."""

        if event_name in {"subject_start", "start"}:
            stage = self._current_stage()
            if stage is None:
                raise RuntimeError("A measured subject requires an active performance stage")
            with self._mutex:
                self._next_subject_ordinal += 1
                ordinal = self._next_subject_ordinal
                self._register_subject(self._global, ordinal)
                self._register_subject(self._stages[stage], ordinal)
            scope = _SubjectScope(
                owner=self._owner,
                ordinal=ordinal,
                stage=stage,
                started_at=time.perf_counter(),
                disposition=(
                    disposition
                    if disposition in {"convert", "quarantine", "block"}
                    else None
                ),
            )
            _SUBJECT_STACK.set((*_SUBJECT_STACK.get(), scope))
            return
        if event_name in {"subject_retry", "retry"}:
            scope = self._current_subject()
            if scope is None:
                raise RuntimeError("A subject retry requires an active measured subject")
            with self._mutex:
                self._global.retry_count += 1
                self._stages[scope.stage].retry_count += 1
            return
        if event_name not in {"subject_end", "end"}:
            raise ValueError("Unsupported Phase 5C subject-observer event")
        stack = _SUBJECT_STACK.get()
        scope = self._current_subject()
        if scope is None or not stack:
            raise RuntimeError("A measured subject end has no matching start")
        duration = time.perf_counter() - scope.started_at
        with self._mutex:
            if scope.disposition == "convert":
                self._global.subject_seconds.append(duration)
                self._stages[scope.stage].subject_seconds.append(duration)
        _SUBJECT_STACK.set(stack[:-1])

    def converter_observer(
        self,
        event_name: str,
        subject_identity: object | None,
        disposition: str | None,
        attempt: int | None,
    ) -> None:
        """Adapter matching historical_recipe_converter.PerformanceObserver exactly."""

        if event_name.startswith("subject_"):
            self.observe_subject(
                event_name,
                subject_identity,
                disposition,
                attempt,
            )
            return
        if event_name == "execution_receipt_start":
            self._observer_stage_start("execution_receipt_generation")
            return
        if event_name == "execution_receipt_end":
            self._observer_stage_end("execution_receipt_generation")
            return
        raise ValueError("Unsupported Phase 5C converter-observer event")

    @contextmanager
    def ignore_queries(self) -> Iterator[None]:
        """Exclude instrumentation-support queries such as pg_database_size/SHOW reads."""

        current = _IGNORE_QUERIES.get()
        token = _IGNORE_QUERIES.set(current | {self._owner})
        try:
            yield
        finally:
            _IGNORE_QUERIES.reset(token)

    def record_database_size(self, size_bytes: int) -> None:
        size = _nonnegative_integer(size_bytes, "database size")
        with self._mutex:
            self._database_size_bytes = size

    def record_artifact_bytes(self, stage: str, size_bytes: int) -> None:
        if stage not in self._stages:
            raise ValueError("Unsupported Phase 5C performance stage")
        size = _nonnegative_integer(size_bytes, "artifact size")
        with self._mutex:
            stored = self._stages[stage].artifact_bytes
            if stored is not None and stored != size:
                raise ValueError("Artifact size was already recorded with a different value")
            self._stages[stage].artifact_bytes = size

    def snapshot(self) -> dict[str, Any]:
        """Return the exact bounded measurements contract consumed by the manifest builder."""

        self._capture_rss()
        with self._mutex:
            stages = {
                name: {
                    "status": aggregate.status,
                    "wall_seconds": (
                        None
                        if aggregate.status == "not_run"
                        else _round_seconds(aggregate.wall_seconds)
                    ),
                    "cpu_seconds": (
                        None
                        if aggregate.status == "not_run"
                        else _round_seconds(aggregate.cpu_seconds)
                    ),
                    "query_count": aggregate.query_count,
                    "scan_counts": dict(aggregate.scan_counts),
                    "rss_high_water_growth_bytes": (
                        None
                        if aggregate.status == "not_run"
                        or self._memory_measurement_method == "unavailable"
                        else aggregate.rss_high_water_growth_bytes
                    ),
                    "artifact_bytes": aggregate.artifact_bytes,
                }
                for name, aggregate in self._stages.items()
            }
            conversion = self._stages["conversion"]
            subject_query_values = [
                conversion.subject_query_counts.get(ordinal, 0)
                for ordinal in sorted(conversion.subject_ordinals)
            ]
            return {
                "stages": stages,
                "peak_python_rss_bytes": self._peak_python_rss_bytes,
                "memory_measurement_method": self._memory_measurement_method,
                "database_size_bytes": self._database_size_bytes,
                "query_count": self._global.query_count,
                "scan_counts": dict(self._global.scan_counts),
                "subject_query_distribution": summarize_distribution(
                    subject_query_values,
                    integral=True,
                ),
                "subject_dependency_query_count": (
                    self._global.dependency_query_count
                ),
                "subject_conversion_seconds": summarize_distribution(
                    conversion.subject_seconds
                ),
                "transaction_seconds": summarize_distribution(
                    self._global.transaction_seconds
                ),
                "operation_lock_wait_seconds": summarize_distribution(
                    self._global.operation_lock_wait_seconds
                ),
                "operation_lock_hold_seconds": summarize_distribution(
                    self._global.operation_lock_hold_seconds
                ),
                "retry_count": self._global.retry_count,
                "artifact_bytes": {
                    "execution_receipt": self._stages[
                        "execution_receipt_generation"
                    ].artifact_bytes,
                    "qualification_receipt": self._stages[
                        "independent_qualification"
                    ].artifact_bytes,
                },
            }

    def _observer_stage_start(self, name: str) -> None:
        current = _CURRENT_STAGE.get()
        owns_stage = current is None or current.owner != self._owner or current.name != name
        scope = _ObserverStageScope(
            owner=self._owner,
            name=name,
            previous=current,
            started_wall=time.perf_counter(),
            started_cpu=time.process_time(),
            started_rss=_peak_rss()[0],
            owns_stage=owns_stage,
        )
        _OBSERVER_STAGE_STACK.set((*_OBSERVER_STAGE_STACK.get(), scope))
        if not owns_stage:
            return
        _CURRENT_STAGE.set(_StageScope(self._owner, name))
        self._capture_rss()
        with self._mutex:
            aggregate = self._stages[name]
            if aggregate.status != "failed":
                aggregate.status = "running"

    def _observer_stage_end(self, name: str) -> None:
        stack = _OBSERVER_STAGE_STACK.get()
        if not stack or stack[-1].owner != self._owner or stack[-1].name != name:
            raise RuntimeError("Measured converter operation has no matching start")
        scope = stack[-1]
        _OBSERVER_STAGE_STACK.set(stack[:-1])
        if not scope.owns_stage:
            return
        elapsed_wall = time.perf_counter() - scope.started_wall
        elapsed_cpu = time.process_time() - scope.started_cpu
        ended_rss, _ = _peak_rss()
        rss_growth = (
            max(0, ended_rss - scope.started_rss)
            if ended_rss is not None and scope.started_rss is not None
            else 0
        )
        with self._mutex:
            aggregate = self._stages[name]
            aggregate.wall_seconds += elapsed_wall
            aggregate.cpu_seconds += elapsed_cpu
            aggregate.rss_high_water_growth_bytes += rss_growth
            if aggregate.status != "failed":
                aggregate.status = "completed"
            if scope.previous is not None and scope.previous.owner == self._owner:
                parent = self._stages[scope.previous.name]
                parent.nested_wall_seconds += elapsed_wall
                parent.nested_cpu_seconds += elapsed_cpu
                parent.nested_rss_high_water_growth_bytes += rss_growth
        _CURRENT_STAGE.set(scope.previous)
        self._capture_rss()

    def _current_stage(self) -> str | None:
        scope = _CURRENT_STAGE.get()
        return scope.name if scope is not None and scope.owner == self._owner else None

    def _current_subject(self) -> _SubjectScope | None:
        stack = _SUBJECT_STACK.get()
        if not stack or stack[-1].owner != self._owner:
            return None
        return stack[-1]

    def _queries_ignored(self) -> bool:
        return self._owner in _IGNORE_QUERIES.get()

    def _before_cursor_execute(
        self,
        connection,
        _cursor,
        statement,
        _parameters,
        execution_context,
        _executemany,
    ) -> None:
        stage = self._current_stage()
        if stage is None or self._queries_ignored():
            return
        subject = self._current_subject()
        classification = classify_sql(
            str(statement),
            archive_schema=self.archive_schema,
            subject_scoped=subject is not None,
        )
        query = _QueryStart(
            stage=stage,
            started_at=time.perf_counter(),
            subject_ordinal=subject.ordinal if subject is not None else None,
            classification=classification,
        )
        with self._mutex:
            self._active_queries[id(execution_context)] = query
            self._record_query(self._global, query)
            self._record_query(self._stages[stage], query)
            if classification.operation_lock_action == "release":
                hold = self._active_lock_holds.pop(id(connection), None)
                if hold is not None:
                    duration = time.perf_counter() - hold.started_at
                    self._global.operation_lock_hold_seconds.append(duration)
                    self._stages[hold.stage].operation_lock_hold_seconds.append(
                        duration
                    )

    def _after_cursor_execute(
        self,
        connection,
        _cursor,
        _statement,
        _parameters,
        execution_context,
        _executemany,
    ) -> None:
        with self._mutex:
            query = self._active_queries.pop(id(execution_context), None)
            if query is None:
                return
            if query.classification.operation_lock_action == "acquire":
                now = time.perf_counter()
                wait = now - query.started_at
                self._global.operation_lock_wait_seconds.append(wait)
                self._stages[query.stage].operation_lock_wait_seconds.append(wait)
                self._active_lock_holds[id(connection)] = _LockHoldStart(
                    stage=query.stage,
                    started_at=now,
                )

    def _transaction_begin(self, connection) -> None:
        stage = self._current_stage()
        if stage is None or self._queries_ignored():
            return
        subject = self._current_subject()
        start = _TransactionStart(
            stage=stage,
            started_at=time.perf_counter(),
            subject_ordinal=subject.ordinal if subject is not None else None,
        )
        with self._mutex:
            self._active_transactions.setdefault(id(connection), []).append(start)

    def _transaction_end(self, connection) -> None:
        with self._mutex:
            stack = self._active_transactions.get(id(connection))
            if not stack:
                return
            start = stack.pop()
            if not stack:
                self._active_transactions.pop(id(connection), None)
            duration = time.perf_counter() - start.started_at
            self._global.transaction_seconds.append(duration)
            self._stages[start.stage].transaction_seconds.append(duration)

    def _record_query(self, aggregate: _Aggregate, query: _QueryStart) -> None:
        classification = query.classification
        aggregate.query_count += 1
        if classification.global_source_pass:
            aggregate.scan_counts["global_source_passes"] += 1
        if classification.archive_support_relation_scan:
            aggregate.scan_counts["archive_support_relation_scans"] += 1
        if classification.daily_log_relation_scan:
            aggregate.scan_counts["daily_log_relation_scans"] += 1
        if classification.ocr_relation_scan:
            aggregate.scan_counts["ocr_relation_scans"] += 1
        if query.subject_ordinal is not None:
            aggregate.subject_query_counts[query.subject_ordinal] = (
                aggregate.subject_query_counts.get(query.subject_ordinal, 0) + 1
            )
            if classification.global_source_pass:
                aggregate.scan_counts["per_subject_global_source_passes"] += 1
            if classification.daily_log_relation_scan:
                aggregate.scan_counts[
                    "per_subject_daily_log_relation_scans"
                ] += 1
            if classification.ocr_relation_scan:
                aggregate.scan_counts["per_subject_ocr_relation_scans"] += 1
        if classification.dependency_query:
            aggregate.dependency_query_count += 1

    @staticmethod
    def _register_subject(aggregate: _Aggregate, ordinal: int) -> None:
        aggregate.subject_ordinals.add(ordinal)
        aggregate.subject_query_counts.setdefault(ordinal, 0)

    def _capture_rss(self) -> None:
        rss, method = _peak_rss()
        with self._mutex:
            if rss is not None:
                self._peak_python_rss_bytes = max(
                    self._peak_python_rss_bytes or 0,
                    rss,
                )
            if self._memory_measurement_method == "unavailable" and method != "unavailable":
                self._memory_measurement_method = method


def _nonnegative_integer(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value
