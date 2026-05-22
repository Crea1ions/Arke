"""Regression tests for S053 — litellm eager import / thread_extractor race condition.

Root cause (S053): `import litellm` was inside `_call_provider()` (lazy). litellm
takes 25 s to import without LITELLM_LOCAL_MODEL_COST_MAP=True. thread_extractor
fires at t=10 s → tried to import a partially-initialized litellm module →
AttributeError / degraded LLM responses.

Fix: `import litellm` moved to module-level in litellm_manager.py so Python's
import lock serialises concurrent imports correctly, and litellm is fully loaded
before any daemon thread wakes.

These tests will FAIL if the lazy import is re-introduced, acting as a permanent
regression guard for S053.
"""

from __future__ import annotations

import inspect
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MANAGER_PATH = Path(__file__).parent.parent / "arke" / "llm" / "litellm_manager.py"
_RUN_SH_PATH  = Path(__file__).parent.parent / "arke-run.sh"


# ---------------------------------------------------------------------------
# 1. Structural guard — no lazy import inside _call_provider
# ---------------------------------------------------------------------------


def test_call_provider_has_no_lazy_litellm_import():
    """_call_provider() must NOT contain 'import litellm' in its body.

    If this test fails, the S053 race condition has been re-introduced.
    """
    from arke.llm.litellm_manager import LiteLLMManager

    source = inspect.getsource(LiteLLMManager._call_provider)
    assert "import litellm" not in source, (
        "import litellm found INSIDE _call_provider() — this re-introduces the "
        "S053 thread_extractor race condition. Move it to module level."
    )


def test_litellm_manager_module_has_toplevel_import():
    """arke/llm/litellm_manager.py must have 'import litellm' at module level
    (outside any class or function), so it is loaded at startup.
    """
    source = _MANAGER_PATH.read_text()

    # Find all occurrences of 'import litellm'
    lines = source.splitlines()
    toplevel_imports = [
        lineno + 1
        for lineno, line in enumerate(lines)
        if line.strip() == "import litellm" or line.startswith("import litellm")
    ]
    assert toplevel_imports, (
        "No top-level 'import litellm' found in litellm_manager.py. "
        "The eager import is missing — S053 fix may have been reverted."
    )

    # None of those occurrences should be indented (i.e. inside a function/method)
    indented = [
        lineno + 1
        for lineno, line in enumerate(lines)
        if ("import litellm" in line) and line[0] in (" ", "\t")
    ]
    assert not indented, (
        f"'import litellm' found at indented lines {indented} — "
        "it is inside a function/method, not at module level."
    )


# ---------------------------------------------------------------------------
# 2. Runtime guard — litellm in sys.modules after LiteLLMManager import
# ---------------------------------------------------------------------------


def test_litellm_in_sysmodules_after_manager_import():
    """Importing LiteLLMManager must bring 'litellm' into sys.modules without
    calling any method (i.e. purely from the top-level module import).

    This confirms the eager import is executing at module load time.
    """
    # litellm may already be in sys.modules (loaded by earlier tests).
    # Either way it must be present — that's the invariant.
    import arke.llm.litellm_manager  # noqa: F401 — side-effect: loads module
    assert "litellm" in sys.modules, (
        "litellm is NOT in sys.modules after importing arke.llm.litellm_manager. "
        "The eager module-level import is missing or not executing."
    )


# ---------------------------------------------------------------------------
# 3. arke-run.sh exports LITELLM_LOCAL_MODEL_COST_MAP=True
# ---------------------------------------------------------------------------


def test_arke_run_sh_exports_cost_map_var():
    """arke-run.sh must export LITELLM_LOCAL_MODEL_COST_MAP=True.

    Without this, litellm performs a 25 s HTTP fetch on every fresh process,
    making the startup window where thread_extractor can race much larger.
    """
    assert _RUN_SH_PATH.exists(), f"arke-run.sh not found at {_RUN_SH_PATH}"
    content = _RUN_SH_PATH.read_text()
    assert "LITELLM_LOCAL_MODEL_COST_MAP=True" in content, (
        "arke-run.sh does not export LITELLM_LOCAL_MODEL_COST_MAP=True. "
        "Add: export LITELLM_LOCAL_MODEL_COST_MAP=True before the exec line."
    )


# ---------------------------------------------------------------------------
# 4. Thread-safety — concurrent import from two threads
# ---------------------------------------------------------------------------


def test_concurrent_litellm_import_no_partial_module(monkeypatch):
    """Simulate the S053 race condition: two threads import litellm concurrently.

    With the eager module-level import, litellm is already in sys.modules when
    thread_extractor fires. This test verifies:
      - No AttributeError / ImportError from either thread
      - Both threads get the SAME, fully-initialized litellm object
      - litellm.completion is accessible (the attribute that was missing in S053)
    """
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")

    errors: list[str] = []
    modules: dict[str, object] = {}

    def _import_litellm(label: str, delay: float = 0.0) -> None:
        time.sleep(delay)
        try:
            import litellm as _lm  # noqa: F401
            modules[label] = _lm
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")

    # Simulate: main thread starts LLM call (t=0), thread_extractor fires (t≈10s).
    # In tests we use ms-scale delays to keep the suite fast.
    t_main      = threading.Thread(target=_import_litellm, args=("main",  0.00), daemon=True)
    t_extractor = threading.Thread(target=_import_litellm, args=("extractor", 0.05), daemon=True)

    t_main.start()
    t_extractor.start()
    t_main.join(timeout=30)
    t_extractor.join(timeout=30)

    assert not errors, f"Import errors in concurrent threads (S053 regression): {errors}"

    main_mod = modules.get("main")
    ext_mod  = modules.get("extractor")

    assert main_mod is not None, "Main thread did not capture litellm module"
    assert ext_mod  is not None, "Extractor thread did not capture litellm module"
    assert main_mod is ext_mod,  "Threads got different litellm objects — module not shared via sys.modules"

    # Key attribute that triggered AttributeError in S053
    assert hasattr(ext_mod, "completion"), (
        "litellm.completion missing on extractor-thread module — "
        "partially-initialized module detected (S053 race condition)"
    )


# ---------------------------------------------------------------------------
# 5. Session startup timing — litellm loaded within acceptable window
# ---------------------------------------------------------------------------


def test_litellm_manager_import_time_with_cost_map(monkeypatch):
    """With LITELLM_LOCAL_MODEL_COST_MAP=True, importing LiteLLMManager must
    complete well within the thread_extractor CANCEL_GRACE_SECONDS window (10 s).

    This ensures the eager import completes before any daemon thread wakes.
    Acceptable threshold: 8 s (leaves 2 s margin before CANCEL_GRACE_SECONDS=10).
    """
    from arke.thread_extractor import CANCEL_GRACE_SECONDS

    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")

    # Force re-import to measure actual load time
    import importlib
    mod_name = "arke.llm.litellm_manager"

    # Remove from sys.modules to force a fresh load
    mods_to_drop = [k for k in sys.modules if k.startswith("litellm") or k == mod_name]
    for k in mods_to_drop:
        sys.modules.pop(k, None)

    t0 = time.perf_counter()
    importlib.import_module(mod_name)
    elapsed = time.perf_counter() - t0

    threshold = CANCEL_GRACE_SECONDS - 2  # 8 s — generous margin

    assert elapsed < threshold, (
        f"arke.llm.litellm_manager took {elapsed:.1f}s to import "
        f"(threshold: {threshold}s = CANCEL_GRACE_SECONDS - 2s). "
        "Set LITELLM_LOCAL_MODEL_COST_MAP=True in the environment or arke-run.sh."
    )
