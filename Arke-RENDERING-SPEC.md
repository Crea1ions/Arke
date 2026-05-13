---
title: "Arke Rendering Specification"
project: "Arke"
type: "reference"
status: "active"
created: 2026-05-13
tags:
  - arke
  - rendering
  - ansi
  - specification
aliases:
  - Rendering Spec
  - ANSI Specification
---

# 📋 Arke Rendering Specification

## Overview

This document defines the **canonical mapping** from Markdown styling tokens to ANSI escape codes used throughout Arke's terminal I/O layer. 

**Key Principle**: All rendering operations MUST use the mappings defined in `arke/rendering/rendering_spec.py`. No inline ANSI construction is permitted.

---

## ANSI 4-bit Palette

Arke uses ANSI 4-bit (16-color) codes only. No truecolor RGB codes are used.

### Semantic Color Mapping

| Style | ANSI Code | Hex | Usage |
|-------|-----------|-----|-------|
| **TEXT** | (default) | — | Primary content |
| **ACCENT** | `\033[96m` | Bright Cyan | Arke brand identity, headers |
| **SUCCESS** | `\033[92m` | Bright Green | Success messages, ✓ indicators |
| **WARNING** | `\033[93m` | Bright Yellow | Caution, warnings |
| **ERROR** | `\033[91m` | Bright Red | Errors, ✗ indicators |
| **MUTED** | `\033[2m` | Dim | Secondary text, timestamps |
| **USER** | `\033[37m` | White | User input |
| **BORDER** | `\033[2m` | Dim | Box drawing, structural elements |

### Text Styles

| Style | ANSI Code | Usage |
|-------|-----------|-------|
| **BOLD** | `\033[1m` | Emphasis, headers, important text |
| **DIM** | `\033[2m` | Secondary content, metadata |
| **ITALIC** | `\033[3m` | De-emphasis, alternative information |

### Reset Code

All styled spans must end with:
```
\033[0m
```

---

## Per-Model Colors

| Model | ANSI Code | Color |
|-------|-----------|-------|
| flash | `\033[96m` | Bright Cyan |
| claude | `\033[95m` | Bright Magenta |
| mistral | `\033[92m` | Bright Green |
| local | `\033[33m` | Yellow |

---

## MarkdownStyle Enum

The `MarkdownStyle` enum in `rendering_spec.py` defines all available styles:

```python
class MarkdownStyle(str, Enum):
    # Text styles
    BOLD = "bold"
    DIM = "dim"
    ITALIC = "italic"

    # Semantic colors
    TEXT = "text"
    MUTED = "muted"
    ACCENT = "accent"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    USER = "user"
    
    # Structural
    BORDER = "border"
    HEADER = "header"

    # Model-specific
    MODEL_FLASH = "model_flash"
    MODEL_CLAUDE = "model_claude"
    MODEL_MISTRAL = "model_mistral"
    MODEL_LOCAL = "model_local"
```

---

## API Usage

### Get ANSI Code

```python
from arke.rendering.rendering_spec import get_ansi_code, MarkdownStyle

code = get_ansi_code(MarkdownStyle.SUCCESS)
# Returns: "\033[92m"
```

### Create Styled Span

```python
from arke.rendering.rendering_spec import validate_ansi_span, MarkdownStyle

span = validate_ansi_span(MarkdownStyle.ERROR, "Error: Something went wrong")
# Returns: "\033[91mError: Something went wrong\033[0m"
```

### Compose Multiple Styles

```python
from arke.rendering.rendering_spec import style_text, MarkdownStyle

text = style_text("Important", MarkdownStyle.BOLD, MarkdownStyle.ACCENT)
# Applies BOLD then ACCENT to "Important"
```

### Model Colors

```python
from arke.rendering.rendering_spec import model_color

color = model_color("flash")
# Returns: "\033[96m" (bright cyan)
```

---

## NO_COLOR Support

When the `NO_COLOR` environment variable is set, `get_ansi_code()` returns empty strings, allowing graceful degradation to plain text.

```bash
NO_COLOR=1 arke chat
# Output will be plain text without ANSI codes
```

---

## Invariants

1. **Determinism**: Same style + text always produces same ANSI output
2. **Isolation**: ANSI codes never span multiple style applications (each has its own reset)
3. **Completeness**: Every `MarkdownStyle` enum value has exactly one ANSI mapping
4. **Compatibility**: Only ANSI 4-bit codes (no RGB truecolor)
5. **Accessibility**: Respects `NO_COLOR` environment variable

---

## Migration Notes

### From RGB Truecolor (Session 029)

Arke previously used RGB truecolor (`\033[38;2;R;G;Bm`). Session 030 migrated to ANSI 4-bit for:
- Better terminal compatibility (older terminals, SSH)
- Respect for user's terminal theme (respects dark/light modes)
- Consistent appearance across environments

### From Ad-hoc ANSI Construction (Session 030)

Rendering code previously scattered ANSI codes inline. Session 033 centralizes all mappings here for:
- Single source of truth
- Easier testing and validation
- Consistency guarantees
- Future extensibility

---

## Testing

Tests are in `tests/test_rendering_spec.py`:

```bash
pytest tests/test_rendering_spec.py -v
```

Coverage includes:
- All enum values have mappings
- ANSI codes are valid
- Span validation and nesting
- Model color selection
- NO_COLOR mode
- Edge cases (empty text, unknown models, etc.)

---

## Design Decisions

### Why ANSI 4-bit?

1. **Compatibility**: Works everywhere (ancient terminals, SSH, tmux, screen)
2. **Theme Respect**: Terminal dark/light modes are automatically respected
3. **Simplicity**: 16 colors are sufficient for structured output
4. **Consistency**: Predictable across all environments

### Why Centralized?

1. **Single Source of Truth**: No conflicting mappings
2. **Testability**: Can validate ANSI codes programmatically
3. **Maintainability**: Changes in one place affect all rendering
4. **Documentation**: Spec is code is documentation

### Why Composition?

Styles are applied via composition (`style_text(..., style1, style2)`) rather than complex nesting to:
- Avoid malformed ANSI sequences
- Ensure each style properly resets
- Allow easy testing of individual styles
- Support dynamic style combination

---

## Future Extensions

This spec is designed to be extended:

- Add new semantic styles by extending `MarkdownStyle` enum
- Add light/dark mode variants (map same style to different codes)
- Add custom theme support (override `STYLE_TO_ANSI` per environment)
- Add style validation/linting for user markdown input

---

**Version**: 1.0 (Session 033)  
**Last Updated**: 2026-05-13  
**Status**: Active
