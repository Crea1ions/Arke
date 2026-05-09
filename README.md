# 🏛️ Arke

> **Agent decides · System executes**
>
> *"Le système ne doit jamais penser à la place de l'agent."*

Arke est un **système d'exécution déterministe et observable** pour agents autonomes, fondé sur un principe central :

> **Toute cognition est centralisée dans l'agent LLM.**
>
> Le système n'interprète jamais, ne choisit jamais, ne décide jamais à sa place.

---

## 🎯 Vision

### Le Problème

La plupart des agents conservent l'illusion que le *système* peut décider intelligemment. Or :

- Le routeur devient un second cerveau
- Les heuristiques s'empilent 
- Les décisions hybrides système/agent brouillent les responsabilités
- Les bugs cognitifs deviennent imprévisibles

### Notre Réponse

Arke impose une **séparation stricte** :

- **Agent:** Unique moteur cognitif. Comprend, choisit, décide.
- **Système:** Infrastructure d'exécution passive. Exécute, trace, isole, valide.

```text
Utilisateur → Agent (SEUL DÉCIDEUR) → Système (EXÉCUTE UNIQUEMENT)
```

---

## ✅ Core Features

| Feature | Role | Status |
|---------|------|--------|
| **Orchestrator** | Intention → Task DAG; cognitive contract enforced | ✅ Working |
| **Dispatch Layer** | Minimal, non-cognitive routing (transport only) | ✅ Working |
| **Memory (SQLite)** | 4-database system (semantic search, patterns, session) | ✅ Working |
| **Sandbox Isolation** | Bubblewrap + whitelist for safe CLI execution | ✅ Working |
| **Skills System** | Pattern recognition; never replaces agent cognition | ✅ Working |
| **Anti-Drift Monitor** | 3 invariants tracked live; violations logged | ✅ Working |
| **Terminal Interface** | Primary: REPL chat mode | ✅ Working |
| **Telegram (Optional)** | Secondary interface; agent-first message handling | ✅ Working |

### Key Principles

```
Principle 1: System never interprets
  → Zero classification without agent intent
  
Principle 2: System never decides tools  
  → Dispatch layer is transport ONLY, not cognitive
  
Principle 3: System never executes without agent intent
  → No autonomous retries, no implicit routing
```

---

## 🏗️ Cognitive Execution Pipeline

```
User Intention
    ↓
Build Context (history + metrics)
    ↓
Inject Cognitive Contract (JSON)
    ↓
Agent LLM (SOLE DECIDER)
    ↓
Parse [TOOL: X] + [ARGS: Y]
    ↓
Minimal Dispatch Layer (non-cognitive)
    ↓
Tool Execution (CLI, Filesystem, SQLite, MCP)
    ↓
Validation Gates
    ↓
Update Anti-Drift Metrics
    ↓
Display Result
```

---

## 🔧 Technical Stack

- **Language:** Python 3.11+
- **CLI Framework:** Typer
- **LLM Abstraction:** LiteLLM (fallback across providers)
- **Memory:** SQLite 4-database system (session, global, project, cache)
- **Sandbox:** Bubblewrap (with fallback)
- **Interfaces:** Terminal (primary), Telegram (optional)
- **Monitoring:** OpenTelemetry (optional)
- **Performance:** Rust router (PyO3, for dispatch speed only)

---

## 📊 Project Status

### Current Phase: **Session 015 Complete**

| Component | Status | Details |
|-----------|--------|---------|
| **Core Agent Loop** | ✅ Complete | 300+ tests passing |
| **Cognitive Contract** | ✅ Complete | 3 invariants monitored |
| **Memory System** | ✅ Complete | SQLite x4, FTS5, semantic |
| **Sandbox Execution** | ✅ Complete | Bubblewrap + whitelist |
| **Skills System** | ✅ Complete | Pattern detection working |
| **Telegram Bot** | ✅ Complete | Agent-first routing (v1.2) |
| **Documentation** | ✅ Complete | Architecture documented |

### Known Issues

- ⚠️ Telegram slash commands (e.g., `/check`, `/stats`) registered but not executing (Session 015 known bug, low priority)

### Deployment Readiness

- ✅ Local development: Complete and tested
- ✅ Core runtime: Production-ready
- 🔄 Containerization: Next phase (separate task)

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- git
- libsqlite3-dev (Linux)
- bubblewrap (optional, for sandbox)

### Installation

