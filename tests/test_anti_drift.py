"""Tests for anti-drift metrics — verify 3 invariants are maintained."""

import pytest

from arke.anti_drift_metrics import AntiDriftMetrics, get_metrics_instance


class TestAntiDriftMetrics:
    """Test suite for anti-drift metrics collection."""

    def setup_method(self):
        """Reset metrics before each test."""
        metrics = get_metrics_instance()
        metrics.reset()

    def test_agent_decision_percentage(self):
        """Test 1: agent_decision_pct tracks LLM_AGENT routing percentage."""
        metrics = get_metrics_instance()
        
        # Simulate 5 agent decisions out of 10 total messages
        for _ in range(5):
            metrics.increment_agent_decision()
        for _ in range(5):
            metrics.increment_slash_or_model()
        
        result = metrics.get_metrics()
        assert result["agent_decisions"] == 5
        assert result["total_messages"] == 10
        assert result["agent_decision_pct"] == 50.0
        assert result["violations"] == 0

    def test_system_classification_violation(self):
        """Test 2: system_classifications detects when system classifies without agent.
        
        This is a VIOLATION of 'system_never_interprets'.
        """
        metrics = get_metrics_instance()
        
        # Simulate system classifying without agent (should never happen)
        metrics.increment_system_classification()
        
        result = metrics.get_metrics()
        assert result["system_classifications"] == 1
        assert result["violations"] == 1  # 1 violation detected
        # This SHOULD trigger an alarm in production

    def test_memory_interception_violation(self):
        """Test 3: memory_interceptions detects patterns intercepted before agent.
        
        This is a VIOLATION of 'system_never_executes_without_llm_intent'.
        """
        metrics = get_metrics_instance()
        
        # Simulate memory pattern intercepted before agent (should never happen)
        metrics.increment_memory_interception()
        
        result = metrics.get_metrics()
        assert result["memory_interceptions"] == 1
        assert result["violations"] == 1  # 1 violation detected

    def test_tool_execution_without_agent_violation(self):
        """Test 4: tool_executions_without_agent detects tools run without agent decision.
        
        This is a VIOLATION of 'system_never_executes_without_llm_intent'.
        """
        metrics = get_metrics_instance()
        
        # Simulate tool executed without agent decision (should never happen)
        metrics.increment_tool_execution_without_agent()
        
        result = metrics.get_metrics()
        assert result["tool_executions_without_agent"] == 1
        assert result["violations"] == 1  # 1 violation detected

    def test_multiple_violations(self):
        """Test all 3 violations together."""
        metrics = get_metrics_instance()
        
        # Simulate multiple violations
        metrics.increment_system_classification()
        metrics.increment_memory_interception()
        metrics.increment_tool_execution_without_agent()
        
        result = metrics.get_metrics()
        assert result["system_classifications"] == 1
        assert result["memory_interceptions"] == 1
        assert result["tool_executions_without_agent"] == 1
        assert result["violations"] == 3  # All 3 violations detected

    def test_healthy_metrics_no_violations(self):
        """Test healthy system (100% agent decisions, 0 violations)."""
        metrics = get_metrics_instance()
        
        # All messages are agent decisions
        for _ in range(10):
            metrics.increment_agent_decision()
        
        result = metrics.get_metrics()
        assert result["agent_decisions"] == 10
        assert result["total_messages"] == 10
        assert result["agent_decision_pct"] == 100.0
        assert result["violations"] == 0

    def test_metrics_thread_safety(self):
        """Test thread-safe metrics (no race conditions)."""
        import threading
        metrics = get_metrics_instance()
        
        def worker():
            for _ in range(100):
                metrics.increment_agent_decision()
        
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        result = metrics.get_metrics()
        assert result["agent_decisions"] == 500
        assert result["total_messages"] == 500

    def test_zero_messages_edge_case(self):
        """Test edge case: no messages yet."""
        metrics = get_metrics_instance()
        result = metrics.get_metrics()
        
        assert result["total_messages"] == 0
        assert result["agent_decisions"] == 0
        assert result["agent_decision_pct"] == 0
        assert result["violations"] == 0

    def test_metrics_reset(self):
        """Test reset clears all counters."""
        metrics = get_metrics_instance()
        
        for _ in range(5):
            metrics.increment_agent_decision()
        
        result1 = metrics.get_metrics()
        assert result1["total_messages"] == 5
        
        metrics.reset()
        result2 = metrics.get_metrics()
        assert result2["total_messages"] == 0
        assert result2["agent_decisions"] == 0
        assert result2["violations"] == 0


# Invariant validation tests


class TestCognitiveInvariants:
    """Test that the 3 cognitive invariants hold."""

    def setup_method(self):
        """Reset metrics before each test."""
        metrics = get_metrics_instance()
        metrics.reset()

    def test_invariant_system_never_interprets(self):
        """Invariant 1: system_never_interprets.
        
        The system never interprets user intention without the agent.
        Violation: system_classifications > 0
        """
        metrics = get_metrics_instance()
        
        # Healthy operation
        for _ in range(10):
            metrics.increment_agent_decision()
        
        result = metrics.get_metrics()
        assert result["system_classifications"] == 0, "VIOLATION: System interpreted without agent"

    def test_invariant_system_never_decides_tools(self):
        """Invariant 2: system_never_decides_tools.
        
        Agent always decides which tools to use, never the system.
        Verified by: agent_decision_pct > threshold (when operating normally)
        """
        metrics = get_metrics_instance()
        
        # Healthy operation: 100% agent decisions
        for _ in range(10):
            metrics.increment_agent_decision()
        
        result = metrics.get_metrics()
        assert result["agent_decision_pct"] == 100.0, "System may have decided tools"

    def test_invariant_system_never_executes_without_llm_intent(self):
        """Invariant 3: system_never_executes_without_llm_intent.
        
        No execution happens without LLM agent intent.
        Violation: memory_interceptions > 0 OR tool_executions_without_agent > 0
        """
        metrics = get_metrics_instance()
        
        # Healthy operation
        for _ in range(10):
            metrics.increment_agent_decision()
        
        result = metrics.get_metrics()
        assert result["memory_interceptions"] == 0, "VIOLATION: Memory intercepted without agent"
        assert result["tool_executions_without_agent"] == 0, "VIOLATION: Tool executed without agent intent"
