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
    name            TEXT      NOT NULL UNIQUE,
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
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Phase 2: GOAP plan tracking (auto-exec opt-in)
    plan_hash           TEXT,                  -- SHA-256 of normalised plan text (NULL for non-plan entries)
    plan_approved_count INTEGER   DEFAULT 0,   -- times user explicitly confirmed this plan
    auto_executable     INTEGER   DEFAULT 0,   -- 1 after user explicitly opts in (never set automatically)
    success_rate        REAL      DEFAULT 1.0  -- fraction of successful executions
);

CREATE INDEX IF NOT EXISTS idx_learnings_plan_hash ON agent_learnings(plan_hash);

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
-- Cognitive Continuity — Memory threads (S023–S028)
-- ============================================================
CREATE TABLE IF NOT EXISTS cognitive_threads (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    content TEXT NOT NULL,
    summary TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activated_at TIMESTAMP,
    activation_count INTEGER DEFAULT 0,
    importance_score REAL DEFAULT 0.5,
    reactivation_score REAL DEFAULT 0,
    density_context REAL,
    tags TEXT,
    source_exchange_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interaction_density (
    id TEXT PRIMARY KEY,
    day TEXT UNIQUE,
    exchange_count INTEGER DEFAULT 0,
    avg_depth_score REAL DEFAULT 0.0,
    session_id TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS initiative_log (
    id TEXT PRIMARY KEY,
    thread_id TEXT,
    type TEXT DEFAULT 'soft_reactivation',
    density_snapshot REAL,
    context_anchor TEXT,
    accepted INTEGER DEFAULT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
-- cognitive_threads — Latent cognitive threads (cross-session continuity)
-- Stored in global.db for persistence across sessions.
-- State machine: open → resurfaced → consumed | dormant
-- ============================================================
CREATE TABLE IF NOT EXISTS cognitive_threads (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT      NOT NULL,
    content              TEXT      NOT NULL,
    summary              TEXT,
    source_exchange_at   TEXT,
    importance_score     REAL      DEFAULT 0.5,
    status               TEXT      DEFAULT 'open',  -- open|resurfaced|consumed|dormant
    activation_count     INTEGER   DEFAULT 0,
    ignored_count        INTEGER   DEFAULT 0,
    last_activated_at    TEXT,
    rescored_at          TEXT,
    created_at           TEXT      DEFAULT (datetime('now')),
    tags                 TEXT      DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_cthreads_status   ON cognitive_threads(status);
CREATE INDEX IF NOT EXISTS idx_cthreads_score    ON cognitive_threads(importance_score);
CREATE INDEX IF NOT EXISTS idx_cthreads_session  ON cognitive_threads(session_id);

-- ============================================================
-- interaction_density — Daily exchange count for pattern modulation
-- Feeds SocialOrchestrator._select_allowed_patterns()
-- ============================================================
CREATE TABLE IF NOT EXISTS interaction_density (
    day              TEXT PRIMARY KEY,          -- date('now') → 'YYYY-MM-DD'
    exchange_count   INTEGER  DEFAULT 0,
    avg_depth_score  REAL     DEFAULT 0.0
);

-- ============================================================
-- initiative_simulation_log — Phase 0 observation log
-- Records what WOULD have been sent (without actually sending anything).
-- Used for qualitative calibration of thresholds before activation.
-- ============================================================
CREATE TABLE IF NOT EXISTS initiative_simulation_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id           INTEGER,
    would_have_sent_at  TEXT,
    thread_summary      TEXT,
    allowed_patterns    TEXT,          -- JSON array of allowed patterns at that moment
    suppressed_reason   TEXT,          -- "user_active"|"cooldown"|"observation_mode"|"no_idle"
    created_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- initiative_log — CIG Phase 1 delivery log
-- Records each soft-reactivation proposed to the user.
-- accepted = 1 if explicit positive signal received, NULL if unknown.
-- NULL is the correct default: absence of reply ≠ rejection.
-- Auto-calibration only counts rows WHERE accepted IS NOT NULL.
-- ============================================================
CREATE TABLE IF NOT EXISTS initiative_log (
    id               TEXT PRIMARY KEY,   -- uuid4
    thread_id        TEXT,
    type             TEXT DEFAULT 'soft_reactivation',
    density_snapshot REAL,
    accepted         INTEGER DEFAULT NULL,  -- NULL=unknown, 1=accepted, 0=rejected
    context_anchor   TEXT,
    timestamp        TEXT DEFAULT (datetime('now'))
);

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

-- ============================================================
-- mcp_cache — MCP tool call cache (TTL per tool type)
-- ============================================================
CREATE TABLE IF NOT EXISTS mcp_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name   TEXT      NOT NULL,
    args_hash   TEXT      NOT NULL,
    response    TEXT      NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP,            -- NULL = never expires
    hit_count   INTEGER   DEFAULT 1,
    UNIQUE(tool_name, args_hash)
);

CREATE INDEX IF NOT EXISTS idx_mcp_cache_expiry ON mcp_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_mcp_cache_tool   ON mcp_cache(tool_name);
