# 🏗️ WORKSPACE_ORCHESTRATION.md

Developer reference for Passive User Workspace (PUW) orchestration in Arke.

---

## 🎯 Architecture Principle

**LLM has zero visibility of workspace structure.**

All filesystem operations go through the **orchestrator**:

```
Orchestrator receives intent
        ↓
Look up intent → path mapping (INTENT_PATH_MAP)
        ↓
workspace.py executes I/O (orchestrator-only)
        ↓
Result stored in WCU
        ↓
LLM never knows about filesystem
```

### Workspace root semantics

- The active execution workspace defaults to the caller directory when `WORKSPACE_ROOT` is not explicitly set.
- The legacy WCU tree (`arke-workspace/WCU`) is optional and read-only from an orchestration perspective.
- Arke must not auto-create or auto-sync the caller directory into WCU.
- If a WCU root is provided explicitly and exists, it may be used for workspace views and legacy artifact storage.

---

## 📍 Intent→Path Mapping

Located in [arke/workspace.py](arke/workspace.py) as `INTENT_PATH_MAP`:

### Layer 1: mobile-notes/ (Capture)

| Intent | Path | Purpose |
|--------|------|---------|
| `STORE_MOBILE_NOTE_TELEGRAM` | `mobile-notes/channels/telegram/` | Store Telegram messages |
| `STORE_MOBILE_NOTE_DISCORD` | `mobile-notes/channels/discord/` | Store Discord messages |
| `STORE_MOBILE_NOTE_EMAIL` | `mobile-notes/channels/email/` | Store email captures |
| `STORE_MOBILE_NOTE_OBSIDIAN` | `mobile-notes/channels/obsidian/` | Store Obsidian sync |
| `STORE_MOBILE_NOTE_API` | `mobile-notes/channels/api/` | Store API captures |
| `CAPTURE_QUICK_NOTE` | `mobile-notes/quick-capture/` | Quick capture |
| `CAPTURE_FLEETING` | `mobile-notes/fleeting/` | Ephemeral notes |
| `CAPTURE_IDEA` | `mobile-notes/ideas/` | Concept development |
| `CAPTURE_VOICE` | `mobile-notes/voice/` | Voice transcriptions |

### Layer 4: shared/ (Restitution — Output)

| Intent | Path | Purpose |
|--------|------|---------|
| `WRITE_SESSION_SUMMARY` | `shared/session-summaries/` | Session recaps |
| `RECAP_DECISION` | `shared/decision-recaps/` | Decision synthesis |
| `LOG_DECISION` | `projects/TEMP/meta-decisions/` | Decision archive |
| `EXPORT_SHARED_INSIGHT` | `shared/generated-insights/` | Insights extracted by Arke |
| `LOG_USER_FACING_EVENT` | `shared/user-facing-logs/` | User-friendly event logs |
| `UPDATE_COGNITIVE_THREAD` | `shared/cognitive-threads/` | Cross-session themes |

### Layer 3: projects/TEMP/ (Structuration)

| Intent | Path | Purpose |
|--------|------|---------|
| `LOG_PROJECT_FEEDBACK` | `projects/TEMP/meta-feedback/` | User feedback, learnings |
| `LOG_PROJECT_OPS` | `projects/TEMP/ops-logs/` | Operational events |

---

## 🔧 How to Add a New Intent

### Step 1: Define the intent in [arke/workspace.py](arke/workspace.py)

```python
INTENT_PATH_MAP = {
    # ... existing intents ...
    "YOUR_NEW_INTENT": "path/to/storage/",
}
```

### Step 2: Orchestrator calls workspace manager

From [arke/orchestrator.py](arke/orchestrator.py) or any orchestrator-level code:

```python
from arke import workspace

# Get workspace manager (already initialized)
ws = workspace.get_workspace()

# Write artifact using intent
file_path = ws.write_artifact(
    intent="YOUR_NEW_INTENT",
    content="<markdown content>",
    filename="optional-custom-name.md",
    metadata={"key": "value", "timestamp": "2026-05-11T14:30:00"}
)
```

### Step 3: Update documentation

- Add intent to this file's intent mapping table
- Update [arke-workspace/WCU/README.md](arke-workspace/WCU/README.md) if layer structure changes
- Update relevant layer README ([shared/README.md](arke-workspace/WCU/shared/README.md), etc.)

### Step 4: Add tests

