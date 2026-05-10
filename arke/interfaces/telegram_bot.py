"""TelegramBot — pure transport adapter for Arke kernel v1.2.

Responsibility: receive Telegram messages, forward to agent via
``chat.py:_ask_agent()``, and route tool execution through
``orchestrator`` while maintaining cognitive contract.

Zero business logic lives here — this is transport only.

Usage:
    1. Configure token: arke /config → 5. Telegram Bot
    2. Start the bot:  arke --telegram
    Or daemon mode:    arke --telegram --daemon

Environment:
    TELEGRAM_BOT_TOKEN — Bot token from BotFather (required).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import structlog
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from arke import orchestrator
from arke.chat import build_cognitive_context, _ask_agent
from arke.task_graph import StepStatus

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Response formatting — Telegram 4096 char limit
# ---------------------------------------------------------------------------


def _chunk_message(text: str, max_length: int = 4096) -> list[str]:
    """Split text into chunks respecting Telegram's message limit."""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current = ""
    
    # Split by lines and respect max_length per chunk
    for line in text.split("\n"):
        # If adding this line would exceed limit, start new chunk
        potential_length = len(current) + len(line) + (1 if current else 0)
        if current and potential_length > max_length:
            chunks.append(current.rstrip())
            current = line + "\n"
        else:
            if current:
                current += "\n"
            current += line
    
    # Add remaining content
    if current:
        chunks.append(current.rstrip())
    
    return chunks if chunks else [text[:max_length]]


# ---------------------------------------------------------------------------
# Handlers — agent-first dispatch
# ---------------------------------------------------------------------------


async def _handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
    """Respond to /start command."""
    await _execute_command(update, "/start")


async def _handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
    """Respond to /help command."""
    await _execute_command(update, "/help")


async def _handle_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
    """Respond to /check command."""
    await _execute_command(update, "/check")


async def _handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
    """Respond to /stats command."""
    await _execute_command(update, "/stats")


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
    """Forward message to agent and route tool execution.
    
    Special handling for slash commands (/check, /stats, etc.) — execute
    Python handlers directly (like terminal), not via agent.
    """
    if not update.message or not update.message.text:
        return

    intention = update.message.text.strip()
    chat_id = update.effective_chat.id  # type: ignore[union-attr]

    log.info("telegram.received", chat_id=chat_id, intention=intention)

    # Check if this is a special slash command
    if intention.startswith("/"):
        await _execute_command(update, intention)
        return

    # Build cognitive context for this Telegram session
    cognitive_json = build_cognitive_context(intention, session_id=f"telegram:{chat_id}")
    ctx: dict[str, Any] = {
        "session_id": f"telegram:{chat_id}",
        "channel": "telegram",
    }

    # Ask agent what to do (direct response or tool execution)
    agent_decision = _ask_agent(cognitive_json, intention, ctx)

    # Case 1: Agent wants direct response (no tool)
    if agent_decision.get("tool") is None:
        reply = agent_decision.get("response", "(no response)")
        for chunk in _chunk_message(reply):
            await update.message.reply_text(chunk)  # type: ignore[union-attr]
        return

    # Case 2: Agent requests tool execution
    tool_name = agent_decision.get("tool")
    log.info("telegram.agent_requested_tool", tool_name=tool_name)

    # Execute via orchestrator (maintains tool-side safety)
    loop = asyncio.get_event_loop()
    task = await loop.run_in_executor(
        None, orchestrator.run, intention, ctx
    )

    # Format result
    if task.status == StepStatus.SUCCESS:
        last_step = task.steps[-1] if task.steps else None
        if last_step and last_step.output:
            output = last_step.output
            if isinstance(output, dict):
                text = output.get("stdout", "").rstrip()
            else:
                text = str(output).rstrip()
        else:
            text = "(success, no output)"
    else:
        failed_step = next(
            (s for s in task.steps if s.status == StepStatus.FAILED), None
        )
        if failed_step:
            text = f"❌ Failed at step {failed_step.id}: {failed_step.error or 'unknown error'}"
        else:
            text = "❌ Task execution failed"

    reply = text or "(no output)"
    log.info("telegram.reply", chat_id=chat_id, length=len(reply))

    # Send in chunks if necessary
    for chunk in _chunk_message(reply):
        await update.message.reply_text(chunk)  # type: ignore[union-attr]


