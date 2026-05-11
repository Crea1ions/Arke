# 📱 mobile-notes/ — Multi-Channel Capture Layer

## Purpose

Quick-capture input from multiple sources (user notes, voice, channels).

**Key principle**: This is a capture layer, not a sync system. Channels forward messages to the orchestrator; the orchestrator decides if/when to store them.

---

## Structure

```
mobile-notes/
├── fleeting/          # Ephemeral quick notes (may be deleted later)
├── ideas/             # Structured ideas & concepts to develop
├── voice/             # Voice memo transcriptions
├── quick-capture/     # Rapid captures (Ctrl+K, etc.)
├── channels/          # I/O adapters (not sync)
│   ├── telegram/      # Telegram messages (user ↔ bot)
│   ├── discord/       # Discord messages (planned)
│   ├── email/         # Email captures (planned)
│   ├── obsidian/      # Obsidian vault sync (planned)
│   └── api/           # API-driven captures (planned)
└── archive/           # Inactive captures
```

---

## How to Use

### Manual Capture

1. **fleeting/** — Quick thoughts, don't worry about organization
   - Example: `2026-05-11-morning-thoughts.md`
   - Can be messy, temporal

2. **ideas/** — Concepts worth developing
   - Example: `wcu-architecture.md`, `cognitive-threads-design.md`
   - More structured than fleeting

3. **voice/** — Transcribed voice notes
   - Example: `2026-05-11-standup-notes.txt`
   - From dictation or voice memo apps

4. **quick-capture/** — Rapid captures (integration point for Ctrl+K, etc.)
   - Example: Auto-populated by capture tools

### Channel Adapters (Automated)

**Telegram, Discord, Email, Obsidian, API** are communication channels. They:

- **Receive user input** → forward to orchestrator
- **Receive Arke output** → display to user
- **Store if orchestrator decides** (via `STORE_MOBILE_NOTE_*` intents)

**Important**:
- Channels do NOT sync with external systems (that's orchestrator's job)
- Messages are stored only if orchestrator sends `STORE_MOBILE_NOTE_TELEGRAM`, etc.
- Users do NOT manually manage channel folders

### When to Archive

Move items to `archive/` when:
- Projects complete
- Notes are old/inactive
- Capture sessions end

---

## Orchestrator Integration

When Arke receives a Telegram message:

```
Telegram bot receives message
        ↓
Forwards to orchestrator (no filesystem access)
        ↓
Orchestrator evaluates → decides if STORE_MOBILE_NOTE_TELEGRAM
        ↓
workspace.py writes to mobile-notes/channels/telegram/
        ↓
Message stored if orchestrator decides
```

**User never manually manages this.**

---

## Content Guidelines

✅ **OK to store here**:
- Notes (any format: .md, .txt, .json)
- Transcriptions (voice-to-text)
- Channel messages (timestamped)
- Quick ideas (unrefined)

❌ **Not OK**:
- Code files (use `/code/` instead)
- Project documentation (use `/projects/TEMP/` instead)
- System logs (keep in SQLite)

---

## Naming Conventions

Suggested format for manual captures:

- `YYYY-MM-DD-[context]-[brief-title].[ext]`
- Example: `2026-05-11-planning-sprint-q2.md`

Channel storage (auto-generated):

- `[TIMESTAMP]-[SOURCE]-[MESSAGE_ID].[ext]`
- Example: `2026-05-11T14:30:22-telegram-m123456.json`

---

*Last updated: 2026-05-11*
