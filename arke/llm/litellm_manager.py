"""LiteLLMManager — unified LLM wrapper with fallback for Arke v0.1.

Supports:
    - Gemini Flash (primary)
    - Ollama/mistral (fallback)

Cost and token usage are logged as structured JSON on every call.
"""

from __future__ import annotations

import os
import signal
import socket
import tomllib
from pathlib import Path
from typing import Any

import structlog
import litellm  # eager — must be fully loaded before any threads start (prevents thread_extractor race condition)
import logging
logging.getLogger("litellm").setLevel(logging.ERROR)  # suppress non-blocking warnings
litellm.suppress_debug_info = True

# Force IPv4-first DNS resolution.
# api.mistral.ai returns both A (IPv4) and AAAA (IPv6) records. On this machine,
# TCP SYN to the IPv6 address is silently dropped by the remote (no SYN-ACK),
# causing the Linux kernel to retry for ~127s before giving up. Reordering
# getaddrinfo results to put AF_INET first bypasses this without disabling IPv6
# globally (/etc/gai.conf would be the system-level alternative).
_orig_getaddrinfo = socket.getaddrinfo

def _ipv4_preferred_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # type: ignore[override]
    results = _orig_getaddrinfo(host, port, family, type, proto, flags)
    ipv4 = [r for r in results if r[0] == socket.AF_INET]
    return ipv4 + [r for r in results if r[0] != socket.AF_INET]

socket.getaddrinfo = _ipv4_preferred_getaddrinfo  # type: ignore[assignment]

log = structlog.get_logger()

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "models.toml"
_LLM_TIMEOUT_SECONDS = 60  # Timeout for LLM API calls (prevents infinite hangs)


