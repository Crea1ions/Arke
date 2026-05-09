"""McpClient — JSON-RPC 2.0 HTTP client for a ContextForge MCP endpoint.

Implements only the two MCP methods used by Arke:
    ``tools/list``  — enumerate available external tools.
    ``tools/call``  — invoke a named tool with typed arguments.

All HTTP is done via :mod:`urllib.request` (stdlib) so no extra
dependency is required.

Raises :class:`McpUnavailableError` (a subclass of ``RuntimeError``)
whenever the server is unreachable or returns a non-200 status.  The
orchestrator catches this and degrades gracefully to the LLM fallback.
"""

from __future__ import annotations

import json
import os
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_BASE_DIR = Path(__file__).parent.parent.parent
_DEFAULT_URL = "http://localhost:3000/mcp"
_DEFAULT_TIMEOUT = 5


class McpUnavailableError(RuntimeError):
    """Raised when the ContextForge endpoint cannot be reached."""


def _load_mcp_config() -> tuple[str, int, bool]:
    """Return ``(base_url, timeout_sec, enabled)`` from ``config/arke.toml``.

    Falls back to defaults when the config file is absent or the
    ``[mcp]`` section is missing.  The ``CONTEXTFORGE_URL`` environment
    variable overrides ``base_url`` at runtime.
    """
    url = _DEFAULT_URL
    timeout = _DEFAULT_TIMEOUT
    enabled = True

    config_path = _BASE_DIR / "config" / "arke.toml"
    try:
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)
        mcp = data.get("mcp", {})
        url = mcp.get("base_url", url)
        timeout = int(mcp.get("timeout_sec", timeout))
        enabled = bool(mcp.get("enabled", enabled))
    except FileNotFoundError:
        pass

    # Runtime override — useful in tests and CI
    url = os.environ.get("CONTEXTFORGE_URL", url)
    return url, timeout, enabled


class McpClient:
    """HTTP JSON-RPC 2.0 client for a ContextForge MCP endpoint.

    Args:
        base_url: Full URL of the MCP endpoint.  Defaults to value from
            ``config/arke.toml`` (``http://localhost:3000/mcp``).
        timeout: HTTP timeout in seconds.  Defaults to ``arke.toml`` value.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        cfg_url, cfg_timeout, self._enabled = _load_mcp_config()
        self._url = base_url if base_url is not None else cfg_url
        self._timeout = timeout if timeout is not None else cfg_timeout
        self._req_id = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the list of tools exposed by ContextForge.

        Returns:
            List of tool descriptors, each with at minimum ``name``,
            ``description``, and ``inputSchema`` keys.

        Raises:
            McpUnavailableError: If the server cannot be reached.
        """
        result = self._request("tools/list", {})
        tools: list[dict] = result.get("tools", [])
        log.info("mcp.tools_listed", count=len(tools), url=self._url)
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a named MCP tool.

        Args:
            name: Tool name as returned by :meth:`list_tools`.
            arguments: Tool arguments conforming to the tool's
                ``inputSchema``.

        Returns:
            Dict with ``content`` (list of content blocks) and
            ``isError`` (bool).  Text content is available via
            ``result["content"][0]["text"]``.

        Raises:
            McpUnavailableError: If the server cannot be reached.
            ValueError: If the server returns a JSON-RPC error.
        """
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        log.info("mcp.tool_called", tool=name, is_error=result.get("isError", False))
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC 2.0 request and return ``result``."""
        if not self._enabled:
            raise McpUnavailableError("MCP integration is disabled in arke.toml")

        self._req_id += 1
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": self._req_id, "method": method, "params": params}
        ).encode()

        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise McpUnavailableError(
                f"ContextForge unreachable at {self._url!r}: {exc}"
            ) from exc

        try:
            data: dict = json.loads(body)
        except json.JSONDecodeError as exc:
            raise McpUnavailableError(
                f"Invalid JSON response from ContextForge: {exc}"
            ) from exc

        if "error" in data:
            err = data["error"]
            raise ValueError(
                f"MCP error {err.get('code', '?')}: {err.get('message', str(err))}"
            )

        return data.get("result", {})
