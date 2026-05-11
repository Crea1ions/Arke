# 💻 code/ — Production Technical Artifacts

## Purpose

Clean, production-ready technical code — independent from cognitive/documentation layers.

---

## Structure

```
code/
├── apps/              # Standalone applications
├── services/          # Backend services / APIs
├── libs/              # Shared libraries & utilities
├── experiments/       # Prototypes, POCs, R&D
└── README.md          # Production rules (this file)
```

---

## Principles

1. **Pure code only** — No documentation here (use `/projects/TEMP/` for docs)
2. **Versioned & deployable** — Ready for production/staging
3. **Independent** — No cognitive logic or project structuring
4. **Clean boundaries** — Clear separation from knowledge layers

---

## Usage

### apps/

Standalone applications (can run independently).

Examples:
- `weather-dashboard/`
- `todo-cli/`
- `note-syncer/`

### services/

Backend services, microservices, APIs.

Examples:
- `auth-service/`
- `data-processor/`
- `api-gateway/`

### libs/

Shared libraries used by multiple apps/services.

Examples:
- `utils/`
- `crypto-helpers/`
- `database-connectors/`

### experiments/

Prototypes, proof-of-concepts, research code.

Examples:
- `ml-pipeline-poc/`
- `new-routing-algorithm/`
- `language-experiment/`

**Note**: Move to production folders once validated, archive when abandoned.

---

## Conventions

- Each project has its own `README.md` with setup/run instructions
- Use consistent package structure (language-specific conventions)
- Always include `.gitignore`
- Prefer monorepo structure over scattered repos

---

## Not Here

❌ Documentation (use `/projects/TEMP/`)
❌ Notes (use `/mobile-notes/`)
❌ Project tracking (use `/projects/TEMP/dev-tracking/`)
❌ Logs (keep in database/logs, not here)

---

*Last updated: 2026-05-11*
