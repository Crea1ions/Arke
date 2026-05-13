"""Tests for task_classifier — Classification logic for SIMPLE, COMPLEX, DANGEROUS tasks."""

import pytest

from arke import task_classifier


class TestSimpleTaskClassification:
    """Simple tasks: read-only, single-step, no side effects."""

    def test_web_search_is_simple(self):
        """Web search should be classified as SIMPLE."""
        result = task_classifier.classify(
            "Search for latest Python news",
            tools=["web_search"],
            step_count=1,
        )
        assert result == "simple"

    def test_calculator_is_simple(self):
        """Calculator operation should be SIMPLE."""
        result = task_classifier.classify(
            "Calculate 15 * 42",
            tools=["calculator"],
            step_count=1,
        )
        assert result == "simple"

    def test_read_operation_is_simple(self):
        """Read operation should be SIMPLE."""
        result = task_classifier.classify(
            "Read and analyze this file",
            tools=["cli"],
            step_count=1,
            args={"command": "cat /tmp/data.txt"},
        )
        assert result == "simple"

    def test_list_operation_is_simple(self):
        """List directory should be SIMPLE."""
        result = task_classifier.classify(
            "List files in /tmp",
            tools=["cli"],
            step_count=1,
            args={"command": "ls /tmp"},
        )
        assert result == "simple"


class TestComplexTaskClassification:
    """Complex tasks: multi-step, modifications, state mutations."""

    def test_multistep_is_complex(self):
        """Multi-step tasks are COMPLEX."""
        result = task_classifier.classify(
            "Extract data from API, transform it, save to database",
            tools=["cli", "sqlite"],
            step_count=3,
        )
        assert result == "complex"

    def test_write_operation_is_complex(self):
        """Write operation should be COMPLEX."""
        result = task_classifier.classify(
            "Create a configuration file",
            tools=["cli"],
            step_count=1,
            args={"command": "echo 'config' > /tmp/config.yaml"},
        )
        assert result == "complex"

    def test_sqlite_insert_is_complex(self):
        """SQLite INSERT should be COMPLEX."""
        result = task_classifier.classify(
            "Insert user data into database",
            tools=["sqlite"],
            step_count=1,
            args={"query": "INSERT INTO users (name) VALUES (?)"},
        )
        assert result == "complex"

    def test_package_install_is_complex(self):
        """Package installation is COMPLEX (system modification)."""
        result = task_classifier.classify(
            "Install required dependencies",
            tools=["cli"],
            step_count=1,
            args={"command": "pip install requests"},
        )
        assert result == "complex"


class TestDangerousTaskClassification:
    """Dangerous tasks: destructive, sensitive paths, sensitive operations."""

    def test_rm_is_dangerous(self):
        """rm command should be DANGEROUS."""
        result = task_classifier.classify(
            "Delete old log files",
            tools=["cli"],
            step_count=1,
            args={"command": "rm /tmp/old_logs.txt"},
        )
        assert result == "dangerous"

    def test_rm_rf_is_dangerous(self):
        """rm -rf is DANGEROUS."""
        result = task_classifier.classify(
            "Clean up the cache directory",
            tools=["cli"],
            step_count=1,
            args={"command": "rm -rf /tmp/cache"},
        )
        assert result == "dangerous"

    def test_sql_delete_is_dangerous(self):
        """SQL DELETE should be DANGEROUS."""
        result = task_classifier.classify(
            "Clean up inactive users",
            tools=["sqlite"],
            step_count=1,
            args={"query": "DELETE FROM users WHERE active = 0"},
        )
        assert result == "dangerous"

    def test_sql_drop_is_dangerous(self):
        """SQL DROP is DANGEROUS."""
        result = task_classifier.classify(
            "Remove the old schema",
            tools=["sqlite"],
            step_count=1,
            args={"query": "DROP TABLE old_schema"},
        )
        assert result == "dangerous"

    def test_unlink_is_dangerous(self):
        """unlink is DANGEROUS."""
        result = task_classifier.classify(
            "Remove a symlink",
            tools=["cli"],
            step_count=1,
            args={"command": "unlink /tmp/symlink"},
        )
        assert result == "dangerous"

    def test_intention_with_delete_keyword_is_dangerous(self):
        """Intention containing 'delete' should be DANGEROUS."""
        result = task_classifier.classify(
            "Delete user account permanently",
            tools=["sqlite"],
            step_count=1,
        )
        assert result == "dangerous"

    def test_intention_with_remove_keyword_is_dangerous(self):
        """Intention with 'remove' keyword should be DANGEROUS."""
        result = task_classifier.classify(
            "Remove all temporary files",
            tools=["cli"],
            step_count=1,
        )
        assert result == "dangerous"

    def test_restricted_path_is_dangerous(self):
        """Write to restricted paths (.ssh, /etc) should be DANGEROUS."""
        result = task_classifier.classify(
            "Update SSH config",
            tools=["cli"],
            step_count=1,
            args={"command": "echo 'new_key' >> ~/.ssh/config"},
        )
        assert result == "dangerous"

    def test_etc_path_is_dangerous(self):
        """Write to /etc should be DANGEROUS."""
        result = task_classifier.classify(
            "Update system config",
            tools=["cli"],
            step_count=1,
            args={"command": "echo 'config' > /etc/app.conf"},
        )
        assert result == "dangerous"


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_tools_defaults_to_complex(self):
        """No tools specified defaults to COMPLEX (conservative)."""
        result = task_classifier.classify(
            "Do something",
            tools=[],
            step_count=1,
        )
        assert result == "complex"

    def test_mixed_safe_and_unsafe_tools(self):
        """Mix of safe + unsafe tools → classify by dangerous content."""
        result = task_classifier.classify(
            "Search and delete results",
            tools=["web_search", "cli"],
            step_count=2,
            args={"command": "rm results.txt"},
        )
        assert result == "dangerous"

    def test_safe_readonly_sql_query(self):
        """SELECT query should be SIMPLE."""
        result = task_classifier.classify(
            "Retrieve user data",
            tools=["sqlite"],
            step_count=1,
            args={"query": "SELECT * FROM users WHERE id = 1"},
        )
        assert result == "simple"

    def test_case_insensitivity_in_delete_detection(self):
        """DELETE detection should be case-insensitive."""
        result = task_classifier.classify(
            "Clean data",
            tools=["sqlite"],
            step_count=1,
            args={"query": "delete FROM old_records"},  # lowercase
        )
        assert result == "dangerous"

    def test_rss_reader_is_simple(self):
        """RSS reader (read-only) should be SIMPLE."""
        result = task_classifier.classify(
            "Read latest tech news",
            tools=["rss_reader"],
            step_count=1,
        )
        assert result == "simple"


class TestExplain:
    """Test explanation messages."""

    def test_explain_simple(self):
        """Explain should return user-friendly text for SIMPLE."""
        msg = task_classifier.explain("simple")
        assert "simple" in msg.lower()
        assert "lecture" in msg.lower() or "read" in msg.lower()

    def test_explain_complex(self):
        """Explain should describe COMPLEX tasks."""
        msg = task_classifier.explain("complex")
        assert "complex" in msg.lower() or "modification" in msg.lower()

    def test_explain_dangerous(self):
        """Explain should emphasize danger of DANGEROUS tasks."""
        msg = task_classifier.explain("dangerous")
        assert "danger" in msg.lower() or "destructive" in msg.lower()
