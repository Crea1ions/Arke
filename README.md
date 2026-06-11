# Arke

> **Agent decides · System executes · Interaction persists**  
> *"The system must never think in place of the agent."*

Arke is a **local-first autonomous agent architecture** where the LLM is the sole decision-maker. It does not interpret intent or select tools on behalf of the agent. It provides a unified endpoint, deterministic orchestration, SQLite-based memory, telemetry, and sandboxed execution around a single cognitive core designed for continuous interaction over time.

---

# Cognitive Dimension

Beyond execution, Arke introduces a structural property:
**temporal continuity of interaction.**

It does not simulate personality. It does not model human behavior.
It maintains persistent interaction state across time, allowing unfinished threads, ideas, and contextual signals to resurface when relevant.

| Usage Density | Emergent Behavior                           |
| ------------- | ------------------------------------------- |
| Low           | Reactive assistant                          |
| Medium        | Persistent memory and continuity            |
| High          | Contextual reactivation and pattern linking |
| Very High     | Collaborative cognitive interaction         |

> Proactivity is not a mode. It is an emergent consequence of interaction density.

No configuration modes. No relationship tiers.
Only memory accumulation over time.

---

# Core

|                         | Purpose                                                        |
| ------------------------------ | -------------------------------------------------------------- |
| **Agent Modes**                | `/ask` `/search` `/plan` `/agent` — tool gating per mode       |
| **Unified Endpoint**           | Single interface for CLI, filesystem, memory, APIs, MCP        |
| **Deterministic Orchestrator** | Execution layer with strict validation gates                   |
| **SQLite Memory System**       | Global / project / session / cache storage (FTS5 + sqlite-vec) |
| **Sandbox Isolation**          | Secure execution via bubblewrap with workspace-aware fallback  |
| **Skills System**              | Detection of repeated patterns and reusable workflows          |
| **Multi-Provider LLM Layer**   | Gemini, Claude, Mistral, OpenAI, Ollama                        |
| **OpenTelemetry Integration**  | Full tracing of execution and cost                             |
| **Terminal REPL**              | Natural language command interface with mode badge             |
| **Workspace Codex**            | Local shared memory (`codex_ask` / `codex_opt`) per workspace |
| **Telegram Interface**         | Optional transport layer (no business logic)                   |
| **External Bridges (optional)** | Complementary connectors outside Arke core                     |

---

# Cognitive Model

Arke follows a strict layered reasoning model:


0. Direct reasoning (LLM)
1. Local deterministic tools (CLI, FS)
2. SQLite memory (FTS5 + vector search)
3. Local skills
4. External MCP services


Core principle:


simplest-first
local-first
MCP-last

Stop at the first sufficient layer.


The hierarchy is descriptive, not enforced.
Only the agent decides.

---

# Execution Pipeline

User Input

↓

Conversation Context (session.db)

↓

Agent LLM (SOLE DECIDER)

↓

Tool Intent

↓

Unified Endpoint

↓

Deterministic Orchestrator

↓

Validation Gates (schema, filesystem, return codes)

↓

Sandbox Execution (bubblewrap)

↓

Telemetry (OpenTelemetry)

↓

Response

↓

Memory Update (skills + history)

↓

(loop back to Conversation Context)

---

# Cognitive Invariants

Arke enforces four core invariants:


system_never_interprets = true
system_never_decides_tools = true
system_never_executes_without_agent_intent = true
no_execution_without_explicit_user_mode = true


This guarantees:

* no implicit routing
* no hidden planners
* no autonomous decision layers
* no execution without explicit agent intent
* no tool calls without the user enabling the appropriate mode

---

# Memory Architecture

| Database     | Purpose                                 |
| ------------ | --------------------------------------- |
| `global.db`  | Preferences, skills, long-term patterns |
| `project.db` | Project-specific context                |
| `session.db` | Active conversation state               |
| `cache.db`   | LLM cache and embeddings                |

Memory strategy:

* **FTS5** → full-text search
* **sqlite-vec** → semantic retrieval (< 5 ms on small corpora)
* **LLM fallback** → only when retrieval is insufficient

---

# Skills System

Arke identifies repeated behavioral patterns and can abstract them into reusable workflows.

* Pattern detection over time
* User-controlled activation
* Reusable execution blocks
* Automatic pruning of unused skills over time

The agent remains the sole decision-maker for skill usage.

---

# Agent Modes

Arke defaults to `/ask` mode — no tools, direct responses only.
The user must explicitly switch modes to grant tool access.