In [tests/test_wcu_structure.py](tests/test_wcu_structure.py):

```python
def test_new_intent_path():
    """Verify YOUR_NEW_INTENT maps to correct path."""
    ws = WorkspaceManager(WCU_ROOT)
    expected = WCU_ROOT / "path/to/storage/"
    assert ws.resolve_intent_path("YOUR_NEW_INTENT") == expected
```

---

## 🚨 CRITICAL Rules

### Stability Contract

1. ✅ **Add new intents** freely
2. ✅ **Add new workspace functions** without exposing to LLM
3. ❌ **Never modify existing intent paths**
4. ❌ **Never let LLM access workspace.py directly**
5. ❌ **Never put paths in LLM context/prompts**
6. ❌ **Never auto-create or sync WCU from the launcher cwd**

### Isolation

- **workspace.py**: Orchestrator-only
- **Telegram bot**: Zero filesystem knowledge (input/output adapter only)
- **LLM**: Completely opaque to filesystem

---

## 📚 WorkspaceManager API

[arke/workspace.py](arke/workspace.py) provides:

### `WorkspaceManager(wcu_root: Path)`

Initialize with WCU root path.

### `validate_structure() -> bool`

Check all required directories exist.

### `resolve_intent_path(intent: str) -> Optional[Path]`

Map intent to full path. Returns `None` if intent unknown.

### `write_artifact(intent, content, filename=None, metadata=None) -> Optional[Path]`

Write content to WCU. Auto-generates filename from timestamp + intent if not provided.

Metadata (if provided) prepended as YAML frontmatter.

### `read_artifact(file_path: Path) -> Optional[str]`

Read artifact from WCU.

### `list_artifacts(intent: str) -> Optional[list]`

List all files for an intent.

### `get_intent_list() -> list`

Return all available intents.

---

## 🧠 Module-Level API

### `initialize_workspace(wcu_root: Path) -> WorkspaceManager`

Initialize the workspace manager singleton when an explicit WCU root exists. **Call only from orchestrator.py on startup.**
This does not create missing directories automatically.

### `get_workspace() -> Optional[WorkspaceManager]`

Retrieve the singleton (after initialization). Safe to call from orchestrator-level code.

---

## 🔄 Example: Orchestrator Writing a Session Summary

```python
# In orchestrator.py or orchestrator-level code
from arke import workspace

ws = workspace.get_workspace()
if ws:
    summary_content = """
# Session 022 Summary
- Date: 2026-05-11
- Duration: 2 hours
- Completed: WCU implementation
- Next: Testing & validation
"""
    
    file_path = ws.write_artifact(
        intent="WRITE_SESSION_SUMMARY",
        content=summary_content,
        filename="2026-05-11_SESSION_022.md",
        metadata={
            "session_id": 22,
            "date": "2026-05-11",
            "duration_minutes": 120
        }
    )
    # file_path = /path/to/arke-workspace/WCU/shared/session-summaries/2026-05-11_SESSION_022.md
```

---

## 🧪 Testing

See [tests/test_wcu_structure.py](tests/test_wcu_structure.py) for:

- ✅ Directory structure validation
- ✅ Intent→path mapping verification
- ✅ Write/read artifact testing
- ✅ Orchestrator initialization
- ✅ Regression tests (legacy intents unchanged)
- ❌ Never test LLM context awareness (should not exist)

---

## 🚀 For Arke Users

If you're using Arke and see files appearing in your workspace:

- **shared/session-summaries/** — Arke's session recaps (read-only recommended)
- **mobile-notes/channels/telegram/** — Telegram messages stored by Arke (read-only)
- **shared/generated-insights/** — Insights extracted by Arke (read-only)

**You are free to**:
- Organize your own content in projects/TEMP/, mobile-notes/fleeting/, etc.
- Create your own sub-folders for custom organization
- Archive old work

**Arke will**:
- Never delete your data
- Never reorganize without asking
- Only write to specific intent paths

---

## 📖 Related Documentation

- [arke-workspace/WCU/README.md](arke-workspace/WCU/README.md) — User-facing WCU overview
- [arke/workspace.py](arke/workspace.py) — Implementation
- [arke/orchestrator.py](arke/orchestrator.py) — Integration point
- [tests/test_wcu_structure.py](tests/test_wcu_structure.py) — Validation tests

---

*Last updated: 2026-05-11*
