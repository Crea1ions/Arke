"""VectorIndex — kNN search index backed by sqlite-vec virtual table.

Stores document embeddings in a ``vec0`` virtual table inside
``global.db``.  When ``vector_search`` is disabled the index is a no-op:
:meth:`search` returns ``[]``, :meth:`index` returns ``-1``.

Schema (created lazily on first access)::

    doc_embeddings   — content store (INTEGER PRIMARY KEY, TEXT content)
    vec_embeddings   — vec0 virtual table  (doc_id INTEGER PRIMARY KEY,
                                            embedding float[N])

The virtual table is created separately from the main schema because
sqlite-vec must be loaded on the connection before any ``vec0`` DDL.
"""

from __future__ import annotations

import json
import sqlite3
import time
import tomllib
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_BASE_DIR = Path(__file__).parent.parent.parent

#: Default embedding dimensions (Gemini text-embedding-004).
DEFAULT_DIMS: int = 768


def load_vector_config() -> dict[str, Any]:
    """Read ``[vector]`` section from ``config/arke.toml``.

    Returns:
        Dict with keys ``enabled``, ``model``, ``dimensions``.
    """
    config_path = _BASE_DIR / "config" / "arke.toml"
    try:
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)
        return data.get("vector", {})
    except FileNotFoundError:
        return {}


class VectorIndex:
    """Manages document indexing and kNN retrieval via sqlite-vec.

    Args:
        db_path: Path to the SQLite database file (usually ``global.db``).
        dimensions: Embedding vector dimensions.  Must match the model.
        enabled: Whether vector operations are active.  When *False*, all
            write/read methods are no-ops.
    """

    def __init__(
        self,
        db_path: Path | str,
        dimensions: int = DEFAULT_DIMS,
        enabled: bool = True,
    ) -> None:
        self._db_path = Path(db_path)
        self._dimensions = dimensions
        self._enabled = enabled
        if enabled:
            self._ensure_tables()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the index is active."""
        return self._enabled

    @property
    def dimensions(self) -> int:
        """Configured vector dimension."""
        return self._dimensions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index(self, content: str, embedding: list[float]) -> int:
        """Persist *content* and its *embedding* in the vector index.

        Args:
            content: The document text to index.
            embedding: Dense float vector of length :attr:`dimensions`.

        Returns:
            ``doc_id`` of the inserted row, or ``-1`` when disabled.
        """
        if not self._enabled:
            return -1

        vec_str = json.dumps(embedding)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO doc_embeddings (content) VALUES (?)", (content,)
            )
            doc_id = cur.lastrowid
            conn.execute(
                "INSERT OR REPLACE INTO vec_embeddings (doc_id, embedding) VALUES (?, ?)",
                (doc_id, vec_str),
            )
            conn.commit()

        log.info("vector.indexed", doc_id=doc_id, dims=len(embedding))
        return doc_id

    def search(self, query_embedding: list[float], k: int = 5) -> list[dict]:
        """Return the *k* nearest documents to *query_embedding*.

        Uses the ``MATCH`` operator from ``vec0`` (Euclidean / L2 distance).

        Args:
            query_embedding: Query vector of length :attr:`dimensions`.
            k: Maximum number of results to return.

        Returns:
            List of dicts with keys ``doc_id``, ``content``, ``distance``.
            Empty list when disabled or no documents indexed.
        """
        if not self._enabled:
            return []

        vec_str = json.dumps(query_embedding)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT v.doc_id, d.content, v.distance
                FROM vec_embeddings v
                JOIN doc_embeddings d ON d.doc_id = v.doc_id
                WHERE v.embedding MATCH ?
                  AND k = ?
                ORDER BY v.distance
                """,
                (vec_str, k),
            ).fetchall()

        return [dict(row) for row in rows]

    def search_timed(
        self, query_embedding: list[float], k: int = 5
    ) -> tuple[list[dict], float]:
        """Like :meth:`search` but also returns elapsed time.

        Args:
            query_embedding: Query vector.
            k: Maximum number of results.

        Returns:
            Tuple ``(results, elapsed_ms)`` where *elapsed_ms* is a float.
        """
        t0 = time.perf_counter()
        results = self.search(query_embedding, k)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return results, elapsed_ms

    def count(self) -> int:
        """Return the total number of indexed documents.

        Returns:
            ``0`` when disabled.
        """
        if not self._enabled:
            return 0
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM doc_embeddings"
            ).fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with sqlite-vec loaded.

        The extension is enabled only for the duration of this connection;
        ``enable_load_extension`` is disabled again after loading for
        security (prevents loading arbitrary extensions later).
        """
        import sqlite_vec  # lazy — only when vector is active

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn

    def _ensure_tables(self) -> None:
        """Create ``doc_embeddings`` and ``vec_embeddings`` if absent."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS doc_embeddings (
                    doc_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                    content    TEXT      NOT NULL,
                    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings
                USING vec0(
                    doc_id    INTEGER PRIMARY KEY,
                    embedding float[{self._dimensions}]
                )
                """
            )
            conn.commit()
        log.info("vector.tables_ready", db=str(self._db_path), dims=self._dimensions)