async def _execute_command(update: Update, command: str) -> None:
    """Execute special slash commands directly (like terminal).
    
    Maps /check, /stats, /model, /skill, /config to Python handlers.
    """
    # Create a printer function that collects output
    output_lines = []
    def printer(text: str = "") -> None:
        output_lines.append(text)
        log.debug("telegram.command_output", text=text)  # Debug logging
    
    cmd = command.split()[0].lower()  # Get command without args
    log.info("telegram.execute_command", cmd=cmd)
    
    try:
        if cmd == "/start":
            printer("🤖 **Arke Kernel v1.2**")
            printer("")
            printer("Agent decides · System executes")
            printer("")
            printer("Channels: Terminal + Telegram ✅")
            printer("Status: Ready")
            printer("")
            printer("Use `/help` for commands")
            
        elif cmd == "/check":
            try:
                from arke.chat_config import print_check
                print_check(printer=printer)
            except Exception as exc:  # noqa: BLE001
                printer(f"⚠️  /check error: {exc}")
                log.error("telegram.check_error", error=str(exc))
                
        elif cmd == "/stats":
            try:
                from arke.skill_manager import SkillManager
                sm = SkillManager()
                stats = sm.get_stats()
                if not stats:
                    printer("📊 No tool usage recorded yet.")
                else:
                    printer("📊 **Tool Usage Statistics**\n")
                    for row in stats:
                        printer(
                            f"  {row['tool_name']:<12} "
                            f"{row['total_calls']:>3} calls · "
                            f"{row['successes']:>3} ok · "
                            f"{row['success_rate']:>5.1f}%"
                        )
            except Exception as exc:  # noqa: BLE001
                printer(f"⚠️  /stats error: {exc}")
                log.error("telegram.stats_error", error=str(exc))
                
        elif cmd == "/help":
            printer("🤖 **Arke Telegram Bot**\n")
            printer("**Commands:**\n")
            printer("  `/start` — Bot greeting + status")
            printer("  `/help` — This message")
            printer("  `/check` — System diagnostics")
            printer("  `/stats` — Tool usage statistics\n")
            printer("**Or send any text for agent-first execution.**")
            printer("")
            printer("The agent will decide whether to use tools (CLI, files, DB) or respond directly.")
            
        else:
            printer(f"❓ Unknown command: {cmd}")
            printer("Available: /start, /help, /check, /stats")
            
    except Exception as exc:  # noqa: BLE001
        error_msg = f"❌ Error executing {cmd}: {exc}"
        printer(error_msg)
        log.error("telegram.command_error", cmd=cmd, error=str(exc), exc_info=True)
    
    # Send accumulated output
    output = "\n".join(output_lines)
    if not output:
        output = "⚠️  No output generated"
        log.warning("telegram.command_no_output", cmd=cmd)
    
    log.info("telegram.command_reply", cmd=cmd, length=len(output))
    
    # Send in chunks
    for chunk in _chunk_message(output):
        try:
            await update.message.reply_text(chunk)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            log.error("telegram.reply_error", chunk_len=len(chunk), error=str(exc))


# ---------------------------------------------------------------------------
# Bot lifecycle
# ---------------------------------------------------------------------------


def build_app(token: str) -> Application:
    """Build a configured telegram Application (agent-first).

    Args:
        token: Bot token from BotFather (e.g. from ~/.arke/.env TELEGRAM_BOT_TOKEN).

    Returns:
        Configured ``Application`` (not started yet).
    """
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", _handle_start))
    app.add_handler(CommandHandler("help", _handle_help))
    app.add_handler(CommandHandler("check", _handle_check))
    app.add_handler(CommandHandler("stats", _handle_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
    return app


def get_token() -> str:
    """Fetch TELEGRAM_BOT_TOKEN from environment or ~/.arke/.env."""
    # First try environment variable
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return token
    
    # Then try ~/.arke/.env
    try:
        from arke.chat_config import _env_list
        env_keys = _env_list()
        token = env_keys.get("TELEGRAM_BOT_TOKEN", "").strip()
        if token:
            return token
    except Exception:  # noqa: BLE001
        pass
    
    return ""


def main() -> None:
    """Start the Telegram bot (blocking, agent-first)."""
    token = get_token()
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN not found.\n"
            "Set it via: arke /config → 5. Telegram Bot\n"
            "Or export TELEGRAM_BOT_TOKEN in your shell."
        )

    log.info("telegram.start", token_preview=f"{token[:6]}...{token[-6:]}")
    app = build_app(token)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
