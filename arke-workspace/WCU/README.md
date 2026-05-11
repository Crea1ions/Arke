# 🧠 Workspace Cognitif Utilisateur (WCU) — Passive User Workspace (PUW)

## Vision

This workspace is a **passive storage system** for user-centric knowledge management, organized across 4 cognitive layers. It is **opaque to the Arke LLM agent** — all filesystem operations are orchestrated externally via the Arke orchestrator, never directly by the language model.

**Key principle**: User workspace ≠ Agent cognition.

---

## 📐 Architecture: 4 Cognitive Layers

```
┌─────────────────────────────────────────────────────┐
│ 1. CAPTURE (mobile-notes/)                          │
│    Input: user notes, voice, quick captures         │
│    Channels: telegram, discord, email, obsidian, api│
├─────────────────────────────────────────────────────┤
│ 2. PRODUCTION (code/)                               │
│    Tech artifacts: apps, services, libs, experiments│
│    Independent from knowledge layers                │
├─────────────────────────────────────────────────────┤
│ 3. STRUCTURATION (projects/TEMP/)                   │
│    Project-level organization: overview, planning,  │
│    decisions, logs, tracking                        │
├─────────────────────────────────────────────────────┤
│ 4. RESTITUTION (shared/)                            │
│    Output: summaries, insights, decision recaps     │
│    User-facing transformation of Arke outputs       │
└─────────────────────────────────────────────────────┘
```

---

## 📁 Directory Structure

```
WCU/
├── mobile-notes/          # Layer 1: Capture (multi-channel input)
│   ├── fleeting/          # Quick ephemeral notes
│   ├── ideas/             # Structured ideas / concepts
│   ├── voice/             # Voice memo transcriptions
│   ├── quick-capture/     # Rapid capture (Ctrl+K integration)
│   ├── channels/          # I/O adapters (not sync layers)
│   │   ├── telegram/      # Telegram messages (in/out)
│   │   ├── discord/       # Discord messages (in/out)
│   │   ├── email/         # Email captures (in/out)
│   │   ├── obsidian/      # Obsidian vault sync (in/out)
│   │   └── api/           # API-driven captures (in/out)
│   └── archive/           # Inactive captures
│
├── code/                  # Layer 2: Production (technical artifacts)
│   ├── apps/              # Standalone applications
│   ├── services/          # Backend services
│   ├── libs/              # Shared libraries
│   ├── experiments/       # Prototypes & POCs
│   └── README.md          # Production conventions
│
├── projects/              # Layer 3: Structuration (cognitive org)
│   └── TEMP/              # Project namespace (user projects)
│       ├── core-overview/ # Vision, principles, alignment
│       ├── core-planning/ # Roadmap, milestones
│       ├── core-architecture/ # Design, models, contracts
│       ├── dev-sessions/  # Session logs & work history
│       ├── dev-tracking/  # Progress, checklists, issues
│       ├── meta-decisions/# Technical/structural decisions (ADR)
│       ├── meta-feedback/ # User feedback, iterations
│       ├── ops-logs/      # Operational logs (not system logs)
│       ├── ext-extensions/# Integrations, plugins
│       ├── resources/     # Shared project resources
│       └── archive/       # Inactive project docs
│
├── shared/                # Layer 4: Restitution (output)
│   ├── session-summaries/ # Structured session recaps
│   ├── decision-recaps/   # Decision synthesis
│   ├── cognitive-threads/ # Cross-session continuity
│   ├── generated-insights/# Arke-extracted insights
│   └── user-facing-logs/  # Simplified, interpreted logs
│
└── archive/               # Layer 5: Passive storage
    # Old projects, inactive work, system snapshots
```

---

## 🧠 Layer Descriptions

### 📱 Layer 1: mobile-notes/ — Capture & Ingestion

**Purpose**: Multi-source input capture, user-controlled.

**What goes here**:
- Quick notes (fleeting/)
- Concept development (ideas/)
- Voice transcriptions (voice/)
- Channel messages (channels/{telegram,discord,email,obsidian,api}/)

