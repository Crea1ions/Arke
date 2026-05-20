"""ChatTheme — ANSI color palette + box-drawing utilities for Arke REPL.

Arke-dark theme (default) — inspired by Ghostty / VSCode Dark Modern.
All output respects ANSI_RESET so terminals without color support
degrade to plain text.

Public API
----------
- ``T``           : theme singleton (color/style constants)
- ``box()``       : render a bordered panel string
- ``header()``    : ``╭─ label · detail ─…─╮`` line
- ``thread_msg()``: full threaded message block
- ``model_icon()``: model name → display icon
- ``fmt_time()``  : datetime → ``HH:MM`` string
"""

from __future__ import annotations

import os
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

def _ansi(code: str) -> str:
    """Return ANSI escape if stdout supports color, else empty string."""
    if _NO_COLOR:
        return ""
    return f"\033[{code}m"


# _rgb / _rgb_bg removed — ANSI 4-bit palette only (no truecolor)


# Detect no-color environments
_NO_COLOR = (
    os.environ.get("NO_COLOR") is not None
    or os.environ.get("TERM") == "dumb"
    or not sys.stdout.isatty()
)

RESET   = _ansi("0")
BOLD    = _ansi("1")
DIM     = _ansi("2")
ITALIC  = _ansi("3")

# --- Arke semantic palette — ANSI 4-bit (16 colors) ----------------------
#  BORDER  → dim (code 2)          — structural chrome
#  TEXT    → default               — primary content
#  MUTED   → dim (code 2)          — secondary / metadata
#  ACCENT  → bright cyan  (96)     — Arke identity
#  SUCCESS → bright green (92)     — ok / done
#  WARNING → bright yellow (93)    — caution
#  ERROR   → bright red   (91)     — failure
#  USER_C  → white        (37)     — user input

BORDER  = _ansi("2")   # dim
TEXT    = ""            # terminal default (no code needed)
MUTED   = _ansi("2")   # dim
ACCENT  = _ansi("96")  # bright cyan
SUCCESS = _ansi("92")  # bright green
WARNING = _ansi("93")  # bright yellow
ERROR   = _ansi("91")  # bright red
USER_C  = _ansi("37")  # white
BLOCK_MARKER = _ansi("93")  # warm marker for message starts

# Per-model colors — ANSI 4-bit
_MODEL_COLOR = {
    "flash":   _ansi("96"),  # bright cyan
    "claude":  _ansi("95"),  # bright magenta
    "mistral": _ansi("92"),  # bright green
    "local":   _ansi("33"),  # yellow
    "pro":     _ansi("33"),  # yellow
}

# Per-model icons
_MODEL_ICON = {
    "flash":   "⚡",
    "claude":  "◆",
    "mistral": "◉",
    "local":   "⬡",
    "pro":     "★",
}

_DEFAULT_WIDTH = 80


# ---------------------------------------------------------------------------
# Public utilities
# ---------------------------------------------------------------------------

def model_color(alias: str) -> str:
    """Return ANSI color string for *alias* (defaults to ACCENT)."""
    return _MODEL_COLOR.get(alias, ACCENT)


def model_icon(alias: str) -> str:
    """Return the icon character for *alias* (defaults to '·')."""
    return _MODEL_ICON.get(alias, "·")


def model_label(alias: str) -> str:
    """Return colored ``Model icon`` string, e.g. ``Flash ⚡``."""
    col = model_color(alias)
    icon = model_icon(alias)
    return f"{col}{BOLD}{alias.capitalize()} {icon}{RESET}"


def arke_label(alias: str) -> str:
    """Return colored Arke wordmark using the current model color only."""
    return f"{model_color(alias)}{BOLD}Arke{RESET}"


def fmt_time() -> str:
    """Return current time as ``HH:MM``."""
    return datetime.now().strftime("%H:%M")


def _strip_ansi(s: str) -> str:
    """Remove ANSI escape sequences to compute visible length."""
    import re
    return re.sub(r"\033\[[0-9;]*m", "", s)


def _visible_len(s: str) -> int:
    return len(_strip_ansi(s))


# ---------------------------------------------------------------------------
# Box-drawing
# ---------------------------------------------------------------------------

def _hline(width: int, char: str = "─") -> str:
    return char * width


