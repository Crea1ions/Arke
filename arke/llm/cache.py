"""LlmCache — prompt-hash-based cache backed by ``cache.db``.

Cache strategy:
    - Key  : SHA-256 hash of ``(prompt, model_name)`` — ensures different
              models never share a cached response.
    - TTL  : Configurable via ``config/arke.toml`` → ``[cache] ttl_hours``
              (default 24 h).  Expired entries are deleted on first access.
    - Miss  : Returns ``None`` → caller must proceed with a real LLM call.
    - Hit   : Returns cached ``(response_text, cost_eur, tokens_used)``
              with ``cost_eur = 0.0`` (no API call made).

The ``purge_expired()`` method can be called manually or triggered
automatically on each :meth:`get` call.
"""

from __future__ import annotations

import hashlib
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arke.memory.manager import MemoryManager

_BASE_DIR = Path(__file__).parent.parent.parent
_DEFAULT_TTL_HOURS = 24


def _load_ttl() -> int:
    """Return TTL in hours from ``config/arke.toml``."""
    config_path = _BASE_DIR / "config" / "arke.toml"
    try:
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)
        return int(data.get("cache", {}).get("ttl_hours", _DEFAULT_TTL_HOURS))
    except FileNotFoundError:
        return _DEFAULT_TTL_HOURS


def prompt_hash(prompt: str, model: str) -> str:
    """Return the SHA-256 hex digest used as the cache key.

    Args:
        prompt: Full prompt string.
        model: Model name (e.g. ``'gemini/gemini-2.0-flash'``).

    Returns:
        64-character hexadecimal string.
    """
    digest_input = f"{model}\x00{prompt}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()


class LlmCache:
    """Cache adapter over ``cache.db`` via :class:`~arke.memory.manager.MemoryManager`.

    Args:
        memory: Optional :class:`~arke.memory.manager.MemoryManager`
            instance.  A new one is created lazily when *None*.
        ttl_hours: TTL override (useful in tests).  Uses ``arke.toml``
            value when *None*.
    """

    def __init__(
        self,
        memory: MemoryManager | None = None,
        ttl_hours: int | None = None,
    ) -> None:
        if memory is None:
            from arke.memory.manager import MemoryManager as _MM

            memory = _MM()
        self._mem = memory
        self._ttl_hours = ttl_hours if ttl_hours is not None else _load_ttl()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self, key: str
    ) -> tuple[str, float, int] | None:
        """Return the cached ``(response_text, cost_eur, tokens_used)`` or ``None``.

        Expired entries are deleted before returning.

        Args:
            key: Cache key produced by :func:`prompt_hash`.

        Returns:
            Tuple or ``None`` on a miss.
        """
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        rows = self._mem.query(
            "cache",
            "SELECT response, tokens_used, cost_eur, expires_at"
            " FROM llm_cache WHERE prompt_hash = ?",
            (key,),
        )
        if not rows:
            return None

        row = rows[0]
        expires_at = row["expires_at"]
        if expires_at and expires_at < now_iso:
            # Expired — delete and treat as miss
            self._mem.query(
                "cache",
                "DELETE FROM llm_cache WHERE prompt_hash = ?",
                (key,),
            )
            return None

        return row["response"], float(row["cost_eur"] or 0.0), int(row["tokens_used"] or 0)

    def put(
        self,
        key: str,
        response: str,
        model: str,
        tokens_used: int = 0,
        cost_eur: float = 0.0,
    ) -> None:
        """Insert or replace a cache entry with the configured TTL.

        Args:
            key: Cache key from :func:`prompt_hash`.
            response: LLM response text.
            model: Model identifier.
            tokens_used: Tokens consumed.
            cost_eur: Cost in euros.
        """
        now = datetime.now(tz=timezone.utc)
        if self._ttl_hours > 0:
            expires_at = (now + timedelta(hours=self._ttl_hours)).isoformat()
        else:
            expires_at = None  # no expiry

        self._mem.query(
            "cache",
            """
            INSERT OR REPLACE INTO llm_cache
                (prompt_hash, response, model, tokens_used, cost_eur, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (key, response, model, tokens_used, cost_eur, now.isoformat(), expires_at),
        )

    def purge_expired(self) -> int:
        """Delete all expired entries.

        Returns:
            Number of rows deleted.
        """
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        rows_before = self._mem.query(
            "cache", "SELECT COUNT(*) AS n FROM llm_cache WHERE expires_at < ?", (now_iso,)
        )
        count = rows_before[0]["n"] if rows_before else 0
        if count:
            self._mem.query(
                "cache",
                "DELETE FROM llm_cache WHERE expires_at < ?",
                (now_iso,),
            )
        return int(count)
