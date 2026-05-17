"""MyTeamHub gateway API for Arke.

Local HTTP server exposing POST /api/v1/chat for MyTeamHub integration.
This adapter keeps MyTeamHub sessions isolated from REPL sessions while
reusing Arke cognitive pipeline.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from arke.chat import (
    _ask_agent,
    _apply_introspection_guard,
    _apply_workspace_listing_guard,
    _build_project_memory_response,
    _get_mode,
    _is_project_memory_request,
    _load_env_file,
    _set_mode,
    _strip_internal_markup,
    _synthesize_tool_results,
    build_cognitive_context,
)
from arke.chat_router import history_append, history_recent
from arke.init_workspace import ensure_arke_workspace
from arke.memory.manager import MemoryManager
from arke.mode_manager import can_execute_tool
from arke.orchestrator import run as run_task
from arke.task_graph import StepStatus


SESSION_TIMEOUT_SECONDS = 12 * 60 * 60
DEFAULT_ARKE_LOCAL_TOKEN = "arke-local-dev-token"

NAVIGATION_MESSAGE = (
    "Arke - Aucun workspace n'est configure pour MyTeamHub.\n\n"
    "Que souhaitez-vous faire ?\n\n"
    "1. /workspace-create <chemin>  - Creer un nouveau workspace .arke/\n"
    "2. /workspace-select <chemin>  - Utiliser un .arke/ existant\n\n"
    "Important: un espace est requis apres la commande.\n"
    "Exemple create : /workspace-create /home/user/projets/mon-projet\n"
    "Exemple select : /workspace-select /home/user/projets/mon-projet"
)

EXPIRATION_MESSAGE = (
    "Session MyTeamHub expiree (inactive depuis 12h).\n"
    "Envoyez un message pour configurer un workspace."
)

WORKSPACE_COMMAND_HELP = (
    "Commande workspace invalide.\n"
    "Utilisez exactement:\n"
    "- /workspace-create <chemin>\n"
    "- /workspace-select <chemin>\n"
    "Exemple: /workspace-select /home/user/projets/mon-projet"
)


@dataclass
class SessionState:
    workspace_root: Path
    mode: str
    last_seen: float


class MyTeamGateway:
    """Stateful MyTeamHub gateway orchestrating Arke message processing."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.RLock()
        self._env_lock = threading.Lock()

    def handle_chat(self, payload: dict[str, Any], auth_header: str | None) -> tuple[int, dict[str, Any]]:
        user_message = str(payload.get("user_message", "")).strip()
        session_id = str(payload.get("session_id", "")).strip()

        if not user_message:
            return 400, {"error": "user_message requis"}
        if not session_id:
            return 400, {"error": "session_id requis"}

        metadata = payload.get("metadata")
        metadata_err = self._validate_metadata(metadata)
        if metadata_err is not None:
            return 400, {"error": metadata_err}

        command = user_message.lower()
        with self._lock:
            state = self._sessions.get(session_id)

            if state and (time.time() - state.last_seen) > SESSION_TIMEOUT_SECONDS:
                del self._sessions[session_id]
                return 200, {
                    "response": EXPIRATION_MESSAGE,
                    "session_id": session_id,
                    "needs_workspace": True,
                }

            create_path = self._extract_workspace_path(user_message, "/workspace-create")
            if create_path is not None:
                workspace_root = self._normalize_workspace_root(Path(create_path))
                workspace_root.mkdir(parents=True, exist_ok=True)
                ensure_arke_workspace(workspace_root)
                self._init_myteam_state(workspace_root)
                self._sessions[session_id] = SessionState(
                    workspace_root=workspace_root,
                    mode="ask",
                    last_seen=time.time(),
                )
                return 200, {
                    "response": (
                        f"Workspace configure : {workspace_root}/.arke\n"
                        "Session MyTeamHub active. Vous pouvez commencer."
                    ),
                    "session_id": session_id,
                    "workspace": str(workspace_root),
                    "mode": "ask",
                }

            select_path = self._extract_workspace_path(user_message, "/workspace-select")
            if select_path is not None:
                workspace_root = self._normalize_workspace_root(Path(select_path))
                if not (workspace_root / ".arke").exists():
                    return 400, {"error": f"Workspace invalide: {workspace_root}/.arke introuvable"}
                ensure_arke_workspace(workspace_root)
                self._init_myteam_state(workspace_root)
                self._sessions[session_id] = SessionState(
                    workspace_root=workspace_root,
                    mode="ask",
                    last_seen=time.time(),
                )
                return 200, {
                    "response": (
                        f"Workspace configure : {workspace_root}/.arke\n"
                        "Session MyTeamHub active. Vous pouvez commencer."
                    ),
                    "session_id": session_id,
                    "workspace": str(workspace_root),
                    "mode": "ask",
                }

            # UX guard: user tried a workspace command but format is invalid.
            if "/workspace-create" in command or "/workspace-select" in command:
                return 200, {
                    "response": WORKSPACE_COMMAND_HELP,
                    "session_id": session_id,
                    "needs_workspace": state is None,
                }

            if state is None:
                return 200, {
                    "response": NAVIGATION_MESSAGE,
                    "session_id": session_id,
                    "needs_workspace": True,
                }

            state.last_seen = time.time()
            if metadata and metadata.get("studio_folder_path"):
                self._sync_structure_only(state.workspace_root, str(metadata.get("studio_folder_path", "")))

            token_error = self._validate_auth(auth_header, state.workspace_root)
            if token_error is not None:
                return 401, {"error": token_error}

            if command == "/ask":
                state.mode = "ask"
                return 200, {"response": "[ask] Mode analyse actif - aucun outil.", "session_id": session_id, "mode": state.mode}
            if command == "/search":
                state.mode = "search"
                return 200, {"response": "[search] Lecture seule active.", "session_id": session_id, "mode": state.mode}
            if command == "/plan":
                state.mode = "plan"
                return 200, {"response": "[plan] Planification active.", "session_id": session_id, "mode": state.mode}
            if command == "/agent":
                state.mode = "agent"
                return 200, {"response": "[agent] Mode execution actif.", "session_id": session_id, "mode": state.mode}
            if command == "/status":
                return 200, {
                    "response": f"Mode: {state.mode}\nWorkspace: {state.workspace_root}",
                    "session_id": session_id,
                    "mode": state.mode,
                }
            if command == "/help":
                return 200, {
                    "response": "Commandes: /ask /search /plan /agent /help /about /status /skills",
                    "session_id": session_id,
                    "mode": state.mode,
                }
            if command == "/about":
                return 200, {"response": "Arke - agent cognitif autonome local-first.", "session_id": session_id, "mode": state.mode}
            if command == "/skills":
                return 200, {"response": "Utilisez la commande REPL /skills pour le detail des skills actifs.", "session_id": session_id, "mode": state.mode}

            response_payload = self._execute_agent_turn(
                session_id=session_id,
                workspace_root=state.workspace_root,
                mode=state.mode,
                user_message=user_message,
                metadata=metadata if isinstance(metadata, dict) else None,
            )
            return 200, response_payload

    def _execute_agent_turn(
        self,
        *,
        session_id: str,
        workspace_root: Path,
        mode: str,
        user_message: str,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        _load_env_file()

        if metadata and metadata.get("selection"):
            user_message = f"{user_message}\n\n[Contexte partage : {metadata['selection']}]"

        myteam_root = workspace_root / ".arke" / "myteam"
        session_db = myteam_root / "sessions" / f"myth_{session_id}.db"

        with self._env_lock:
            old_workspace = os.environ.get("WORKSPACE_ROOT")
            old_session_db = os.environ.get("ARKE_SESSION_DB_PATH")
            os.environ["WORKSPACE_ROOT"] = str(workspace_root)
            os.environ["ARKE_SESSION_DB_PATH"] = str(session_db)
            try:
                mm = MemoryManager()
                _set_mode(mode)

                recent = history_recent(mm, n=5)
                context: dict[str, Any] = {
                    "agent_mode": mode,
                    "WORKSPACE_ROOT": str(workspace_root),
                    "session_id": session_id,
                }
                if recent:
                    context["history"] = recent

                cognitive_json = build_cognitive_context(user_message, session_id=session_id)
                context["cognitive_contract_json"] = cognitive_json

                agent_decision = _ask_agent(cognitive_json, user_message, context)
                agent_decision, force_render = _apply_introspection_guard(
                    user_message,
                    agent_decision,
                    cognitive_json,
                    context,
                )
                agent_decision, guard_applied = _apply_workspace_listing_guard(
                    user_message,
                    agent_decision,
                    mode,
                )
                force_render = force_render or guard_applied

                if agent_decision.get("tool") is None:
                    response = _strip_internal_markup(
                        agent_decision.get("response", "")
                    ).replace("\r\n", "\n").replace("\r", "")
                    if mode in ("search", "agent") and _is_project_memory_request(user_message):
                        response = _build_project_memory_response(mm)
                    if not response and force_render:
                        response = "Compris."

                    history_append(mm, "user", user_message, model_used=None)
                    history_append(mm, "assistant", response or "Reponse directe.", model_used=None)
                    self._write_action_log(
                        workspace_root,
                        {
                            "direction": "outgoing",
                            "session_id": session_id,
                            "mode": mode,
                            "response_length": len(response or ""),
                            "tools_used": [],
                        },
                    )
                    return {
                        "response": response or "Reponse directe.",
                        "session_id": session_id,
                        "mode": mode,
                        "tools_used": [],
                    }

                requested_tool = str(agent_decision.get("tool"))
                if not can_execute_tool(requested_tool, mode):
                    blocked = f"[Mode /{mode}] Analyse uniquement. Utilisez /agent pour executer des outils systeme."
                    history_append(mm, "user", user_message, model_used=None)
                    history_append(mm, "assistant", blocked, model_used=None)
                    return {
                        "response": blocked,
                        "session_id": session_id,
                        "mode": mode,
                        "tools_used": [],
                    }

                context["agent_decision"] = agent_decision
                start = time.perf_counter()
                task = run_task(user_message, context)
                duration_ms = int((time.perf_counter() - start) * 1000)
                tools_used = [step.tool for step in task.steps]

                if task.status == StepStatus.SUCCESS:
                    if mode in ("search", "agent"):
                        response = _synthesize_tool_results(user_message, task.steps) or "Exploration completee."
                    else:
                        response = _strip_internal_markup(agent_decision.get("response", "") or "")
                        if not response:
                            outputs: list[str] = []
                            for step in task.steps:
                                if step.status == StepStatus.SUCCESS:
                                    out = step.output
                                    if isinstance(out, dict):
                                        val = str(out.get("stdout", "")).strip()
                                    else:
                                        val = str(out).strip()
                                    if val:
                                        outputs.append(val)
                            response = "\n\n".join(outputs).strip() or "Tache terminee."
                else:
                    failed_step = next((s for s in task.steps if s.status == StepStatus.FAILED), None)
                    tool_name = failed_step.tool if failed_step else "?"
                    response = f"Echec : {tool_name}"

                history_append(mm, "user", user_message, model_used=None)
                history_append(mm, "assistant", response, model_used=None)

                self._write_action_log(
                    workspace_root,
                    {
                        "direction": "outgoing",
                        "session_id": session_id,
                        "mode": mode,
                        "response_length": len(response),
                        "tools_used": tools_used,
                        "duration_ms": duration_ms,
                    },
                )

                return {
                    "response": response,
                    "session_id": session_id,
                    "mode": mode,
                    "tools_used": tools_used,
                    "duration_ms": duration_ms,
                }
            finally:
                if old_workspace is None:
                    os.environ.pop("WORKSPACE_ROOT", None)
                else:
                    os.environ["WORKSPACE_ROOT"] = old_workspace
                if old_session_db is None:
                    os.environ.pop("ARKE_SESSION_DB_PATH", None)
                else:
                    os.environ["ARKE_SESSION_DB_PATH"] = old_session_db

    def _validate_metadata(self, metadata: Any) -> str | None:
        if metadata is None:
            return None
        if not isinstance(metadata, dict):
            return "metadata doit etre un objet"

        selection = str(metadata.get("selection", "")).strip()
        if not selection:
            return None

        required = ["selection", "file_path", "editor_language", "studio_folder_path"]
        missing = [k for k in required if not str(metadata.get(k, "")).strip()]
        if missing:
            return f"Metadata mal formee: champs manquants ({', '.join(missing)})"
        return None

    def _validate_auth(self, auth_header: str | None, workspace_root: Path) -> str | None:
        state_path = workspace_root / ".arke" / "myteam" / "state.json"
        if not state_path.exists():
            return "Token Arke invalide"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return "Token Arke invalide"

        expected = str(state.get("token", "")).strip()
        if not expected:
            return "Token Arke invalide"

        bearer = (auth_header or "").strip()
        if not bearer.startswith("Bearer "):
            return "Token Arke invalide"
        token = bearer.removeprefix("Bearer ").strip()
        if token != expected:
            return "Token Arke invalide"
        return None

    def _init_myteam_state(self, workspace_root: Path) -> None:
        myteam_root = workspace_root / ".arke" / "myteam"
        (myteam_root / "sessions").mkdir(parents=True, exist_ok=True)
        (myteam_root / "logs").mkdir(parents=True, exist_ok=True)
        (myteam_root / "structure").mkdir(parents=True, exist_ok=True)

        state_path = myteam_root / "state.json"
        token = os.environ.get("ARKE_MYTEAM_TOKEN") or DEFAULT_ARKE_LOCAL_TOKEN
        state = {
            "workspace_root": str(workspace_root),
            "token": token,
            "updated_at": int(time.time()),
        }
        state_path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
        os.chmod(state_path, 0o600)

    def _write_action_log(self, workspace_root: Path, payload: dict[str, Any]) -> None:
        myteam_log = workspace_root / ".arke" / "myteam" / "logs" / "myth_actions.log"
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **payload,
        }
        myteam_log.parent.mkdir(parents=True, exist_ok=True)
        with myteam_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=True) + "\n")

    def _sync_structure_only(self, workspace_root: Path, studio_folder_path: str) -> None:
        structure_root = workspace_root / ".arke" / "myteam" / "structure"
        structure_root.mkdir(parents=True, exist_ok=True)

        source = Path(studio_folder_path).expanduser()
        if source.exists() and source.is_dir():
            source = source.resolve()
            safe_root = structure_root / source.name
            safe_root.mkdir(parents=True, exist_ok=True)
            for current_dir, dirs, _files in os.walk(source):
                rel = Path(current_dir).resolve().relative_to(source)
                target_dir = safe_root / rel
                target_dir.mkdir(parents=True, exist_ok=True)
                for d in dirs:
                    (target_dir / d).mkdir(parents=True, exist_ok=True)
            return

        pseudo = studio_folder_path.strip().replace("\\", "/")
        if pseudo.startswith("/"):
            pseudo = pseudo[1:]
        if not pseudo:
            return
        target = structure_root / pseudo
        target.mkdir(parents=True, exist_ok=True)

    def _extract_workspace_path(self, raw_message: str, command: str) -> str | None:
        """Extract workspace path from flexible command forms.

        Accepted forms:
        - /workspace-select /path/to/project
        - /workspace-select/path/to/project
        - 2. /workspace-select /path/to/project
        """
        message = raw_message.strip()
        lowered = message.lower()
        idx = lowered.find(command)
        if idx == -1:
            return None

        tail = message[idx + len(command):].strip()
        if not tail:
            return ""

        if tail.startswith("/"):
            return tail

        # Support slash-stuck command style: /workspace-select/home/user/...
        if not tail.startswith("/") and "/" in tail and not tail.startswith("-"):
            return "/" + tail

        return tail

    def _normalize_workspace_root(self, path_value: Path) -> Path:
        """Normalize command path to project root, accepting <root> or <root>/.arke."""
        p = path_value.expanduser().resolve()
        if p.name == ".arke":
            return p.parent
        return p


_GATEWAY = MyTeamGateway()


class _Handler(BaseHTTPRequestHandler):
    server_version = "ArkeMyTeam/0.1"

    def _json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/v1/chat":
            self._json(404, {"error": "Not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json(400, {"error": "JSON invalide"})
            return

        status, body = _GATEWAY.handle_chat(payload, self.headers.get("Authorization"))
        self._json(status, body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 4777) -> None:
    """Run local MyTeamHub gateway server."""
    server = ThreadingHTTPServer((host, port), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
