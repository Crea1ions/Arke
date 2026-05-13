"""Tests for result_analyzer — Result interpretation and summarization."""

import pytest

from arke import result_analyzer
from arke.task_graph import Step, StepStatus


class TestDiagnosticAnalysis:
    """Test diagnostic result analysis."""

    def test_analyze_disk_output(self):
        """Test disk usage analysis."""
        result = result_analyzer._analyze_disk_output(
            "Filesystem     Size  Used Avail Use% Mounted on\n"
            "/dev/sda1      100G   30G   70G  30% /\n"
        )
        assert "30G" in result
        assert "70G" in result

    def test_analyze_memory_output(self):
        """Test memory usage analysis."""
        result = result_analyzer._analyze_memory_output(
            "Mem:            15Gi       7,0Gi       4,0Gi\n"
        )
        assert "7,0Gi" in result or "7,0G" in result
        assert "15Gi" in result or "15G" in result

    def test_analyze_load_output(self):
        """Test load average analysis."""
        result = result_analyzer._analyze_load_output(
            " 10:30:45 up 2 days, load average: 1.23, 1.45, 1.67\n"
        )
        assert "1.23" in result
        assert "charge" in result.lower() or "load" in result.lower()

    def test_analyze_process_output(self):
        """Test process analysis."""
        output = (
            "USER       PID %CPU %MEM    VSZ   RSS TTY STAT\n"
            "user1      100  0.5  1.2  10000  2000 ?   S\n"
            "user2      200  0.3  0.8   8000  1600 ?   S\n"
        )
        result = result_analyzer._analyze_process_output(output)
        assert "processus" in result.lower() or "process" in result.lower()

    def test_infer_failure_reason_permission(self):
        """Test failure reason inference for permission errors."""
        reason = result_analyzer._infer_failure_reason("ss", "Permission denied")
        assert "permission" in reason.lower() or "accès" in reason.lower()

    def test_infer_failure_reason_not_found(self):
        """Test failure reason for command not found."""
        reason = result_analyzer._infer_failure_reason("systemctl", "command not found")
        assert "not available" in reason.lower() or "non disponible" in reason.lower()


class TestFormatSummary:
    """Test summary formatting."""

    def test_format_summary_with_metrics(self):
        """Test formatting analysis with metrics."""
        analysis = {
            "summary": ["💾 Disque: 30G utilisé, 70G libre (30% utilisé)"],
            "metrics": {"disk": "30G utilisé"},
            "failures": [],
            "recommendation": "✅ Système opérationnel.",
        }
        result = result_analyzer.format_summary(analysis)
        assert "Disque" in result or "disque" in result.lower()
        assert "Système" in result or "système" in result.lower()

    def test_format_summary_with_failures(self):
        """Test formatting with failures."""
        analysis = {
            "summary": [],
            "metrics": {},
            "failures": [{"tool": "ss", "reason": "Commande non disponible"}],
            "recommendation": "ℹ️ Certaines commandes",
        }
        result = result_analyzer.format_summary(analysis)
        assert "ss" in result
        assert "Commandes" in result or "commandes" in result.lower()


class TestAnalyzeDiagnosticResults:
    """Test full diagnostic analysis workflow."""

    def test_analyze_with_successful_steps(self):
        """Test analysis of successful diagnostic steps."""
        steps = [
            type("Step", (), {
                "tool": "cli",
                "status": type("Status", (), {"name": "SUCCESS"})(),
                "output": {"stdout": "Filesystem Size Used Avail\n/dev/sda1  100G 30G  70G"},
                "goal": "df"
            })(),
        ]
        
        result = result_analyzer.analyze_diagnostic_results(
            steps, "Rapport d'état des disques"
        )
        
        assert result["metrics"] or result["summary"]
        assert len(result["failures"]) == 0

    def test_analyze_with_failed_steps(self):
        """Test analysis with failed steps."""
        steps = [
            type("Step", (), {
                "tool": "ss",
                "status": type("Status", (), {"name": "FAILED"})(),
                "output": {"stdout": "command not found"},
                "goal": "network"
            })(),
        ]
        
        result = result_analyzer.analyze_diagnostic_results(
            steps, "Rapport réseau"
        )
        
        assert len(result["failures"]) > 0
        assert result["failures"][0]["tool"] == "ss"

    def test_analyze_generates_recommendation(self):
        """Test that analysis generates recommendations."""
        steps = [
            type("Step", (), {
                "tool": "ss",
                "status": type("Status", (), {"name": "FAILED"})(),
                "output": {"stdout": "error"},
                "goal": "network"
            })(),
        ]
        
        result = result_analyzer.analyze_diagnostic_results(
            steps, "État du système"
        )
        
        assert result["recommendation"] is not None