```bash
git clone https://github.com/Crea1ions/Arke.git
cd Arke
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### First Run

```bash
# Interactive chat
arke

# Execute intention directly
arke run "echo hello"

# Telegram bot (requires TELEGRAM_BOT_TOKEN)
arke --telegram
```

**→ Full setup guide:** See [SETUP.md](./SETUP.md)

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| [SETUP.md](./SETUP.md) | Installation, configuration, Telegram setup, troubleshooting |
| [Arke-architecture.md](./Arke-02-architecture/Arke-architecture.md) | Component design, tool hierarchy, anti-drift monitoring |
| [Arke-cognitive-contract.md](./Arke-cognitive-contract.md) | Cognitive invariants, contract spec, decision model |

---

## 🔐 Philosophy Guardrails

### What Arke WILL NEVER Do

❌ Implicit routing without agent intent  
❌ Classification (conversation vs task) without agent cognition  
❌ Autonomous retries or intelligent fallbacks  
❌ System-made decisions, even "smart" ones  
❌ Hybrid system/LLM decision-making  
❌ Execution without explicit agent intent  

### What Arke ALWAYS Does

✅ Agent decides. Always.  
✅ System executes. Passively.  
✅ Trace every decision point  
✅ Monitor cognitive invariants live  
✅ Sandbox all risky operations  
✅ Log all violations  

---

## 🧪 Testing

```bash
# Run all tests (300+ passing)
pytest tests/ -v

# Run specific test
pytest tests/test_cognitive_contract.py -v

# With coverage
pytest tests/ --cov=arke
```

---

## 📝 License

MIT License. See [LICENSE](./LICENSE) for details.

---

## 🤝 Contributing

Contributions welcome. Please ensure:

1. No changes to cognitive invariants
2. All new code type-hinted
3. Tests passing before PR
4. Philosophy alignment verified

---

## 📞 Support

- **Documentation:** See [SETUP.md](./SETUP.md) and [Arke-architecture.md](./Arke-02-architecture/Arke-architecture.md)
- **Issues:** Report on GitHub with environment details
- **Design discussions:** See [Arke-cognitive-contract.md](./Arke-cognitive-contract.md)

---

**Version:** 1.2 · **Status:** Production-ready (core) · **Last Updated:** 2026-05-09

---

# Philosophie

## Cognition centralisée

Dans Arke :

* l’agent comprend l’intention
* l’agent choisit les outils
* l’agent structure l’exécution
* l’agent décide du niveau de profondeur nécessaire

Le système :

* exécute
* trace
* isole
* valide
* expose les capacités disponibles

Mais :

* ne route jamais
* n’interprète jamais
* ne choisit jamais d’outil
* ne transforme jamais une intention utilisateur

---

# Principe Fondamental

```text
Utilisateur → Agent → Monde
Jamais Utilisateur → Système → Décision
```

---

# Architecture

```text
Utilisateur
↓
Chat UI
↓
Contrat Cognitif
↓
Agent Arke (seul décideur)
↓
Endpoint Unifié
↓
Orchestrateur
↓
Outils
```

---

# Rôle des couches

| Couche               | Rôle                                        |
| -------------------- | ------------------------------------------- |
| **Chat UI**          | Interface conversationnelle universelle     |
| **Contrat cognitif** | Rappelle les invariants de raisonnement     |
| **Agent Arke**       | Seul moteur cognitif                        |
| **Endpoint unifié**  | Interface standardisée vers les outils      |
| **Orchestrateur**    | Exécution déterministe et sandboxée         |
| **Outils**           | Agissent sur le système ou le monde externe |

---

# Ce que le système ne fait jamais

Arke interdit explicitement :

* le routing implicite
* la classification conversation vs tâche
* les planners système
* les heuristiques de sélection d’outil
* les retries intelligents autonomes
* les décisions hybrides système/LLM
* l’exécution sans intention explicite de l’agent

---

# Hiérarchie Cognitive des Outils

L’agent raisonne du plus simple au plus complexe.

Cette hiérarchie est :

* descriptive
* cognitive
* non prescriptive

Le système ne l’impose jamais.

| Niveau                    | Usage                                   |
| ------------------------- | --------------------------------------- |
| **0 — Réflexion directe** | Réponse sans outil                      |
| **1 — Outils locaux**     | CLI, FS, SQLite, mémoire FTS5           |
| **2 — Skills locaux**     | Workflows explicitement définis         |
| **3 — Recherche avancée** | Recherche vectorielle locale / LLM      |
| **4 — MCP externe**       | Services externes rares et stratégiques |

---

# Mantra d’Exécution

```text
simplest-first
local-first
MCP-last