**Important**:
- Not automatically cleaned
- Channels are **I/O adapters**, not sync systems
- Telegram, Discord, etc. forward user messages to orchestrator; orchestrator decides if/when to store
- Never touched by LLM directly

---

### 💻 Layer 2: code/ — Production Artifacts

**Purpose**: Clean technical production, independent from cognitive layers.

**What goes here**:
- Applications (apps/)
- Services (services/)
- Libraries (libs/)
- Prototypes (experiments/)

**Important**:
- Strictly separated from Layer 3 (projects/)
- No cognitive structuring here
- Pure code, versioned, deployable

---

### 📁 Layer 3: projects/TEMP/ — Project Structuration

**Purpose**: User-driven cognitive organization of projects.

**Submodules**:
- **core-overview/**: Vision, principles, alignment
- **core-planning/**: Roadmap, milestones, sprints
- **core-architecture/**: System design, contracts, models
- **dev-sessions/**: Work session logs & continuity
- **dev-tracking/**: Progress tracking, checklists, blockers
- **meta-decisions/**: Architecture Decision Records (ADRs)
- **meta-feedback/**: User feedback, iterations, learnings
- **ops-logs/**: Project-level operational events (not system logs)
- **ext-extensions/**: Integrations, plugins, automations
- **resources/**: Shared project resources
- **archive/**: Inactive docs

**Important**:
- Separate from code/ (no code here, only documentation)
- User-organized, not automated
- LLM-opaque (no direct LLM access)

---

### 🧠 Layer 4: shared/ — Restitution & Output

**Purpose**: Transformation of Arke outputs into user-facing format.

**What goes here**:
- Session summaries (from orchestrator intents)
- Decision recaps (synthesized from discussions)
- Cognitive threads (cross-session continuity)
- Generated insights (Arke extractions)
- User-facing logs (simplified, interpreted)

**What does NOT go here**:
- System logs (SQLite activity, runtime state)
- Agent memory (use SQLite instead)
- Raw orchestrator outputs (transform first)

**Important**:
- Strictly output-only (users read, don't write manually)
- Arke writes here via orchestrator intents
- All content must be human-readable

---

### 📦 Layer 5: archive/ — Passive Storage

**Purpose**: Inactive project storage.

**What goes here**:
- Completed projects
- Old work
- System snapshots
- Anything not actively used

---

## ⚙️ Orchestrator Integration (For Developers)

This workspace is managed by the **Arke orchestrator**, not by the LLM agent.

**How it works**:
1. User sends input (Telegram, CLI, API)
2. Orchestrator receives → extracts intent
3. Orchestrator maps intent to WCU path (via `INTENT_PATH_MAP`)
4. Orchestrator writes to WCU using `workspace.py`
5. LLM never sees filesystem structure

**Standard intents**:
- `WRITE_SESSION_SUMMARY` → shared/session-summaries/
- `STORE_MOBILE_NOTE_TELEGRAM` → mobile-notes/channels/telegram/
- `LOG_DECISION` → projects/TEMP/meta-decisions/
- `EXPORT_SHARED_INSIGHT` → shared/generated-insights/
- ... (see WORKSPACE_ORCHESTRATION.md in project root)

---

## 📋 Usage Guidelines

### As a User

1. **Capture notes** in mobile-notes/ (manual or via Telegram)
2. **Organize projects** in projects/TEMP/ (use submodules as guides)
3. **Review outputs** in shared/ (Arke contributions appear here)
4. **Archive old work** in archive/

### As a Developer

See WORKSPACE_ORCHESTRATION.md (in project root) for:
- Intent→path mapping contract
- Orchestrator responsibilities
- Adding new intents
- Testing WCU integration

---

## 🔒 Stability Guarantees

✅ **This workspace is stable**:
- No unexpected reorganization
- No automatic cleanup without approval
- Clear layer boundaries
- Orchestrator is single authority for I/O

---

*Last updated: 2026-05-11*
