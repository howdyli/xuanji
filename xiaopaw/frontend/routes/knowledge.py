"""Knowledge-base API route handlers.

CRUD for knowledge bases + documents, multipart upload with async ingestion,
document/chunk inspection and a debug hybrid-search endpoint. All handlers are
``check_auth`` gated and tenant-scoped: personal bases key on the caller's
``routing_key`` (owner_key), org bases on the caller's ``org_id`` with writes
restricted to admins. Tenant values are always derived from the authenticated
user — never from the request body.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

from xiaopaw.frontend.routes.helpers import (
    check_auth,
    get_current_user,
    get_routing_key_from_request,
)
from xiaopaw.knowledge.ingest import schedule_ingest
from xiaopaw.knowledge.retriever import retrieve, to_citations
from xiaopaw.knowledge.store import KnowledgeStore

logger = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 32 * 1024 * 1024  # 32 MiB per document
_ALLOWED_EXTS = {".pdf", ".docx", ".md", ".markdown", ".txt", ".text"}


# ── shared plumbing ──────────────────────────────────────────────────────────


def _err(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _get_store(request: web.Request) -> KnowledgeStore | None:
    pg_store = request.app.get("pg_store")
    if not pg_store or not getattr(pg_store, "_available", False):
        return None
    return KnowledgeStore(pg_store._dsn)


class _Tenant:
    """Authenticated tenant context resolved from the request (never the body)."""

    def __init__(self, request: web.Request) -> None:
        user = get_current_user(request) or {}
        self.owner_key = get_routing_key_from_request(request)
        self.org_id = user.get("org_id")
        self.is_admin = bool(user.get("is_admin"))
        self.username = user.get("username") or "unknown"

    def can_read(self, base: dict) -> bool:
        return KnowledgeStore.can_access(
            base, owner_key=self.owner_key, org_id=self.org_id
        )

    def can_write(self, base: dict) -> bool:
        if not self.can_read(base):
            return False
        # Org bases: writes (upload/delete) require an org administrator.
        if base["scope"] == "org":
            return self.is_admin
        return True


def _kb_storage_dir(request: web.Request, kb_id: str) -> Path:
    """Filesystem home for a base's uploaded source files (outside per-user ws)."""
    base = request.app.get("workspace_dir", "") or "."
    path = Path(base) / ".knowledge" / kb_id
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── Knowledge bases ──────────────────────────────────────────────────────────


async def handle_base_create(request: web.Request) -> web.Response:
    """POST /api/frontend/knowledge/bases — create a knowledge base."""
    if not check_auth(request):
        return _err("unauthorized", 401)
    store = _get_store(request)
    if store is None:
        return _err("database not available", 503)

    try:
        body = await request.json()
    except Exception:
        return _err("invalid JSON body", 422)

    name = (body.get("name") or "").strip()
    scope = (body.get("scope") or "personal").strip()
    description = (body.get("description") or "").strip()
    if not name:
        return _err("name is required", 422)
    if scope not in ("personal", "org"):
        return _err("scope must be 'personal' or 'org'", 422)

    tenant = _Tenant(request)
    if scope == "org":
        if tenant.org_id is None:
            return _err("no organization for current user", 403)
        if not tenant.is_admin:
            return _err("org knowledge base requires admin", 403)

    base = store.create_base(
        name=name,
        scope=scope,
        owner_key=tenant.owner_key,
        org_id=tenant.org_id if scope == "org" else None,
        description=description,
        created_by=tenant.username,
    )
    return web.json_response(base, status=201)


async def handle_base_list(request: web.Request) -> web.Response:
    """GET /api/frontend/knowledge/bases — list bases visible to the caller."""
    if not check_auth(request):
        return _err("unauthorized", 401)
    store = _get_store(request)
    if store is None:
        return web.json_response({"bases": []})
    tenant = _Tenant(request)
    bases = store.list_bases(owner_key=tenant.owner_key, org_id=tenant.org_id)
    return web.json_response({"bases": bases})


async def handle_base_delete(request: web.Request) -> web.Response:
    """DELETE /api/frontend/knowledge/bases/{kb_id} — delete a base (cascades)."""
    if not check_auth(request):
        return _err("unauthorized", 401)
    store = _get_store(request)
    if store is None:
        return _err("database not available", 503)

    kb_id = request.match_info["kb_id"]
    base = store.get_base(kb_id)
    if not base:
        return _err("not found", 404)
    tenant = _Tenant(request)
    if not tenant.can_read(base):
        return _err("forbidden", 403)
    if not tenant.can_write(base):
        return _err("org knowledge base requires admin", 403)

    store.delete_base(kb_id)
    return web.json_response({"success": True})


# ── Documents ────────────────────────────────────────────────────────────────


