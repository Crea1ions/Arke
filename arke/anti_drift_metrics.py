"""Anti-Drift Metrics — Détection de violations des 3 invariants cognitifs.

Le système Arke repose sur 3 invariants immuables (cognitive_contract.md):
1. system_never_interprets: Agent décide, système exécute
2. system_never_decides_tools: Agent décide des outils, pas le système
3. system_never_executes_without_llm_intent: Toute exécution nécessite LLM intent

Cette module collecte des métriques temps réel pour détecter les violations.

Métriques (exposed via get_metrics()):
- agent_decision_pct: % de messages routés via LLM_AGENT vs total
- system_classifications: Nombre de fois où système a classifié sans agent (doit être 0)
- memory_interceptions: Patterns mémoire interceptés avant agent (doit être 0)
- tool_executions_without_agent: Outils exécutés sans décision agent (doit être 0)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class AntiDriftMetrics:
    """Singleton thread-safe pour collecter les métriques anti-drift."""

    # Compteurs (incrémentés par orchestrator, chat, etc.)
    agent_decisions: int = 0  # Nombre de décisions agent (LLM_AGENT route)
    total_messages: int = 0  # Total messages reçus (agent + slash + model override)
    system_classifications: int = 0  # Fois où système a classifié sans agent (VIOLATION)
    memory_interceptions: int = 0  # Patterns mémoire interceptés avant agent (VIOLATION)
    tool_executions_without_agent: int = 0  # Outils exécutés sans intent agent (VIOLATION)

    # Lock pour thread-safety (multithreaded REPL possible)
    _lock: Lock = field(default_factory=Lock)

    def increment_agent_decision(self) -> None:
        """Incrémenter agent_decisions et total_messages."""
        with self._lock:
            self.agent_decisions += 1
            self.total_messages += 1

    def increment_slash_or_model(self) -> None:
        """Incrémenter total_messages pour slash/model override (pas une décision agent)."""
        with self._lock:
            self.total_messages += 1

    def increment_system_classification(self) -> None:
        """🔴 VIOLATION: Système a classifié sans agent."""
        with self._lock:
            self.system_classifications += 1
            self.total_messages += 1

    def increment_memory_interception(self) -> None:
        """🔴 VIOLATION: Mémoire interceptée avant agent."""
        with self._lock:
            self.memory_interceptions += 1

    def increment_tool_execution_without_agent(self) -> None:
        """🔴 VIOLATION: Outil exécuté sans décision agent."""
        with self._lock:
            self.tool_executions_without_agent += 1

    def get_metrics(self) -> dict:
        """Retourner snapshot des métriques actuelles."""
        with self._lock:
            agent_decision_pct = (
                100 * self.agent_decisions / self.total_messages
                if self.total_messages > 0
                else 0
            )
            return {
                "agent_decision_pct": round(agent_decision_pct, 1),
                "total_messages": self.total_messages,
                "agent_decisions": self.agent_decisions,
                "system_classifications": self.system_classifications,
                "memory_interceptions": self.memory_interceptions,
                "tool_executions_without_agent": self.tool_executions_without_agent,
                "violations": (
                    self.system_classifications
                    + self.memory_interceptions
                    + self.tool_executions_without_agent
                ),
            }

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._lock:
            self.agent_decisions = 0
            self.total_messages = 0
            self.system_classifications = 0
            self.memory_interceptions = 0
            self.tool_executions_without_agent = 0


# Global singleton instance
_METRICS_INSTANCE: AntiDriftMetrics | None = None
_INSTANCE_LOCK = threading.Lock()


def get_metrics_instance() -> AntiDriftMetrics:
    """Retourner le singleton thread-safe AntiDriftMetrics."""
    global _METRICS_INSTANCE
    if _METRICS_INSTANCE is None:
        with _INSTANCE_LOCK:
            if _METRICS_INSTANCE is None:
                _METRICS_INSTANCE = AntiDriftMetrics()
    return _METRICS_INSTANCE
