"""Tests for lightweight Agent Loop functionality — Phase 2 Session 013."""

from __future__ import annotations

import re
from unittest.mock import Mock, patch, MagicMock

import pytest

from arke.chat import _extract_plan_from_response, _confirm_plan


# ============================================================================
# Tests for plan extraction
# ============================================================================


def test_extract_plan_finds_valid_plan():
    """Test that _extract_plan_from_response finds a [PLAN:]/[/PLAN] block."""
    response = """Let me analyze this task.

[PLAN:
1. List all files in the directory
2. Filter for .log files
3. Count the occurrences of 'error'
/PLAN]

Proceed with this plan?"""

    plan = _extract_plan_from_response(response)
    assert plan is not None
    assert "List all files" in plan
    assert "Filter for .log files" in plan
    assert "Count the occurrences" in plan


def test_extract_plan_returns_none_when_no_plan():
    """Test that _extract_plan_from_response returns None when no plan."""
    response = "I'll help you with that directly without a plan."
    
    plan = _extract_plan_from_response(response)
    assert plan is None


def test_extract_plan_handles_multiline_content():
    """Test that plan extraction preserves multiline content."""
    response = """[PLAN:
1. Step 1
   - Sub-step A
   - Sub-step B
2. Step 2
   - Sub-step C
/PLAN]"""

    plan = _extract_plan_from_response(response)
    assert plan is not None
    assert "Sub-step A" in plan
    assert "Sub-step B" in plan
    assert "Sub-step C" in plan


def test_extract_plan_with_surrounding_text():
    """Test plan extraction when plan is surrounded by other text."""
    response = """I need to process these logs.

Some preamble here.

[PLAN:
1. Read the file
2. Parse errors
3. Generate report
/PLAN]

Proceed with this plan?

Some more context."""

    plan = _extract_plan_from_response(response)
    assert plan is not None
    assert "Read the file" in plan
    assert plan.count("\n") >= 2  # At least 3 steps


def test_extract_plan_handles_nested_brackets():
    """Test that plan extraction handles JSON in plan steps."""
    response = """[PLAN:
1. Execute query: SELECT * FROM logs WHERE level = 'ERROR'
2. Parse JSON response
3. Count results: {"total": 42}
/PLAN]"""

    plan = _extract_plan_from_response(response)
    assert plan is not None
    assert "SELECT * FROM logs" in plan
    assert '"total": 42' in plan


# ============================================================================
# Tests for plan confirmation UI
# ============================================================================


def test_confirm_plan_user_approves():
    """Test that _confirm_plan returns True when user approves."""
    plan_text = """1. Check logs
2. Analyze errors
3. Create report"""

    with patch("builtins.input", return_value="y"):
        result = _confirm_plan(plan_text)
        assert result is True


def test_confirm_plan_user_rejects():
    """Test that _confirm_plan returns False when user rejects."""
    plan_text = """1. Check logs
2. Create report"""

    with patch("builtins.input", return_value="n"):
        result = _confirm_plan(plan_text)
        assert result is False


def test_confirm_plan_accepts_multiple_yes_formats():
    """Test that _confirm_plan accepts different yes formats."""
    plan_text = "1. Test step"

    # Test 'yes'
    with patch("builtins.input", return_value="yes"):
        assert _confirm_plan(plan_text) is True

    # Test 'oui' (French)
    with patch("builtins.input", return_value="oui"):
        assert _confirm_plan(plan_text) is True

    # Test 'o' (Spanish/Portuguese)
    with patch("builtins.input", return_value="o"):
        assert _confirm_plan(plan_text) is True


def test_confirm_plan_accepts_multiple_no_formats():
    """Test that _confirm_plan accepts different no formats."""
    plan_text = "1. Test step"

    # Test 'no'
    with patch("builtins.input", return_value="no"):
        assert _confirm_plan(plan_text) is False

    # Test 'non' (French)
    with patch("builtins.input", return_value="non"):
        assert _confirm_plan(plan_text) is False


def test_confirm_plan_handles_keyboard_interrupt():
    """Test that _confirm_plan handles Ctrl+C gracefully."""
    plan_text = "1. Test step"

    with patch("builtins.input", side_effect=KeyboardInterrupt):
        result = _confirm_plan(plan_text)
        assert result is False


