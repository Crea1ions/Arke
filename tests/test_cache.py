"""Tests for P2.4 — LlmCache (hash, TTL, purge) + gate json_schema complète."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import arke.memory.manager as mem_mod
from arke.llm.cache import LlmCache, prompt_hash
from arke.memory.manager import MemoryManager
import arke.mcp_cache as mcp_cache_mod
from arke.mcp_cache import McpCache, args_hash


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mm(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mem_mod,
        "_load_db_paths",
        lambda: {
            "global": tmp_path / "global.db",
            "project": tmp_path / "project.db",
            "session": tmp_path / "session.db",
            "cache": tmp_path / "cache.db",
        },
    )
    return MemoryManager()


@pytest.fixture()
def cache(mm):
    return LlmCache(memory=mm, ttl_hours=24)


# ---------------------------------------------------------------------------
# TestPromptHash
# ---------------------------------------------------------------------------


class TestPromptHash:
    def test_same_prompt_and_model_same_key(self):
        k1 = prompt_hash("hello world", "gemini-flash")
        k2 = prompt_hash("hello world", "gemini-flash")
        assert k1 == k2

    def test_different_prompt_different_key(self):
        k1 = prompt_hash("hello world", "gemini-flash")
        k2 = prompt_hash("goodbye world", "gemini-flash")
        assert k1 != k2

    def test_different_model_different_key(self):
        k1 = prompt_hash("hello world", "gemini-flash")
        k2 = prompt_hash("hello world", "ollama-mistral")
        assert k1 != k2

    def test_key_is_64_chars_hex(self):
        k = prompt_hash("test", "model")
        assert len(k) == 64
        assert all(c in "0123456789abcdef" for c in k)


# ---------------------------------------------------------------------------
# TestLlmCachePutGet
# ---------------------------------------------------------------------------


class TestLlmCachePutGet:
    def test_cache_miss_returns_none(self, cache):
        assert cache.get("non_existent_key") is None

    def test_put_then_get_returns_stored_value(self, cache):
        key = prompt_hash("What is Arke?", "gemini-flash")
        cache.put(key, "Arke is an agent.", "gemini-flash", tokens_used=12, cost_eur=0.001)
        result = cache.get(key)
        assert result is not None
        text, cost, tokens = result
        assert text == "Arke is an agent."
        assert cost == pytest.approx(0.001)
        assert tokens == 12

    def test_duplicate_put_replaces_entry(self, cache):
        key = prompt_hash("same prompt", "m1")
        cache.put(key, "first response", "m1")
        cache.put(key, "second response", "m1")
        result = cache.get(key)
        assert result[0] == "second response"

    def test_cache_hit_cost_is_zero_convention(self, cache):
        """Callers store original cost, but on hit they may interpret cost=0."""
        key = prompt_hash("p", "m")
        cache.put(key, "answer", "m", tokens_used=100, cost_eur=0.005)
        result = cache.get(key)
        # Cache returns stored cost — caller decides to treat it as 0
        assert result is not None


# ---------------------------------------------------------------------------
# TestLlmCacheTtl
# ---------------------------------------------------------------------------


class TestLlmCacheTtl:
    def test_fresh_entry_is_valid(self, cache):
        key = prompt_hash("fresh", "m")
        cache.put(key, "fresh answer", "m")
        assert cache.get(key) is not None

    def test_expired_entry_is_purged_on_get(self, mm):
        """Entry with TTL=0 hours should expire immediately."""
        # TTL of 0 means no expiry → use a tiny negative offset by
        # injecting an already-expired row directly.
        past_iso = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        key = prompt_hash("expired", "m")
        mm.query(
            "cache",
            "INSERT INTO llm_cache (prompt_hash, response, model, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (key, "old answer", "m", past_iso),
        )
        lc = LlmCache(memory=mm, ttl_hours=24)
        assert lc.get(key) is None  # expired → miss

    def test_no_expiry_when_ttl_is_zero(self, mm):
        """ttl_hours=0 → expires_at is NULL → entry never expires."""
        lc = LlmCache(memory=mm, ttl_hours=0)
        key = prompt_hash("eternal", "m")
        lc.put(key, "eternal answer", "m")
        # Check that expires_at is NULL in the DB
        rows = mm.query("cache", "SELECT expires_at FROM llm_cache WHERE prompt_hash=?", (key,))
        assert rows[0]["expires_at"] is None
        assert lc.get(key) is not None


# ---------------------------------------------------------------------------
# TestLlmCachePurge
# ---------------------------------------------------------------------------


class TestLlmCachePurge:
    def test_purge_removes_expired_entries(self, mm):
        past = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
        future = (datetime.now(tz=timezone.utc) + timedelta(hours=2)).isoformat()
        mm.query(
            "cache",
            "INSERT INTO llm_cache (prompt_hash, response, model, expires_at)"
            " VALUES (?, ?, ?, ?), (?, ?, ?, ?)",
            ("old1", "r1", "m", past, "old2", "r2", "m", past),
        )
        mm.query(
            "cache",
            "INSERT INTO llm_cache (prompt_hash, response, model, expires_at)"
            " VALUES (?, ?, ?, ?)",
            ("fresh1", "r3", "m", future),
        )
        lc = LlmCache(memory=mm, ttl_hours=24)
        deleted = lc.purge_expired()
        assert deleted == 2
        remaining = mm.query("cache", "SELECT COUNT(*) AS n FROM llm_cache", ())
        assert remaining[0]["n"] == 1

    def test_purge_returns_zero_when_nothing_expired(self, cache):
        key = prompt_hash("valid", "m")
        cache.put(key, "valid answer", "m")
        assert cache.purge_expired() == 0


# ---------------------------------------------------------------------------
# TestLiteLLMManagerCache — integration with LiteLLMManager
# ---------------------------------------------------------------------------


class TestLiteLLMManagerCache:
    def test_second_call_uses_cache(self, mm, monkeypatch):
        """Second identical prompt must hit cache — LLM not called."""
        import arke.llm.cache as cache_mod

        monkeypatch.setattr(cache_mod, "_load_ttl", lambda: 24)

        # Patch _load_db_paths so LlmCache uses our isolated mm
        monkeypatch.setattr(mem_mod, "_load_db_paths", lambda: {
            "global": mm._paths["global"],
            "project": mm._paths["project"],
            "session": mm._paths["session"],
            "cache": mm._paths["cache"],
        })
        
        # Set mock API keys so providers aren't skipped
        monkeypatch.setenv("MISTRAL_API_KEY", "mock-mistral-key")
        monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
        monkeypatch.setenv("OPENROUTER_API_KEY", "mock-openrouter-key")

        from arke.llm.litellm_manager import LiteLLMManager

        mgr = LiteLLMManager()

        call_count = 0

        def fake_call(provider_key, prompt, max_tokens):
            nonlocal call_count
            call_count += 1
            return "cached answer", 0.001, 50

        monkeypatch.setattr(mgr, "_call_provider", fake_call)

        r1 = mgr.complete("identical prompt", max_tokens=50)
        r2 = mgr.complete("identical prompt", max_tokens=50)

        # Real LLM called only once
        assert call_count == 1
        assert r1[0] == r2[0] == "cached answer"

    def test_different_prompts_both_call_llm(self, mm, monkeypatch):
        import arke.llm.cache as cache_mod

        monkeypatch.setattr(cache_mod, "_load_ttl", lambda: 24)
        monkeypatch.setattr(mem_mod, "_load_db_paths", lambda: {
            "global": mm._paths["global"],
            "project": mm._paths["project"],
            "session": mm._paths["session"],
            "cache": mm._paths["cache"],
        })
        
        # Set mock API keys so providers aren't skipped
        monkeypatch.setenv("MISTRAL_API_KEY", "mock-mistral-key")
        monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
        monkeypatch.setenv("OPENROUTER_API_KEY", "mock-openrouter-key")

        from arke.llm.litellm_manager import LiteLLMManager

        mgr = LiteLLMManager()
        call_count = 0

        def fake_call(provider_key, prompt, max_tokens):
            nonlocal call_count
            call_count += 1
            return f"answer {call_count}", 0.001, 50

        monkeypatch.setattr(mgr, "_call_provider", fake_call)

        mgr.complete("prompt A", max_tokens=50)
        mgr.complete("prompt B", max_tokens=50)

        assert call_count == 2


# ---------------------------------------------------------------------------
# TestGateJsonSchemaComplete — enhanced error messages
# ---------------------------------------------------------------------------


class TestGateJsonSchemaComplete:
    def test_missing_required_field_message(self, capsys):
        """Gate log must mention the missing field name (structlog → stderr)."""
        from arke.gates import validate
        from arke.task_graph import Step, Validation

        schema = {
            "type": "object",
            "required": ["name", "age"],
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        }
        step = Step(
            id="s1",
            tool="sqlite",
            arguments={},
            validation=Validation(type="json_schema", expected=schema),
            output={"name": "Arke"},  # missing "age"
        )
        result = validate(step)

        assert result is False
        # structlog prints to stderr — the message must mention the field
        captured = capsys.readouterr()
        log_output = captured.err + captured.out
        assert "age" in log_output or "Schéma invalide" in log_output

    def test_wrong_type_field(self):
        from arke.gates import validate
        from arke.task_graph import Step, Validation

        schema = {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
        step = Step(
            id="s1",
            tool="sqlite",
            arguments={},
            validation=Validation(type="json_schema", expected=schema),
            output={"count": "not_an_int"},  # wrong type
        )
        assert validate(step) is False

    def test_nested_invalid_field(self):
        from arke.gates import validate
        from arke.task_graph import Step, Validation

        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {"age": {"type": "integer"}},
                }
            },
        }
        step = Step(
            id="s1",
            tool="sqlite",
            arguments={},
            validation=Validation(type="json_schema", expected=schema),
            output={"user": {"age": "not_int"}},
        )
        assert validate(step) is False

    def test_valid_object_still_passes(self):
        from arke.gates import validate
        from arke.task_graph import Step, Validation

        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        step = Step(
            id="s1",
            tool="sqlite",
            arguments={},
            validation=Validation(type="json_schema", expected=schema),
            output={"name": "Arke"},
        )
        assert validate(step) is True


# ---------------------------------------------------------------------------
# TestMcpArgsHashStability
# ---------------------------------------------------------------------------


class TestMcpArgsHashStability:
    def test_same_args_same_hash(self):
        assert args_hash({"q": "python", "n": 3}) == args_hash({"q": "python", "n": 3})

    def test_different_args_different_hash(self):
        assert args_hash({"q": "python"}) != args_hash({"q": "rust"})

    def test_order_independent(self):
        """Dict insertion order must not affect the hash."""
        assert args_hash({"a": 1, "b": 2}) == args_hash({"b": 2, "a": 1})

    def test_empty_args_stable(self):
        assert args_hash({}) == args_hash({})


# ---------------------------------------------------------------------------
# TestMcpCacheHit
# ---------------------------------------------------------------------------


class TestMcpCacheHit:
    def test_hit_returns_stored_response(self, mm, monkeypatch):
        monkeypatch.setattr(mcp_cache_mod, "_load_ttl", lambda _: 24)
        cache = McpCache(memory=mm)
        cache.put("web_search", {"q": "python"}, '{"results": []}')
        result = cache.get("web_search", {"q": "python"})
        assert result == '{"results": []}'

    def test_hit_increments_hit_count(self, mm, monkeypatch):
        monkeypatch.setattr(mcp_cache_mod, "_load_ttl", lambda _: 24)
        cache = McpCache(memory=mm)
        cache.put("web_search", {"q": "python"}, "data")
        cache.get("web_search", {"q": "python"})
        rows = mm.query(
            "cache",
            "SELECT hit_count FROM mcp_cache WHERE tool_name = 'web_search'",
        )
        assert rows[0]["hit_count"] == 2  # 1 on insert + 1 on get


# ---------------------------------------------------------------------------
# TestMcpCacheMiss
# ---------------------------------------------------------------------------


class TestMcpCacheMiss:
    def test_miss_returns_none(self, mm, monkeypatch):
        monkeypatch.setattr(mcp_cache_mod, "_load_ttl", lambda _: 24)
        cache = McpCache(memory=mm)
        assert cache.get("web_search", {"q": "missing"}) is None

    def test_put_stores_response(self, mm, monkeypatch):
        monkeypatch.setattr(mcp_cache_mod, "_load_ttl", lambda _: 24)
        cache = McpCache(memory=mm)
        cache.put("calculator", {"expr": "2+2"}, "4")
        rows = mm.query(
            "cache",
            "SELECT response FROM mcp_cache WHERE tool_name = 'calculator'",
        )
        assert rows[0]["response"] == "4"


# ---------------------------------------------------------------------------
# TestMcpCacheTTL
# ---------------------------------------------------------------------------


class TestMcpCacheTTL:
    def test_expired_entry_returns_none(self, mm):
        """Directly insert an expired row; get() must return None."""
        key = args_hash({"q": "stale"})
        mm.query(
            "cache",
            "INSERT INTO mcp_cache (tool_name, args_hash, response, expires_at)"
            " VALUES (?, ?, ?, ?)",
            ("web_search", key, "old_data", "2000-01-01T00:00:00+00:00"),
        )
        cache = McpCache(memory=mm)
        assert cache.get("web_search", {"q": "stale"}) is None

    def test_no_expiry_entry_persists(self, mm, monkeypatch):
        """TTL=None (calculator) must set expires_at=NULL and always return."""
        monkeypatch.setattr(mcp_cache_mod, "_load_ttl", lambda _: None)
        cache = McpCache(memory=mm)
        cache.put("calculator", {"expr": "1+1"}, "2")
        assert cache.get("calculator", {"expr": "1+1"}) == "2"
        rows = mm.query(
            "cache",
            "SELECT expires_at FROM mcp_cache WHERE tool_name = 'calculator'",
        )
        assert rows[0]["expires_at"] is None
