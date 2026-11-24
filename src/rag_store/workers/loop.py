"""Worker loop shared by ingestion and Docling processes."""

from __future__ import annotations

import socket
import threading
from datetime import datetime, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from rag_store.common.errors import LeaseLost
from rag_store.common.logging import get_logger
from rag_store.config.settings import Settings
from rag_store.database.models import IngestionJob, WorkerHeartbeat
from rag_store.database.session import session_scope
from rag_store.embedding.client import EmbeddingClient
from rag_store.ingestion.jobs import claim_job, recover_expired_leases
from rag_store.monitoring import metrics
from rag_store.workers.pipeline import Pipeline

log = get_logger("worker")


class Worker:
    def __init__(self, settings: Settings, session_factory, *, kind: str, docling=None):
        self.settings = settings
        self.session_factory = session_factory
        self.kind = kind
        self.worker_id = settings.worker_id or f"{kind}-{socket.gethostname()}"
        embeddings = EmbeddingClient(settings, session_factory)
        self.pipeline = Pipeline(settings, session_factory, embeddings, docling=docling)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def serve(self) -> None:
        log.info("worker_started", component=self.kind, worker_id=self.worker_id)
        while not self._stop.is_set():
            if self.settings.maintenance.enabled:
                metrics.SCANNER_LEADER.set(0)
                self._stop.wait(self.settings.scanner.interval_seconds)
                continue
            worked = False
            try:
                worked = self.run_once()
            except Exception as exc:
                log.error("worker_iteration_failed", error_type=exc.__class__.__name__)
            if not worked:
                self._stop.wait(self.settings.jobs.poll_seconds)

    def run_once(self) -> bool:
        if self.settings.maintenance.enabled:
            return False
        with session_scope(self.session_factory) as session:
            recover_expired_leases(session)
            self._heartbeat_row(session)
            job = claim_job(
                session,
                worker_id=self.worker_id,
                predicate=self._predicate(),
                lease_seconds=self.settings.jobs.lease_seconds,
            )
            if job is None:
                return False
            job_id, token, job_type = job.id, job.fencing_token, job.job_type
        self._stop_beat = threading.Event()
        beater = threading.Thread(target=self._beat, args=(job_id, token), daemon=True)
        beater.start()
        try:
            if job_type == "convert":
                self.pipeline.convert(job_id, token, self.worker_id)
            elif job_type == "chunk_embed":
                self.pipeline.chunk_and_embed(job_id, token, self.worker_id)
            else:
                with session_scope(self.session_factory) as session:
                    from rag_store.ingestion.jobs import fail_or_retry

                    fail_or_retry(session, job_id, token, self.worker_id, f"unsupported job type {job_type}", base_seconds=30)
        except LeaseLost:
            log.info("lease_lost", job_id=str(job_id))
        finally:
            self._stop_beat.set()
        return True

    def _predicate(self):
        route = IngestionJob.payload["route"].astext
        if self.kind == "docling":
            return and_(IngestionJob.job_type == "convert", route == "docling")
        return or_(
            and_(IngestionJob.job_type == "convert", route == "lightweight"),
            IngestionJob.job_type == "chunk_embed",
        )

    def _heartbeat_row(self, session: Session) -> None:
        row = session.get(WorkerHeartbeat, self.worker_id)
        now = datetime.now(timezone.utc)
        if row is None:
            session.add(
                WorkerHeartbeat(
                    worker_id=self.worker_id,
                    component=self.kind,
                    hostname=socket.gethostname(),
                    pid=0,
                    last_seen=now,
                    details={},
                )
            )
        else:
            row.last_seen = now
            row.component = self.kind

    def _beat(self, job_id, token) -> None:
        while not self._stop_beat.wait(self.settings.jobs.heartbeat_seconds):
            try:
                with session_scope(self.session_factory) as session:
                    from rag_store.ingestion.jobs import heartbeat

                    heartbeat(session, job_id, token, self.worker_id, self.settings.jobs.lease_seconds)
            except LeaseLost:
                return
            except Exception:
                return
