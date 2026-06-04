-- 玄机 pgvector schema
-- Requires: CREATE EXTENSION IF NOT EXISTS vector;

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
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_routing_key
    ON sessions (routing_key);

CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
    ON sessions (updated_at DESC);

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

