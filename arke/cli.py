"""CLI — Arke, agent cognitif autonome.

``arke`` (sans argument) lance le chat interactif — porte d'entrée principale.
Les sous-commandes sont réservées aux usages scripting/CI.

Usage:
    arke                            Chat interactif (défaut)
    arke run "<intention>"          Exécute une intention (scripting)
    arke memory query "<sql>"       Requête mémoire (scripting)
    arke skill list / prune         Gestion des skills (scripting)
"""

from __future__ import annotations

import json
import sys
from typing import Optional

import structlog
import typer

from arke import orchestrator
from arke.task_graph import StepStatus
from arke.telemetry import init_tracer

# Initialise OTel (no-op when telemetry.enabled = false)
try:
    init_tracer()
except Exception:  # noqa: BLE001
    pass

# ---------------------------------------------------------------------------
# Logging — JSON output
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="arke",
    help="Arke — agent cognitif autonome. Tapez 'arke' pour démarrer le chat.",
    add_completion=False,
    invoke_without_command=True,
)

memory_app = typer.Typer(help="Memory database commands (scripting).")
app.add_typer(memory_app, name="memory")

skill_app = typer.Typer(help="Skill management commands (scripting).")
app.add_typer(skill_app, name="skill")


@app.callback(invoke_without_command=True)
def default(
    ctx: typer.Context,
    telegram: bool = typer.Option(
        False,
        "--telegram",
        "-t",
        help="Start Telegram bot instead of interactive chat.",
    ),
    daemon: bool = typer.Option(
        False,
        "--daemon",
        "-d",
        help="Run Telegram bot in background (requires --telegram).",
    ),
) -> None:
    """Launch interactive chat unless a subcommand or --telegram is specified."""
    import os
    # Si WORKSPACE_ROOT n'est pas défini, injecte le dossier courant
    if "WORKSPACE_ROOT" not in os.environ:
        os.environ["WORKSPACE_ROOT"] = os.getcwd()
    if ctx.invoked_subcommand is None:
        if telegram:
            _start_telegram(daemon=daemon)
        else:
            from arke.chat import start
            start()


@app.command("chat")
def chat_cmd() -> None:
    """Mode chat interactif (alias explicite)."""
    import os
    if "WORKSPACE_ROOT" not in os.environ:
        os.environ["WORKSPACE_ROOT"] = os.getcwd()
    from arke.chat import start
    start()


@app.command()
def run(
    intention: str = typer.Argument(..., help="Natural-language intention to execute."),
    context_json: Optional[str] = typer.Option(
        None,
        "--context",
        "-c",
        help="JSON object with execution context (e.g. '{\"log_file\": \"access.log\"}').",
    ),
) -> None:
    """Execute an intention through the Arke kernel."""

    import os
    ctx: dict = {}
    if context_json:
        try:
            ctx = json.loads(context_json)
        except json.JSONDecodeError as exc:
            typer.echo(f"Error: invalid --context JSON — {exc}", err=True)
            raise typer.Exit(1)
    # Si WORKSPACE_ROOT n'est pas défini, injecte le dossier courant
    if "WORKSPACE_ROOT" not in os.environ:
        os.environ["WORKSPACE_ROOT"] = os.getcwd()
    ctx["WORKSPACE_ROOT"] = os.environ["WORKSPACE_ROOT"]

    task = orchestrator.run(intention, ctx)

    if task.status == StepStatus.SUCCESS:
        # Print the final step output to stdout
        last = task.steps[-1]
        output = last.output
        if isinstance(output, dict):
            typer.echo(output.get("stdout", "").rstrip())
        else:
            typer.echo(str(output).rstrip())
        # Detect patterns and propose new skills interactively
        if sys.stdin.isatty():
            _maybe_propose_skills()
    else:
        typer.echo(f"Task failed at step: {_first_failed(task)}", err=True)
        raise typer.Exit(1)


@memory_app.command("query")
def memory_query(
    sql: str = typer.Argument(..., help="SQL query to execute."),
    db: str = typer.Option("global", "--db", help="Database name: global|project|session|cache."),
) -> None:
    """Execute a raw SQL query against a memory database."""
    from arke.memory.manager import MemoryManager

    mm = MemoryManager()
    rows = mm.query(db, sql, ())
    for row in rows:
        typer.echo(json.dumps(dict(row), default=str))


@memory_app.command("stats")
def memory_stats() -> None:
    """Show per-tool usage statistics (success count, rate, calls)."""
    from arke.skill_manager import SkillManager

    sm = SkillManager()
    stats = sm.get_stats()

    if not stats:
        typer.echo("No tool usage recorded yet.")
        return

    header = f"{'Tool':<12} {'Calls':>6} {'Successes':>10} {'Rate':>8}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for row in stats:
        typer.echo(
            f"{row['tool_name']:<12} {row['total_calls']:>6}"
            f" {int(row['successes']):>10} {row['success_rate']:>7.1f}%"
        )


