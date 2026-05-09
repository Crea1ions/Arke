"""arke.vector — semantic search backed by sqlite-vec.

Exports:
    :class:`~arke.vector.embedder.Embedder`
    :class:`~arke.vector.embedder.VectorDisabledError`
    :class:`~arke.vector.index.VectorIndex`
    :func:`~arke.vector.index.load_vector_config`
"""
from arke.vector.embedder import Embedder, VectorDisabledError
from arke.vector.index import VectorIndex, load_vector_config

__all__ = ["Embedder", "VectorDisabledError", "VectorIndex", "load_vector_config"]
