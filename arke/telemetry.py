"""Telemetry — OpenTelemetry tracing + optional Prometheus metrics.

Usage::

    # At startup (e.g. CLI entry point)
    from arke.telemetry import init_tracer
    init_tracer()

    # Around each step attempt
    from arke.telemetry import trace_step
    span_attrs: dict = {}
    with trace_step(tool, step_id, task_id) as span_attrs:
        result = do_work()
        span_attrs.update({"cost_eur": 0.001, "tokens": 42, "success": True})

Config (arke.toml)::

    [telemetry]
    enabled       = false         # flip to true to emit spans
    otlp_endpoint = ""            # e.g. "http://localhost:4318/v1/traces"
    prometheus    = false         # requires opentelemetry-exporter-prometheus

"""

from __future__ import annotations

import tomllib
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

_TRACER_NAME = "arke.orchestrator"
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "arke.toml"

# Module-level Prometheus counter handles (None when not initialised)
_task_counter: Any = None
_cost_counter: Any = None
_token_counter: Any = None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_telemetry_config() -> dict:
    """Read ``[telemetry]`` section from *arke.toml*."""
    try:
        with open(_CONFIG_PATH, "rb") as fh:
            return tomllib.load(fh).get("telemetry", {})
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_tracer() -> None:
    """Initialise OTel TracerProvider (call once at application startup).

    * If ``enabled = false``: installs a NoOp provider — no spans, no errors.
    * If ``enabled = true`` and ``otlp_endpoint`` set: attaches OTLP HTTP exporter.
    * If ``enabled = true`` and no endpoint: provider is active but spans are
      discarded (useful for unit tests that capture spans via InMemorySpanExporter).
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    cfg = load_telemetry_config()

    if not cfg.get("enabled", False):
        trace.set_tracer_provider(trace.NoOpTracerProvider())
        return

    provider = TracerProvider()

    otlp_endpoint = cfg.get("otlp_endpoint", "").strip()
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"OTLP exporter could not be initialised ({exc}); traces will be discarded.",
                stacklevel=2,
            )

    trace.set_tracer_provider(provider)

    if cfg.get("prometheus", False):
        _init_prometheus(provider)


def _init_prometheus(trace_provider: Any) -> None:  # noqa: ARG001
    """Attach Prometheus metrics reader if the optional package is present."""
    global _task_counter, _cost_counter, _token_counter

    try:
        from opentelemetry.exporter.prometheus import PrometheusMetricReader  # type: ignore[import]
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry import metrics

        reader = PrometheusMetricReader()
        meter_provider = MeterProvider(metric_readers=[reader])
        metrics.set_meter_provider(meter_provider)

        meter = meter_provider.get_meter(_TRACER_NAME)
        _task_counter = meter.create_counter(
            "arke_tasks_total",
            description="Total Arke tasks executed.",
        )
        _cost_counter = meter.create_counter(
            "arke_cost_total",
            unit="EUR",
            description="Total LLM cost in EUR.",
        )
        _token_counter = meter.create_counter(
            "arke_tokens_total",
            description="Total tokens consumed.",
        )
    except ImportError:
        warnings.warn(
            "opentelemetry-exporter-prometheus is not installed; "
            "Prometheus metrics are disabled.  "
            "Install with: pip install opentelemetry-exporter-prometheus",
            stacklevel=3,
        )


# ---------------------------------------------------------------------------
# Tracing helpers
# ---------------------------------------------------------------------------


@contextmanager
def trace_step(
    tool: str,
    step_id: str,
    task_id: str,
    *,
    _tracer: Any = None,
) -> Generator[dict[str, Any], None, None]:
    """Context manager that wraps one step attempt with an OTel span.

    Yields a mutable *attrs* dict; callers should populate it with::

        attrs["cost_eur"] = float   # LLM cost for this attempt
        attrs["tokens"]   = int     # tokens consumed
        attrs["success"]  = bool    # True → span.OK, False → span.ERROR

    Span attributes set automatically: ``arke.tool``, ``arke.step_id``,
    ``arke.task_id``, ``arke.cost_eur``, ``arke.tokens``.

    Args:
        _tracer: Optional tracer instance (used in unit tests to inject a
            tracer from a fresh ``TracerProvider`` instead of the global one).
    """
    from opentelemetry import trace

    tracer = _tracer if _tracer is not None else trace.get_tracer(_TRACER_NAME)
    attrs: dict[str, Any] = {}

    with tracer.start_as_current_span(f"step.{tool}") as span:
        span.set_attribute("arke.tool", tool)
        span.set_attribute("arke.step_id", step_id)
        span.set_attribute("arke.task_id", task_id)

        yield attrs

        cost = float(attrs.get("cost_eur", 0.0))
        tokens = int(attrs.get("tokens", 0))
        success = bool(attrs.get("success", True))

        span.set_attribute("arke.cost_eur", cost)
        span.set_attribute("arke.tokens", tokens)
        span.set_attribute("arke.success", success)

        if success:
            span.set_status(trace.StatusCode.OK)
        else:
            span.set_status(trace.StatusCode.ERROR, "step failed")


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------


def record_task_metrics(cost_eur: float, tokens: int) -> None:
    """Increment Prometheus counters (no-op when Prometheus is not enabled)."""
    try:
        if _task_counter is not None:
            _task_counter.add(1)
        if _cost_counter is not None:
            _cost_counter.add(cost_eur)
        if _token_counter is not None:
            _token_counter.add(tokens)
    except Exception:  # noqa: BLE001
        pass
