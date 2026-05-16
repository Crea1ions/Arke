# -*- coding: utf-8 -*-
"""Stateless startup banner renderer for the Arke REPL."""

from __future__ import annotations

import os
import shutil
import sys

MIN_WIDTH = 84
FULL_GAP = "    "

RESET = "\033[0m"
CYAN = "\033[96m"
BLUE = "\033[94m"
WHITE = "\033[37m"
GRAY = "\033[90m"
MAGENTA = "\033[95m"
YELLOW = "\033[93m"

ARKE_LINES = [
    "  █████╗ ██████╗ ██╗  ██╗███████╗",
    "  ██╔══██╗██╔══██╗██║ ██╔╝██╔════╝",
    "  ███████║██████╔╝█████╔╝ █████╗  ",
    "  ██╔══██║██╔══██╗██╔═██╗ ██╔══╝  ",
    "  ██║  ██║██║  ██║██║  ██╗███████╗",
    "  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝",
]

AGENT_LINES = [
    "█████╗  ██████╗ ███████╗███╗   ██╗████████╗",
    "██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝",
    "███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ",
    "██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ",
    "██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ",
    "╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ",
]

LEFT_TITLE_WIDTH = 34
RIGHT_TITLE_WIDTH = 44


def c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            os.system("")
        except Exception:
            return False
    return True


def supports_unicode() -> bool:
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    return (not encoding) or ("utf" in encoding)


def _display_width(text: str) -> int:
    try:
        from wcwidth import wcswidth

        width = wcswidth(text)
        return width if width >= 0 else len(text)
    except Exception:
        return len(text)


def _pad_visual(text: str, width: int) -> str:
    pad = max(0, width - _display_width(text))
    return text + (" " * pad)


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


def _separator(width: int, cap: int) -> str:
    return "-" * max(1, min(width, cap))


def build_banner_lines(context: dict) -> list[str]:
    width = int(context.get("width") or 80)
    workspace = str(context.get("workspace") or "")
    workspace_name = workspace.rstrip("/").split("/")[-1] if workspace else "unknown"
    model = str(context.get("model") or "flash")
    mode = str(context.get("mode") or "ask")
    is_compact = bool(context.get("is_compact", width < MIN_WIDTH or not supports_unicode()))

    if is_compact:
        sep = _separator(width, 50)
        return [
            "ARKE-AGENT",
            _truncate("- Une fondation commune pour penser et construire.", width),
            _truncate("- arche · themelios", width),
            sep,
            _truncate("/ask /search /plan /agent /help", width),
            _truncate(f'@"model" switch models LLM ({model})', width),
            sep,
            _truncate(f"workspace: {workspace_name}", width),
            _truncate("memory: active", width),
            _truncate(f"mode: {mode}", width),
            sep,
        ]

    title_lines = [
        f"{_pad_visual(left, LEFT_TITLE_WIDTH)}{FULL_GAP}{_pad_visual(right, RIGHT_TITLE_WIDTH)}"
        for left, right in zip(ARKE_LINES, AGENT_LINES)
    ]
    sep = _separator(width, max(len(title_lines[0]), 80))
    return [
        *title_lines,
        "",
        "- Une fondation commune pour penser et construire.",
        "- arche · themelios",
        sep,
        f"{'/ask':<16}explore & reason",
        f"{'/search':<16}retrieve & inspect",
        f"{'/plan':<16}structure before action",
        f"{'/agent':<16}execute with confirmation",
        f"{'/help':<16}commands & usage",
        f'{"@\"model\"":<16}switch models LLM ({model})',
        sep,
        f"{'workspace':<12}connected",
        f"{'memory':<12}active",
        f"{'mode':<12}{mode}",
        sep,
    ]


def _render_compact_line(line: str) -> str:
    if line == "ARKE-AGENT":
        return f"{c('ARKE', CYAN)}-{c('AGENT', BLUE)}"
    if set(line) == {"-"}:
        return c(line, GRAY)
    if line.startswith("/"):
        return " ".join(c(token, CYAN) for token in line.split())
    if line.startswith('@"model"'):
        label = '@"model"'
        return f"{c(label, MAGENTA)}{c(line[len(label):], GRAY)}"
    if line.startswith("workspace:") or line.startswith("memory:") or line.startswith("mode:"):
        label, _, value = line.partition(":")
        value_color = YELLOW if label == "mode" else WHITE
        return f"{c(label + ':', GRAY)} {c(value.strip(), value_color)}"
    if line.startswith("- arche"):
        return c(line, GRAY)
    return c(line, WHITE)


def _render_full_line(index: int, line: str) -> str:
    if index < len(ARKE_LINES):
        left = _pad_visual(ARKE_LINES[index], LEFT_TITLE_WIDTH)
        right = _pad_visual(AGENT_LINES[index], RIGHT_TITLE_WIDTH)
        return f"{c(left, CYAN)}{FULL_GAP}{c(right, BLUE)}"
    if set(line) == {"-"}:
        return c(line, GRAY)
    if line.startswith("- Une"):
        return c(line, WHITE)
    if line.startswith("- arche"):
        return c(line, GRAY)
    if line.startswith("/"):
        label = line[:16]
        desc = line[16:]
        return f"{c(label, CYAN)}{c(desc, WHITE)}"
    if line.startswith('@"model"'):
        label = line[:16]
        desc = line[16:]
        return f"{c(label, MAGENTA)}{c(desc, GRAY)}"
    if line.startswith("workspace") or line.startswith("memory") or line.startswith("mode"):
        label = line[:12]
        value = line[12:]
        value_color = YELLOW if label.strip() == "mode" else WHITE
        return f"{c(label, GRAY)}{c(value, value_color)}"
    return line


def render_banner(lines: list[str], context: dict) -> list[str]:
    if not supports_color():
        return lines

    is_compact = bool(context.get("is_compact", False))
    if is_compact:
        return [_render_compact_line(line) for line in lines]
    return [_render_full_line(index, line) for index, line in enumerate(lines)]


def generate_banner(
    workspace: str = "",
    model: str = "",
    mode: str = "",
    width: int | None = None,
) -> list[str]:
    if width is None:
        width = shutil.get_terminal_size((80, 24)).columns
    context = {
        "workspace": workspace,
        "model": model,
        "mode": mode,
        "width": width,
        "is_compact": width < MIN_WIDTH or not supports_unicode(),
    }
    return render_banner(build_banner_lines(context), context)
