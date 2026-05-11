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


def _rgb(r: int, g: int, b: int) -> str:
    if _NO_COLOR:
        return ""
    return f"\033[38;2;{r};{g};{b}m"


def _rgb_bg(r: int, g: int, b: int) -> str:
    if _NO_COLOR:
        return ""
    return f"\033[48;2;{r};{g};{b}m"


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

# --- Arke-dark semantic palette -------------------------------------------
#  border    #2A2F3A  → RGB(42,47,58)
#  surface   #171A21  → used for separators
#  text      #E6EAF2  → RGB(230,234,242)
#  muted     #8B93A7  → RGB(139,147,167)
#  accent    #6DD6FF  → RGB(109,214,255)  — Arke identity
#  success   #7EE787  → RGB(126,231,135)
#  warning   #E3B341  → RGB(227,179,65)
#  error     #FF7B72  → RGB(255,123,114)
#  user      #ADBAC7  → RGB(173,186,199)  — grey-cold
#  flash     #5FD7FF  → RGB(95,215,255)
#  claude    #C6A0FF  → RGB(198,160,255)
#  mistral   #7EE787  → RGB(126,231,135)
#  local     #FFB86B  → RGB(255,184,107)

BORDER  = _rgb(42, 47, 58)
TEXT    = _rgb(230, 234, 242)
MUTED   = _rgb(139, 147, 167)
ACCENT  = _rgb(109, 214, 255)
SUCCESS = _rgb(126, 231, 135)
WARNING = _rgb(227, 179, 65)
ERROR   = _rgb(255, 123, 114)
USER_C  = _rgb(173, 186, 199)

# Per-model colors
_MODEL_COLOR = {
    "flash":   _rgb(95, 215, 255),
    "claude":  _rgb(198, 160, 255),
    "mistral": _rgb(126, 231, 135),
    "local":   _rgb(255, 184, 107),
    "pro":     _rgb(255, 184, 107),
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
    """Return colored ``alias icon`` string, e.g. ``flash ⚡``."""
    col = model_color(alias)
    icon = model_icon(alias)
    return f"{col}{BOLD}{alias} {icon}{RESET}"


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
    header = f"{BORDER}├─{RESET} {USER_C}user{RESET} {MUTED}· {ts}{RESET}"
    content = f"{BORDER}│{RESET}  {TEXT}{text}{RESET}"
    return f"{BORDER}│{RESET}\n{header}\n{content}"


def agent_header(alias: str, width: int = _DEFAULT_WIDTH) -> str:
    """Render ``├─ arke · flash ⚡ · HH:MM`` header line."""
    ts = fmt_time()
    mlabel = model_label(alias)
    return (f"{BORDER}│{RESET}\n"
            f"{BORDER}├─{RESET} {ACCENT}{BOLD}arke{RESET} "
            f"{MUTED}·{RESET} {mlabel} "
            f"{MUTED}· {ts}{RESET}")


def agent_footer(alias: str) -> str:
    """Return ``└─ arke · flash ⚡ · HH:MM`` closing line."""
    ts = fmt_time()
    mlabel = model_label(alias)
    return (f"{BORDER}└─{RESET} {ACCENT}{BOLD}arke{RESET} "
            f"{MUTED}·{RESET} {mlabel} "
            f"{MUTED}· {ts}{RESET}")


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
    """``│      line`` indented output line."""
    return f"{BORDER}│{RESET}      {TEXT}{line}{RESET}"


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


def llm_output_line(line: str) -> str:
    """LLM response line with left thread bar."""
    return f"{BORDER}│{RESET}  {TEXT}{line}{RESET}"


def prompt_line(alias: str) -> str:
    """Return the prompt string: ``flash ⚡ · HH:MM\\n› ``"""
    ts = fmt_time()
    mlabel = model_label(alias)
    return f"\n{mlabel} {MUTED}· {ts}{RESET}\n{ACCENT}›{RESET} "


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

# Subtle top→bottom gradient for the logo — identity cyan, not per-model rainbow.
# "AR" area brighter sky, "KE" area slightly deeper blue-cyan.
_LOGO_GRADIENT = [
    _rgb(139, 233, 253),   # #8BE9FD  bright sky        (top)
    _rgb(109, 214, 255),   # #6DD6FF  ACCENT            (mid-high)
    _rgb(95,  215, 255),   # #5FD7FF  flash cyan        (mid)
    _rgb(95,  215, 255),   # #5FD7FF  flash cyan        (mid)
    _rgb(72,  196, 252),   # #48C4FC  slightly deeper   (low)
    _rgb(55,  178, 248),   # #37B2F8  deepest           (bottom)
]

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

_INITIATIVE_C = _rgb(181, 160, 255)  # soft violet — distinct from all other roles


def initiative_block(text: str) -> str:
    """Format a cognitive initiative for REPL display.

    Visually distinct from user/agent blocks to signal it is a system-initiated
    cognitive resumption, not a response to a user message.
    """
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M")
    header = f"{BORDER}├─{RESET} {_INITIATIVE_C}◈ arke{RESET} {MUTED}· {ts} · reprise cognitive{RESET}"
    content = f"{BORDER}│{RESET}  {ITALIC}{_INITIATIVE_C}{text}{RESET}"
    return f"{BORDER}│{RESET}\n{header}\n{content}"
