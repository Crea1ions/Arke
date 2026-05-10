# 🏛️ Arke

> **Agent decides · System executes**
>
> *“The system must never think in place of the agent.”*

Arke is a **deterministic and observable execution system** for autonomous agents built around one central principle:

> **All cognition is centralized inside the LLM agent.**
>
> The system never interprets, never chooses, and never decides in its place.

---

# 🎯 Vision

Most AI agent systems slowly drift toward hybrid cognition:

* routers become hidden decision engines
* orchestration layers start interpreting intent
* heuristics accumulate over time
* execution pipelines become opaque

Arke exists to enforce a strict separation:

| Layer      | Responsibility                         |
| ---------- | -------------------------------------- |
| **Agent**  | Understands, reasons, chooses, decides |
| **System** | Executes, validates, isolates, traces  |

```text
User → Agent (SOLE DECIDER) → System (EXECUTION ONLY)
```

The system is infrastructure.
The agent is cognition.

---

# ✅ Core Features

| Feature                        | Purpose                                                        |
| ------------------------------ | -------------------------------------------------------------- |
| **Unified Endpoint**           | Single interface to CLI, filesystem, SQLite, memory, APIs, MCP |
| **Deterministic Orchestrator** | Passive execution engine with validation gates                 |
| **SQLite Memory System**       | Local-first persistent memory (FTS5 + sqlite-vec)              |
| **Sandbox Isolation**          | Bubblewrap-based secure execution                              |
| **Skills System**              | Reusable deterministic and cognitive workflows                 |
| **Anti-Drift Monitoring**      | Live tracking of cognitive invariants                          |
| **Terminal-First Interface**   | Natural language REPL                                          |
| **Telegram Interface**         | Optional transport layer                                       |

---

# 🧠 Cognitive Model

Arke follows a strict cognitive hierarchy:

```text
0. Direct reasoning
1. Local deterministic tools
2. Local skills
3. Semantic/vector search
4. External MCP services
```

Core mantra:

```text
simplest-first
local-first
MCP-last

Stop at the first sufficient level.
```

The hierarchy is:

* descriptive
* cognitive
* non-prescriptive

The system never enforces it.

Only the agent decides.

---

# 🏗️ Cognitive Execution Pipeline

```text
User Input
    ↓
Conversation Context
    ↓
Cognitive Contract Injection
    ↓
Agent LLM (SOLE DECIDER)
    ↓
Tool Intent
    ↓
Unified Endpoint
    ↓
Deterministic Orchestrator
    ↓
Execution + Validation Gates
    ↓
Telemetry + Anti-Drift Metrics
    ↓
Response
```

---

# 🔐 Cognitive Invariants

Arke enforces three non-negotiable invariants:

```text
system_never_interprets = true
system_never_decides_tools = true
system_never_executes_without_llm_intent = true
```

This means:

❌ No implicit routing
❌ No conversation/task classification
❌ No autonomous retries
❌ No hidden planners
❌ No hybrid cognition
❌ No execution without explicit agent intent

---

# 🧰 Unified Endpoint

The Unified Endpoint exposes system capabilities to the agent:

* CLI
* filesystem
* SQLite
* memory
* skills
* vector search
* MCP
* APIs

Its role is only to:

* normalize
* expose
* translate

It never decides which tool to use.

---

# ⚙️ Orchestrator

The orchestrator is a passive execution engine.

## Responsibilities

* action execution
* sandboxing
* technical validation
* telemetry
* isolation
* runtime error handling

## Non-responsibilities

* intent interpretation
* tool selection
* reasoning
* planning
* user classification

---

# 🧠 Memory Architecture

Arke uses multiple local SQLite databases:

| Database     | Purpose                              |
| ------------ | ------------------------------------ |
| `global.db`  | global memory, skills, configuration |
| `project.db` | project context                      |
| `session.db` | conversational context               |
| `cache.db`   | internal technical cache             |

Memory strategy:

* **FTS5** → exact search
* **sqlite-vec** → semantic retrieval
* **LLM** → only if memory is insufficient

---

# 🧩 Skills System

Arke supports two skill categories:

| Type                     | Controlled By |
| ------------------------ | ------------- |
| **Deterministic Skills** | Orchestrator  |
| **Cognitive Skills**     | Agent         |

Deterministic skills execute directly.

Cognitive skills structure workflows and context, but the agent always remains the decision-maker.

---

# 🔭 Observability

Every action is traceable:

* selected tool
* execution duration
* token usage
* cost
* validations
* runtime errors
* OpenTelemetry traces

Observability exists to:

* understand
* debug
* audit

Never to replace cognition.

---

# 🔧 Technical Stack

| Component         | Technology                        |
| ----------------- | --------------------------------- |
| Language          | Python 3.11+                      |
| CLI               | Typer                             |
| Memory            | SQLite + FTS5 + sqlite-vec        |
| LLM Layer         | LiteLLM                           |
| Sandbox           | Bubblewrap                        |
| Monitoring        | OpenTelemetry                     |
| Performance Layer | Rust (PyO3 dispatch acceleration) |

---

# 📊 Project Status

| Component          | Status    |
| ------------------ | --------- |
| Core Agent Loop    | ✅ Working |
| Cognitive Contract | ✅ Working |
| SQLite Memory      | ✅ Working |
| Sandbox Execution  | ✅ Working |
| Skills System      | ✅ Working |
| Telegram Interface | ✅ Working |
| Anti-Drift Metrics | ✅ Working |

### Current Status

* 300+ tests passing
* Local-first runtime operational
* Architecture aligned with cognitive contract
* Production-ready core runtime

---

# 🚀 Quick Start

## Requirements

* Python 3.11+
* git
* SQLite development libraries
* bubblewrap (optional)

## Installation

```bash
git clone https://github.com/Crea1ions/Arke.git
cd Arke

python3 -m venv .venv
source .venv/bin/activate

pip install -e .
```

## First Run

```bash
# Interactive mode
arke

# Execute directly
arke run "analyze nginx logs"

# Telegram interface
arke --telegram
```

→ Full setup guide: `SETUP.md`

---

# 📚 Documentation

| Document                     | Purpose                                 |
| ---------------------------- | --------------------------------------- |
| `SETUP.md`                   | Installation and configuration          |
| `Arke-cognitive-contract.md` | Cognitive invariants and decision model |
| `Arke-architecture.md`       | Internal architecture                   |
| `Arke-alignment.md`          | System alignment doctrine               |

---

# 🧪 Testing

```bash
pytest tests/ -v
```

Coverage includes:

* cognitive contract invariants
* execution safety
* memory systems
* orchestrator validation
* anti-drift guarantees

---

# 🤝 Contributing

Contributions are welcome, provided they preserve:

* cognitive invariants
* agent-first architecture
* deterministic execution
* local-first philosophy

---

# 📜 License

MIT License.
