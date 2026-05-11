# 📁 projects/TEMP/ — Project Structuration Layer

## Purpose

User-driven cognitive organization of projects — all documentation, planning, decisions, and tracking live here.

**Key principle**: This is where you think about and document projects (not where code lives — that's `/code/`).

---

## Structure

```
projects/
└── TEMP/                  # Project namespace (can expand to TEMP, ACTIVE, ARCHIVED, etc.)
    ├── core-overview/     # Vision, principles, alignment
    ├── core-planning/     # Roadmap, milestones, sprints
    ├── core-architecture/ # System design, models, contracts
    ├── dev-sessions/      # Work session logs & continuity
    ├── dev-tracking/      # Progress tracking, checklists, blockers
    ├── meta-decisions/    # Architecture Decision Records (ADRs)
    ├── meta-feedback/     # User feedback, iterations, learnings
    ├── ops-logs/          # Project-level operational events
    ├── ext-extensions/    # Integrations, plugins, automations
    ├── resources/         # Shared resources (images, data, etc.)
    └── archive/           # Inactive project docs
```

---

## Submodule Descriptions

### 📋 core-overview/

**Vision, principles, alignment.**

Examples:
- `PROJECT_CHARTER.md` — What is this project? Why?
- `VISION.md` — Long-term vision
- `PRINCIPLES.md` — Design principles, non-negotiables
- `SUCCESS_CRITERIA.md` — How do we know it works?
- `ALIGNMENT.md` — How does this fit with other projects?

**When to update**: Project inception, major pivots, annual reviews

---

### 🗺️ core-planning/

**Roadmap, milestones, sprints.**

Examples:
- `ROADMAP.md` — Quarterly/yearly plan
- `MILESTONES.md` — Major checkpoints
- `SPRINT_001.md` — Current sprint (backlog, goals)
- `Q2-2026-PLAN.md` — Quarterly planning

**When to update**: Sprint planning, roadmap reviews

---

### 🏗️ core-architecture/

**System design, models, contracts.**

Examples:
- `ARCHITECTURE.md` — System design, components, flows
- `DATA_MODEL.md` — Database schema, entities
- `API_SPEC.md` — API contracts
- `COGNITIVE_CONTRACT.md` — Agent/system invariants (if applicable)
- `DEPLOYMENT_MODEL.md` — How is this deployed?

**When to update**: Major design decisions, tech pivots

---

### 📝 dev-sessions/

**Work session logs & continuity.**

Examples:
- `SESSION_001_KICKOFF.md` — First session
- `SESSION_015_TELEGRAM_INTEGRATION.md` — Feature work
- `BILAN_FINAL_SESSION_021.md` — Session recap

**When to update**: After each work session

---

### ✅ dev-tracking/

**Progress tracking, checklists, blockers.**

Examples:
- `PROGRESS.md` — Overall progress (% complete)
- `CHECKLISTS.md` — Feature checklists, tasks
- `BLOCKERS.md` — Current issues, risks
- `BURNDOWN.md` — Sprint burndown (if agile)
- `BUG_TRACKER.md` — Known bugs, fixes

**When to update**: Daily/weekly during active work

---

### 🎯 meta-decisions/

**Architecture Decision Records (ADRs).**

Examples:
- `ADR-001-CHOOSE_FRAMEWORK.md` — Why React vs Vue?
- `ADR-002-DATABASE_CHOICE.md` — Why SQLite vs PostgreSQL?
- `ADR-003-API_STRUCTURE.md` — REST vs GraphQL?

**Format**:
```
# ADR-XXX: [Decision Title]

## Context
[Situation requiring decision]

## Decision
[What we decided]

## Rationale
[Why this decision]

## Consequences
[Positive/negative outcomes]
```

**When to update**: When making architectural choices

---

### 💬 meta-feedback/

**User feedback, iterations, learnings.**

Examples:
- `USER_FEEDBACK_Q2.md` — Collected feedback
- `RETROSPECTIVE_SPRINT_001.md` — What went well/wrong?
- `LEARNINGS_PHASE_1.md` — Key lessons
- `IMPROVEMENTS_BACKLOG.md` — Ideas for iteration

**When to update**: End of phase, user testing sessions

---

### 📊 ops-logs/

**Project-level operational events (not system logs).**

Examples:
- `DEPLOYMENTS.md` — When deployed to staging/prod
- `INCIDENTS.md` — Major incidents, resolutions
- `MAINTENANCE.md` — Maintenance windows, upgrades
- `EXTERNAL_EVENTS.md` — Partner changes, API updates

**Note**: System logs stay in SQLite/logs, this is project-level ops only.

**When to update**: As events happen

---

### 🔌 ext-extensions/

**Integrations, plugins, automations.**

Examples:
- `TELEGRAM_BOT_INTEGRATION.md` — Telegram bot setup
- `SLACK_PLUGIN.md` — Slack integration
- `AUTOMATION_RULES.md` — Automations in place
- `WEBHOOKS.md` — External webhook handlers

**When to update**: When adding new integrations

---

### 📦 resources/

**Shared resources (images, data, templates).**

Examples:
- `images/` — Screenshots, diagrams
- `data/` — Sample datasets
- `templates/` — Document templates
- `assets/` — Icons, logos

**When to use**: When documentation references external assets

---

### 📦 archive/

**Inactive project docs.**

Move here when:
- Project completed
- Major pivot (old docs become historical)
- Migrated to new structure

---

## Workflow Example

**New project starts:**
1. Create `core-overview/` → write charter + vision
2. Create `core-planning/` → outline roadmap
3. Create `core-architecture/` → sketch design
4. Create `dev-tracking/` → start checklist
5. Each session → add to `dev-sessions/`
6. Each decision → log to `meta-decisions/` (ADR)
7. Feedback/learnings → `meta-feedback/`
8. When done → move to `archive/`

---

## Content Guidelines

✅ **OK**:
- Markdown documents
- Diagrams (in resources/)
- Timelines, checklists
- Decisions, rationales
- Session notes

❌ **Not OK**:
- Code files (use `/code/`)
- System logs (use database/logs)
- Configuration files (use project config)
- Binary executables

---

## Naming Conventions

Suggested format:
- `FILENAME_SUBJECT.md` (e.g., `ADR-001-FRAMEWORK_CHOICE.md`)
- `SESSION_NNN_TITLE.md` (e.g., `SESSION_015_TELEGRAM_INTEGRATION.md`)
- `YYYY-MM-DD_SUBJECT.md` for dated entries

---

*Last updated: 2026-05-11*
