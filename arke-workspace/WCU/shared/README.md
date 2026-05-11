# 🧠 shared/ — Restitution & Output Layer

## Purpose

Transformation of Arke orchestrator outputs into human-readable, user-facing format.

**Key principle**: This is where Arke writes results. Users read, rarely write manually.

---

## Structure

```
shared/
├── session-summaries/     # Structured session recaps
├── decision-recaps/       # Synthesized decisions
├── cognitive-threads/     # Cross-session continuity
├── generated-insights/    # Arke-extracted insights
└── user-facing-logs/      # Simplified, interpreted logs
```

---

## Submodule Descriptions

### 📋 session-summaries/

**Structured summaries of work sessions.**

Content:
- Session date, duration, participants
- Main work completed
- Decisions made
- Blockers encountered
- Next steps

Example: `2026-05-11_SESSION_022_SUMMARY.md`

**Written by**: Arke orchestrator (via `WRITE_SESSION_SUMMARY` intent)
**Read by**: User (for continuity, tracking)

---

### 🎯 decision-recaps/

**Synthesized decisions from discussions.**

Content:
- Decision title
- Context/problem
- What was decided
- Rationale
- Consequences
- Date decided

Example: `2026-05-11_DECISION_TELEGRAM_SYNC_ARCHITECTURE.md`

**Written by**: Arke (via `LOG_DECISION` intent, or user manually)
**Read by**: User (for decision history)

---

### 🔗 cognitive-threads/

**Cross-session continuity and recurring themes.**

Content:
- Thread name (e.g., "Performance Optimization", "User Auth")
- Related sessions
- Key insights
- Current status
- Open questions

Example: `cognitive-thread_performance-optimization.md`

**Written by**: Arke ThreadExtractor (cross-session analysis)
**Read by**: User (for context on ongoing themes)

---

### 💡 generated-insights/

**Arke-extracted insights and learnings.**

Content:
- Insight title
- Supporting evidence
- Applicability
- Recommended actions
- Confidence level

Example: `2026-05-11_INSIGHT_SESSION_CLUSTERING_PATTERN.md`

**Written by**: Arke (via `EXPORT_SHARED_INSIGHT` intent)
**Read by**: User (for knowledge synthesis)

---

### 📊 user-facing-logs/

**Simplified, interpreted logs (not system logs).**

Content:
- Event description
- Timestamp
- Severity (info/warning/attention)
- Action taken
- Resolution (if applicable)

Example: `2026-05-11_LOGS_DAILY_SUMMARY.md`

**Written by**: Arke (via `LOG_USER_FACING_EVENT` intent)
**Read by**: User (for audit trail, understanding)

---

## What Does NOT Go Here

❌ **System logs**:
- SQLite activity
- Agent runtime state
- Internal orchestrator traces
- Memory layer activity

→ These stay in database and system logs, not here.

❌ **Raw orchestrator outputs**:
- Unstructured JSON
- Intermediate computation results
- Raw API responses

→ These should be transformed first.

❌ **Manual project documentation**:
- Use `/projects/TEMP/` instead

---

## Content Guidelines

✅ **Must be**:
- Human-readable
- User-focused (no technical jargon unless necessary)
- Timestamped
- Structured (markdown, clear formatting)
- Actionable

✅ **Should include**:
- Title/headline
- Date/time
- Context (why this matters)
- Main content
- Next steps (if applicable)

---

## Naming Conventions

Suggested formats:

**By type**:
- `YYYY-MM-DD_SESSION_NNN_SUMMARY.md`
- `YYYY-MM-DD_DECISION_[TITLE].md`
- `cognitive-thread_[TOPIC].md`
- `YYYY-MM-DD_INSIGHT_[TOPIC].md`
- `YYYY-MM-DD_LOGS_[CONTEXT].md`

**Examples**:
- `2026-05-11_SESSION_022_SUMMARY.md`
- `2026-05-11_DECISION_WCU_IMPLEMENTATION.md`
- `cognitive-thread_arke-cognitive-continuity.md`
- `2026-05-11_INSIGHT_SESSION_CLUSTERING.md`
- `2026-05-11_LOGS_DAILY_SUMMARY.md`

---

## Lifecycle

1. **Creation**: Arke writes (via orchestrator intents) or user creates manually
2. **Review**: User reads, provides feedback (optional)
3. **Reference**: Used for context in future sessions
4. **Archive**: Move to projects/TEMP/archive/ when no longer actively referenced

---

## Orchestrator Integration

Arke writes to `shared/` through these standard intents:

- `WRITE_SESSION_SUMMARY` → session-summaries/
- `LOG_DECISION` → decision-recaps/
- `EXPORT_SHARED_INSIGHT` → generated-insights/
- `LOG_USER_FACING_EVENT` → user-facing-logs/
- `UPDATE_COGNITIVE_THREAD` → cognitive-threads/

See [WORKSPACE_ORCHESTRATION.md](../WORKSPACE_ORCHESTRATION.md) for full intent reference.

---

## Related

- [../README.md](../README.md) — WCU overview
- [../projects/TEMP/README.md](../projects/TEMP/README.md) — Where user-created project docs go
- [../mobile-notes/README.md](../mobile-notes/README.md) — Capture layer (input)

---

*Last updated: 2026-05-11*
