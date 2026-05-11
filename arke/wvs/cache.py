"""
Workspace statistics cache — session-level singleton.

CRITICAL: This module is orchestrator-only. Never expose to LLM context.
"""

from pathlib import Path
from typing import Optional, Dict, Any
from arke.workspace import get_workspace_stats


class WorkspaceCache:
    """
    Session-level cache for workspace statistics.
    
    Singleton pattern ensures stats are computed once per session.
    Provides invalidation for testing and future multi-session scenarios.
    """
    
    _instance: Optional['WorkspaceCache'] = None
    _stats: Optional[Dict[str, Dict[str, Any]]] = None
    _wcu_root: Optional[Path] = None
    
    def __new__(cls):
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def initialize(cls, wcu_root: Path) -> 'WorkspaceCache':
        """
        Initialize cache with WCU root.
        
        Computes stats on first call, then serves from cache.
        
        Args:
            wcu_root: Path to WCU root directory
            
        Returns:
            WorkspaceCache singleton instance
        """
        cls._wcu_root = Path(wcu_root)
        # Stats computed lazily on first get()
        return cls()
    
    @classmethod
    def get(cls) -> Optional[Dict[str, Dict[str, Any]]]:
        """
        Get workspace stats (computed once per session).
        
        Returns:
            Dict of stats by section, or None if not initialized
        """
        if cls._stats is None and cls._wcu_root is not None:
            cls._stats = get_workspace_stats(cls._wcu_root)
        return cls._stats
    
    @classmethod
    def invalidate(cls):
        """
        Invalidate cache (for testing or multi-session scenarios).
        
        Next get() will recompute from filesystem.
        """
        cls._stats = None
        cls._wcu_root = None
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if cache is initialized."""
        return cls._wcu_root is not None