def box(lines: list[str], width: int = _DEFAULT_WIDTH, title: str = "") -> str:
    """Render a full ╭─…─╮ / │ … │ / ╰─…─╯ bordered panel.

    Args:
        lines: Content lines (may contain ANSI codes).
        width: Total panel width (default 80).
        title: Optional text embedded in the top border.

    Returns:
        Multi-line string ready to print.
    """
    inner = width - 2  # space between the two │ chars
    out: list[str] = []

    # Top border
    if title:
        t = f" {title} "
        t_len = _visible_len(t)
        left_fill = (inner - t_len) // 2
        right_fill = inner - t_len - left_fill
        top = (f"{BORDER}╭{_hline(left_fill)}{RESET}{BOLD}{ACCENT}{t}{RESET}"
               f"{BORDER}{_hline(right_fill)}╮{RESET}")
    else:
        top = f"{BORDER}╭{_hline(inner)}╮{RESET}"
    out.append(top)

    # Empty line after top border
    out.append(f"{BORDER}│{RESET}{' ' * inner}{BORDER}│{RESET}")

    # Content
    for line in lines:
        # Pad visible text to inner width
        vis = _visible_len(line)
        pad = inner - 2 - min(vis, inner - 2)  # 2-space left indent
        out.append(f"{BORDER}│{RESET}  {line}{' ' * max(0, pad)}{BORDER}│{RESET}")

    # Empty line before bottom border
    out.append(f"{BORDER}│{RESET}{' ' * inner}{BORDER}│{RESET}")
    out.append(f"{BORDER}╰{_hline(inner)}╯{RESET}")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Thread / conversation block helpers
# ---------------------------------------------------------------------------

def user_block(text: str, width: int = _DEFAULT_WIDTH) -> str:
    """Render a user message thread entry.

    Format::

        │
        ├─ user · HH:MM
        │  text
    """
    ts = fmt_time()
    header = f"{BORDER}├─{RESET} {USER_C}Toi {BLOCK_MARKER}◉{RESET} {MUTED}· {ts}{RESET}"
    content = f"{BORDER}{BLOCK_MARKER}└─{RESET} {TEXT}{text}{RESET}"
    return f"{BORDER}│{RESET}\n{header}\n{content}"


def agent_header(alias: str, width: int = _DEFAULT_WIDTH) -> str:
    """Render a colored Arke header line."""
    ts = fmt_time()
    return (f"{BORDER}│{RESET}\n"
            f"{BORDER}├─{RESET} {arke_label(alias)} {MUTED}· {ts}{RESET}")


def agent_footer(alias: str) -> str:
    """Return a colored Arke closing line."""
    ts = fmt_time()
    return f"{BORDER}└─{RESET} {arke_label(alias)} {MUTED}· {ts}{RESET}"


def step_line(tool: str, detail: str, prefix: str = "⠋") -> str:
    """``│  ⠋ tool    detail`` progress line."""
    tool_col = MUTED
    return f"{BORDER}│{RESET}  {tool_col}{prefix} {tool:<10}{RESET} {TEXT}{detail}{RESET}"


def step_ok(detail: str) -> str:
    """``│    ✓ detail`` success line."""
    return f"{BORDER}│{RESET}    {SUCCESS}✓{RESET} {MUTED}{detail}{RESET}"


def step_err(detail: str) -> str:
    """``│    ✗ detail`` error line."""
    return f"{BORDER}│{RESET}    {ERROR}✗{RESET} {MUTED}{detail}{RESET}"


def step_meta(kind: str, detail: str) -> str:
    """``│  ┆ kind    detail`` reflection/meta line."""
    return f"{BORDER}│{RESET}  {DIM}┆{RESET} {MUTED}{kind:<10}{RESET} {DIM}{detail}{RESET}"


def step_output(line: str) -> str:
    """``└─ line`` indented output line."""
    return f"{BORDER}{BLOCK_MARKER}└─{RESET} {TEXT}{line}{RESET}"


def done_line(tokens: int, elapsed: float, cost: float) -> str:
    """``│  ✓ terminé · N tokens · X.Xs · X.XXXX €``"""
    parts = [f"{SUCCESS}✓ terminé{RESET}"]
    if tokens:
        parts.append(f"{MUTED}{tokens} tokens{RESET}")
    parts.append(f"{MUTED}{elapsed:.1f} s{RESET}")
    if cost:
        parts.append(f"{MUTED}{cost:.4f} €{RESET}")
    return f"{BORDER}│{RESET}  " + f" {MUTED}·{RESET} ".join(parts)


def error_line(msg: str) -> str:
    return f"{BORDER}│{RESET}  {ERROR}✗ {msg}{RESET}"


def error() -> str:
    """Return error color code for inline use."""
    return ERROR


def success() -> str:
    """Return success color code for inline use."""
    return SUCCESS


def warning() -> str:
    """Return warning color code for inline use."""
    return WARNING


def llm_output_line(line: str) -> str:
    """LLM response line with left thread bar."""
    return f"{BORDER}{BLOCK_MARKER}└─{RESET} {TEXT}{line}{RESET}"


