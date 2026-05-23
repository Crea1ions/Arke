"""Embedder — generates dense vector embeddings for semantic search.

Uses ``litellm.embedding()`` to call the configured embedding model
(default: ``gemini/text-embedding-004``).

When ``vector_search = false`` (or ``enabled = false``) in ``arke.toml``,
:class:`Embedder` raises :exc:`VectorDisabledError` on any :meth:`embed`
call.

Configuration (``config/arke.toml``)::

    [vector]
    enabled    = true
    model      = "gemini/text-embedding-004"
    dimensions = 768
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_BASE_DIR = Path(__file__).parent.parent.parent

#: Default embedding model.
DEFAULT_MODEL: str = "gemini/text-embedding-004"

#: Default vector dimensions (Gemini text-embedding-004).
DEFAULT_DIMS: int = 768


class VectorDisabledError(RuntimeError):
    """Raised when vector search is disabled in ``arke.toml``."""


def _load_embedder_config() -> dict:
    """Read ``[vector]`` section from ``arke.toml``.

    Returns:
        Dict with keys ``enabled``, ``model``, ``dimensions``.
        Defaults to enabled=True, model=DEFAULT_MODEL, dimensions=DEFAULT_DIMS.
    """
    config_path = _BASE_DIR / "config" / "arke.toml"
    try:
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)
        return data.get("vector", {})
    except FileNotFoundError:
        return {}


class Embedder:
    """Generates dense embeddings via ``litellm.embedding()``.

    Args:
        model: Embedding model name.  Defaults to ``[vector] model`` in
            ``arke.toml`` or :data:`DEFAULT_MODEL`.
        dimensions: Vector length.  Defaults to ``[vector] dimensions``
            or :data:`DEFAULT_DIMS`.
        enabled: Override ``[vector] enabled`` from config when not *None*.
    """

    def __init__(
        self,
        model: str | None = None,
        dimensions: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        cfg = _load_embedder_config()
        self._enabled = enabled if enabled is not None else cfg.get("enabled", True)
        self._model = model or cfg.get("model", DEFAULT_MODEL)
        self._dimensions = dimensions or cfg.get("dimensions", DEFAULT_DIMS)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether embedding is active."""
        return self._enabled

    @property
    def dimensions(self) -> int:
        """Configured vector dimension."""
        return self._dimensions

    @property
    def model(self) -> str:
        """Embedding model name."""
        return self._model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for *text*.

        Args:
            text: Input text to embed (content or query string).

        Returns:
            Dense float vector of length :attr:`dimensions`.

        Raises:
            VectorDisabledError: If ``enabled = false`` in config.
            RuntimeError: If the embedding API call fails.
        """
        if not self._enabled:
            raise VectorDisabledError(
                "Vector search is disabled — set [vector] enabled = true in arke.toml"
            )

        import litellm  # lazy import — not needed when disabled
        litellm.suppress_debug_info = True

        response = litellm.embedding(model=self._model, input=[text])
        return response.data[0]["embedding"]
