"""Tests — P3.3 : Observabilité OpenTelemetry + Sandboxing bubblewrap.

Coverage:
  - telemetry.load_telemetry_config / init_tracer (disabled + enabled)
  - trace_step context manager: attributes, status OK/ERROR
  - trace_step with NoOp tracer: no exception
  - record_task_metrics: no exception when counters are None
  - sandbox.load_sandbox_config / is_bwrap_available
  - sandboxed_run: bwrap path, no-bwrap fallback (warning), disabled
  - orchestrator._exec_cli uses sandbox
  - e2e: orchestrator._traced_dispatch produces span, task metrics
"""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Telemetry — config
# ---------------------------------------------------------------------------


def test_load_telemetry_config_defaults(tmp_path, monkeypatch):
    """Missing [telemetry] section returns empty dict."""
    toml_content = b"[memory]\nglobal_path = 'memory/global.db'\n"
    (tmp_path / "arke.toml").write_bytes(toml_content)

    import arke.telemetry as tel

    monkeypatch.setattr(tel, "_CONFIG_PATH", tmp_path / "arke.toml")
    cfg = tel.load_telemetry_config()
    assert isinstance(cfg, dict)
    assert cfg == {}


def test_load_telemetry_config_full(tmp_path, monkeypatch):
    toml_content = (
        b"[telemetry]\nenabled = true\notlp_endpoint = 'http://localhost:4318/v1/traces'\n"
        b"prometheus = false\n"
    )
    (tmp_path / "arke.toml").write_bytes(toml_content)

    import arke.telemetry as tel

    monkeypatch.setattr(tel, "_CONFIG_PATH", tmp_path / "arke.toml")
    cfg = tel.load_telemetry_config()
    assert cfg["enabled"] is True
    assert "4318" in cfg["otlp_endpoint"]
    assert cfg["prometheus"] is False


# ---------------------------------------------------------------------------
# Telemetry — init_tracer (disabled)
# ---------------------------------------------------------------------------


def test_init_tracer_disabled(tmp_path, monkeypatch):
    """When enabled = false, NoOpTracerProvider is installed — no exception."""
    from opentelemetry import trace as otel_trace

    toml_content = b"[telemetry]\nenabled = false\n"
    (tmp_path / "arke.toml").write_bytes(toml_content)

    import arke.telemetry as tel

    monkeypatch.setattr(tel, "_CONFIG_PATH", tmp_path / "arke.toml")
    tel.init_tracer()  # must not raise

    tracer = otel_trace.get_tracer("test")
    with tracer.start_as_current_span("noop") as span:
        assert span is not None  # span object exists even when no-op


def test_init_tracer_enabled_no_endpoint(tmp_path, monkeypatch):
    """When enabled = true and no endpoint, provider active but no export error."""
    toml_content = b"[telemetry]\nenabled = true\notlp_endpoint = ''\nprometheus = false\n"
    (tmp_path / "arke.toml").write_bytes(toml_content)

    import arke.telemetry as tel

    monkeypatch.setattr(tel, "_CONFIG_PATH", tmp_path / "arke.toml")
    tel.init_tracer()  # must not raise


# ---------------------------------------------------------------------------
# Telemetry — trace_step
# ---------------------------------------------------------------------------


def test_trace_step_captures_attributes():
    """trace_step sets arke.tool, arke.step_id, arke.cost_eur, arke.tokens on span."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("arke.orchestrator")

    from arke.telemetry import trace_step

    with trace_step("cli", "step-1", "task-abc", _tracer=tracer) as attrs:
        attrs.update({"cost_eur": 0.001, "tokens": 50, "success": True})

    spans = exporter.get_finished_spans()
    assert len(spans) >= 1
    last = spans[-1]
    assert last.attributes["arke.tool"] == "cli"
    assert last.attributes["arke.step_id"] == "step-1"
    assert last.attributes["arke.cost_eur"] == pytest.approx(0.001)
    assert last.attributes["arke.tokens"] == 50


def test_trace_step_status_ok():
    """Span status = OK when success=True."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.trace import StatusCode

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("arke.orchestrator")

    from arke.telemetry import trace_step

    with trace_step("llm", "s1", "t1", _tracer=tracer) as attrs:
        attrs["success"] = True

    span = exporter.get_finished_spans()[-1]
    assert span.status.status_code == StatusCode.OK