| Mode      | Tools Allowed                                     | Use Case                          |
| --------- | ------------------------------------------------- | --------------------------------- |
| `/ask`    | **none** — direct LLM response only               | Discussion, questions, concepts   |
| `/search` | SQLite, memory FTS/vector, web, calculator        | Read-only research                |
| `/plan`   | memory read/write, SQLite, vector                 | Structured planning and reasoning |
| `/agent`  | **all** (unrestricted)                            | Implementation, files, CLI        |

Enforcement is double-gated: pre-orchestrator check in `chat.py` and inside `orchestrator._dispatch()`.
The active mode is displayed in the REPL prompt (`[ask] ›`) and injected into the cognitive contract.

### Workspace root

Arke now uses the caller workspace as the default execution root when `WORKSPACE_ROOT` is not explicitly set.

### REPL startup

The REPL now starts without blocking startup prompts.

* no automatic workspace selection prompt
* no automatic legacy migration prompt
* manual workspace actions only via `/workspace list`, `/workspace select`, `/workspace sync`
* startup banner rendered once with repository path displayed first
* compact fallback banner when terminal width or Unicode support is insufficient
The legacy WCU tree (`arke-workspace/WCU`) is treated as an optional artifact for workspace views only: it is not auto-created and is not synced from the launcher directory.

### Workspace Codex

Arke supports a workspace-local Codex designed to capture project culture and conventions.

Each workspace owns two YAML files in `.arke/`:

* `.arke/codex_ask.yaml` for reflective guidance in `/ask`
* `.arke/codex_opt.yaml` for operational guidance in `/search`, `/plan`, `/agent`

The Codex is local, editable, and mode-aware:

* `/codex` shows a summary and available Codex commands
* `/codex ask` and `/codex opt` display each Codex file
* `/codex ask edit` and `/codex opt edit` update Codex entries explicitly

Codex is preference/context memory. It does not override mode permissions or Themelios safety rules.

---

# Observability

All executions are traced via OpenTelemetry:

* tool selection
* latency
* token usage
* cost
* validation results
* runtime errors

Observability is strictly diagnostic.
It never participates in decision-making.

---

# Technical Stack

| Component  | Technology                       |
| ---------- | -------------------------------- |
| Language   | Python 3.11+                     |
| Router     | Rust (PyO3)                      |
| CLI        | Typer                            |
| Memory     | SQLite + WAL + FTS5 + sqlite-vec |
| LLM Layer  | LiteLLM                          |
| Sandbox    | Bubblewrap                       |
| Monitoring | OpenTelemetry                    |
| Interface  | Terminal REPL + Telegram         |

---

# Status

* Version: v1.8.0
* Tests: 533 / 533 passing
* Regressions: 0
* Suite runtime: ~12.6s
* Router latency: < 0.002 ms

### Optional Complementary Extension

Arke can expose optional local bridges for external tools.
These bridges are complementary extensions and are not part of Arke's core architecture or identity.
Arke remains fully operational as a standalone local-first agent without them.

- **MyTeamHub** is a cognitive IDE built on three principles:
  - **Files-first** — every interaction is anchored to a file open in the editor. No floating context.
  - **Agent roundtable** — specialized agents (Explorer, Critical Analyst, Collaborator, Synthesizer) each bring a distinct perspective to the same shared context.
  - **User as Game Master** — the user controls what context is shared, which agent speaks, and when. Agents suggest, never decide.

  When connected to Arke via a local bridge, MyTeamHub becomes a complementary interface where:
  - Arke joins the agent roundtable as an invited participant, keeping its full REPL capabilities (/ask, /search, /plan, /agent).
  - Context sharing is strictly opt-in via an editor toggle (OFF by default).
  - Sessions and memory remain isolated from MyTeamHub's other agents — Arke sees only what the user explicitly shares.

### CLI safety notes

* `printf` is whitelisted for file creation workflows.
* `tree` is whitelisted for read-only inspection.
* `/workspace/...` is treated as the sandbox workspace alias, including in fallback execution paths.

---

# Quick Start

## Install


git clone https://github.com/Crea1ions/Arke.git
cd Arke
python3 -m venv .venv
source .venv/bin/activate
pip install -e .


## Run


arke chat
arke run "analyze nginx logs"
arke --telegram


---

# Documentation

| Document                      | Purpose                        |
| ----------------------------- | ------------------------------ |
| `SETUP.md`                    | Installation and configuration |
| `Arke-cognitive-alignment.md` | Cognitive continuity model     |
| `Arke-architecture.md`        | System architecture            |
| `Arke-alignment.md`           | Agent / System separation      |

---

# Testing


pytest tests/ -v


Covers:

* deterministic execution
* memory consistency
* sandbox safety
* skill lifecycle
* orchestrator validation

---

# Contributing

Contributions are welcome if they preserve:

* agent-first decision model
* deterministic execution layer
* local-first architecture
* SQLite-based persistence
* strict system/agent separation

---

# License

MIT License

---


