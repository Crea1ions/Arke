# 📖 Setup Guide — Arke

Complete installation, configuration, and getting started guide.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [First Run](#first-run)
5. [Telegram Bot Setup](#telegram-bot-setup)
6. [Verifying Installation](#verifying-installation)
7. [Troubleshooting](#troubleshooting)
8. [Advanced Configuration](#advanced-configuration)
9. [Development Setup](#development-setup)

---

## Requirements

### System
- **Python:** 3.11 or higher
- **Git:** For cloning and version control
- **libsqlite3-dev:** For SQLite development headers (Linux only)
  ```bash
  # Ubuntu/Debian
  sudo apt-get install libsqlite3-dev
  
  # macOS (usually pre-installed)
  brew install sqlite
  ```

### Optional
- **Bubblewrap:** For sandbox CLI execution (Linux)
  ```bash
  sudo apt-get install bubblewrap
  ```
  If not available, Arke falls back to unsandboxed execution (logged as fallback).

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/Crea1ions/Arke.git
cd Arke
```

### 2. Create Virtual Environment

```bash
# Create venv
python3 -m venv .venv

# Activate (Linux/macOS)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate
```

### 3. Install Package

```bash
# Development install (editable)
pip install -e .

# Or production install
pip install .
```

### 4. Verify Installation

```bash
arke --help
```

Expected output:
```
 Usage: arke [OPTIONS] COMMAND [ARGS]...

 Arke — Autonomous cognitive agent

Options:
  --help  Show this message and exit.

Commands:
  chat       Interactive REPL chat mode
  run        Execute intention directly
  memory     Query memory databases
  skill      Manage skills
```

---

## Configuration

### 1. Config Files Location

Arke looks for config files in this order:
1. `./config/` (project root)
2. `~/.arke/` (user home)
3. `/etc/arke/` (system-wide)

### 2. Main Configuration: `config/arke.toml`

Create `config/arke.toml` with minimal settings:

```toml
[memory]
memory_path = "./memory"
db_mode = "WAL"

[routing]
tool_hierarchy = ["cli", "fs", "sqlite", "scripts", "api", "mcp", "llm"]

[llm]
default_model = "flash"
max_tokens = 2048
timeout = 30

[sandbox]
enabled = true
read_only = true
tmp_isolation = true

[telemetry]
enabled = false  # Set to true if using OpenTelemetry
```

**Full example available in:** [config/arke.toml.example](./config/arke.toml.example)

### 3. LLM Providers: `config/models.toml`

Configure LLM fallback order. See [config/models.toml](./config/models.toml) for details.

### 4. Security: `config/security.toml`

Whitelist of allowed CLI commands. Default includes:
```
ls, cat, pwd, date, echo, grep, wc, sort, uniq, cut, tr, sed, awk, find, 
head, tail, file, git, python, curl, wget, jq
```

See [config/security.toml](./config/security.toml) to customize.

---

## Environment Variables

### LLM API Keys

Set these in your shell or `.env` file (not tracked by git):

```bash
# Google Gemini
export GEMINI_API_KEY="your-key-here"

# Mistral
export MISTRAL_API_KEY="your-key-here"

# Anthropic Claude
export ANTHROPIC_API_KEY="your-key-here"

# OpenRouter
export OPENROUTER_API_KEY="your-key-here"
```

### Telegram Bot (Optional)

```bash
export TELEGRAM_BOT_TOKEN="your-bot-token-here"
```

### Other Options

```bash
# Logging level
export LOG_LEVEL="INFO"  # Options: DEBUG, INFO, WARNING, ERROR

# Cache TTL (seconds)
export CACHE_TTL="3600"

# Sandbox mode
export SANDBOX_ENABLED="true"
```

### Using `.env` File

Create `.env` in project root (never commit):

```bash
# .env (gitignore'd)
GEMINI_API_KEY=xxx
TELEGRAM_BOT_TOKEN=xxx
LOG_LEVEL=INFO
```

Load with:
```bash
set -a
source .env
set +a
```

---

## First Run

### 1. Interactive Chat Mode

```bash
arke
```

Expected:
```
Arke v1.2 — Agent autonome
Type /help for commands or just chat naturally.

› What's the current time?
```

Type a question and press Enter. Arke will:
1. Build cognitive context
2. Ask agent LLM for decision
3. Execute tool if needed
4. Display result

Exit with Ctrl+C or `/exit`.

### 2. Direct Execution

```bash
arke run "echo hello from Arke"
```

Expected:
```
hello from Arke
```

### 3. Telegram Bot Mode

```bash
arke --telegram
```

Expected:
```
Telegram bot running. Press Ctrl+C to stop.
```

Send a message to your bot on Telegram. The bot will:
1. Route to agent
2. Execute intention
3. Send chunked response back to Telegram

---

## Telegram Bot Setup

### Prerequisites

- Telegram account
- BotFather chat access

### Step-by-Step

#### 1. Create Bot with BotFather

Open Telegram and search for **@BotFather**.

```
/start
/newbot
```

Follow prompts:
- **Name:** e.g., "Arke Agent"
- **Username:** e.g., "arke_agent_bot" (must be unique, end with `_bot`)

BotFather will respond:
```
Done! Congratulations on your new bot. You'll find it at 
t.me/arke_agent_bot. You can now add a description, about section and commands.

Use this token to access the HTTP API:
123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
```

#### 2. Save Token

Copy the token (123456:ABC-...).

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
```

Or add to `.env`:
```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
```

#### 3. Start Bot

```bash
arke --telegram
```

Expected:
```
Telegram bot running on https://localhost:8443
Press Ctrl+C to stop
```

#### 4. Test

Open Telegram, find your bot (`@arke_agent_bot`), and send:
```
What time is it?
```

Expected response from bot within 5 seconds.

#### 5. (Optional) Configure BotFather

Back in BotFather chat:

```
/mybots
→ Select your bot
→ Bot Settings
→ Edit Commands
```

Add commands for quick access:
```
/check - System status
/stats - Usage metrics
/help - Show help
/about - About Arke
```

**Note:** Session 015 has a known bug: slash commands are registered but may not execute (see [Troubleshooting](#troubleshooting)).

---

## Verifying Installation

### 1. Run Tests

```bash
# All tests
pytest tests/ -v

# Expected output
tests/test_cognitive_contract.py::test_contract_injection PASSED
tests/test_orchestrator.py::test_cli_execution PASSED
tests/test_memory.py::test_fts5_search PASSED
... (300+ tests)

PASSED [300+ passed in X.XXs]
```

### 2. Check Memory Databases

```bash
ls -la memory/
```

Expected:
```
-rw-r--r-- session.db
-rw-r--r-- global.db
-rw-r--r-- project.db
-rw-r--r-- cache.db
```

If absent, they'll be created on first run.

### 3. Quick Functionality Test

```bash
arke run "date +%Y-%m-%d"
```

Should output today's date. If not:
- Check Python version: `python3 --version` (must be 3.11+)
- Check sandbox: `which bwrap` (optional)
- Check permissions: `ls -l arke/`

---

## Troubleshooting

### "No module named 'arke'"

**Problem:** `arke` command not found after installation.

**Solution:**
```bash
# Ensure venv is activated
source .venv/bin/activate

# Reinstall
pip install -e .

# Verify
python -m arke --help
```

### "Telegram bot not responding"

**Problem:** Message sent to bot but no reply within 10 seconds.

**Solution:**

1. **Verify token is set:**
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   ```
   Should print your token. If empty:
   ```bash
   export TELEGRAM_BOT_TOKEN="your-token-here"
   arke --telegram
   ```

2. **Check bot is running:**
   ```bash
   # In another terminal
   curl http://localhost:8443/
   ```
   Should respond (or error if bot not HTTP-accessible).

3. **Check logs:**
   ```bash
   export LOG_LEVEL=DEBUG
   arke --telegram
   ```
   Look for errors in output.

4. **Known issue (Session 015):** Slash commands don't execute.
   - **Workaround:** Send text: "check system" instead of `/check`

### "Permission denied" in sandbox

**Problem:** `Error: Permission denied /tmp/arke-xxx`

**Solution:**

This means Bubblewrap sandbox hit a permission issue. Arke will fall back to unsandboxed execution (logged as `[FALLBACK: bwrap unavailable]`).

To fix:
```bash
# Install bwrap
sudo apt-get install bubblewrap

# Verify
which bwrap

# Re-run
arke run "echo test"
```

If still failing, disable sandbox temporarily:
```bash
export SANDBOX_ENABLED=false
arke run "echo test"
```

### "Database is locked"

**Problem:** `sqlite3.OperationalError: database is locked`

**Solution:**

Multiple instances of Arke running in parallel. SQLite doesn't handle concurrent writes well.

```bash
# Find running processes
ps aux | grep arke

# Kill if needed
pkill -f "arke"

# Restart
arke
```

### "LLM call timeout"

**Problem:** `Timeout: LLM call exceeded 30s`

**Solution:**

1. **Check internet connection**
2. **Check LLM provider status** (Gemini, Mistral, Claude down?)
3. **Increase timeout:**
   ```bash
   # In config/arke.toml
   [llm]
   timeout = 60  # was 30
   ```
4. **Check API keys:**
   ```bash
   echo $GEMINI_API_KEY  # should be set
   ```

### "Tests failing locally but passing in CI"

**Problem:** Some tests pass in CI but fail on your machine.

**Solution:**

1. **Check Python version:**
   ```bash
   python3 --version  # must be 3.11+
   ```

2. **Clear caches:**
   ```bash
   rm -rf .pytest_cache __pycache__ .mypy_cache .ruff_cache
   pytest tests/ -v
   ```

3. **Reinstall dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -e ".[dev]"
   ```

4. **Check environment:**
   ```bash
   env | grep -E "(GEMINI|MISTRAL|TELEGRAM|LOG_LEVEL)"
   ```

---

## Advanced Configuration

### OpenTelemetry Export

To enable distributed tracing:

1. **Install exporter:**
   ```bash
   pip install opentelemetry-exporter-otlp-proto-http
   ```

2. **Configure in `config/arke.toml`:**
   ```toml
   [telemetry]
   enabled = true
   exporter = "otlp_proto_http"
   endpoint = "http://localhost:4318"
   ```

3. **Start Jaeger (for visualization):**
   ```bash
   docker run -d -p 6831:6831/udp -p 16686:16686 jaegertracing/all-in-one
   ```

4. **View traces:**
   ```
   http://localhost:16686
   ```

### LLM Fallback Strategy

Configure fallback order in `config/models.toml`:

```toml
fallback_order = [
    "gemini/gemini-2.0-flash",      # Try Gemini first (fast, cheap)
    "mistral/mistral-large-latest",  # Then Mistral
    "anthropic/claude-sonnet-4-5",   # Then Claude
    "ollama/mistral"                 # Local fallback
]
```

If one provider fails, Arke auto-retries next in list.

### Memory & Caching

```toml
[memory]
# Cache LLM responses for 1 hour
cache_ttl = 3600

# Vector embedding model
embedder = "gemini"

# FTS5 index size
max_fts_index = 100000  # documents
```

### Custom Skills

See [arke/skill_registry.py](./arke/skill_registry.py) for details.

```python
# Define a skill
skill = {
    "name": "my_skill",
    "definition": "Does something useful",
    "enabled": True,
    "tags": ["custom"]
}

# Register
arke run "register_skill my_skill"
```

---

## Development Setup

### 1. Install Dev Dependencies

```bash
pip install -e ".[dev]"
```

### 2. Run Tests Locally

```bash
# All tests with output
pytest tests/ -v -s

# Specific test file
pytest tests/test_orchestrator.py -v

# With coverage
pytest tests/ --cov=arke --cov-report=html
```

### 3. Code Quality

```bash
# Type checking (if mypy configured)
mypy arke/

# Linting (if ruff configured)
ruff check arke/

# Formatting (if black configured)
black arke/ --check
```

### 4. Add a New Tool

See [arke/tool_registry.py](./arke/tool_registry.py) and [Arke-architecture.md](./Arke-02-architecture/Arke-architecture.md).

### 5. Debug Mode

```bash
export LOG_LEVEL=DEBUG
export DEBUG=1
arke

# Verbose output
arke --debug
```

---

## Next Steps

- **Read:** [Arke-architecture.md](./Arke-02-architecture/Arke-architecture.md) for component details
- **Learn:** [Arke-cognitive-contract.md](./Arke-cognitive-contract.md) for philosophy
- **Contribute:** [CONTRIBUTING.md](./CONTRIBUTING.md) (when added)

---

**Questions?** Check [README.md](./README.md) or open a GitHub issue.

