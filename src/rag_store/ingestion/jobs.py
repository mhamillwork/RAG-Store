"""Durable PostgreSQL job queue.

Claiming uses FOR UPDATE SKIP LOCKED. Completion and failure updates include the
fencing token so an expired worker cannot overwrite a newer attempt. Execution is
at-least-once; writes are idempotent per document version.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from rag_store.common.errors import LeaseLost, NotFound
from rag_store.database.models import IngestionAttempt, IngestionJob

PRIORITY = {"interactive": 10, "ordinary": 40, "bulk": 70, "reindex": 90}
TERMINAL = {"completed", "failed", "cancelled", "conversion_completed"}
CLAIMABLE = {"queued", "retry_pending"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_job(session: Session, *, worker_id: str, predicate, lease_seconds: int) -> IngestionJob | None:
    stmt = (
        select(IngestionJob)
        .where(IngestionJob.state.in_(tuple(CLAIMABLE)))
        .where(IngestionJob.next_run_at <= utcnow())
        .where(predicate)
        .order_by(IngestionJob.priority.asc(), IngestionJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.scalars(stmt).first()
    if job is None:
        return None
    job.fencing_token += 1
    job.worker_id = worker_id
    job.attempt_count += 1
    job.heartbeat_at = utcnow()
    job.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
    job.started_at = job.started_at or utcnow()
    job.updated_at = utcnow()
    job.state = "chunking" if job.job_type == "chunk_embed" else "validating"
    session.add(
        IngestionAttempt(
            job_id=job.id,
            attempt_number=job.attempt_count,
            worker_id=worker_id,
            fencing_token=job.fencing_token,
            outcome="running",
        )
    )
    session.flush()
    return job


def recover_expired_leases(session: Session) -> int:
    result = session.execute(
        update(IngestionJob)
        .where(IngestionJob.lease_expires_at.is_not(None))
        .where(IngestionJob.lease_expires_at < utcnow())
        .where(IngestionJob.state.notin_(tuple(TERMINAL | CLAIMABLE)))
        .values(
            state="retry_pending",
            worker_id=None,
            lease_expires_at=None,
            last_error="lease expired before the worker finished",
            next_run_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    return result.rowcount or 0


def _locked(session: Session, job_id: UUID, token: int, worker_id: str) -> IngestionJob:
    job = session.get(IngestionJob, job_id)
    if job is None or job.fencing_token != token or job.worker_id != worker_id:
        raise LeaseLost("This worker no longer holds the job lease.")
    return job


def heartbeat(session: Session, job_id: UUID, token: int, worker_id: str, lease_seconds: int) -> None:
    job = _locked(session, job_id, token, worker_id)
    job.heartbeat_at = utcnow()
    job.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
    job.updated_at = utcnow()


def set_state(session: Session, job_id: UUID, token: int, worker_id: str, state: str, progress: dict | None = None) -> IngestionJob:
    job = _locked(session, job_id, token, worker_id)
    job.state = state
    job.updated_at = utcnow()
    if progress is not None:
        merged = dict(job.progress or {})
        merged.update(progress)
        job.progress = merged
    return job


def succeed(session: Session, job_id: UUID, token: int, worker_id: str, state: str = "completed") -> None:
    job = _locked(session, job_id, token, worker_id)
    job.state = state
    job.finished_at = utcnow()
    job.updated_at = utcnow()
    job.worker_id = None
    job.lease_expires_at = None
    _finish_attempt(session, job, "success", "")


def fail_or_retry(session: Session, job_id: UUID, token: int, worker_id: str, error: str, *, base_seconds: int) -> str:
    job = _locked(session, job_id, token, worker_id)
    job.last_error = error[:4000]
    job.updated_at = utcnow()
    job.worker_id = None
    job.lease_expires_at = None
    if job.attempt_count >= job.max_attempts:
        job.state = "failed"
        job.finished_at = utcnow()
        _finish_attempt(session, job, "failed", job.last_error)
        return "failed"
    delay = min(base_seconds * (2 ** max(job.attempt_count - 1, 0)), 900)
    job.state = "retry_pending"
    job.next_run_at = utcnow() + timedelta(seconds=delay)
    _finish_attempt(session, job, "retry", job.last_error)
    return "retry_pending"


def _finish_attempt(session: Session, job: IngestionJob, outcome: str, error: str) -> None:
    attempt = session.scalars(
        select(IngestionAttempt)
        .where(IngestionAttempt.job_id == job.id, IngestionAttempt.fencing_token == job.fencing_token)
        .order_by(IngestionAttempt.started_at.desc())
    ).first()
    if attempt is not None:
        attempt.outcome = outcome
        attempt.error = error[:4000]
        attempt.finished_at = utcnow()


def enqueue(session: Session, **kwargs) -> IngestionJob:
    existing = session.scalars(select(IngestionJob).where(IngestionJob.idempotency_key == kwargs["idempotency_key"])).first()
    if existing is not None:
        return existing
    job = IngestionJob(**kwargs)
    session.add(job)
    session.flush()
    return job


def retry_job(session: Session, job_id: UUID) -> IngestionJob:
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise NotFound("Job not found.")
    if job.state not in {"failed", "cancelled"}:
        raise NotFound("Only a failed or cancelled job can be retried.") if False else _conflict(job)
    job.state = "retry_pending"
    job.next_run_at = utcnow()
    job.last_error = ""
    job.worker_id = None
    job.lease_expires_at = None
    job.updated_at = utcnow()
    job.max_attempts = max(job.max_attempts, job.attempt_count + 1)
    return job


def _conflict(job: IngestionJob):
    from rag_store.common.errors import Conflict

    raise Conflict(f"Job {job.id} is {job.state} and cannot be retried.")


def cancel_job(session: Session, job_id: UUID) -> IngestionJob:
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise NotFound("Job not found.")
    if job.state in {"completed", "conversion_completed"}:
        from rag_store.common.errors import Conflict

        raise Conflict("A completed job cannot be cancelled.")
    job.state = "cancelled"
    job.finished_at = utcnow()
    job.worker_id = None
    job.lease_expires_at = None
    job.updated_at = utcnow()
    return job
