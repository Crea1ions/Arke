"""McpCache — tool-call cache backed by ``cache.db``.

Cache strategy:
    - Key  : (tool_name, SHA-256 of json.dumps(tool_args, sort_keys=True))
    - TTL  : Configurable via ``config/arke.toml`` → ``[mcp.cache_ttl]``
              (default 24 h). 0 in config = never expires (None).
    - Miss  : Returns ``None`` → caller proceeds with a live MCP call.
    - Hit   : Returns cached response string directly.

The ``purge_expired()`` method can be called manually to reclaim space.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arke.memory.manager import MemoryManager

_BASE_DIR = Path(__file__).parent.parent
_DEFAULT_TTL_HOURS = 24


def _load_ttl(tool_name: str) -> int | None:
    """Return TTL hours for *tool_name* from ``config/arke.toml``, or None for no expiry.

    ``0`` in config maps to ``None`` (never expires).

    Args:
        tool_name: MCP tool identifier (e.g. ``"web_search"``).

    Returns:
        Hours as int, or None for no expiry.
    """
    config_path = _BASE_DIR / "config" / "arke.toml"
    try:
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)
        ttl_map = data.get("mcp", {}).get("cache_ttl", {})
        if tool_name in ttl_map:
            val = int(ttl_map[tool_name])
            return None if val == 0 else val
        return _DEFAULT_TTL_HOURS
    except FileNotFoundError:
        return _DEFAULT_TTL_HOURS


def args_hash(tool_args: dict) -> str:
    """Return SHA-256 hex digest of the serialised *tool_args*.

    Keys are sorted to ensure deterministic output regardless of insertion
    order.

    Args:
        tool_args: Arguments passed to the MCP tool.

    Returns:
        64-character hexadecimal string.
    """
    payload = json.dumps(tool_args, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class McpCache:
    """Cache adapter over ``cache.db`` via :class:`~arke.memory.manager.MemoryManager`.

    Args:
        memory: Optional :class:`~arke.memory.manager.MemoryManager`
            instance.  A new one is created lazily when *None*.
    """

    def __init__(self, memory: MemoryManager | None = None) -> None:
        if memory is None:
            from arke.memory.manager import MemoryManager as _MM

            memory = _MM()
        self._mem = memory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, tool_name: str, tool_args: dict) -> str | None:
        """Return cached response text or ``None`` on miss or expiry.

        Expired entries are deleted on first access.  Hit counter is
        incremented for each cache hit.

        Args:
            tool_name: MCP tool identifier (e.g. ``"web_search"``).
            tool_args: Arguments passed to the tool.

        Returns:
            Cached response string or ``None``.
        """
        key = args_hash(tool_args)
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        rows = self._mem.query(
            "cache",
            "SELECT response, expires_at FROM mcp_cache"
            " WHERE tool_name = ? AND args_hash = ?",
            (tool_name, key),
        )
        if not rows:
            return None

        row = rows[0]
        expires_at = row["expires_at"]
        if expires_at and expires_at < now_iso:
            # Expired — delete and treat as miss
            self._mem.query(
                "cache",
                "DELETE FROM mcp_cache WHERE tool_name = ? AND args_hash = ?",
                (tool_name, key),
            )
            return None

        # Increment hit counter
        self._mem.query(
            "cache",
            "UPDATE mcp_cache SET hit_count = hit_count + 1"
            " WHERE tool_name = ? AND args_hash = ?",
            (tool_name, key),
        )
        return row["response"]

    def put(self, tool_name: str, tool_args: dict, response: str) -> None:
        """Insert or replace a cache entry with TTL from config.

        Args:
            tool_name: MCP tool identifier.
            tool_args: Arguments passed to the tool.
            response: Response text to cache (typically JSON).
        """
        key = args_hash(tool_args)
        now = datetime.now(tz=timezone.utc)
        ttl_hours = _load_ttl(tool_name)
        expires_at = (now + timedelta(hours=ttl_hours)).isoformat() if ttl_hours else None
        self._mem.query(
            "cache",
            """
            INSERT OR REPLACE INTO mcp_cache
                (tool_name, args_hash, response, created_at, expires_at, hit_count)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (tool_name, key, response, now.isoformat(), expires_at),
        )

    def purge_expired(self) -> int:
        """Delete all expired entries.

        Returns:
            Number of rows deleted.
        """
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        rows = self._mem.query(
            "cache",
            "SELECT COUNT(*) AS n FROM mcp_cache"
            " WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now_iso,),
        )
        count = rows[0]["n"] if rows else 0
        if count:
            self._mem.query(
                "cache",
                "DELETE FROM mcp_cache WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now_iso,),
            )
        return int(count)
