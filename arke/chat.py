"""Arke Chat — REPL interactif à la Claude Code.

Usage::

    arke chat

Boucle REPL avec :
- Prompt modèle + heure avec readline history (↑/↓)
- 5 modes d'entrée via :mod:`arke.chat_router`
- Affichage step-by-step de l'orchestrateur dans un fil threadé
- Résumé coût/tokens/durée après chaque tâche
- LLM conversationnel direct (bypass orchestrateur)
- Contexte multi-tour (5 derniers échanges injectés)
- Ctrl+C double : 1er interrompt la tâche, 2e quitte
- Ctrl+D / /exit : quitter proprement
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import readline  # noqa: F401 — side-effect: enables readline in input()
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from arke.chat_router import (
    MODEL_ALIASES,
    SLASH_COMMANDS,
    RouteKind,
    RouteResult,
    history_append,
    history_recent,
    memory_forget,
    memory_read,
    memory_write,
    route,
)
from arke.anti_drift_metrics import get_metrics_instance
from arke.tool_registry import TOOL_REGISTRY
from arke.thread_extractor import extract_async
from arke.social_orchestrator import SocialOrchestrator

log = structlog.get_logger()

# Theme is loaded lazily so tests that don't import chat.py directly still work
from arke import chat_theme as T  # noqa: E402

_ARKE_ENV_PATH = Path.home() / ".arke" / ".env"

# Visual placeholder for newline in the paste-review prompt
_PASTE_NL = " ↵ "


def _read_paste_buffered(prompt: str) -> str:
    """Read one user turn, absorbing pasted multiline text into a review step.

    For single-line input the behaviour is identical to ``input(prompt)``.
    When the OS stdin buffer still contains data after the first ``input()``
    call (i.e. the user pasted multiple lines), the remaining bytes are drained
    via a non-blocking ``os.read()`` loop, assembled into a single string, and
    re-injected into a second ``input()`` so the user can review and edit before
    confirming with Enter.

    The fd ``O_NONBLOCK`` flag is always restored in a ``finally`` block.
    """
    first_line = input(prompt)

    fd = sys.stdin.fileno()
    old_fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, old_fl | os.O_NONBLOCK)
    buf = b""
    try:
        while True:
            try:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                buf += chunk
            except BlockingIOError:
                break
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, old_fl)

    if not buf:
        return first_line

    # Decode + normalise line endings
    extra = buf.decode("utf-8", errors="replace").replace("\r\n", "\n")
    full_text = (first_line + "\n" + extra).rstrip("\n")

    # Build display: replace \n with _PASTE_NL for inline review
    display = full_text.replace("\n", _PASTE_NL)

    def _pre_hook() -> None:
        readline.insert_text(display)
        readline.redisplay()

    readline.set_pre_input_hook(_pre_hook)
    try:
        reviewed = input(prompt)
    finally:
        readline.set_pre_input_hook(None)

    return reviewed.replace(_PASTE_NL, "\n")


# Active model alias for the current session (mutable via @alias or /model)
_active_model_alias: list[str] = ["flash"]

# Spinner frames for loading indication
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_spinner_state: list[int] = [0]


def _spinner_tick() -> None:
    """Print a spinner frame to indicate processing."""
    frame = _SPINNER_FRAMES[_spinner_state[0] % len(_SPINNER_FRAMES)]
    sys.stderr.write(f"\r{frame} Processing...")
    sys.stderr.flush()
    _spinner_state[0] += 1


def _spinner_stop() -> None:
    """Clear spinner and return to normal prompt."""
    sys.stderr.write("\r" + " " * 20 + "\r")
    sys.stderr.flush()


def _get_alias() -> str:
    return _active_model_alias[0]


def _set_alias(alias: str) -> None:
    _active_model_alias[0] = alias


def _load_env_file() -> None:
    """Load ``~/.arke/.env`` into ``os.environ`` (API keys for litellm)."""
    if not _ARKE_ENV_PATH.exists():
        return
    for line in _ARKE_ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip()


def _silence_logs() -> None:
    """Silence structlog JSON output during chat mode (CRITICAL level only)."""
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(50),  # CRITICAL
    )


def _load_agent_config() -> dict:
    """Load [agent] section from config/arke.toml."""
    import tomllib
    config_path = Path(__file__).parent.parent / "config" / "arke.toml"
    try:
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)
        return data.get("agent", {})
    except Exception:  # noqa: BLE001
        return {}


def build_cognitive_context(user_message: str, session_id: str = "") -> str:
    """Build the cognitive contract JSON injected before every LLM call.
    
    Args:
        user_message: The user's input message
        session_id: Optional session ID (generated if not provided)
    
    Returns:
        JSON string containing cognitive contract context
    """
    if not session_id:
        session_id = str(uuid.uuid4())
    
    contract = {
        "session": {
            "id": session_id,
            "conversation_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat()
        },
        "input": user_message,
        "hierarchy": {
            "0_direct_response": "penser avant d'agir",
            "1_local_light": "CLI, FS, SQLite, mémoire FTS5",
            "2_skills_local": "workflows appris, patterns connus",
            "3_vector_local": "recherche sémantique sqlite-vec",
            "4_mcp_external": "périphérie du cerveau, rare et stratégique"
        },
        "mantra": "simplest-first, local-first, MCP-last. Stop at the first sufficient level.",
        "constraints": {
            "agent_decides_everything": True,
            "system_never_interprets": True,
            "system_never_executes_without_llm_intent": True
        },
        "mcp_servers": {
            "web_search": {
                "type": "Python",
                "timeout": 30,
                "tools": [
                    {"name": "web_search", "description": "Recherche web via DuckDuckGo", "params": ["query", "max_results"]},
                    {"name": "fetch_page", "description": "Récupère contenu complet d'une page", "params": ["url", "max_length"]}
                ]
            },
            "calculator": {
                "type": "Python",
                "timeout": 10,
                "tools": [
                    {"name": "calculate", "description": "Évalue expression mathématique", "params": ["expression"]},
                    {"name": "convert_units", "description": "Convertit unité (m→cm, €→$, etc)", "params": ["value", "from_unit", "to_unit"]},
                    {"name": "random_number", "description": "Génère nombre aléatoire", "params": ["min", "max", "integer"]},
                    {"name": "statistics", "description": "Calcule stats (mean/median/sum/min/max/variance)", "params": ["numbers", "operation"]}
                ]
            },
            "rss_reader": {
                "type": "Python",
                "timeout": 20,
                "tools": [
                    {"name": "read_rss", "description": "Lit flux RSS/Atom", "params": ["url", "limit"]},
                    {"name": "discover_rss", "description": "Découvre flux RSS sur un site", "params": ["url"]},
                    {"name": "fetch_full_content", "description": "Récupère contenu complet d'un article RSS", "params": ["url"]}
                ]
            },
            "github": {
                "type": "Python",
                "timeout": 30,
                "tools": [
                    {"name": "github_repo", "description": "Info dépôt GitHub (stars, description, etc)", "params": ["owner", "repo"]},
                    {"name": "github_search", "description": "Recherche dépôts GitHub", "params": ["query", "max_results", "sort"]},
                    {"name": "github_readme", "description": "Récupère README d'un dépôt", "params": ["owner", "repo", "branch"]},
                    {"name": "github_user", "description": "Info utilisateur GitHub", "params": ["username"]}
                ]
            },
            "freeweb": {
                "type": "npx",
                "timeout": 60,
                "tools": [
                    {"name": "web_search", "description": "Recherche multi-source (Yahoo, Bing)", "params": ["query", "max_results"]}
                ]
            }
        }
    }
    
    return json.dumps(contract, indent=2)


def _build_system_prompt(mm: Any) -> str:
    """Build the system prompt with Arke's identity + live runtime stats."""
    agent_cfg = _load_agent_config()
    base = agent_cfg.get("system_prompt", "Tu es Arke, un agent cognitif autonome.")

    # --- Live stats ----------------------------------------------------------
    lines = []
    try:
        from arke.skill_registry import SkillRegistry
        skills = SkillRegistry().list_active()
        lines.append(f"- Skills actifs : {len(skills)}")
    except Exception:  # noqa: BLE001
        pass

    try:
        rows = mm.query("session", "SELECT COUNT(*) AS n FROM chat_history", ())
        n_msgs = rows[0]["n"] if rows else 0
        lines.append(f"- Messages en session : {n_msgs}")
    except Exception:  # noqa: BLE001
        pass

    try:
        rows = mm.query("session", "SELECT value FROM session_context WHERE key = 'chat_notes'", ())
        notes = rows[0]["value"] if rows else ""
        if notes:
            lines.append(f"- Notes mémorisées :\n{notes}")
    except Exception:  # noqa: BLE001
        pass

    env_keys = []
    for k in ("MISTRAL_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        if os.environ.get(k):
            env_keys.append(k.replace("_API_KEY", "").lower())
    if env_keys:
        lines.append(f"- Providers LLM configurés : {', '.join(env_keys)}")

    stats_block = "\n## État session\n" + "\n".join(lines) if lines else ""
    return base.strip() + stats_block


# ---------------------------------------------------------------------------
# Step-by-step display hook — threaded style
# ---------------------------------------------------------------------------


class _StepPrinter:
    """Monkey-patches orchestrator._execute_step to print threaded progress."""

    def __init__(self, total_steps: int) -> None:
        self._n = 0
        self._total = total_steps

    def before(self, step: Any) -> None:
        self._n += 1
        label = _step_label(step)
        print(T.step_line(step.tool, label))
        sys.stdout.flush()

    def after(self, step: Any, success: bool) -> None:
        if success:
            print(T.step_ok(step.tool))
        else:
            print(T.step_err(step.tool))
        sys.stdout.flush()


def _step_label(step: Any) -> str:
    args = step.arguments
    if step.tool == "cli":
        return args.get("command", "")[:60]
    if step.tool == "fs":
        return args.get("path", "")
    if step.tool == "sqlite":
        return args.get("query", "")[:60]
    if step.tool == "llm":
        return args.get("task_type", "reasoning")
    if step.tool == "mcp":
        return args.get("tool_name", "auto") or "auto"
    return str(args)[:60]


# ---------------------------------------------------------------------------
# Direct LLM conversation
# ---------------------------------------------------------------------------


def _pick_default_model() -> str | None:
    """Return the best available model based on configured API keys."""
    if os.environ.get("MISTRAL_API_KEY"):
        return MODEL_ALIASES["mistral"]
    if os.environ.get("GEMINI_API_KEY"):
        return MODEL_ALIASES["flash"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        return MODEL_ALIASES["claude"]
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter/mistral/mistral-large-latest"
    return None


# ---------------------------------------------------------------------------
# Streaming display with Rich
# ---------------------------------------------------------------------------


class StreamingMarkdownDisplay:
    """Display streaming LLM output in real-time using Rich Live Markdown."""

    def __init__(self, use_live: bool = True):
        """Initialize streaming display.
        
        Args:
            use_live: If True, use Rich Live for real-time updates (nicer but experimental).
                     If False, use simple line buffering (more stable).
        """
        self.buffer = []
        self.use_live = use_live
        self._live = None
        self._last_update_time = time.time()
        self._update_interval = 0.05  # 50ms minimum between updates
        
        if use_live:
            try:
                from rich.live import Live
                from rich.markdown import Markdown
                
                self._Live = Live
                self._Markdown = Markdown
            except ImportError:
                self.use_live = False
                log.warning("streaming.rich_not_available, falling back to line buffering")

    def add_token(self, token: str) -> None:
        """Add a token to the display buffer and update if needed."""
        self.buffer.append(token)
        
        # Update display every 50ms or immediately on line breaks
        current_time = time.time()
        should_update = (
            "\n" in token
            or (current_time - self._last_update_time) >= self._update_interval
        )
        
        if should_update:
            self._update_display()
            self._last_update_time = time.time()

    def _update_display(self) -> None:
        """Update the live display with accumulated buffer."""
        if not self.use_live:
            return
        
        try:
            full_text = "".join(self.buffer)
            if not self._live:
                self._live = self._Live(self._Markdown(full_text), transient=False)
                self._live.start()
            else:
                self._live.update(self._Markdown(full_text))
        except Exception as exc:
            log.debug("streaming.display_update_failed", error=str(exc))

    def get_full_text(self) -> str:
        """Get the complete accumulated text."""
        return "".join(self.buffer)

    def tokens_added(self) -> bool:
        """Check if any tokens have been added to the buffer."""
        return len(self.buffer) > 0

    def close(self) -> None:
        """Finalize and close the display."""
        if self._live:
            try:
                self._live.stop()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Plan detection and confirmation for multi-step tasks
# ---------------------------------------------------------------------------


def _extract_plan_from_response(response_text: str) -> str | None:
    """Extract plan block from [PLAN:]/PLAN] markers.
    
    Args:
        response_text: The agent's response text
    
    Returns:
        The plan text if found, otherwise None
    """
    plan_match = re.search(r'\[PLAN:(.*?)/PLAN\]', response_text, re.DOTALL)
    if plan_match:
        return plan_match.group(1).strip()
    return None


def _confirm_plan(plan_text: str) -> bool:
    """Display plan and ask user for confirmation.
    
    Args:
        plan_text: The plan text to display
    
    Returns:
        True if user confirms, False otherwise
    """
    print(T.BORDER + "┌" + T.RESET)
    print(T.BORDER + "│ 📋 Plan de travail" + T.RESET)
    print(T.BORDER + "├" + T.RESET)
    for line in plan_text.splitlines():
        print(T.BORDER + "│ " + T.RESET + line)
    print(T.BORDER + "└" + T.RESET)
    print()
    
    # Ask for confirmation
    while True:
        try:
            response = input(T.prompt_line("Exécuter ce plan? (y/n): ")).strip().lower()
            if response in ("y", "yes", "oui", "o"):
                return True
            elif response in ("n", "no", "non"):
                return False
        except KeyboardInterrupt:
            print("\n" + T.step_err("cli") + " Annulation")
            return False
        except EOFError:
            print("\n" + T.step_err("cli") + " Annulation")
            return False






# ---------------------------------------------------------------------------


def _ask_agent(
    cognitive_json: str,
    intention: str,
    context: dict[str, Any],
    stream_display_callback=None,
) -> dict[str, Any]:
    """Ask the LLM agent to decide: direct response or tool execution?
    
    Sends the cognitive contract JSON + intention to the LLM.
    Agent should respond with either:
      {"tool": null, "response": "..."}  — direct answer, no tool
      {"tool": "cli|fs|sqlite|mcp", "args": {...}}  — run this tool
    
    If agent requests tool="llm", it is executed directly here (not via orchestrator).
    Thus this function returns ONLY {"tool": None, ...} or {"tool": cli|fs|sqlite|mcp, ...}.
    
    Args:
        cognitive_json: The cognitive contract JSON string
        intention: User's raw message
        context: Execution context (history, model override, etc.)
        stream_display_callback: Optional callback(token_str) for streaming display
    
    Returns:
        Dict with "tool" (None or cli|fs|sqlite|mcp) and either "response" or "args".
    """
    from arke.llm.litellm_manager import LiteLLMManager
    
    # Build the system prompt
    system_prompt = (
        "Tu es Arke, un agent cognitif autonome.\n\n"
        "## Format de réponse\n"
        "Réponds en Markdown naturel, de façon conversationnelle et concise.\n\n"
        "Si tu dois utiliser un outil (cli, fs, sqlite, mcp), termine ta réponse par:\n"
        "[OUTIL: nom_de_outil]\n"
        "[ARGS: arguments_en_json]\n\n"
        "Exemples :\n"
        "[OUTIL: cli]\n"
        "[ARGS: {\"command\": \"ls -la\"}]\n\n"
        "[OUTIL: fs]\n"
        "[ARGS: {\"path\": \"/etc/hostname\"}]\n\n"
        "[OUTIL: sqlite]\n"
        "[ARGS: {\"db\": \"session\", \"query\": \"INSERT OR REPLACE INTO session_context (key, value) VALUES (?, ?)\", \"params\": [\"projet\", \"Arke\"]}]\n\n"
        "## Outils disponibles (hiérarchie: simplest-first, local-first, MCP-last)\n"
        "- fs : fichiers et dossiers. Lit le contenu, liste les répertoires. Ne crée pas de fichiers.\n"
        "- cli : exécute une commande shell. Pour créer/modifier un fichier, utiliser echo ou un redirect.\n"
        "- sqlite : requêtes SQL sur les bases mémoire (session, global, project).\n"
        "- mcp : services externes (5 serveurs, 13 outils) — DERNIER RECOURS après avoir vérifié les niveaux 0-3.\n\n"
        "## MCP — Services externes disponibles (5 serveurs, 13 outils)\n"
        "IMPORTANT : Utilise MCP UNIQUEMENT après avoir vérifié que les outils locaux (fs, cli, sqlite) sont insuffisants.\n\n"
        "### 5 serveurs MCP disponibles\n"
        "1. **web_search** (Python) — Recherche web DuckDuckGo\n"
        "   - Outils : web_search, fetch_page\n\n"
        "2. **calculator** (Python) — Calculs mathématiques\n"
        "   - Outils : calculate, convert_units, random_number, statistics\n\n"
        "3. **rss_reader** (Python) — Lecteur RSS/Atom\n"
        "   - Outils : read_rss, discover_rss, fetch_full_content\n\n"
        "4. **github** (Python) — API GitHub\n"
        "   - Outils : github_repo, github_search, github_readme, github_user\n\n"
        "5. **freeweb** (npx) — Recherche web multi-source (Yahoo, Bing, etc.)\n\n"
        "### Format d'appel MCP (2 formats supportés)\n"
        "**Format 1 : Recommandé (serveurs Python)**\n"
        "[OUTIL: mcp]\n"
        "[ARGS: {\"_server\": \"SERVER_NAME\", \"tool_name\": \"TOOL_NAME\", \"tool_args\": {\"arg1\": \"value1\"}}]\n\n"
        "Exemples:\n"
        "- Cherche web : {\"_server\": \"web_search\", \"tool_name\": \"web_search\", \"tool_args\": {\"query\": \"machine learning\", \"max_results\": 5}}\n"
        "- Calcul : {\"_server\": \"calculator\", \"tool_name\": \"calculate\", \"tool_args\": {\"expression\": \"25% of 1000\"}}\n"
        "- RSS : {\"_server\": \"rss_reader\", \"tool_name\": \"read_rss\", \"tool_args\": {\"url\": \"https://simonwillison.net/atom.xml\", \"limit\": 3}}\n"
        "- GitHub : {\"_server\": \"github\", \"tool_name\": \"github_search\", \"tool_args\": {\"query\": \"arke agent\", \"max_results\": 3}}\n\n"
        "**Format 2 : Legacy (fallback)**\n"
        "[ARGS: {\"service\": \"SERVICE\", \"action\": \"ACTION\", \"params\": {...}}]\n\n"
        "## Sandbox CLI\n"
        "IMPORTANT : Chaque commande CLI s'exécute dans un environnement isolé. "
        "Un fichier créé dans /tmp n'existe que pendant cette commande. "
        "Pour créer ET lire un fichier, enchaîne tout dans la même commande : "
        "echo 'contenu' > /tmp/fichier && cat /tmp/fichier\n\n"
        "## Bases de données SQLite (IMPORTANT: toujours préciser 'db')\n\n"
        "POUR OPÉRATIONS DE MÉMOIRE: ajoute toujours `\"db\": \"session\"` aux arguments SQLite\n\n"
        "**session.db** (conversationnel — utile pour memory_write/read/forget):\n"
        "- `session_context` (key TEXT, value TEXT) — TOUJOURS PASSER `\"db\": \"session\"`\n"
        "- `chat_history` — historique de conversation\n"
        "- `memory_fts` — recherche FTS5 sur historique\n\n"
        "**global.db** (défaut si db non spécifié):\n"
        "- `config`, `tool_usage`, `skills`, `pattern_log`\n\n"
        "**project.db** (contexte projet):\n"
        "- `docs`, `docs_fts`\n\n"
        "Exemples:\n"
        "- Mémoire: {\"db\": \"session\", \"query\": \"INSERT OR REPLACE INTO session_context (key, value) VALUES (?, ?)\", \"params\": [\"nom\", \"valeur\"]}\n"
        "- Lecture: {\"db\": \"session\", \"query\": \"SELECT value FROM session_context WHERE key = ?\" , \"params\": [\"nom\"]}\n"
        "- Suppression: {\"db\": \"session\", \"query\": \"DELETE FROM session_context WHERE key LIKE ?\" , \"params\": [\"%searchterm%\"]}\n\n"
        "## 🧠 Apprentissage — Apprendre de l'expérience\n\n"
        "Tu peux interroger et enrichir ta mémoire d'apprentissage pour t'améliorer au fil du temps.\n\n"
        "**LECTURE (avant d'agir):**\n"
        "- Cherche une expérience similaire :\n"
        "[OUTIL: memory_search]\n"
        "[ARGS: {\"query\": \"keywords describing similar task\", \"limit\": 5}]\n\n"
        "**ÉCRITURE (après succès):**\n"
        "- L'orchestre enregistre automatiquement tes succès dans `agent_learnings`.\n"
        "- Si tu veux enregistrer explicitement une leçon, utilise sqlite :\n"
        "[OUTIL: sqlite]\n"
        "[ARGS: {\"db\": \"global\", \"query\": \"INSERT INTO agent_learnings (intention_pattern, tool_sequence, success, lesson) VALUES (?, ?, ?, ?)\", \"params\": [\"description de la tâche\", \"[...]\", 1, \"ce qu'il faut retenir\"]}]\n\n"
        "**PATTERNS RÉPÉTÉS:**\n"
        "- Quand un pattern se répète ≥5 fois, le système l'enregistre dans pattern_log.\n"
        "- Tu peux l'interroger :\n"
        "[OUTIL: sqlite]\n"
        "[ARGS: {\"db\": \"global\", \"query\": \"SELECT tool_name, COUNT(*) as freq FROM pattern_log WHERE timestamp > datetime('now', '-7 days') GROUP BY tool_name HAVING freq >= 5\"}]\n\n"
        "**COMPÉTENCES:**\n"
        "- Après une tâche réussie avec 3+ étapes, tu peux créer une compétence.\n"
        "- Le système détecte les occasions et affiche : \"💡 Pattern detected. /skill to create one.\"\n"
        "- Utilise `/skill` pour créer une compétence réutilisable.\n\n"
        "## 🎯 Planification pour tâches multi-étapes (IMPORTANT)\n\n"
        "Si la tâche nécessite PLUSIEURS ÉTAPES:\n"
        "1. D'abord, propose un plan avec le format:\n"
        "   [PLAN:\n"
        "   1. Description de l'étape 1\n"
        "   2. Description de l'étape 2\n"
        "   3. Description de l'étape 3\n"
        "   /PLAN]\n\n"
        "2. Termine par: Proceed with this plan?\n\n"
        "3. Après validation de l'utilisateur, une fois chaque étape complétée, tu verras le résultat précédent dans le contexte. Tu peux alors décider de l'étape suivante.\n\n"
        "Exemple:\n"
        "[PLAN:\n"
        "1. Lister les fichiers dans /tmp\n"
        "2. Grep les fichiers contenant 'error'\n"
        "3. Créer un rapport avec les résultats\n"
        "/PLAN]\n"
        "Proceed with this plan?\n\n"
        "Si tu n'as pas besoin d'outil, réponds normalement sans balises.\n\n"
        "## Règle absolue\n"
        "Tu réponds TOUJOURS. Même face à une réflexion ouverte ou une observation, "
        "accuse réception et propose d'approfondir. Le silence n'est jamais une option."
    )
    
    # Build history context
    history_text = ""
    if context.get("history"):
        history_text = "## Historique récent:\n"
        for msg in context["history"]:
            role = msg.get("role", "?")
            content = msg.get("content", "")[:100]
            history_text += f"- {role}: {content}...\n"
        history_text += "\n"
    
    # Build the full prompt
    prompt = f"""{system_prompt}

## Contrat cognitif:
{cognitive_json}

{history_text}## Message utilisateur:
{intention}

Réponds en Markdown naturel. Si tu dois utiliser un outil, ajoute les balises [OUTIL:] et [ARGS:] à la fin."""
    
    # Reload env vars in case new keys were added via /config
    _load_env_file()
    
    # Call LLM for agent decision
    manager = LiteLLMManager()
    try:
        if stream_display_callback:
            # Stream mode: accumulate tokens via callback
            response_text = ""
            for token in manager.stream_complete(
                prompt=prompt, task_type="classification", max_tokens=16384
            ):
                response_text += token
                if stream_display_callback:
                    stream_display_callback(token)
        else:
            # Non-streaming mode (original behavior)
            response_text, _cost, _tokens = manager.complete(
                prompt=prompt, task_type="classification", max_tokens=16384
            )
    except TimeoutError as exc:
        log.error("llm.agent_timeout", error=str(exc))
        raise  # Re-raise timeout so caller can handle it
    except Exception as exc:
        log.error("llm.agent_decision_failed", error=str(exc), exc_info=True)
        raise  # Re-raise so caller can handle it appropriately
    
    # Parse response with Markdown + [OUTIL:] and [ARGS:] tags
    response_text = response_text.strip()
    
    # Look for [OUTIL: tool_name] and [ARGS: {...}] tags
    outil_match = re.search(r'\[OUTIL:\s*(\w+)\]', response_text)
    args_match = re.search(r'\[ARGS:\s*(\{)', response_text)
    
    if outil_match and args_match:
        # Extract tool and args
        tool = outil_match.group(1).lower()
        try:
            # Find the start of the JSON object and parse it properly
            json_start = args_match.start(1)
            # Find matching closing brace using JSON parsing (more reliable than regex)
            json_str = response_text[json_start:]
            
            # Use json.JSONDecoder to find where the JSON ends
            decoder = json.JSONDecoder()
            args, idx = decoder.raw_decode(json_str)
            args_json = json_str[:idx]
        except json.JSONDecodeError as exc:
            log.warning("llm.agent_args_parse_failed", error=str(exc), raw=json_str[:100] if 'json_str' in locals() else "")
            args = {}
        
        # Remove tags from response text to show only Markdown
        clean_response = re.sub(r'\[OUTIL:.*?\]\n?', '', response_text)
        clean_response = re.sub(r'\[ARGS:.*?\]\n?', '', clean_response).strip()
        
        # If agent requests tool="llm", execute it directly here (not via orchestrator)
        if tool == "llm":
            prompt_template = args.get("prompt_template", intention)
            task_type = args.get("task_type", "reasoning")
            max_tokens = args.get("max_tokens", 500)
            try:
                llm_response, _cost, _tokens = manager.complete(
                    prompt=prompt_template, task_type=task_type, max_tokens=max_tokens
                )
                return {"tool": None, "response": llm_response}
            except Exception as exc:
                log.error("llm.agent_execution_failed", error=str(exc))
                return {"tool": None, "response": f"Erreur LLM: {str(exc)}"}
        
        # Return decision with cleaned response (tool must be cli|fs|sqlite|mcp)
        return {
            "tool": tool if tool in ["cli", "fs", "sqlite", "mcp"] else None,
            "args": args,
            "response": clean_response or None
        }
    else:
        # No tool tags found — pure conversational response
        return {"tool": None, "response": response_text}


# Main REPL
# ---------------------------------------------------------------------------


def start() -> None:
    """Launch the interactive REPL."""
    _load_env_file()
    _silence_logs()

    from arke.memory.manager import MemoryManager
    import shutil

    mm = MemoryManager()

    # Detect sandbox for banner footer
    sandbox_ok = bool(shutil.which("bwrap"))
    print(T.banner(sandbox=sandbox_ok))
    print()

    _ctrl_c_count = [0]
    _task_running = [False]

    # --- Cognitive continuity infrastructure ---
    import uuid as _uuid
    _session_id = str(_uuid.uuid4())
    _social_orchestrator = SocialOrchestrator(mm, _session_id)
    _social_orchestrator.start()
    _cancel_extraction = [None]  # type: list[threading.Event | None]

    def _run_task(result: RouteResult) -> None:
        """Execute a task intention through the orchestrator with threaded step display."""
        import arke.orchestrator as orch
        from arke.task_graph import StepStatus
        import arke.router as router_mod

        intention = result.intention
        context: dict[str, Any] = {}

        if result.model_id:
            context["model_override"] = result.model_id

        recent = history_recent(mm, n=5)
        if recent:
            context["history"] = recent

        # Inject cognitive contract into context (preserves Chantier C)
        cognitive_json = build_cognitive_context(intention)
        context["cognitive_contract_json"] = cognitive_json

        # Setup streaming display for agent response
        stream_display = StreamingMarkdownDisplay(use_live=True)
        
        def stream_callback(token: str) -> None:
            """Callback to display streaming tokens."""
            stream_display.add_token(token)
        
        # Ask agent to decide: tool or direct response (with streaming)
        # Show spinner while waiting for LLM response
        print(f"\n{T.MUTED}Thinking...{T.RESET}")
        try:
            agent_decision = _ask_agent(cognitive_json, intention, context, stream_display_callback=stream_callback)
        except TimeoutError as exc:
            print(f"\n{T.error()}LLM Provider Timeout{T.RESET}")
            print(f"{T.MUTED}The LLM provider did not respond within 60 seconds.{T.RESET}")
            print(f"{T.MUTED}Possible causes:{T.RESET}")
            print(f"{T.MUTED}- API overloaded or down{T.RESET}")
            print(f"{T.MUTED}- Network issue{T.RESET}")
            print(f"{T.MUTED}- Message too long for the model{T.RESET}")
            history_append(mm, "user", intention, model_used=None)
            history_append(mm, "assistant", f"Error: {exc}", model_used=None)
            return
        except Exception as exc:
            print(f"\n{T.error()}Error contacting LLM{T.RESET}")
            print(f"{T.MUTED}Error: {exc}{T.RESET}")
            history_append(mm, "user", intention, model_used=None)
            history_append(mm, "assistant", f"Error: {exc}", model_used=None)
            return
        
        # Finalize streaming display
        stream_display.close()
        
        # If agent says no tool needed, respond directly
        if agent_decision.get("tool") is None:
            # Direct response from agent
            response = agent_decision.get("response", "")
            
            # Check for plan in response
            plan = _extract_plan_from_response(response) if response else None
            if plan:
                # Display the plan and ask for confirmation
                print()
                if not _confirm_plan(plan):
                    print(T.step_err("cli") + " Tâche annulée.")
                    history_append(mm, "user", intention, model_used=None)
                    history_append(mm, "assistant", "Plan rejected by user.", model_used=None)
                    return
                print()
                # Plan confirmed, continue to execution
                # Remove plan markers from response display
                clean_response = re.sub(r'\[PLAN:.*?/PLAN\]', '', response, flags=re.DOTALL).strip()
                response = clean_response
            
            alias = result.model_alias or _get_alias()
            print(T.agent_header(alias))
            print(T.BORDER + "│" + T.RESET)
            # Skip redundant print if response was already streamed via stream_display
            if response and not stream_display.tokens_added():
                for line in response.splitlines():
                    print(T.step_output(line))
            print(T.BORDER + "│" + T.RESET)
            history_append(mm, "user", intention, model_used=None)
            history_append(mm, "assistant", response or (plan or "Plan proposed"), model_used=None)
            return
        
        # Agent wants to use a tool; pass decision to orchestrator
        context["agent_decision"] = agent_decision
        
        try:
            task_plan = router_mod.plan(intention, context)
            total = len(task_plan.steps)
        except Exception:  # noqa: BLE001
            total = 1

        printer = _StepPrinter(total)

        # Print agent header block
        alias = result.model_alias or _get_alias()
        print(T.agent_header(alias))
        # Routing meta line
        if total > 0:
            try:
                first_tool = task_plan.steps[0].tool
                print(T.step_meta("tool", f"agent → {first_tool}"))
            except Exception:  # noqa: BLE001
                pass
        print(T.BORDER + "│" + T.RESET)

        # Patch _execute_step
        _orig_execute = orch._execute_step

        def _patched_execute(step, step_outputs, ctx, task):
            printer.before(step)
            _orig_execute(step, step_outputs, ctx, task)
            from arke.task_graph import StepStatus as SS
            printer.after(step, step.status == SS.SUCCESS)

        orch._execute_step = _patched_execute
        t0 = time.perf_counter()
        try:
            task = orch.run(intention, context)
        finally:
            orch._execute_step = _orig_execute

        elapsed = time.perf_counter() - t0

        # Output
        if task.status == StepStatus.SUCCESS:
            last = task.steps[-1]
            output = last.output
            if isinstance(output, dict):
                text = output.get("stdout", "").rstrip()
            else:
                text = str(output).rstrip()
            if text:
                print(T.BORDER + "│" + T.RESET)
                for line in text.splitlines():
                    print(T.step_output(line))
            cost = task.total_cost or 0.0
            print(T.done_line(task.tokens_used, elapsed, cost))
            print(T.BORDER + "│" + T.RESET)
            response_text = text or "Tâche terminée."
            
            # Check for distillation hint (Session 014.2.3)
            try:
                hint_rows = mm.query(
                    "session",
                    "SELECT value FROM session_context WHERE key = 'show_distillation_hint'",
                    ()
                )
                if hint_rows and hint_rows[0]["value"] == "1":
                    print(f"{T.ACCENT}💡 Pattern detected. /skill to create one.{T.RESET}")
                    # Clear the flag so hint only shows once
                    mm.query(
                        "session",
                        "INSERT OR REPLACE INTO session_context (key, value) VALUES (?, ?)",
                        ("show_distillation_hint", "0")
                    )
            except Exception:
                pass  # Hint display must never interrupt
        else:
            failed_step = next((s for s in task.steps if s.status == StepStatus.FAILED), None)
            tool_name = failed_step.tool if failed_step else "?"
            print(T.error_line(f"Échec à l'étape : {tool_name}"))
            print(T.BORDER + "│" + T.RESET)
            response_text = f"Échec : {tool_name}"

        history_append(mm, "user", intention, model_used=None)
        history_append(mm, "arke", response_text, model_used=result.model_id)

        # --- Cognitive continuity: record exchange + trigger extraction ---
        depth_score = min((len(intention) + len(response_text)) / 2000.0, 1.0)
        _social_orchestrator.record_exchange(depth_score)
        # Cancel previous extraction if still pending, start fresh
        if _cancel_extraction[0] is not None:
            _cancel_extraction[0].set()
        import threading as _threading
        _cancel_extraction[0] = _threading.Event()
        extract_async(mm, _session_id, intention, response_text, _cancel_extraction[0])

    # -----------------------------------------------------------------------
    # REPL loop
    # -----------------------------------------------------------------------

    while True:
        try:
            # Signal any pending extraction to abort (user is active)
            _social_orchestrator.record_input()
            if _cancel_extraction[0] is not None:
                _cancel_extraction[0].set()

            # Check for pending cognitive initiative (pull model, Phase 0: always None)
            if _social_orchestrator.has_pending_initiative():
                if _social_orchestrator.is_user_idle():
                    initiative = _social_orchestrator.pop_initiative()
                    if initiative:
                        print(T.initiative_block(initiative))

            raw = _read_paste_buffered(T.prompt_line(_get_alias()))
            _ctrl_c_count[0] = 0
        except KeyboardInterrupt:
            _ctrl_c_count[0] += 1
            if _ctrl_c_count[0] >= 2:
                print(f"\n{T.MUTED}Au revoir.{T.RESET}")
                break
            print(f"\n{T.MUTED}(Ctrl+C encore pour quitter){T.RESET}")
            continue
        except EOFError:
            print(f"\n{T.MUTED}Au revoir.{T.RESET}")
            break

        raw = raw.strip()
        if not raw:
            continue

        # Print user block in the thread
        print(T.user_block(raw))

        result = route(raw)

        # --- Slash commands --------------------------------------------------
        if result.kind == RouteKind.SLASH:
            cmd = result.slash

            if cmd == "/exit":
                print(f"{T.MUTED}Au revoir.{T.RESET}")
                break

            elif cmd == "/help":
                _print_help()

            elif cmd == "/clear":
                memory_forget(mm, "")
                print(f"{T.MUTED}Historique et notes effacés.{T.RESET}")

            elif cmd == "/stats":
                _print_stats(mm)

            elif cmd == "/skills":
                _print_skills()

            elif cmd == "/skill":
                _handle_skill_distillation(mm)

            elif cmd == "/check":
                from arke.chat_config import print_check
                print_check()

            elif cmd == "/status":
                _print_status(mm)

            elif cmd == "/model":
                new_alias = _print_model_selector()
                if new_alias:
                    _set_alias(new_alias)

            elif cmd == "/memory":
                _print_memory(mm)

            elif cmd == "/about":
                _print_about()

            elif cmd == "/config":
                from arke.chat_config import run_config
                run_config()

            elif cmd == "/threads":
                threads = _social_orchestrator.list_threads()
                if not threads:
                    print(f"{T.MUTED}Aucun fil cognitif actif.{T.RESET}")
                else:
                    print(f"{T.ACCENT}Fils cognitifs actifs ({len(threads)}) :{T.RESET}")
                    for th in threads:
                        score = f"{th['importance_score']:.2f}"
                        print(
                            f"  {T.MUTED}#{th['id']}{T.RESET} "
                            f"[{T.ACCENT}{score}{T.RESET}] "
                            f"{T.TEXT}{th['content'][:80]}{T.RESET} "
                            f"{T.MUTED}({th['status']}){T.RESET}"
                        )

            elif cmd == "/drop-thread":
                try:
                    tid = int(raw.split()[1])
                    ok = _social_orchestrator.drop_thread(tid)
                    msg = f"Fil #{tid} marqué consumed." if ok else f"Fil #{tid} introuvable."
                    print(f"{T.MUTED}{msg}{T.RESET}")
                except (ValueError, IndexError):
                    print(f"{T.MUTED}Usage : /drop-thread <id>{T.RESET}")

            elif cmd == "/pause-initiatives":
                hours = 8.0
                parts = raw.split()
                if len(parts) > 1:
                    try:
                        hours = float(parts[1].rstrip("h"))
                    except ValueError:
                        pass
                _social_orchestrator.pause(hours)
                print(f"{T.MUTED}Initiatives suspendues pour {hours:.0f}h.{T.RESET}")

            elif cmd == "/resume-initiatives":
                _social_orchestrator.resume()
                print(f"{T.MUTED}Initiatives réactivées.{T.RESET}")

            # Track slash command in metrics
            get_metrics_instance().increment_slash_or_model()
            continue

        # --- Model override —update active alias ----------------------------
        if result.kind == RouteKind.MODEL_OVERRIDE and result.model_alias:
            _set_alias(result.model_alias)
            print(T.step_meta("modèle", f"→ {result.model_alias} {T.model_icon(result.model_alias)}"))
            # Track model override in metrics
            get_metrics_instance().increment_slash_or_model()
            continue

        # --- Agent execution (unified via orchestrator) ----------------------
        # All non-slash, non-@model messages route here (agent-first principle)
        if result.kind == RouteKind.LLM_AGENT:
            # Track agent decision in anti-drift metrics
            get_metrics_instance().increment_agent_decision()
            _task_running[0] = True
            try:
                _run_task(result)
            except KeyboardInterrupt:
                print(f"\n{T.MUTED}Tâche interrompue. (Ctrl+C encore pour quitter){T.RESET}")
                _ctrl_c_count[0] = 1
            except Exception as exc:  # noqa: BLE001
                print(T.error_line(f"Erreur inattendue : {exc}"), file=sys.stderr)
                log.error("chat.task.error", error=str(exc))
            finally:
                _task_running[0] = False

    # Clean shutdown
    _social_orchestrator.stop()


# ---------------------------------------------------------------------------
# Slash command implementations
# ---------------------------------------------------------------------------


def _handle_skill_distillation(mm: Any) -> None:
    """Handle /skill command: generate a skill from recent learnings.
    
    Non-blocking implementation (Session 014.2):
    1. Query agent_learnings for recent successful patterns
    2. Ask agent to synthesize a reusable skill
    3. Store as skill record in DB
    """
    from arke import chat_theme as T
    from arke.memory.manager import MemoryManager
    
    try:
        print(f"{T.MUTED}Analyzing recent learning experiences…{T.RESET}")
        
        # Get recent successful learnings
        mm_query = MemoryManager()
        rows = mm_query.query(
            "global",
            """SELECT intention_pattern, tool_sequence, lesson, created_at 
               FROM agent_learnings 
               WHERE success = 1 
               ORDER BY created_at DESC 
               LIMIT 10
            """,
            ()
        )
        
        if not rows:
            print(f"{T.MUTED}Aucune expérience d'apprentissage pour générer une skill.{T.RESET}")
            return
        
        # Summarize learnings for agent - debug row access
        try:
            learnings_summary = "\n".join([
                f"- {row['intention_pattern']}: {row['lesson']}"
                for row in rows[:5]
            ])
        except Exception as e:
            print(f"{T.ERROR}Error building learnings summary: {str(e)}{T.RESET}")
            raise
        
        print(f"{T.MUTED}Found {len(rows)} learning experiences. Generating skill…{T.RESET}")
        print()
        
        # Ask agent to create a skill (non-blocking, async-friendly)
        skill_prompt = f"""Based on these recent successful learning patterns:

{learnings_summary}

Réponds UNIQUEMENT avec ce JSON (pas de Markdown, pas de backticks autour) :
{{"name": "nom_skill", "description": "ce que fait ce skill", "tool": "cli|fs|sqlite|mcp"}}

Exemple valide :
{{"name": "create_tmp_file", "description": "Crée un fichier dans /tmp avec contenu et vérifie qu'il existe", "tool": "cli"}}

Génère maintenant le JSON pour ces patterns:"""
        
        from arke.llm.litellm_manager import LiteLLMManager
        manager = LiteLLMManager()
        
        skill_json, _cost, _tokens = manager.complete(
            prompt=skill_prompt,
            task_type="skill_generation",
            max_tokens=500
        )
        
        # Parse and store skill with AGGRESSIVE fallback for LLM responses
        import json
        
        skill_data = None
        
        # Try 1: Direct parse
        try:
            skill_data = json.loads(skill_json)
        except json.JSONDecodeError:
            pass
        
        # Try 2: Remove markdown markers
        if skill_data is None:
            cleaned = re.sub(r'```(json)?\s*|\s*```', '', skill_json).strip()
            try:
                skill_data = json.loads(cleaned)
            except json.JSONDecodeError:
                pass
        
        # Try 3: Find JSON object pattern {...}
        if skill_data is None:
            match = re.search(r'\{[^{}]*"name"[^{}]*\}', skill_json, re.DOTALL | re.IGNORECASE)
            if match:
                try:
                    skill_data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        
        # Try 4: Fallback - extract values manually from response
        if skill_data is None:
            name_match = re.search(r'["\']?name["\']?\s*[:\=]\s*["\']([^"\']+)["\']', skill_json, re.IGNORECASE)
            desc_match = re.search(r'["\']?description["\']?\s*[:\=]\s*["\']([^"\']+)["\']', skill_json, re.IGNORECASE)
            tool_match = re.search(r'["\']?tool["\']?\s*[:\=]\s*["\']([^"\']+)["\']', skill_json, re.IGNORECASE)
            
            if name_match:
                skill_data = {
                    "name": name_match.group(1) or "auto_skill",
                    "description": desc_match.group(1) if desc_match else "Auto-generated skill",
                    "tool": tool_match.group(1) if tool_match else "cli"
                }
        
        # Final fallback: use defaults
        if skill_data is None:
            skill_data = {
                "name": f"pattern_skill_{len(rows)}",
                "description": f"Skill created from {len(rows)} learning experiences",
                "tool": "cli"
            }
        
        # Store directly in skills table
        mm_query.query(
            "global",
            """INSERT INTO skills (id, name, description, prompt_template, tool)
               VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                skill_data.get("name", "unnamed_skill"),
                skill_data.get("description", ""),
                learnings_summary,
                skill_data.get("tool", "cli"),
            )
        )
        
        print(T.SUCCESS + "✓ " + T.RESET + f"Skill created: {skill_data.get('name')}")
        print(f"{T.MUTED}{skill_data.get('description')}{T.RESET}")
        print()
            
    except ValueError as e:
        print(f"{T.ERROR}✗ Le format de la compétence n'est pas valide. Réessaie.{T.RESET}")
        log.warning("skill_json_parse_error", error=str(e))
    except json.JSONDecodeError as e:
        print(f"{T.ERROR}✗ Le format de la compétence n'est pas valide. Réessaie.{T.RESET}")
        log.warning("skill_json_parse_error", error=str(e))
    except Exception as exc:
        print(f"{T.ERROR}✗ Skill generation error: {str(exc)}{T.RESET}")
        log.warning("skill_generation_error", error=str(exc))


def _print_help() -> None:
    from arke import chat_theme as T
    lines = [
        f"{T.ACCENT}Modes d'entrée (Agent-First){T.RESET}",
        "",
        f"  {T.MUTED}Agent{T.RESET}           tous les messages (sauf slash/@ ci-dessous)",
        f"                        → orchestrateur → LLM + outils",
        f"  {T.MUTED}Modèle{T.RESET}        @flash / @claude / @mistral / @local",
        f"  {T.MUTED}Mémoire{T.RESET}       agent contrôle (agent sees: souviens-toi, rappelle…)",
        "",
        f"{T.ACCENT}Commandes slash{T.RESET}",
        "",
    ]
    for cmd, desc in SLASH_COMMANDS.items():
        lines.append(f"  {T.BOLD}{cmd:<10}{T.RESET} {T.MUTED}{desc}{T.RESET}")
    lines.append("")
    lines.append(f"{T.ACCENT}Alias de modèles{T.RESET}")
    lines.append("")
    for alias, model_id in MODEL_ALIASES.items():
        lines.append(f"  {T.model_label(alias)}  {T.DIM}→ {model_id}{T.RESET}")
    lines.append("")
    print()
    print(T.box(lines))
    print()


def _print_stats(mm: Any) -> None:
    from arke.skill_manager import SkillManager
    from arke.skill_registry import SkillRegistry
    from arke import chat_theme as T

    sm = SkillManager()
    stats = sm.get_stats()

    lines: list[str] = []
    lines.append(f"{T.ACCENT}Outils{T.RESET}")
    lines.append("")
    if stats:
        header = f"  {T.MUTED}{'Outil':<12} {'Appels':>6} {'Succès':>8} {'Taux':>7}{T.RESET}"
        lines.append(header)
        lines.append(f"  {T.BORDER}{'─'*38}{T.RESET}")
        for row in stats:
            rate = row["success_rate"]
            rate_col = T.SUCCESS if rate >= 80 else T.WARNING if rate >= 50 else T.ERROR
            lines.append(
                f"  {T.TEXT}{row['tool_name']:<12}{T.RESET}"
                f" {T.MUTED}{row['total_calls']:>6}{T.RESET}"
                f" {T.MUTED}{int(row['successes']):>8}{T.RESET}"
                f" {rate_col}{rate:>6.1f}%{T.RESET}"
            )
    else:
        lines.append(f"  {T.MUTED}Aucun usage enregistré.{T.RESET}")

    lines.append("")
    lines.append(f"{T.ACCENT}Skills{T.RESET}")
    lines.append("")
    registry = SkillRegistry()
    skills = registry.list_active()
    if skills:
        for sk in skills:
            score = sk.get("reuse_score", 0.0)
            icon = T.SUCCESS + "●" + T.RESET if sk["usage_count"] > 0 else T.MUTED + "○" + T.RESET
            lines.append(
                f"  {icon} {T.TEXT}{sk['name']}{T.RESET}  "
                f"{T.MUTED}score {score:.0f} · {sk['usage_count']} usages{T.RESET}"
            )
    else:
        lines.append(f"  {T.MUTED}Aucun skill actif.{T.RESET}")

    lines.append("")
    rows = mm.query("session", "SELECT COUNT(*) AS n FROM chat_history", ())
    n_msgs = rows[0]["n"] if rows else 0
    lines.append(f"  {T.MUTED}Session : {n_msgs} message(s){T.RESET}")

    print()
    print(T.box(lines, title="Statistiques"))
    print()


def _print_skills() -> None:
    from arke.skill_registry import SkillRegistry
    from arke import chat_theme as T

    registry = SkillRegistry()
    skills = registry.list_active()

    lines: list[str] = []
    if not skills:
        lines.append(f"  {T.MUTED}Aucun skill actif.{T.RESET}")
    else:
        for sk in skills:
            score = sk.get("reuse_score", 0.0)
            created = sk.get("created_at", "")[:10]
            lines.append(
                f"  {T.SUCCESS}●{T.RESET} {T.TEXT}{sk['name']}{T.RESET}  "
                f"{T.MUTED}{sk['tool']} · {sk['usage_count']} usages · score {score:.0f} · {created}{T.RESET}"
            )
    print()
    print(T.box(lines, title="Skills actifs"))
    print()


def _print_status(mm: Any) -> None:
    """Print the real runtime state of the Arke system."""
    import shutil
    from pathlib import Path as _Path
    from arke import chat_theme as T

    lines: list[str] = []

    # --- Bases SQLite --------------------------------------------------------
    lines.append(f"{T.ACCENT}Bases SQLite{T.RESET}")
    lines.append("")
    base_dir = _Path(__file__).parent.parent / "memory"
    for db in ("global.db", "project.db", "session.db", "cache.db"):
        p = base_dir / db
        if p.exists():
            size_kb = p.stat().st_size // 1024
            lines.append(f"  {T.SUCCESS}✓{T.RESET}  {T.TEXT}{db:<15}{T.RESET} {T.MUTED}{size_kb:>5} KB{T.RESET}")
        else:
            lines.append(f"  {T.ERROR}✗{T.RESET}  {T.TEXT}{db:<15}{T.RESET} {T.MUTED}absent{T.RESET}")

    # --- Mémoire session -----------------------------------------------------
    try:
        rows = mm.query("session", "SELECT COUNT(*) AS n FROM chat_history", ())
        n_msgs = rows[0]["n"] if rows else 0
        rows2 = mm.query("session", "SELECT value FROM session_context WHERE key = 'chat_notes'", ())
        notes = rows2[0]["value"] if rows2 else ""
        n_notes = len([l for l in notes.splitlines() if l.strip()]) if notes else 0
        lines.append("")
        lines.append(f"{T.ACCENT}Session{T.RESET}")
        lines.append("")
        lines.append(f"  {T.MUTED}messages historique{T.RESET}  {T.TEXT}{n_msgs}{T.RESET}")
        lines.append(f"  {T.MUTED}notes mémorisées{T.RESET}    {T.TEXT}{n_notes}{T.RESET}")
    except Exception:  # noqa: BLE001
        pass

    # --- Skills --------------------------------------------------------------
    try:
        from arke.skill_registry import SkillRegistry
        skills = SkillRegistry().list_active()
        lines.append("")
        lines.append(f"{T.ACCENT}Skills{T.RESET}  {T.MUTED}{len(skills)} actif(s){T.RESET}")
        for sk in skills[:5]:
            lines.append(f"  {T.MUTED}• {sk['name']} ({sk['tool']}, {sk['usage_count']} usages){T.RESET}")
        if len(skills) > 5:
            lines.append(f"  {T.DIM}… et {len(skills) - 5} autre(s){T.RESET}")
    except Exception:  # noqa: BLE001
        pass

    # --- Providers LLM -------------------------------------------------------
    lines.append("")
    lines.append(f"{T.ACCENT}Providers LLM{T.RESET}")
    lines.append("")
    provider_map = {
        "MISTRAL_API_KEY": "mistral",
        "GEMINI_API_KEY": "flash/gemini",
        "ANTHROPIC_API_KEY": "claude",
        "OPENROUTER_API_KEY": "openrouter",
    }
    for env_key, label in provider_map.items():
        if os.environ.get(env_key):
            lines.append(f"  {T.SUCCESS}✓{T.RESET}  {T.TEXT}{label:<16}{T.RESET}")
        else:
            lines.append(f"  {T.ERROR}✗{T.RESET}  {T.MUTED}{label:<16}{T.RESET}")

    # --- Sandbox -------------------------------------------------------------
    lines.append("")
    bwrap = shutil.which("bwrap")
    sbx = f"{T.SUCCESS}✓  bubblewrap{T.RESET}" if bwrap else f"{T.ERROR}✗  sandbox non disponible{T.RESET}"
    lines.append(f"  {sbx}")

    print()
    print(T.box(lines, title="État du système"))
    print()


# ---------------------------------------------------------------------------
# New slash commands: /model  /memory  /about
# ---------------------------------------------------------------------------


def _print_model_selector() -> str | None:
    """Interactive model selector. Returns the chosen alias or None."""
    from arke import chat_theme as T

    models = [
        ("flash",   "gemini/gemini-2.0-flash",          "défaut"),
        ("claude",  "anthropic/claude-sonnet-4-5",       ""),
        ("mistral", "mistral/mistral-large-latest",      ""),
        ("local",   "ollama/mistral",                    "local — aucune clé requise"),
    ]

    print()
    lines: list[str] = [f"{T.ACCENT}Modèles disponibles{T.RESET}", ""]
    for i, (alias, model_id, note) in enumerate(models):
        note_str = f"  {T.DIM}{note}{T.RESET}" if note else ""
        lines.append(
            f"  {T.MUTED}{i + 1}.{T.RESET}  {T.model_label(alias)}"
            f"  {T.DIM}{model_id}{T.RESET}{note_str}"
        )
    lines.append("")
    lines.append(f"  {T.MUTED}0. Annuler{T.RESET}")
    print(T.box(lines, title="Sélecteur de modèle"))

    try:
        choice = input(f"\n{T.ACCENT}›{T.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    mapping = {str(i + 1): alias for i, (alias, _mid, _note) in enumerate(models)}
    selected = mapping.get(choice)
    if selected:
        print(T.step_meta("modèle", f"→ {selected} {T.model_icon(selected)}"))
    return selected


def _print_memory(mm: Any) -> None:
    """Display session memory notes."""
    from arke import chat_theme as T

    try:
        rows = mm.query(
            "session",
            "SELECT value FROM session_context WHERE key = 'chat_notes'",
            (),
        )
        notes_raw = rows[0]["value"] if rows else ""
        note_lines = [l for l in notes_raw.splitlines() if l.strip()] if notes_raw else []
    except Exception:  # noqa: BLE001
        note_lines = []

    lines: list[str] = [f"{T.ACCENT}Notes de session{T.RESET}", ""]
    if note_lines:
        for note in note_lines:
            lines.append(f"  {T.MUTED}•{T.RESET} {T.TEXT}{note.lstrip('- ').strip()}{T.RESET}")
    else:
        lines.append(f"  {T.MUTED}Aucune note mémorisée.{T.RESET}")

    lines.append("")
    lines.append(f"  {T.DIM}souviens-toi que …  /  rappelle-moi …  /  oublie …{T.RESET}")

    print()
    print(T.box(lines, title="Mémoire"))
    print()


def _print_about() -> None:
    """Display Arke identity and philosophy."""
    from arke import chat_theme as T

    lines = [
        f"  {T.ACCENT}{T.BOLD}Arke{T.RESET}  {T.MUTED}du grec ἀρχή (arkhḗ) : commencement, principe{T.RESET}",
        "",
        f"  {T.DIM}« Le commencement est la moitié de tout. »{T.RESET}",
        "",
        f"  {T.MUTED}Construit avec{T.RESET}  Python · Rust · SQLite · MCP",
        "",
        f"  {T.ACCENT}Philosophie{T.RESET}",
        "",
        f"    {T.TEXT}Minimal Abstraction{T.RESET}",
        f"    {T.TEXT}Maximum Execution{T.RESET}",
        "",
        f"  {T.ACCENT}Architecture{T.RESET}",
        "",
        f"    {T.TEXT}L'agent décide{T.RESET}",
        f"    {T.TEXT}Le système exécute{T.RESET}",
        "",
        f"  {T.MUTED}243 tests · sandbox actif · mémoire FTS5{T.RESET}",
        "",
        f"  {T.DIM}~/dev/APP/003-Agent-Autonome-Arke{T.RESET}",
    ]
    print()
    print(T.box(lines, title="À propos"))
    print()
