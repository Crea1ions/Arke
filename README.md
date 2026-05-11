# 🏛️ Arke

> **Agent decides · System executes · Interaction persists**  
> *"The system must never think in place of the agent."*

Arke is a **local-first autonomous agent architecture** where the LLM is the sole decision-maker. It does not interpret intent or select tools on behalf of the agent. It provides a unified endpoint, deterministic orchestration, SQLite-based memory, telemetry, and sandboxed execution around a single cognitive core designed for continuous interaction over time.

---

# 🎯 The Problem Arke Solves

Most AI agent systems gradually converge toward hybrid cognition:
- routers silently become decision layers
- orchestration accumulates implicit heuristics
- execution layers begin to interpret intent
- the system starts “thinking” instead of strictly executing
- agent autonomy becomes partially illusory

Arke enforces a strict separation that most systems blur over time:

| Layer     | Responsibility                         |
|----------|----------------------------------------|
| Agent     | Understands, reasons, decides          |
| System    | Executes, validates, isolates, traces  |


User → Agent (SOLE DECIDER) → System (EXECUTION ONLY)


The system is infrastructure.
The agent is cognition.
Nothing in between.

---

# 🧠 Cognitive Dimension

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

# ✅ Core Features

| Feature                        | Purpose                                                        |
| ------------------------------ | -------------------------------------------------------------- |
| **Unified Endpoint**           | Single interface for CLI, filesystem, memory, APIs, MCP        |
| **Deterministic Orchestrator** | Execution layer with strict validation gates                   |
| **SQLite Memory System**       | Global / project / session / cache storage (FTS5 + sqlite-vec) |
| **Sandbox Isolation**          | Secure execution via bubblewrap                                |
| **Skills System**              | Detection of repeated patterns and reusable workflows          |
| **Multi-Provider LLM Layer**   | Gemini, Claude, Mistral, OpenAI, Ollama                        |
| **OpenTelemetry Integration**  | Full tracing of execution and cost                             |
| **Terminal REPL**              | Natural language command interface                             |
| **Telegram Interface**         | Optional transport layer (no business logic)                   |

---

# 🧠 Cognitive Model

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

# 🏗️ Execution Pipeline

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

# 🔐 Cognitive Invariants

Arke enforces three core invariants:


system_never_interprets = true
system_never_decides_tools = true
system_never_executes_without_agent_intent = true


This guarantees:

* no implicit routing
* no hidden planners
* no autonomous decision layers
* no execution without explicit agent intent

---

# 🧠 Memory Architecture

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

# 🧩 Skills System

Arke identifies repeated behavioral patterns and can abstract them into reusable workflows.

* Pattern detection over time
* User-controlled activation
* Reusable execution blocks
* Automatic pruning of unused skills over time

The agent remains the sole decision-maker for skill usage.

---

# 🔭 Observability

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

# 🔧 Technical Stack

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

# 🚀 Status

* Tests: 243 / 243 passing
* Regressions: 0
* Suite runtime: ~12.6s
* Router latency: < 0.002 ms

---

# 🚀 Quick Start

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

# 📚 Documentation

| Document                      | Purpose                        |
| ----------------------------- | ------------------------------ |
| `SETUP.md`                    | Installation and configuration |
| `Arke-cognitive-alignment.md` | Cognitive continuity model     |
| `Arke-architecture.md`        | System architecture            |
| `Arke-alignment.md`           | Agent / System separation      |

---

# 🧪 Testing


pytest tests/ -v


Covers:

* deterministic execution
* memory consistency
* sandbox safety
* skill lifecycle
* orchestrator validation

---

# 🤝 Contributing

Contributions are welcome if they preserve:

* agent-first decision model
* deterministic execution layer
* local-first architecture
* SQLite-based persistence
* strict system/agent separation

---

# 📜 License

MIT License

---


