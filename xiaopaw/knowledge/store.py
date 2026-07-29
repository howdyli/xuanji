"""PostgreSQL/pgvector persistence for the knowledge base.

Centralizes all SQL so route handlers, the ingest worker and the retriever
share one tenant-safe data layer. Every read/write that a user can trigger is
scoped by tenant (``owner_key`` for personal, ``org_id`` for org libraries);
callers must never pass tenant values sourced from an LLM.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class KnowledgeStore:
    """Thin data-access layer over the ``knowledge_*`` tables."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _conn(self):
        return psycopg2.connect(self._dsn)

    # ── Knowledge bases ──────────────────────────────────────────────────

    def create_base(
        self,
        *,
        name: str,
        scope: str,
        owner_key: str,
        org_id: int | None,
        description: str,
        created_by: str,
    ) -> dict:
        kb_id = _new_id("kb")
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO knowledge_bases
                   (id, name, scope, owner_key, org_id, description, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (kb_id, name, scope, owner_key, org_id, description, created_by),
            )
        return {"id": kb_id, "name": name, "scope": scope}

    def list_bases(self, *, owner_key: str, org_id: int | None) -> list[dict]:
        """List bases visible to a tenant: own personal + own org."""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT kb.*, COUNT(d.id) AS document_count
                       FROM knowledge_bases kb
                       LEFT JOIN knowledge_documents d ON d.kb_id = kb.id
                       WHERE (kb.scope = 'personal' AND kb.owner_key = %s)
                          OR (kb.scope = 'org' AND kb.org_id = %s AND %s IS NOT NULL)
                       GROUP BY kb.id
                       ORDER BY kb.updated_at DESC""",
                    (owner_key, org_id, org_id),
                )
                return [_iso(dict(r)) for r in cur.fetchall()]

    def get_base(self, kb_id: str) -> dict | None:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM knowledge_bases WHERE id = %s", (kb_id,))
                row = cur.fetchone()
                return _iso(dict(row)) if row else None

    def delete_base(self, kb_id: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_bases WHERE id = %s", (kb_id,))

    @staticmethod
    def can_access(base: dict, *, owner_key: str, org_id: int | None) -> bool:
        """Whether a tenant may read a base (write checks add admin on top)."""
        if base["scope"] == "personal":
            return base["owner_key"] == owner_key
        return org_id is not None and base["org_id"] == org_id

    # ── Documents ────────────────────────────────────────────────────────

    def create_document(
        self,
        *,
        kb_id: str,
        title: str,
        source_type: str,
        source_uri: str,
        mime: str,
        byte_size: int,
        created_by: str,
    ) -> str:
        doc_id = _new_id("doc")
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO knowledge_documents
                   (id, kb_id, title, source_type, source_uri, mime, byte_size,
                    status, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)""",
                (doc_id, kb_id, title, source_type, source_uri, mime, byte_size, created_by),
            )
        return doc_id

    def list_documents(self, kb_id: str) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, kb_id, title, source_type, source_uri, mime,
                              byte_size, status, error_msg, chunk_count,
                              created_by, created_at, updated_at
                       FROM knowledge_documents WHERE kb_id = %s
                       ORDER BY created_at DESC""",
                    (kb_id,),
                )
                return [_iso(dict(r)) for r in cur.fetchall()]

    def get_document(self, doc_id: str) -> dict | None:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM knowledge_documents WHERE id = %s", (doc_id,))
                row = cur.fetchone()
                return _iso(dict(row)) if row else None

    def get_document_chunks(self, doc_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, chunk_index, content, token_count, locator
                       FROM knowledge_chunks WHERE doc_id = %s
                       ORDER BY chunk_index ASC LIMIT %s OFFSET %s""",
                    (doc_id, limit, offset),
                )
                return [dict(r) for r in cur.fetchall()]

    def delete_document(self, doc_id: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_documents WHERE id = %s", (doc_id,))

    def set_document_source_uri(self, doc_id: str, source_uri: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE knowledge_documents
                   SET source_uri = %s, updated_at = NOW() WHERE id = %s""",
                (source_uri, doc_id),
            )

    def set_document_status(
        self, doc_id: str, status: str, *, error_msg: str = "", chunk_count: int | None = None
    ) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            if chunk_count is None:
                cur.execute(
                    """UPDATE knowledge_documents
                       SET status = %s, error_msg = %s, updated_at = NOW()
                       WHERE id = %s""",
                    (status, error_msg[:1000], doc_id),
                )
            else:
                cur.execute(
                    """UPDATE knowledge_documents
                       SET status = %s, error_msg = %s, chunk_count = %s, updated_at = NOW()
                       WHERE id = %s""",
                    (status, error_msg[:1000], chunk_count, doc_id),
                )

    def replace_chunks(self, doc_id: str, kb_id: str, rows: list[dict]) -> int:
        """Delete existing chunks for a doc and insert the new set atomically.

        Each row: {chunk_index, content, token_count, locator, embedding(list)}.
        """
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_chunks WHERE doc_id = %s", (doc_id,))
            for r in rows:
                cur.execute(
                    """INSERT INTO knowledge_chunks
                       (id, doc_id, kb_id, chunk_index, content, token_count,
                        locator, embedding, search_text)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        _new_id("chk"), doc_id, kb_id, r["chunk_index"],
                        r["content"], r["token_count"], r["locator"],
                        str(r["embedding"]), r["content"],
                    ),
                )
        return len(rows)

    def reset_stale_processing(self, timeout_minutes: int = 10) -> list[str]:
        """Reset documents stuck in ``processing`` past the timeout to ``pending``."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE knowledge_documents
                   SET status = 'pending', updated_at = NOW()
                   WHERE status = 'processing'
                     AND updated_at < NOW() - (%s || ' minutes')::interval
                   RETURNING id""",
                (str(timeout_minutes),),
            )
            return [r[0] for r in cur.fetchall()]

    def list_pending(self) -> list[str]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM knowledge_documents WHERE status = 'pending'")
            return [r[0] for r in cur.fetchall()]

    # ── Hybrid retrieval candidates ──────────────────────────────────────

    def search_candidates(
        self,
        *,
        query_vec: list[float],
        query_text: str,
        owner_key: str,
        org_id: int | None,
        kb_id: str | None = None,
        kb_ids: list[str] | None = None,
        limit: int,
    ) -> tuple[list[dict], list[dict]]:
        """Return (vector_ranked, text_ranked) chunk candidates, tenant-filtered.

        Tenant filter is applied in SQL and cannot be overridden by the caller's
        free-text inputs; ``kb_id``/``kb_ids`` only narrow within the visible
        set. ``kb_ids`` (multi-base allowlist, e.g. session bindings) takes
        priority over the legacy single ``kb_id``; empty list means no filter.
        """
        tenant_sql = (
            "((kb.scope = 'personal' AND kb.owner_key = %(owner_key)s) "
            "OR (kb.scope = 'org' AND %(org_id)s IS NOT NULL AND kb.org_id = %(org_id)s))"
        )
        effective_kb_ids = list(kb_ids) if kb_ids else ([kb_id] if kb_id else None)
        kb_sql = " AND c.kb_id = ANY(%(kb_ids)s)" if effective_kb_ids else ""
        params: dict[str, Any] = {
            "owner_key": owner_key,
            "org_id": org_id,
            "kb_ids": effective_kb_ids,
            "qvec": str(query_vec),
            "qtext": query_text,
            "limit": limit,
        }

        select = (
            "SELECT c.id, c.doc_id, c.kb_id, c.chunk_index, c.content, c.locator, "
            "d.title AS document_title "
            "FROM knowledge_chunks c "
            "JOIN knowledge_bases kb ON kb.id = c.kb_id "
            "JOIN knowledge_documents d ON d.id = c.doc_id "
        )

        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Tune HNSW ef_search for better recall at query time.
                cur.execute("SET LOCAL hnsw.ef_search = 100")

                cur.execute(
                    select
                    + f"WHERE {tenant_sql}{kb_sql} AND c.embedding IS NOT NULL "
                    + "ORDER BY c.embedding <=> %(qvec)s::vector ASC "
                    + "LIMIT %(limit)s",
                    params,
                )
                vector_rows = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    select
                    + f"WHERE {tenant_sql}{kb_sql} "
                    + "AND c.search_tsv @@ websearch_to_tsquery('simple', %(qtext)s) "
                    + "ORDER BY ts_rank(c.search_tsv, websearch_to_tsquery('simple', %(qtext)s)) DESC "
                    + "LIMIT %(limit)s",
                    params,
                )
                text_rows = [dict(r) for r in cur.fetchall()]

        return vector_rows, text_rows

    # ── Session bindings (schema only wired in P0) ───────────────────────

    def set_session_bases(self, session_id: str, kb_ids: list[str]) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM session_knowledge_bases WHERE session_id = %s", (session_id,))
            for kb_id in kb_ids:
                cur.execute(
                    """INSERT INTO session_knowledge_bases (session_id, kb_id)
                       VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                    (session_id, kb_id),
                )

    def get_session_bases(self, session_id: str) -> list[str]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT kb_id FROM session_knowledge_bases WHERE session_id = %s",
                (session_id,),
            )
            return [r[0] for r in cur.fetchall()]


def _iso(row: dict) -> dict:
    """Serialize timestamp columns to ISO strings for JSON responses."""
    for k in ("created_at", "updated_at"):
        if row.get(k) is not None and hasattr(row[k], "isoformat"):
            row[k] = row[k].isoformat()
    return row
