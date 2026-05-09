-- ============================================================
-- global.db — Persistent memory (preferences, tools, skills)
-- ============================================================
CREATE TABLE IF NOT EXISTS config (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name     TEXT      NOT NULL,
    success       INTEGER   NOT NULL DEFAULT 0,
    cost_eur      REAL               DEFAULT 0.0,
    tokens_used   INTEGER            DEFAULT 0,
    context_hash  TEXT,
    timestamp     TIMESTAMP          DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skills (
    id              TEXT PRIMARY KEY,
    name            TEXT      NOT NULL,
    description     TEXT,
    prompt_template TEXT,
    tool            TEXT,
    usage_count     INTEGER   DEFAULT 0,
    last_used       TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pattern_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT      NOT NULL,
    bucket    TEXT      NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- agent_learnings — Agent's experience memory (learning from successes/failures)
-- Records task sequences and outcomes for autonomous learning
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_learnings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    intention_pattern   TEXT      NOT NULL,    -- Description of task (e.g., "analyze logs for errors")
    tool_sequence       TEXT      NOT NULL,    -- JSON array: [{tool, args, success}, ...]
    success             BOOLEAN   NOT NULL DEFAULT 1,
    outcome_summary     TEXT,                  -- What happened (e.g., "3 errors found")
    lesson              TEXT,                  -- What to remember for next time
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_learnings_intention ON agent_learnings(intention_pattern);
CREATE INDEX IF NOT EXISTS idx_learnings_success ON agent_learnings(success);
CREATE INDEX IF NOT EXISTS idx_learnings_created ON agent_learnings(created_at);

-- ============================================================
-- project.db — Project context (docs, history)
-- ============================================================
CREATE TABLE IF NOT EXISTS docs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    path       TEXT      NOT NULL,
    topic      TEXT,
    type       TEXT,
    content    TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    path,
    topic,
    content,
    content='docs',
    content_rowid='id'
);

-- ============================================================
-- session.db — Transient state (current context, active tasks)
-- ============================================================
CREATE TABLE IF NOT EXISTS session_context (
    key   TEXT PRIMARY KEY,
    value TEXT,
    ttl   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS active_tasks (
    id          TEXT PRIMARY KEY,
    description TEXT,
    status      TEXT      DEFAULT 'pending',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    role        TEXT      NOT NULL,   -- 'user' | 'arke'
    content     TEXT      NOT NULL,
    model_used  TEXT,                 -- NULL for non-LLM responses
    timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    content='chat_history',
    content_rowid='id'
);

-- ============================================================
-- FTS5 Triggers — synchronisation automatique chat_history → memory_fts
-- Chaque INSERT/DELETE dans chat_history met à jour l'index FTS5.
-- Source : recommandation communauté SQLite (Option B)
-- ============================================================
CREATE TRIGGER IF NOT EXISTS chat_history_ai AFTER INSERT ON chat_history BEGIN
    INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS chat_history_ad AFTER DELETE ON chat_history BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

-- ============================================================
-- cache.db — LLM optimisation (cached responses, TTL)
-- ============================================================
CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash TEXT PRIMARY KEY,
    response    TEXT      NOT NULL,
    model       TEXT      NOT NULL,
    tokens_used INTEGER   DEFAULT 0,
    cost_eur    REAL      DEFAULT 0.0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP
);