def prompt_line(alias: str) -> str:
    """Return the prompt string: ``Arke · HH:MM\n› ``"""
    ts = fmt_time()
    return f"\n{arke_label(alias)} {MUTED}· {ts}{RESET}\n{ACCENT}›{RESET} "


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

# Subtle top→bottom gradient for the logo — identity cyan, not per-model rainbow.
# "AR" area brighter sky, "KE" area slightly deeper blue-cyan.
# Logo rendered in a single ACCENT color — no gradient (4-bit compat)
_LOGO_GRADIENT = [ACCENT] * 6

_LOGO_LINES = [
    " █████╗ ██████╗ ██╗  ██╗███████╗",
    "██╔══██╗██╔══██╗██║ ██╔╝██╔════╝",
    "███████║██████╔╝█████╔╝ █████╗",
    "██╔══██║██╔══██╗██╔═██╗ ██╔══╝",
    "██║  ██║██║  ██║██║  ██╗███████╗",
    "╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝",
]

_TAGLINE = "Agent decides · System executes"

_BANNER_CMDS = [
    ("/help",   "aide & commandes"),
    ("/model",  "changer de LLM"),
    ("/stats",  "métriques"),
    ("/check",  "diagnostic"),
    ("/memory", "notes & contexte"),
    ("/about",  "à propos"),
]


def banner(sandbox: bool = True) -> str:
    """Render the Arke splash banner — left-aligned, runtime-focused."""
    width = 66
    inner = width - 2   # 64
    LM    = 3           # left margin

    def pad_line() -> str:
        return f"{BORDER}│{RESET}{' ' * inner}{BORDER}│{RESET}"

    def left(s: str) -> str:
        """Left-align content with margin, fill remaining width."""
        vis = _visible_len(s)
        rp  = max(0, inner - LM - vis)
        return f"{BORDER}│{RESET}{' ' * LM}{s}{' ' * rp}{BORDER}│{RESET}"

    lines: list[str] = []

    # ── top border ──────────────────────────────────────────────────────────
    lines.append(f"{BORDER}╭{'─' * inner}╮{RESET}")
    lines.append(pad_line())

    # ── logo: subtle cyan gradient, top-light → bottom-deep ─────────────────
    for i, logo_line in enumerate(_LOGO_LINES):
        c = _LOGO_GRADIENT[i % len(_LOGO_GRADIENT)]
        lines.append(left(f"{c}{BOLD}{logo_line}{RESET}"))

    lines.append(pad_line())

    # ── tagline ──────────────────────────────────────────────────────────────
    lines.append(left(f"{TEXT}{BOLD}{_TAGLINE}{RESET}"))
    lines.append(pad_line())

    # ── model agents with names + colored icons ───────────────────────────────
    model_parts: list[str] = []
    for alias in ("flash", "claude", "mistral", "local"):
        c    = _MODEL_COLOR[alias]
        icon = _MODEL_ICON[alias]
        model_parts.append(f"{c}{alias} {icon}{RESET}")
    lines.append(left("   ".join(model_parts)))

    lines.append(pad_line())

    # ── commands: single column, cmd left-padded to fixed width ──────────────
    cmd_w = max(len(cmd) for cmd, _ in _BANNER_CMDS) + 3  # e.g. 10
    for cmd, desc in _BANNER_CMDS:
        padded = cmd.ljust(cmd_w)
        lines.append(left(f"{ACCENT}{padded}{RESET}{MUTED}{desc}{RESET}"))

    lines.append(pad_line())

    # ── footer: runtime status ────────────────────────────────────────────────
    sbx_c   = SUCCESS if sandbox else WARNING
    sbx_str = "sandbox actif" if sandbox else "sandbox inactif"
    lines.append(left(f"{sbx_c}{sbx_str}{RESET}{MUTED} · mémoire FTS5{RESET}"))
    lines.append(pad_line())

    # ── bottom border ─────────────────────────────────────────────────────────
    lines.append(f"{BORDER}╰{'─' * inner}╯{RESET}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cognitive initiative block
# ---------------------------------------------------------------------------

_INITIATIVE_C = _ansi("95")  # bright magenta — cognitive initiative (4-bit)


def initiative_block(text: str) -> str:
    """Format a cognitive initiative for REPL display.

    Visually distinct from user/agent blocks to signal it is a system-initiated
    cognitive resumption, not a response to a user message.
    """
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M")
    header = (
        f"{BORDER}├─{RESET} {_INITIATIVE_C}◈ arke{RESET} "
        f"{MUTED}· {ts} · Dialogue actif{RESET}"
    )
    content = f"{BORDER}│{RESET}  {ITALIC}{_INITIATIVE_C}{text}{RESET}"
    return f"{BORDER}│{RESET}\n{header}\n{content}"