def test_trace_step_status_error():
    """Span status = ERROR when success=False."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.trace import StatusCode

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("arke.orchestrator")

    from arke.telemetry import trace_step

    with trace_step("cli", "s2", "t2", _tracer=tracer) as attrs:
        attrs["success"] = False

    span = exporter.get_finished_spans()[-1]
    assert span.status.status_code == StatusCode.ERROR


def test_trace_step_noop_no_exception():
    """trace_step with NoOp provider must not raise."""
    from opentelemetry import trace

    trace.set_tracer_provider(trace.NoOpTracerProvider())

    from arke.telemetry import trace_step

    with trace_step("fs", "s3", "t3") as attrs:
        attrs["success"] = True  # no exception expected


# ---------------------------------------------------------------------------
# Telemetry — record_task_metrics
# ---------------------------------------------------------------------------


def test_record_task_metrics_noop(monkeypatch):
    """record_task_metrics is a no-op when counters are None (no Prometheus)."""
    import arke.telemetry as tel

    monkeypatch.setattr(tel, "_task_counter", None)
    monkeypatch.setattr(tel, "_cost_counter", None)
    monkeypatch.setattr(tel, "_token_counter", None)

    tel.record_task_metrics(0.05, 100)  # must not raise


# ---------------------------------------------------------------------------
# Sandbox — config
# ---------------------------------------------------------------------------


def test_load_sandbox_config_defaults(tmp_path, monkeypatch):
    toml_content = b"[memory]\nglobal_path = 'x'\n"
    (tmp_path / "arke.toml").write_bytes(toml_content)

    import arke.sandbox as sb

    monkeypatch.setattr(sb, "_CONFIG_PATH", tmp_path / "arke.toml")
    cfg = sb.load_sandbox_config()
    assert cfg == {}


def test_load_sandbox_config_enabled(tmp_path, monkeypatch):
    toml_content = b"[sandbox]\nenabled = false\n"
    (tmp_path / "arke.toml").write_bytes(toml_content)

    import arke.sandbox as sb

    monkeypatch.setattr(sb, "_CONFIG_PATH", tmp_path / "arke.toml")
    cfg = sb.load_sandbox_config()
    assert cfg["enabled"] is False


# ---------------------------------------------------------------------------
# Sandbox — is_bwrap_available
# ---------------------------------------------------------------------------


def test_is_bwrap_available_mocked_true(monkeypatch):
    import arke.sandbox as sb

    sb._reset_availability_cache()
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/bwrap")
    assert sb.is_bwrap_available() is True
    sb._reset_availability_cache()


def test_is_bwrap_available_mocked_false(monkeypatch):
    import arke.sandbox as sb

    sb._reset_availability_cache()
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert sb.is_bwrap_available() is False
    sb._reset_availability_cache()


# ---------------------------------------------------------------------------
# Sandbox — sandboxed_run
# ---------------------------------------------------------------------------


def test_sandboxed_run_disabled_fallback():
    """sandbox_enabled=False → runs without bwrap, returns correct dict."""
    from arke.sandbox import sandboxed_run

    result = sandboxed_run("echo arke-sandbox-test", sandbox_enabled=False)
    assert result["return_code"] == 0
    assert "arke-sandbox-test" in result["stdout"]
    assert isinstance(result["stderr"], str)


def test_sandboxed_run_warns_when_bwrap_missing(monkeypatch):
    """sandboxed_run warns and falls back when bwrap unavailable."""
    import arke.sandbox as sb

    sb._reset_availability_cache()
    monkeypatch.setattr(sb, "_bwrap_available", False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = sb.sandboxed_run("echo fallback", sandbox_enabled=True)

    assert result["return_code"] == 0
    assert "fallback" in result["stdout"]
    assert any("bwrap" in str(w.message).lower() for w in caught)
    sb._reset_availability_cache()


def test_sandboxed_run_with_bwrap():
    """When bwrap is available, sandboxed_run succeeds."""
    import shutil

    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed on this machine")

    from arke.sandbox import sandboxed_run

    result = sandboxed_run("echo hello-from-sandbox", sandbox_enabled=True)
    assert result["return_code"] == 0
    assert "hello-from-sandbox" in result["stdout"]


# ---------------------------------------------------------------------------
# E2E — orchestrator + telemetry integration
# ---------------------------------------------------------------------------


def test_orchestrator_exec_cli_sandbox_disabled(monkeypatch, tmp_path):
    """_exec_cli respects sandbox config; sandbox_enabled=False runs without bwrap."""
    toml_content = b"[sandbox]\nenabled = false\n"
    (tmp_path / "arke.toml").write_bytes(toml_content)

    import arke.sandbox as sb

    monkeypatch.setattr(sb, "_CONFIG_PATH", tmp_path / "arke.toml")

    from arke.task_graph import Step, StepStatus
    import arke.orchestrator as orch

    step = Step(id="s0", tool="cli", arguments={"command": "echo sandbox-off"})
    result = orch._exec_cli(step)
    assert result["return_code"] == 0
    assert "sandbox-off" in result["stdout"]


def test_traced_dispatch_populates_span(monkeypatch):
    """_traced_dispatch calls _dispatch and populates span_attrs with success=True."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("arke.orchestrator")

    # Patch trace_step to inject our fresh tracer
    import arke.telemetry as tel
    from contextlib import contextmanager

    original_trace_step = tel.trace_step

    @contextmanager
    def patched_trace_step(tool, step_id, task_id, **_kwargs):
        with original_trace_step(tool, step_id, task_id, _tracer=tracer) as attrs:
            yield attrs

    monkeypatch.setattr(tel, "trace_step", patched_trace_step)

    from arke.task_graph import Step, Task
    import arke.orchestrator as orch

    step = Step(id="s1", tool="fs", arguments={"path": "/nonexistent/file.txt"})
    task = Task(id="t1", description="test", steps=[step])

    result = orch._traced_dispatch(step, {}, task)
    assert result["return_code"] == 1  # file not found but no exception

    spans = exporter.get_finished_spans()
    assert any("step.fs" in s.name for s in spans)
    last = next(s for s in spans if "step.fs" in s.name)
    assert last.attributes["arke.tool"] == "fs"
    assert last.attributes["arke.success"] is True