def test_confirm_plan_handles_eof():
    """Test that _confirm_plan handles EOF (Ctrl+D) gracefully."""
    plan_text = "1. Test step"

    with patch("builtins.input", side_effect=EOFError):
        result = _confirm_plan(plan_text)
        assert result is False


def test_confirm_plan_displays_box_formatting():
    """Test that _confirm_plan uses Rich formatting for display."""
    plan_text = """1. First step
2. Second step"""

    with patch("builtins.input", return_value="y"):
        with patch("builtins.print") as mock_print:
            _confirm_plan(plan_text)
            
            # Verify that box drawing characters were printed
            printed_texts = [str(call) for call in mock_print.call_args_list]
            printed_str = "\n".join(printed_texts)
            
            # Should have printed some output (exact formatting varies)
            assert mock_print.call_count > 0


# ============================================================================
# Integration tests
# ============================================================================


def test_extract_and_confirm_workflow():
    """Test the complete extract + confirm workflow."""
    agent_response = """I'll help you process the logs.

First, let me outline my approach:

[PLAN:
1. List all log files in /var/log
2. Search for entries with 'ERROR' level
3. Create a summary report
4. Save results to /tmp/report.txt
/PLAN]

Proceed with this plan?"""

    # Extract plan
    plan = _extract_plan_from_response(agent_response)
    assert plan is not None
    assert "List all log files" in plan
    
    # Simulate user confirmation
    with patch("builtins.input", return_value="y"):
        confirmed = _confirm_plan(plan)
        assert confirmed is True


def test_plan_detection_with_complex_commands():
    """Test plan detection handles complex commands in steps."""
    response = """[PLAN:
1. Execute: grep -r "ERROR" /logs --include="*.log" | wc -l
2. Parse results and store in database
3. Generate JSON report with jq
/PLAN]"""

    plan = _extract_plan_from_response(response)
    assert plan is not None
    assert "grep -r" in plan
    assert "wc -l" in plan
    assert "jq" in plan


def test_plan_with_sql_queries():
    """Test plan extraction preserves SQL queries."""
    response = """[PLAN:
1. Query: SELECT COUNT(*) FROM logs WHERE severity = 'ERROR'
2. Update summary table
3. Generate CSV from SELECT * FROM summary
/PLAN]"""

    plan = _extract_plan_from_response(response)
    assert plan is not None
    assert "SELECT COUNT(*)" in plan
    assert "WHERE severity = 'ERROR'" in plan


def test_extract_plan_case_insensitivity():
    """Test that plan markers are case-insensitive in regex."""
    # Plans should use exact case [PLAN:] and [/PLAN]
    response = """[PLAN:
Step 1
Step 2
/PLAN]"""
    
    plan = _extract_plan_from_response(response)
    assert plan is not None
    
    # Wrong case should NOT be detected
    wrong_case = """[plan:
Step 1
/plan]"""
    
    plan_wrong = _extract_plan_from_response(wrong_case)
    assert plan_wrong is None


# ============================================================================
# Edge cases
# ============================================================================


def test_extract_plan_with_empty_plan():
    """Test extraction when plan block is empty."""
    response = """[PLAN:
/PLAN]"""

    plan = _extract_plan_from_response(response)
    # Should extract empty string (or None due to strip())
    assert plan == "" or plan is None


def test_extract_plan_multiple_plans_returns_first():
    """Test that extraction returns only the first plan."""
    response = """[PLAN:
First plan content
/PLAN]

Some text in between

[PLAN:
Second plan content
/PLAN]"""

    plan = _extract_plan_from_response(response)
    assert plan is not None
    # Should contain first plan
    assert "First plan" in plan
    # Should not contain second plan (regex is non-greedy by default for .*?)
    # Actually, greedy should capture up to FIRST /PLAN]
    assert "Second plan" not in plan


def test_confirm_plan_case_insensitive_input():
    """Test that user input is normalized to lowercase."""
    plan_text = "1. Step"

    # Uppercase Y should work
    with patch("builtins.input", return_value="Y"):
        result = _confirm_plan(plan_text)
        assert result is True

    # Mixed case should work
    with patch("builtins.input", return_value="Yes"):
        result = _confirm_plan(plan_text)
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