@memory_app.command("search")
def memory_search(
    term: str = typer.Argument(..., help="Full-text search term."),
    db: str = typer.Option("project", "--db", help="Database name (default: project)."),
) -> None:
    """Full-text search (FTS5) in a memory database."""
    from arke.memory.manager import MemoryManager

    mm = MemoryManager()
    rows = mm.search(db, term)
    for row in rows:
        typer.echo(json.dumps(dict(row), default=str))


@memory_app.command("semantic")
def memory_semantic(
    term: str = typer.Argument(..., help="Natural-language search query."),
    k: int = typer.Option(5, "--top", "-k", help="Number of results to return."),
) -> None:
    """Semantic (vector) search in the document index.

    Requires ``[vector] enabled = true`` in arke.toml.
    Falls back to a clear message when vector search is disabled.
    """
    from arke.vector import Embedder, VectorDisabledError, VectorIndex, load_vector_config
    from arke.memory.manager import MemoryManager

    cfg = load_vector_config()
    enabled = cfg.get("enabled", True)

    if not enabled:
        typer.echo(
            "Vector search est désactivé (vector_search = false dans arke.toml).\n"
            "Utilisez 'arke memory search' pour la recherche FTS5.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        embedder = Embedder()
        query_vec = embedder.embed(term)
    except VectorDisabledError as exc:
        typer.echo(f"Erreur : {exc}", err=True)
        raise typer.Exit(1)

    mm = MemoryManager()
    db_path = mm._paths["global"]
    index = VectorIndex(db_path=db_path, dimensions=embedder.dimensions, enabled=True)

    results = index.search(query_vec, k=k)

    if not results:
        typer.echo("Aucun résultat.")
        return

    for r in results:
        typer.echo(
            json.dumps(
                {"doc_id": r["doc_id"], "distance": r["distance"], "content": r["content"]},
                ensure_ascii=False,
            )
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _start_telegram(daemon: bool = False) -> None:
    """Start the Telegram bot.
    
    Args:
        daemon: If True, start in background (not fully implemented for daemon).
    """
    try:
        from arke.interfaces.telegram_bot import get_token, main
        
        # Validate token is configured
        token = get_token()
        if not token:
            typer.echo(
                "❌ TELEGRAM_BOT_TOKEN not configured.\n"
                "Set it up with: arke /config → 5. Telegram Bot",
                err=True,
            )
            raise typer.Exit(1)
        
        # Start bot
        typer.echo("🤖 Starting Telegram bot (Ctrl+C to stop)...")
        if daemon:
            typer.echo("  (daemon mode not yet implemented; running in foreground)")
        main()
        
    except ImportError as exc:
        typer.echo(f"Error: Telegram dependencies not installed — {exc}", err=True)
        raise typer.Exit(1)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


def _first_failed(task) -> str:  # noqa: ANN001
    for step in task.steps:
        if step.status == StepStatus.FAILED:
            return step.id
    return "unknown"


def _maybe_propose_skills() -> None:
    """Detect new skill candidates and prompt the user to activate them."""
    from arke.skill_detector import SkillDetector
    from arke.skill_registry import SkillRegistry

    try:
        templates = SkillDetector().detect_new()
    except Exception:  # noqa: BLE001
        return

    for tmpl in templates:
        answer = typer.prompt(
            f"\nNouveau skill détecté : '{tmpl.name}' ({tmpl.tool}, "
            f"{tmpl.trigger_count}×). Créer le skill ? [oui/non]",
            default="non",
        )
        if answer.strip().lower() in ("oui", "o", "yes", "y"):
            skill_id = SkillRegistry().activate(tmpl)
            typer.echo(f"✓ Skill '{tmpl.name}' activé (id: {skill_id[:8]})")
        else:
            typer.echo(f"  Skill '{tmpl.name}' ignoré.")


# ---------------------------------------------------------------------------
# Skill commands
# ---------------------------------------------------------------------------


@skill_app.command("list")
def skill_list() -> None:
    """List active auto-generated skills (score réutilisabilité inclus)."""
    from arke.skill_registry import SkillRegistry

    skills = SkillRegistry().list_active()

    if not skills:
        typer.echo("Aucun skill actif.")
        return

    header = f"{'Name':<30} {'Tool':<8} {'Uses':>5} {'Score':>7} {'ID'}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for s in skills:
        typer.echo(
            f"{s['name']:<30} {s['tool']:<8} {int(s['usage_count']):>5}"
            f" {float(s['reuse_score']):>7.3f} {s['id'][:8]}"
        )


@skill_app.command("prune")
def skill_prune() -> None:
    """Remove skills unused for more than 30 days."""
    from arke.skill_registry import SkillRegistry

    deleted = SkillRegistry().prune()
    if deleted == 0:
        typer.echo("Aucun skill à supprimer.")
    else:
        typer.echo(f"{deleted} skill(s) supprimé(s) (inactifs depuis >30j).")


if __name__ == "__main__":
    app()
