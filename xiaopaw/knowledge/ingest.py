"""Async ingestion pipeline: extract -> chunk -> embed -> upsert.

Runs in-process as fire-and-forget asyncio tasks. Blocking work (parsing,
embedding, DB) is offloaded to a thread. Document status in the DB is the
source of truth; a startup recovery pass re-queues anything left ``pending`` or
stuck ``processing``.
"""

from __future__ import annotations

import asyncio
import logging
import os

from xiaopaw.knowledge.adapters import AdapterError, DocumentSource, get_adapter
from xiaopaw.knowledge.chunker import chunk_text
from xiaopaw.knowledge.embedder import embed_texts

logger = logging.getLogger(__name__)

# Keep references so tasks are not garbage-collected mid-flight.
_INFLIGHT: set[asyncio.Task] = set()

_INGEST_SEMAPHORE = asyncio.Semaphore(3)
_INGEST_TIMEOUT = 300  # 5 minutes


def _ingest_sync(store, doc_id: str) -> None:
    """Synchronous ingestion body (run via a thread executor)."""
    doc = store.get_document(doc_id)
    if doc is None:
        logger.warning("ingest: document %s vanished", doc_id)
        return

    store.set_document_status(doc_id, "processing")
    try:
        source = DocumentSource(
            source_type=doc["source_type"],
            uri=doc["source_uri"],
            title=doc["title"],
            mime=doc.get("mime", ""),
        )
        result = get_adapter(source).extract(source)

        chunk_rows: list[dict] = []
        strategy = os.environ.get("XIAOPAW_CHUNK_STRATEGY", "recursive")
        for section in result.sections:
            for ch in chunk_text(section.text, strategy=strategy, base_locator=section.locator):
                chunk_rows.append(
                    {
                        "chunk_index": len(chunk_rows),
                        "content": ch.content,
                        "token_count": ch.token_count,
                        "locator": ch.locator,
                    }
                )

        if not chunk_rows:
            raise AdapterError("no chunks produced from document")

        vectors = embed_texts([r["content"] for r in chunk_rows])
        for row, vec in zip(chunk_rows, vectors):
            row["embedding"] = vec

        count = store.replace_chunks(doc_id, doc["kb_id"], chunk_rows)
        store.set_document_status(doc_id, "ready", chunk_count=count)
        logger.info("ingest: document %s ready (%d chunks)", doc_id, count)
    except Exception as exc:
        logger.exception("ingest: document %s failed", doc_id)
        store.set_document_status(doc_id, "failed", error_msg=str(exc))


async def ingest_document(store, doc_id: str) -> None:
    """Ingest one document with concurrency control and timeout."""
    async with _INGEST_SEMAPHORE:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(_ingest_sync, store, doc_id),
                timeout=_INGEST_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error("ingest: document %s timed out after %ds", doc_id, _INGEST_TIMEOUT)
            store.set_document_status(
                doc_id, "failed", error_msg=f"ingestion timed out after {_INGEST_TIMEOUT}s"
            )


def schedule_ingest(store, doc_id: str) -> None:
    """Fire-and-forget ingestion; safe to call from a request handler."""
    task = asyncio.create_task(ingest_document(store, doc_id), name=f"kb-ingest-{doc_id}")
    _INFLIGHT.add(task)
    task.add_done_callback(_INFLIGHT.discard)


async def recover_pending(store, *, stale_timeout_minutes: int = 10) -> int:
    """Startup pass: reset stuck ``processing`` docs and re-queue ``pending`` ones."""
    reset = await asyncio.to_thread(store.reset_stale_processing, stale_timeout_minutes)
    if reset:
        logger.info("ingest: reset %d stale processing documents", len(reset))
    pending = await asyncio.to_thread(store.list_pending)
    for doc_id in pending:
        schedule_ingest(store, doc_id)
    if pending:
        logger.info("ingest: re-queued %d pending documents", len(pending))
    return len(pending)
