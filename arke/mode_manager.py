"""arke/mode_manager.py — Source unique de vérité pour la gestion des modes agent.

Centralise :
- état courant du mode (ask | search | plan | agent)
- matrice de permissions par mode
- chargement des schémas JSON d'entrée par mode
- construction du contexte d'entrée injecté dans chaque appel LLM
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_VALID_MODES: frozenset[str] = frozenset({"ask", "search", "plan", "agent"})
_DEFAULT_MODE: str = "ask"
_SCHEMAS_DIR: Path = Path(__file__).parent.parent / "config" / "mode_schemas"

# ---------------------------------------------------------------------------
# État courant du mode (mutable via liste — thread-local compatible)
# ---------------------------------------------------------------------------

_agent_mode: list[str] = [_DEFAULT_MODE]


def get_mode() -> str:
    """Retourne le mode agent actif."""
    return _agent_mode[0]


def set_mode(mode: str) -> None:
    """Définit le mode agent actif.

    Args:
        mode: Un des modes valides : ask | search | plan | agent.

    Raises:
        ValueError: Si le mode n'est pas dans _VALID_MODES.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"Mode invalide : {mode!r}. Valides : {sorted(_VALID_MODES)}")
    _agent_mode[0] = mode


def is_valid_mode(mode: str) -> bool:
    """Retourne True si le mode est valide."""
    return mode in _VALID_MODES


# ---------------------------------------------------------------------------
# Matrice de permissions par mode
# ---------------------------------------------------------------------------

#: Tools permitted per mode. ``None`` means unrestricted (agent mode).
MODE_PERMISSIONS: dict[str, frozenset[str] | None] = {
    "ask":    frozenset(),
    "search": frozenset({
        "sqlite", "memory_fts", "memory_read", "memory_search",
        "vector_search", "web_search", "rss_reader", "calculator", "mcp",
    }),
    "plan":   frozenset({
        "sqlite", "memory_fts", "memory_read", "memory_search",
        "memory_write", "memory_forget", "vector_search",
    }),
    "agent":  None,  # accès complet
}


def can_execute_tool(tool_name: str, mode: str) -> bool:
    """Retourne True si *tool_name* est autorisé dans *mode*.

    Args:
        tool_name: Identifiant de l'outil (cli, fs, sqlite, mcp, …)
        mode: Cle du mode agent (ask, search, plan, agent).

    Returns:
        True si l'exécution est autorisée, False si bloquée.
    """
    allowed = MODE_PERMISSIONS.get(mode, frozenset())
    if allowed is None:  # mode agent — accès complet
        return True
    return tool_name in allowed


# ---------------------------------------------------------------------------
# Schémas JSON d'entrée par mode
# ---------------------------------------------------------------------------

def load_mode_schema(mode: str) -> dict:
    """Charge le schéma JSON d'entrée pour un mode donné.

    Lit ``config/mode_schemas/{mode}_input.json``. Retourne un dict vide
    si le fichier est absent (dégradé gracieux).

    Args:
        mode: Clé du mode agent (ask, search, plan, agent).

    Returns:
        Dict du schéma chargé, ou {} si absent.
    """
    schema_path = _SCHEMAS_DIR / f"{mode}_input.json"
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def build_input_context(
    mode: str,
    user_message: str,
    session_id: str = "",
    history: list | None = None,
    workspace_root: str | None = None,
) -> str:
    """Construit le contexte JSON injecté avant chaque appel LLM.

    Fusionne le schéma du mode avec les données runtime (session, message,
    historique). La structure est spécifique à chaque mode — aucun socle
    commun forcé au-delà du strict minimum runtime.

    Args:
        mode: Mode agent actif (ask | search | plan | agent).
        user_message: Message brut de l'utilisateur.
        session_id: ID de session (généré si absent).
        history: Historique de conversation (optionnel).

    Returns:
        Chaîne JSON prête à être injectée dans le contexte LLM.
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    schema = load_mode_schema(mode)

    context: dict = {
        "runtime": {
            "session_id": session_id,
            "turn_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
        },
        "input": {
            "user_message": user_message,
            "history_length": len(history) if history else 0,
        },
    }
    if workspace_root:
        context["runtime"]["WORKSPACE_ROOT"] = workspace_root

    context["priority_context_header"] = {
        "label": "CONTEXTE PRIORITAIRE",
        "scope": "Dernier échange et cadre de réponse courant",
        "instruction": (
            "Ce bloc prime sur les messages bruts. Il sert à préserver le lien "
            "entre la question actuelle et la réflexion précédente."
        ),
    }

    context["available_modes"] = {
        "ask": "Raisonnement, explication, analyse. Lecture mémoire et contexte.",
        "search": "Exploration lecture seule. Accès fs, SQLite, MCP search.",
        "plan": "Planification structurée. Lecture seule. Aucun outil d'écriture.",
        "agent": "Exécution technique complète. Tous outils disponibles.",
    }

    context["relay_instruction"] = (
        "Si la demande sort de ton périmètre actuel, réponds dans ton périmètre "
        "et indique le mode adapté à l'utilisateur."
    )

    # Fusionner avec le schéma du mode (le schéma enrichit le contexte)
    if schema:
        context.update(schema)

    # Toujours exposer le mode en tête pour la lisibilité LLM
    context["runtime"]["mode"] = mode

    return json.dumps(context, indent=2, ensure_ascii=False)