async def handle_document_upload(request: web.Request) -> web.Response:
    """POST /api/frontend/knowledge/bases/{kb_id}/documents — upload → 202."""
    if not check_auth(request):
        return _err("unauthorized", 401)
    store = _get_store(request)
    if store is None:
        return _err("database not available", 503)

    kb_id = request.match_info["kb_id"]
    base = store.get_base(kb_id)
    if not base:
        return _err("not found", 404)
    tenant = _Tenant(request)
    if not tenant.can_read(base):
        return _err("forbidden", 403)
    if not tenant.can_write(base):
        return _err("org knowledge base requires admin", 403)

    ctype = (request.content_type or "").lower()
    if "multipart" not in ctype:
        return _err("multipart/form-data required", 400)

    reader = await request.multipart()
    filename = ""
    mime = ""
    payload = b""
    async for part in reader:
        if part.name in ("file", "document"):
            filename = part.filename or ""
            mime = part.headers.get("Content-Type", "")
            buf = bytearray()
            while True:
                chunk = await part.read_chunk(64 * 1024)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > _MAX_UPLOAD_BYTES:
                    return _err("file too large", 413)
            payload = bytes(buf)
            break

    if not filename or not payload:
        return _err("no file provided", 422)

    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        return _err(f"unsupported file type: {ext or '(none)'}", 415)

    doc_id = store.create_document(
        kb_id=kb_id,
        title=Path(filename).name,
        source_type="file",
        source_uri="",  # set below once persisted
        mime=mime,
        byte_size=len(payload),
        created_by=tenant.username,
    )

    dest = _kb_storage_dir(request, kb_id) / f"{doc_id}{ext}"
    dest.write_bytes(payload)
    store.set_document_source_uri(doc_id, str(dest))

    schedule_ingest(store, doc_id)
    return web.json_response(
        {"id": doc_id, "status": "pending", "title": Path(filename).name},
        status=202,
    )


async def handle_document_list(request: web.Request) -> web.Response:
    """GET /api/frontend/knowledge/bases/{kb_id}/documents — list with status."""
    if not check_auth(request):
        return _err("unauthorized", 401)
    store = _get_store(request)
    if store is None:
        return _err("database not available", 503)

    kb_id = request.match_info["kb_id"]
    base = store.get_base(kb_id)
    if not base:
        return _err("not found", 404)
    tenant = _Tenant(request)
    if not tenant.can_read(base):
        return _err("forbidden", 403)

    return web.json_response({"documents": store.list_documents(kb_id)})


async def handle_document_detail(request: web.Request) -> web.Response:
    """GET /api/frontend/knowledge/documents/{doc_id} — detail + paged chunks."""
    if not check_auth(request):
        return _err("unauthorized", 401)
    store = _get_store(request)
    if store is None:
        return _err("database not available", 503)

    doc_id = request.match_info["doc_id"]
    doc = store.get_document(doc_id)
    if not doc:
        return _err("not found", 404)
    base = store.get_base(doc["kb_id"])
    tenant = _Tenant(request)
    if not base or not tenant.can_read(base):
        return _err("forbidden", 403)

    try:
        limit = min(200, max(1, int(request.query.get("limit", "50"))))
        offset = max(0, int(request.query.get("offset", "0")))
    except ValueError:
        return _err("invalid pagination", 422)

    chunks = store.get_document_chunks(doc_id, limit=limit, offset=offset)
    return web.json_response({"document": doc, "chunks": chunks})


async def handle_document_delete(request: web.Request) -> web.Response:
    """DELETE /api/frontend/knowledge/documents/{doc_id} — delete a document."""
    if not check_auth(request):
        return _err("unauthorized", 401)
    store = _get_store(request)
    if store is None:
        return _err("database not available", 503)

    doc_id = request.match_info["doc_id"]
    doc = store.get_document(doc_id)
    if not doc:
        return _err("not found", 404)
    base = store.get_base(doc["kb_id"])
    tenant = _Tenant(request)
    if not base or not tenant.can_read(base):
        return _err("forbidden", 403)
    if not tenant.can_write(base):
        return _err("org knowledge base requires admin", 403)

    # Best-effort remove the persisted source file.
    try:
        uri = doc.get("source_uri") or ""
        if uri and Path(uri).is_file():
            Path(uri).unlink(missing_ok=True)
    except Exception as exc:  # pragma: no cover - filesystem edge
        logger.warning("kb: failed to remove source file for %s: %s", doc_id, exc)

    store.delete_document(doc_id)
    return web.json_response({"success": True})


# ── Debug search ─────────────────────────────────────────────────────────────


async def handle_search(request: web.Request) -> web.Response:
    """POST /api/frontend/knowledge/search — debug hybrid retrieval + citations."""
    if not check_auth(request):
        return _err("unauthorized", 401)
    store = _get_store(request)
    if store is None:
        return _err("database not available", 503)

    try:
        body = await request.json()
    except Exception:
        return _err("invalid JSON body", 422)

    query = (body.get("query") or "").strip()
    kb_id = body.get("kb_id") or None
    if not query:
        return _err("query is required", 422)
    try:
        top_k = min(20, max(1, int(body.get("top_k", 6))))
    except (TypeError, ValueError):
        return _err("invalid top_k", 422)

    tenant = _Tenant(request)
    if kb_id:
        base = store.get_base(kb_id)
        if not base or not tenant.can_read(base):
            return _err("forbidden", 403)

    try:
        chunks = retrieve(
            store,
            query=query,
            owner_key=tenant.owner_key,
            org_id=tenant.org_id,
            kb_id=kb_id,
            top_k=top_k,
        )
    except Exception as exc:
        logger.exception("kb search failed")
        return _err(f"search failed: {exc}", 500)

    return web.json_response({"citations": to_citations(chunks)})


def register_knowledge_routes(app: web.Application) -> None:
    """Register knowledge-base API routes."""
    p = "/api/frontend/knowledge"
    app.router.add_post(f"{p}/bases", handle_base_create)
    app.router.add_get(f"{p}/bases", handle_base_list)
    app.router.add_delete(f"{p}/bases/{{kb_id}}", handle_base_delete)
    app.router.add_post(f"{p}/bases/{{kb_id}}/documents", handle_document_upload)
    app.router.add_get(f"{p}/bases/{{kb_id}}/documents", handle_document_list)
    app.router.add_get(f"{p}/documents/{{doc_id}}", handle_document_detail)
    app.router.add_delete(f"{p}/documents/{{doc_id}}", handle_document_delete)
    app.router.add_post(f"{p}/search", handle_search)
