-- 玄机 pgvector schema
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    routing_key     TEXT NOT NULL,
    user_message    TEXT NOT NULL,
    assistant_reply TEXT NOT NULL,
    summary         TEXT NOT NULL,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    turn_ts         BIGINT NOT NULL,
    summary_vec     vector(1024),
    message_vec     vector(1024),
    search_text     TEXT NOT NULL DEFAULT '',
    search_tsv      TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', search_text)) STORED
);

-- HNSW indexes for vector search
CREATE INDEX IF NOT EXISTS idx_memories_summary_vec
    ON memories USING hnsw (summary_vec vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_memories_message_vec
    ON memories USING hnsw (message_vec vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_memories_search_tsv
    ON memories USING gin (search_tsv);

-- Tag search
CREATE INDEX IF NOT EXISTS idx_memories_tags
    ON memories USING gin (tags);

-- Routing key isolation
CREATE INDEX IF NOT EXISTS idx_memories_routing_key
    ON memories (routing_key);

-- Time-based queries
CREATE INDEX IF NOT EXISTS idx_memories_created_at
    ON memories (created_at DESC);

-- ============================================================
-- Frontend: conversations & sessions tables (ElectricSQL compat)
-- ElectricSQL requires tables with PRIMARY KEY and logical replication
-- ============================================================

CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,    -- msg_id
    session_id  TEXT NOT NULL,
    routing_key TEXT NOT NULL,
    role        TEXT NOT NULL,       -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_session_id
    ON conversations (session_id);

CREATE INDEX IF NOT EXISTS idx_conversations_created_at
    ON conversations (created_at ASC);

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    routing_key   TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    message_count INT NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'completed',
    team_id       INTEGER,
    shared_by     TEXT NOT NULL DEFAULT '',
    share_permission TEXT NOT NULL DEFAULT 'view',
    org_id        BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent migration for pre-existing sessions tables (multi-tenant).
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS org_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_sessions_routing_key
    ON sessions (routing_key);

CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
    ON sessions (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_team_id
    ON sessions (team_id);

CREATE INDEX IF NOT EXISTS idx_sessions_org_id
    ON sessions (org_id);

-- ============================================================
-- Skills management: metadata for builtin + user-uploaded skills
-- File system stores SKILL.md / scripts; DB stores enable state,
-- author/version metadata, and per-session skill assignments.
-- ============================================================

CREATE TABLE IF NOT EXISTS skills (
    name           TEXT PRIMARY KEY,                 -- kebab-case skill identifier
    source         TEXT NOT NULL,                    -- 'builtin' | 'user'
    type           TEXT NOT NULL DEFAULT 'task',     -- 'task' | 'reference'
    description    TEXT NOT NULL DEFAULT '',
    author         TEXT NOT NULL DEFAULT '',
    version        TEXT NOT NULL DEFAULT '1.0.0',
    enabled        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skills_source
    ON skills (source);

CREATE INDEX IF NOT EXISTS idx_skills_enabled
    ON skills (enabled);

-- Per-session skill subset selection. Empty rows = use all enabled skills.
CREATE TABLE IF NOT EXISTS session_skills (
    session_id  TEXT NOT NULL,
    skill_name  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, skill_name)
);

CREATE INDEX IF NOT EXISTS idx_session_skills_session_id
    ON session_skills (session_id);

-- ============================================================
-- Skill market: cached remote-repository index for installable skills.
-- Populated by MarketSync (every 6h via background task) from Vercel
-- Skills + ClawHub. manifest_json stores the original adapter payload
-- so protocol drift can be diagnosed without re-fetching.
-- ============================================================

CREATE TABLE IF NOT EXISTS skill_market (
    name           TEXT PRIMARY KEY,
    source_type    TEXT NOT NULL CHECK (source_type IN ('vercel', 'clawhub')),
    version        TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    author         TEXT NOT NULL DEFAULT '',
    repo_url       TEXT NOT NULL DEFAULT '',
    install_url    TEXT NOT NULL,
    manifest_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at     TIMESTAMPTZ,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skill_market_source
    ON skill_market (source_type);

CREATE INDEX IF NOT EXISTS idx_skill_market_fetched
    ON skill_market (fetched_at DESC);

-- ============================================================
-- Users: PostgreSQL mirror for community FK references.
-- Auth source-of-truth remains in SQLite (auth.db); this table
-- is populated by sync or manual insert so that community_skills,
-- skill_reviews, and user_favorites can enforce referential integrity.
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username
    ON users (username);

-- ============================================================
-- Community skills: user-published skills for the skill market.
-- Supports rating, search, category filtering, and install tracking.
-- ============================================================

CREATE TABLE IF NOT EXISTS community_skills (
    id            BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    publisher     TEXT NOT NULL REFERENCES users(username),
    category      TEXT NOT NULL DEFAULT 'general',
    tags          TEXT[] DEFAULT '{}',
    description   TEXT NOT NULL,
    version       TEXT NOT NULL DEFAULT '1.0.0',
    icon_url      TEXT,
    screenshots   TEXT[] DEFAULT '{}',
    repo_url      TEXT,
    install_url   TEXT NOT NULL,
    archive_hash  TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','approved','rejected','suspended')),
    license       TEXT DEFAULT 'MIT',
    rating_avg    NUMERIC(2,1) DEFAULT 0.0,
    rating_count  INTEGER DEFAULT 0,
    install_count INTEGER DEFAULT 0,
    featured      BOOLEAN DEFAULT FALSE,
    manifest_json JSONB DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_community_status
    ON community_skills (status);

CREATE INDEX IF NOT EXISTS idx_community_category
    ON community_skills (category);

CREATE INDEX IF NOT EXISTS idx_community_rating
    ON community_skills (rating_avg DESC);

CREATE INDEX IF NOT EXISTS idx_community_installs
    ON community_skills (install_count DESC);

CREATE INDEX IF NOT EXISTS idx_community_search
    ON community_skills
    USING gin (to_tsvector('simple', coalesce(name,'') || ' ' || coalesce(description,'')));

-- Moderation audit fields (idempotent migration for pre-existing tables).
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS reviewed_by  TEXT;
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS reviewed_at  TIMESTAMPTZ;
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS review_note  TEXT NOT NULL DEFAULT '';

-- Version-update moderation: staged install-artifact changes awaiting re-review.
-- Live version/install_url/archive_hash/status keep serving the approved build
-- while pending_* holds the submitted artifact update until an admin decides.
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_version       TEXT;
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_install_url   TEXT;
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_archive_hash  TEXT;
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS has_pending_update    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_submitted_at  TIMESTAMPTZ;

-- Private (org-scoped) registry: 'public' skills are globally visible; 'private'
-- skills are visible/installable only within their owning organization
-- (owner_org_id). Private skills auto-approve on publish (intra-org trust).
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS visibility    TEXT NOT NULL DEFAULT 'public';
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS owner_org_id  BIGINT;

CREATE INDEX IF NOT EXISTS idx_community_visibility
    ON community_skills (visibility, owner_org_id);

-- ============================================================
-- Skill reviews: per-user ratings and comments for community skills.
-- One review per (skill, user) pair enforced by UNIQUE constraint.
-- ============================================================

CREATE TABLE IF NOT EXISTS skill_reviews (
    id            BIGSERIAL PRIMARY KEY,
    skill_name    TEXT NOT NULL REFERENCES community_skills(name),
    user_id       TEXT NOT NULL REFERENCES users(username),
    rating        INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment       TEXT DEFAULT '',
    version       TEXT,
    helpful_count INTEGER DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (skill_name, user_id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_skill
    ON skill_reviews (skill_name, created_at DESC);

-- ============================================================
-- Skill categories: dictionary table for community skill classification.
-- ============================================================

CREATE TABLE IF NOT EXISTS skill_categories (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    icon       TEXT,
    sort_order INTEGER DEFAULT 0
);

-- Seed default categories
INSERT INTO skill_categories (id, name, icon, sort_order) VALUES
    ('document', '文档处理', '📄', 1),
    ('data',     '数据分析', '📊', 2),
    ('code',     '代码开发', '💻', 3),
    ('creative', '创意设计', '🎨', 4),
    ('system',   '系统管理', '⚙️',  5),
    ('search',   '信息检索', '🔍', 6),
    ('general',  '通用工具', '🔧', 7);

-- ============================================================
-- User favorites: bookmarked community skills per user.
-- ============================================================

CREATE TABLE IF NOT EXISTS user_favorites (
    user_id    TEXT NOT NULL REFERENCES users(username),
    skill_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, skill_name)
);

-- ============================================================
-- Agent 协作活动表 —— 记录 Agent 执行元数据（可视化用）
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_activities (
    id            BIGSERIAL PRIMARY KEY,
    session_id    TEXT NOT NULL,
    turn_id       TEXT NOT NULL DEFAULT '',
    event_type    TEXT NOT NULL,
    agent_role    TEXT NOT NULL DEFAULT '',
    tool_name     TEXT NOT NULL DEFAULT '',
    skill_name    TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'active',
    duration_ms   INTEGER DEFAULT 0,
    metadata      JSONB DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_activities_session
    ON agent_activities (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_activities_turn
    ON agent_activities (turn_id);

-- ============================================================
-- Notifications: per-user pull-based notifications (e.g. skill
-- moderation outcomes). Recipient is a username; consumers poll
-- via the frontend API. No cross-channel push.
-- ============================================================
CREATE TABLE IF NOT EXISTS notifications (
    id          BIGSERIAL PRIMARY KEY,
    recipient   TEXT NOT NULL,            -- username
    type        TEXT NOT NULL,            -- 'skill_approved' | 'skill_rejected'
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {skill_name, reviewer, note, is_update}
    read        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient
    ON notifications (recipient, read, created_at DESC);

-- ============================================================
-- Knowledge Base (RAG): personal + org document libraries.
-- Documents are uploaded/imported, then asynchronously parsed,
-- chunked and embedded (text-embedding-v3, dim=1024) into
-- knowledge_chunks for hybrid (vector + full-text) retrieval.
-- Tenant isolation: personal libs filter by owner_key (routing_key),
-- org libs by org_id. Mirrors the `memories` HNSW + tsvector pattern.
-- ============================================================

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id          TEXT PRIMARY KEY,                     -- kb-<uuid>
    name        TEXT NOT NULL,
    scope       TEXT NOT NULL CHECK (scope IN ('personal','org')),
    owner_key   TEXT NOT NULL DEFAULT '',             -- routing_key (personal ownership)
    org_id      BIGINT,                                -- org ownership
    description TEXT NOT NULL DEFAULT '',
    created_by  TEXT NOT NULL DEFAULT '',              -- username
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_owner ON knowledge_bases (scope, owner_key);
CREATE INDEX IF NOT EXISTS idx_kb_org   ON knowledge_bases (scope, org_id);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id          TEXT PRIMARY KEY,                     -- doc-<uuid>
    kb_id       TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('file','url','feishu')),
    source_uri  TEXT NOT NULL DEFAULT '',              -- file path / URL / feishu token
    mime        TEXT NOT NULL DEFAULT '',
    byte_size   BIGINT NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','processing','ready','failed')),
    error_msg   TEXT NOT NULL DEFAULT '',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kdoc_kb     ON knowledge_documents (kb_id);
CREATE INDEX IF NOT EXISTS idx_kdoc_status ON knowledge_documents (status);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id          TEXT PRIMARY KEY,                     -- chk-<uuid>
    doc_id      TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    kb_id       TEXT NOT NULL,                         -- denormalized for per-kb filtering
    chunk_index INTEGER NOT NULL,
    content     TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    locator     TEXT NOT NULL DEFAULT '',              -- 'page=3' / 'heading=...' (citation anchor)
    embedding   vector(1024),
    search_text TEXT NOT NULL DEFAULT '',
    search_tsv  TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', search_text)) STORED,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kchunk_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_kchunk_tsv ON knowledge_chunks USING gin (search_tsv);
CREATE INDEX IF NOT EXISTS idx_kchunk_kb  ON knowledge_chunks (kb_id);
CREATE INDEX IF NOT EXISTS idx_kchunk_doc ON knowledge_chunks (doc_id);

-- Session <-> knowledge base binding (enables auto pre-retrieval in P1).
CREATE TABLE IF NOT EXISTS session_knowledge_bases (
    session_id TEXT NOT NULL,
    kb_id      TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, kb_id)
);

CREATE INDEX IF NOT EXISTS idx_skb_session ON session_knowledge_bases (session_id);

