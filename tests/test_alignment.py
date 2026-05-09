"""
Test suite for Arke Agent-First Alignment (Chantier A, Phase 3).

Validates that:
- Router removes implicit classifications
- All non-slash/@ messages route to agent
- Memory requests are NOT intercepted (go to agent)
- Slash commands still work
- @model switching still works
"""

import pytest
from arke.chat_router import route, RouteKind


class TestAgentFirstRouting:
    """Verify agent-first routing behavior (no implicit classification)."""

    def test_greeting_routes_to_agent(self):
        """Greeting should route to agent, not be classified as conversational."""
        result = route("Salut!")
        assert result.intention == "Salut!"
        # Should route to agent (not implicit classification)
        assert result.kind == RouteKind.LLM_AGENT

    def test_question_routes_to_agent(self):
        """Question should route to agent, not intercepted."""
        result = route("Quelle heure est-il?")
        assert result.intention == "Quelle heure est-il?"
        # Must go to agent
        assert result.kind == RouteKind.LLM_AGENT

    def test_memory_request_not_intercepted(self):
        """Memory request must route to agent (CRITICAL FIX).
        
        Previously: "Remember to call Alice" → MEMORY_WRITE (system intercepted)
        Now: "Remember to call Alice" → LLM_AGENT (agent controls)
        """
        result = route("Remember to call Alice")
        # Must route to agent (not intercepted by system patterns)
        assert result.kind == RouteKind.LLM_AGENT, \
            "Memory request was intercepted! System should not interpret memory operations."

    def test_souviens_toi_not_intercepted(self):
        """French 'Souviens-toi' must also not be intercepted."""
        result = route("Souviens-toi d'appeler Alice")
        assert result.kind == RouteKind.LLM_AGENT

    def test_file_operation_routes_to_agent(self):
        """File operations should route to agent (not auto-dispatched)."""
        result = route("Lis le fichier test.txt")
        # Should not be auto-dispatched
        assert result.kind == RouteKind.LLM_AGENT

    def test_cli_like_routes_to_agent(self):
        """CLI-like commands should route to agent (not auto-dispatched)."""
        result = route("Affiche hello avec echo")
        assert result.kind == RouteKind.LLM_AGENT

    def test_ambiguous_query_routes_to_agent(self):
        """Ambiguous queries should route to agent (agent asks for clarification)."""
        result = route("Trouve ça")
        assert result.kind == RouteKind.LLM_AGENT

    def test_slash_command_deterministic(self):
        """Slash commands should still work (explicit, not interpretation)."""
        result = route("/check")
        assert result.kind == RouteKind.SLASH
        assert result.slash == "/check"

    def test_slash_command_with_args(self):
        """/status and other slash commands work."""
        result = route("/help all")
        assert result.kind == RouteKind.SLASH
        assert result.slash == "/help"

    def test_model_override_deterministic(self):
        """@model switching should still work (explicit, not interpretation)."""
        result = route("@flash bonjour")
        assert result.kind == RouteKind.MODEL_OVERRIDE
        assert result.model_alias == "flash"
        assert result.intention == "bonjour"

    def test_model_override_with_unknown_model(self):
        """Unknown @model should not override (stays as agent message)."""
        result = route("@unknown_model hello")
        # Should route to agent (not a known model override)
        assert result.kind == RouteKind.LLM_AGENT or result.model_alias is None


class TestNoSystemInterpretation:
    """Verify system no longer interprets user intent."""

    def test_no_implicit_task_routing(self):
        """No messages should route to RouteKind.TASK (deprecated)."""
        test_messages = [
            "Salut!",
            "Remember to call Alice",
            "List files",
            "What is this?",
            "Analyze this log",
            "Find the bug",
            "/check",
            "@flash hello"
        ]
        
        # Only slash and MODEL_OVERRIDE are exceptions
        for msg in test_messages:
            result = route(msg)
            # Everything else should be either SLASH, MODEL_OVERRIDE, or LLM_AGENT
            assert result.kind in [RouteKind.SLASH, RouteKind.MODEL_OVERRIDE, RouteKind.LLM_AGENT], \
                f"Message '{msg}' routed to unknown kind: {result.kind}"
            # Specifically, there should be NO TASK or old routing types
            assert str(result.kind) != "RouteKind.TASK", \
                f"TASK routing still exists for: {msg}"

    def test_no_memory_interception(self):
        """No message should route to MEMORY_* kinds (memory is now agent-controlled)."""
        memory_requests = [
            "Remember to call Alice",
            "Souviens-toi d'appeler Bob",
            "Rappelle-moi de faire ça",
            "Recall my notes",
            "Oublie l'ancienne version",
            "Forget about that",
        ]
        
        for msg in memory_requests:
            result = route(msg)
            # MEMORY_WRITE/READ/FORGET don't exist anymore - all route to LLM_AGENT
            assert result.kind == RouteKind.LLM_AGENT, \
                f"Message '{msg}' did not route to agent! Got: {result.kind}"


class TestRoutingConsistency:
    """Verify routing behavior is consistent across similar inputs."""

    def test_similar_greetings_all_route_to_agent(self):
        """All greeting variations should route to agent."""
        greetings = ["Bonjour", "Salut", "Coucou", "Hello", "Hi"]
        
        for greeting in greetings:
            result = route(greeting)
            assert result.kind == RouteKind.LLM_AGENT, \
                f"Greeting '{greeting}' did not route to agent"

    def test_similar_questions_all_route_to_agent(self):
        """All question variations should route to agent."""
        questions = ["Quelle heure?", "Comment vas-tu?", "Que peux-tu faire?"]
        
        for question in questions:
            result = route(question)
            assert result.kind == RouteKind.LLM_AGENT, \
                f"Question '{question}' did not route to agent"


class TestExplicitCommandsStillWork:
    """Verify explicit commands (slash, @model) still work after cleanup."""

    def test_common_slash_commands(self):
        """Common slash commands should work."""
        # Use only commands that are actually defined in SLASH_COMMANDS
        commands = ["/check", "/help", "/status", "/config"]
        
        for cmd in commands:
            result = route(cmd)
            assert result.kind == RouteKind.SLASH, \
                f"Slash command '{cmd}' not recognized"

    def test_model_aliases(self):
        """Known model aliases should work."""
        # Use only aliases that are actually defined in MODEL_ALIASES
        aliases = ["@flash", "@claude", "@mistral", "@local"]
        
        for alias_str in aliases:
            result = route(f"{alias_str} test")
            # Should parse @alias correctly and route to MODEL_OVERRIDE
            assert result.model_alias == alias_str[1:], \
                f"Alias '{alias_str}' not parsed correctly"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
