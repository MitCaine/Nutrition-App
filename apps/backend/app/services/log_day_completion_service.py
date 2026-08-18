from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.create_idempotency import CreateOperationIdempotency
from app.models.log import DailyLogDayCompletion
from app.repositories.log_repository import LogRepository
from app.schemas.log import (
    DailyLogCompleteRequest,
    DailyLogCompleteResponse,
    DailyLogMutationStatusResponse,
)
from app.services.calendar_service import CalendarService
from app.services.create_idempotency import (
    CreateIdempotencyCoordinator,
    CreateOperationIdempotencyConflictError,
    CreateOperationResultUnavailableError,
    create_fingerprint,
    is_create_idempotency_conflict,
)

COMPLETE_OPERATION = "log.complete"


class EmptyDailyLogDateError(ValueError):
    code = "daily_log_date_empty"
    message = "A Daily Log date must contain at least one entry before it can be marked Complete."


class CompleteMutationPayloadConflictError(ValueError):
    code = "log_mutation_payload_conflict"
    message = (
        "This Complete mutation was already submitted with different details. "
        "Start a new mutation and review the current date."
    )


class CompleteMutationResultUnavailableError(ValueError):
    code = "log_mutation_unresolved"
    message = (
        "The outcome of this Complete mutation is not yet available. "
        "Check its status before starting another mutation."
    )


def _complete_fingerprint(payload: DailyLogCompleteRequest) -> str:
    return create_fingerprint(payload, context={"operation": COMPLETE_OPERATION})


class LogDayCompletionService:
    """Authoritative positive day-level Complete mutation boundary."""

    def __init__(self, db: Session):
        self.db = db
        self.logs = LogRepository(db)
        self.mutation_receipts = CreateIdempotencyCoordinator(db)

    def get_completion(
        self,
        user_id: UUID,
        logged_date: date,
    ) -> DailyLogDayCompletion | None:
        return self.logs.get_day_completion(user_id, logged_date)

    def assert_complete(
        self,
        user_id: UUID,
        logged_date: date,
    ) -> DailyLogDayCompletion:
        """Retain the E4-01 persistence-only helper for internal callers/tests."""

        try:
            if not self.logs.has_logs_for_date(user_id, logged_date):
                raise EmptyDailyLogDateError(EmptyDailyLogDateError.message)
            completion = self.logs.assert_day_completion(user_id, logged_date)
            self.db.commit()
            return completion
        except Exception:
            self.db.rollback()
            raise

    def _find_receipt(
        self,
        user_id: UUID,
        client_request_id: UUID,
        fingerprint: str,
    ) -> CreateOperationIdempotency | None:
        try:
            return self.mutation_receipts.find(
                user_id,
                COMPLETE_OPERATION,
                client_request_id,
                fingerprint,
            )
        except CreateOperationIdempotencyConflictError as exc:
            raise CompleteMutationPayloadConflictError(
                CompleteMutationPayloadConflictError.message
            ) from exc

    def _replay_receipt(
        self,
        receipt: CreateOperationIdempotency,
    ) -> DailyLogCompleteResponse:
        try:
            snapshot = self.mutation_receipts.replay_snapshot(receipt)
            return DailyLogCompleteResponse.model_validate(snapshot)
        except CreateOperationResultUnavailableError as exc:
            raise CompleteMutationResultUnavailableError(
                CompleteMutationResultUnavailableError.message
            ) from exc

    def mark_complete(
        self,
        user_id: UUID,
        payload: DailyLogCompleteRequest,
    ) -> DailyLogCompleteResponse:
        """Commit one deterministic Complete assertion and its receipt atomically."""

        fingerprint = _complete_fingerprint(payload)
        try:
            existing = self._find_receipt(
                user_id,
                payload.client_request_id,
                fingerprint,
            )
            if existing is not None:
                return self._replay_receipt(existing)

            # The authoritative calendar lock serializes owner mutations and
            # fences future dates without using the device clock.
            CalendarService(self.db).validate_mutation_context(
                user_id,
                payload.calendar_revision,
                payload.logged_date,
            )

            anchor = self.logs.lock_first_for_date(user_id, payload.logged_date)
            if anchor is None:
                raise EmptyDailyLogDateError(EmptyDailyLogDateError.message)

            # A concurrent identical request may have committed while this
            # transaction waited for the owner/date lock. Recheck before reserve.
            existing = self._find_receipt(
                user_id,
                payload.client_request_id,
                fingerprint,
            )
            if existing is not None:
                result = self._replay_receipt(existing)
                self.db.commit()
                return result

            try:
                receipt = self.mutation_receipts.reserve(
                    user_id,
                    COMPLETE_OPERATION,
                    payload.client_request_id,
                    fingerprint,
                    anchor.id,
                )
            except IntegrityError as exc:
                if not is_create_idempotency_conflict(exc):
                    raise
                self.db.rollback()
                existing = self._find_receipt(
                    user_id,
                    payload.client_request_id,
                    fingerprint,
                )
                if existing is None:
                    raise
                return self._replay_receipt(existing)

            completion = self.logs.assert_day_completion(user_id, payload.logged_date)
            result = DailyLogCompleteResponse.model_validate(completion)
            self.mutation_receipts.complete(receipt, result.model_dump(mode="json"))
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def mutation_status(
        self,
        user_id: UUID,
        client_request_id: UUID,
    ) -> DailyLogMutationStatusResponse:
        """Read one owner-scoped Complete receipt without mutating domain state."""

        receipt = self.db.scalar(
            select(CreateOperationIdempotency).where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == COMPLETE_OPERATION,
                CreateOperationIdempotency.client_request_id == client_request_id,
            )
        )
        if receipt is None:
            return DailyLogMutationStatusResponse(
                operation="complete",
                client_request_id=client_request_id,
                status="confirmed_non_commit",
            )
        if receipt.response_snapshot is None or receipt.completed_at is None:
            return DailyLogMutationStatusResponse(
                operation="complete",
                client_request_id=client_request_id,
                status="unresolved",
            )
        try:
            completion = DailyLogCompleteResponse.model_validate(receipt.response_snapshot)
        except Exception:
            return DailyLogMutationStatusResponse(
                operation="complete",
                client_request_id=client_request_id,
                status="unresolved",
            )
        return DailyLogMutationStatusResponse(
            operation="complete",
            client_request_id=client_request_id,
            status="confirmed_success",
            completion=completion,
        )