Stop at the first sufficient level.
```

---

# Endpoint Unifié

L’Endpoint unifié expose les capacités système :

* CLI
* filesystem
* SQLite
* mémoire
* skills
* vector search
* MCP
* APIs

Son rôle est :

* normaliser
* traduire
* exposer

Il ne décide jamais quel outil utiliser.

---

# Orchestrateur

L’orchestrateur est un moteur d’exécution passif.

## Il fait

* exécution des actions agent
* sandboxing
* validation technique
* telemetry
* isolation
* gestion des erreurs techniques

## Il ne fait pas

* interprétation d’intention
* choix d’outil
* raisonnement
* planification
* classification utilisateur

---

# Local-First

Arke privilégie la souveraineté locale :

* SQLite
* FTS5
* sqlite-vec
* shell local
* filesystem local

Le réseau et les MCP sont considérés comme :

* périphériques
* coûteux
* moins déterministes

---

# Mémoire

Arke utilise plusieurs bases SQLite locales.

| Base         | Usage                                  |
| ------------ | -------------------------------------- |
| `global.db`  | Configuration, skills, mémoire globale |
| `project.db` | Contexte projet                        |
| `session.db` | Contexte conversationnel immédiat      |
| `cache.db`   | Cache technique interne                |

## Stratégie mémoire

* FTS5 → exact match
* sqlite-vec → recherche sémantique
* LLM → uniquement si la mémoire est insuffisante

---

# Skills

Les skills sont des workflows réutilisables.

## Skills déterministes

Exécutés directement par l’orchestrateur.

Exemples :

* backup
* sync
* deploy

## Skills cognitifs

Pilotés par l’agent.

Ils :

* structurent
* contextualisent
* organisent

Mais l’agent reste toujours décideur.

---

# Observabilité

Chaque action est traçable :

* outil utilisé
* durée
* coût
* tokens
* validations
* erreurs
* telemetry OTel

L’observabilité sert :

* à comprendre
* à auditer
* à déboguer

Jamais à remplacer la cognition agent.

---

# Sandbox & Sécurité

Les actions système peuvent être isolées via :

* bubblewrap
* gates de validation
* whitelists
* contrôles filesystem
* validation de return codes

La sécurité bloque techniquement.

Elle ne décide jamais cognitivement.

---

# Contrat Cognitif

Chaque message utilisateur est encapsulé dans un contrat cognitif qui rappelle :

* les invariants système
* la hiérarchie cognitive
* les contraintes anti-dérive
* les limites MCP

Le contrat :

* borne le système
* protège l’agent

Mais ne décide jamais à sa place.

---

# Invariants Arke

```text
system_never_interprets = true
system_never_decides_tools = true
system_never_executes_without_llm_intent = true
```

---

# Architecture Interne

```text
arke/
  chat.py              — Interface conversationnelle
  chat_router.py       — Dispatch minimal non cognitif
  orchestrator.py      — Exécution déterministe
  endpoint.py          — Interface unifiée des outils
  tool_registry.py     — Registre descriptif des capacités
  task_graph.py        — Structures d’exécution agent
  telemetry.py         — Observabilité OpenTelemetry
  sandbox.py           — Isolation bubblewrap
  gates.py             — Validation technique
  security.py          — Politiques techniques

  memory/
    manager.py         — Accès SQLite
    schema.sql         — FTS5 + sqlite-vec

  skills/
    detector.py        — Observation statistique
    manager.py         — Gestion des skills
    registry.py        — Registre SQLite

  interfaces/
    mcp_client.py      — MCP externe
    telegram_bot.py    — Transport uniquement

config/
tests/
```

---

# Ce qu’Arke cherche à éviter

Arke combat explicitement :

* les frameworks “brain”
* les routers intelligents cachés
* les pipelines opaques
* la cognition distribuée
* les décisions hybrides système/LLM
* l’hallucination opérationnelle

---

# Objectif

Créer un système où :

* 100% des décisions viennent de l’agent
* 0 décision implicite vient du système
* toute action est traçable
* toute exécution est vérifiable

---

# Vision

Arke n’est pas un assistant.

C’est une architecture où :

> **le LLM est le seul lieu de cognition,**
> **et tout le reste est une infrastructure déterministe autour de lui.**

---

# Licence

MIT