def _load_config() -> dict[str, Any]:
    try:
        with open(_CONFIG_PATH, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        log.warning("llm.models_config_missing", path=str(_CONFIG_PATH))
        return {}


class LiteLLMManager:
    """Wrapper around litellm with provider fallback and cost accounting.

    Provider order is read from ``config/models.toml`` → ``[fallback] order``.
    """

    def __init__(self) -> None:
        self._config = _load_config()
        self._fallback_order: list[str] = self._config.get("fallback", {}).get(
            "order", ["gemini_flash", "ollama"]
        )

    def complete(
        self,
        prompt: str,
        task_type: str = "reasoning",
        max_tokens: int = 2048,
    ) -> tuple[str, float, int]:
        """Send *prompt* to the first available provider.

        Checks the LLM cache before making an API call.  On a cache hit,
        returns the stored response immediately with ``cost_eur = 0.0``.

        Args:
            prompt: The full prompt string.
            task_type: Hint for context — ``'reasoning'``, ``'summary'``, ``'bash'``, ``'classification'``.
            max_tokens: Maximum tokens in the response.

        Returns:
            Tuple of ``(response_text, cost_eur, tokens_used)``.
        """
        from arke.llm.cache import LlmCache, prompt_hash  # lazy — avoids circular import

        cache = LlmCache()
        # Use first provider model name as cache key component
        model_cfg = self._config.get("models", {}).get(
            self._fallback_order[0] if self._fallback_order else "default", {}
        )
        model_name_for_key = model_cfg.get("model", self._fallback_order[0] if self._fallback_order else "default")
        key = prompt_hash(prompt, model_name_for_key)

        cached = cache.get(key)
        if cached is not None:
            log.info("llm.cache_hit", key=key[:12])
            return cached

        last_error: Exception | None = None

        for provider_key in self._fallback_order:
            # Check if required API key is configured
            if not self._has_required_api_key(provider_key):
                log.debug("llm.provider_skipped_no_key", provider=provider_key)
                continue
            
            try:
                result = self._call_provider(provider_key, prompt, max_tokens)
                # Store in cache before returning
                try:
                    cache.put(key, result[0], model_name_for_key, result[2], result[1])
                except Exception:  # noqa: BLE001
                    pass  # cache write failure must not interrupt execution
                return result
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "llm.provider_failed",
                    provider=provider_key,
                    error=str(exc),
                )
                last_error = exc

        raise RuntimeError(
            f"All LLM providers failed. Last error: {last_error}"
        ) from last_error

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _has_required_api_key(self, provider_key: str) -> bool:
        """Check if the required API key is configured for this provider."""
        api_key_map = {
            "mistral": "MISTRAL_API_KEY",
            "gemini_flash": "GEMINI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        env_var = api_key_map.get(provider_key)
        if not env_var:
            return False
        return bool(os.environ.get(env_var, "").strip())

    def _call_provider(
        self, provider_key: str, prompt: str, max_tokens: int
    ) -> tuple[str, float, int]:
        model_cfg = self._config.get("models", {}).get(provider_key, {})
        model_name: str = model_cfg.get("model", provider_key)
        base_url: str | None = model_cfg.get("base_url")
        cost_per_1k_input: float = model_cfg.get("cost_per_1k_input", 0.0)
        cost_per_1k_output: float = model_cfg.get("cost_per_1k_output", 0.0)

        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "timeout": _LLM_TIMEOUT_SECONDS,  # Add timeout to prevent infinite hangs
        }
        if base_url:
            kwargs["base_url"] = base_url
        
        # Set API key for each provider
        if provider_key == "gemini_flash":
            api_key = os.environ.get("GEMINI_API_KEY", "")
            if api_key:
                kwargs["api_key"] = api_key
        elif provider_key == "mistral":
            api_key = os.environ.get("MISTRAL_API_KEY", "")
            if api_key:
                kwargs["api_key"] = api_key
        elif provider_key == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if api_key:
                kwargs["api_key"] = api_key

        try:
            response = litellm.completion(**kwargs)  # type: ignore[attr-defined]
        except Exception as exc:
            # Re-raise with clear timeout error message
            if "timeout" in str(exc).lower():
                log.error(
                    "llm.timeout",
                    provider=provider_key,
                    timeout_seconds=_LLM_TIMEOUT_SECONDS,
                )
                raise TimeoutError(
                    f"LLM provider '{provider_key}' did not respond within {_LLM_TIMEOUT_SECONDS}s"
                ) from exc
            raise

        content: str = response.choices[0].message.content or ""
        input_tokens: int = response.usage.prompt_tokens if response.usage else 0
        output_tokens: int = response.usage.completion_tokens if response.usage else 0
        total_tokens = input_tokens + output_tokens
        cost_eur = (
            (input_tokens / 1000) * cost_per_1k_input
            + (output_tokens / 1000) * cost_per_1k_output
        )

        log.info(
            "llm.complete",
            provider=provider_key,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_eur=round(cost_eur, 6),
        )

        return content, cost_eur, total_tokens

    def stream_complete(
        self,
        prompt: str,
        task_type: str = "reasoning",
        max_tokens: int = 2048,
    ):
        """Stream LLM response token-by-token from first available provider.

        Streams tokens in real-time. Yields individual token strings as they arrive.
        Caller should accumulate tokens in buffer and track usage.

        Args:
            prompt: The full prompt string.
            task_type: Hint for context.
            max_tokens: Maximum tokens in the response.

        Yields:
            Individual token strings as they stream from the LLM.

        Raises:
            RuntimeError: If all providers fail.
        """
        last_error: Exception | None = None

        for provider_key in self._fallback_order:
            if not self._has_required_api_key(provider_key):
                log.debug("llm.stream_provider_skipped_no_key", provider=provider_key)
                continue

            try:
                yield from self._stream_provider(provider_key, prompt, max_tokens)
                return
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "llm.stream_provider_failed",
                    provider=provider_key,
                    error=str(exc),
                )
                last_error = exc

        raise RuntimeError(
            f"All LLM providers failed for streaming. Last error: {last_error}"
        ) from last_error

    # ------------------------------------------------------------------
    # Streaming helpers
    # ------------------------------------------------------------------

    def _stream_provider(
        self, provider_key: str, prompt: str, max_tokens: int
    ):
        """Stream tokens from a specific provider."""
        model_cfg = self._config.get("models", {}).get(provider_key, {})
        model_name: str = model_cfg.get("model", provider_key)
        base_url: str | None = model_cfg.get("base_url")

        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": True,  # Enable streaming
            "timeout": _LLM_TIMEOUT_SECONDS,  # Add timeout to prevent infinite hangs
        }
        if base_url:
            kwargs["base_url"] = base_url

        # Set API key for each provider
        if provider_key == "gemini_flash":
            api_key = os.environ.get("GEMINI_API_KEY", "")
            if api_key:
                kwargs["api_key"] = api_key
        elif provider_key == "mistral":
            api_key = os.environ.get("MISTRAL_API_KEY", "")
            if api_key:
                kwargs["api_key"] = api_key
        elif provider_key == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if api_key:
                kwargs["api_key"] = api_key

        try:
            response = litellm.completion(**kwargs)  # type: ignore[attr-defined]
        except Exception as exc:
            # Re-raise with clear timeout error message
            if "timeout" in str(exc).lower():
                log.error(
                    "llm.stream_timeout",
                    provider=provider_key,
                    timeout_seconds=_LLM_TIMEOUT_SECONDS,
                )
                raise TimeoutError(
                    f"LLM provider '{provider_key}' did not respond within {_LLM_TIMEOUT_SECONDS}s"
                ) from exc
            raise

        # Iterate through streaming chunks
        for chunk in response:
            # Extract content from delta
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content

        log.info("llm.stream_complete", provider=provider_key, model=model_name)
