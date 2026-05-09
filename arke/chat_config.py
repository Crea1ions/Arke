"""ChatConfig — /config menu interactif et /check dashboard.

/config
-------
Menu numéroté qui modifie ``config/arke.toml`` en direct.
Les clés API sont stockées dans ``~/.arke/.env``, jamais dans le repo.

/check
------
Vérifie l'état de chaque composant sans modifier quoi que ce soit.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "arke.toml"
_ARKE_ENV_DIR = Path.home() / ".arke"
_ARKE_ENV_PATH = _ARKE_ENV_DIR / ".env"


# ---------------------------------------------------------------------------
# TOML helpers — read + line-level patch (no external dep)
# ---------------------------------------------------------------------------


def _read_toml() -> dict:
    """Return parsed arke.toml content."""
    try:
        with open(_CONFIG_PATH, "rb") as fh:
            return tomllib.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def _patch_toml_value(section: str, key: str, value: str | bool) -> None:
    """Overwrite a single key inside *[section]* in arke.toml using line regex.

    Supports bool (``true`` / ``false``) and quoted strings.
    Does not require tomlkit — safe for simple scalar values.
    """
    raw = _CONFIG_PATH.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)

    in_section = False
    new_lines = []
    replaced = False

    str_value: str
    if isinstance(value, bool):
        str_value = "true" if value else "false"
    else:
        # Wrap in double quotes only if not already quoted
        str_value = f'"{value}"' if not str(value).startswith('"') else str(value)

    section_header = re.compile(rf"^\[{re.escape(section)}\]")
    any_section = re.compile(r"^\[")
    key_pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)")

    for line in lines:
        if section_header.match(line):
            in_section = True
            new_lines.append(line)
            continue
        if in_section and any_section.match(line) and not section_header.match(line):
            in_section = False
        if in_section and not replaced:
            m = key_pattern.match(line)
            if m:
                # Preserve inline comment if present
                comment_match = re.search(r"\s+#.*$", line)
                comment = comment_match.group(0) if comment_match else ""
                new_lines.append(f"{m.group(1)}{str_value}{comment}\n")
                replaced = True
                continue
        new_lines.append(line)

    if replaced:
        _CONFIG_PATH.write_text("".join(new_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# ~/.arke/.env helpers
# ---------------------------------------------------------------------------


def _env_set(key: str, value: str) -> None:
    """Write or update *key=value* in ``~/.arke/.env``."""
    _ARKE_ENV_DIR.mkdir(parents=True, exist_ok=True)
    if _ARKE_ENV_PATH.exists():
        lines = _ARKE_ENV_PATH.read_text().splitlines(keepends=True)
        pattern = re.compile(rf"^{re.escape(key)}\s*=")
        new_lines = [line for line in lines if not pattern.match(line)]
    else:
        new_lines = []
    new_lines.append(f"{key}={value}\n")
    _ARKE_ENV_PATH.write_text("".join(new_lines))
    # Restrict permissions: owner read/write only
    _ARKE_ENV_PATH.chmod(0o600)


def _env_remove(key: str) -> bool:
    """Remove *key* from ``~/.arke/.env``. Returns True if found."""
    if not _ARKE_ENV_PATH.exists():
        return False
    lines = _ARKE_ENV_PATH.read_text().splitlines(keepends=True)
    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    new_lines = [line for line in lines if not pattern.match(line)]
    removed = len(new_lines) < len(lines)
    _ARKE_ENV_PATH.write_text("".join(new_lines))
    return removed


def _env_list() -> dict[str, str]:
    """Return all key-value pairs from ``~/.arke/.env``."""
    if not _ARKE_ENV_PATH.exists():
        return {}
    result: dict[str, str] = {}
    for line in _ARKE_ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


# ---------------------------------------------------------------------------
# /check — component health dashboard
# ---------------------------------------------------------------------------


def run_check() -> dict[str, Any]:
    """Validate the state of all Arke components.

    Returns a dict: ``{component: {"ok": bool, "detail": str}}``.
    Never raises.
    """
    results: dict[str, Any] = {}

    # --- Anti-Drift Metrics (Phase 4) ----------------------------------------
    from arke.anti_drift_metrics import get_metrics_instance
    metrics = get_metrics_instance().get_metrics()
    
    # Check invariants
    violations = metrics["violations"]
    if violations == 0:
        results["anti-drift"] = {"ok": True, "detail": f"0 violations (agent: {metrics['agent_decision_pct']}%)"}
    else:
        results["anti-drift"] = {"ok": False, "detail": f"⚠️  {violations} violations detected!"}

    # --- sqlite-vec ----------------------------------------------------------
    try:
        import sqlite3
        import sqlite_vec  # type: ignore[import]
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        version = conn.execute("SELECT vec_version()").fetchone()[0]
        results["sqlite-vec"] = {"ok": True, "detail": f"v{version}"}
    except Exception as exc:  # noqa: BLE001
        results["sqlite-vec"] = {"ok": False, "detail": str(exc)}

    # --- bubblewrap ----------------------------------------------------------
    import shutil
    bwrap = shutil.which("bwrap")
    if bwrap:
        try:
            import subprocess
            out = subprocess.run(  # noqa: S603
                ["bwrap", "--version"], capture_output=True, text=True, timeout=3
            )
            results["bubblewrap"] = {"ok": True, "detail": out.stdout.strip() or out.stderr.strip()}
        except Exception as exc:  # noqa: BLE001
            results["bubblewrap"] = {"ok": False, "detail": str(exc)}
    else:
        results["bubblewrap"] = {"ok": False, "detail": "bwrap not found in PATH"}

    # --- OTel endpoint -------------------------------------------------------
    cfg = _read_toml()
    otel_cfg = cfg.get("telemetry", {})
    if not otel_cfg.get("enabled", False):
        results["otel"] = {"ok": True, "detail": "disabled (NoOp)"}
    else:
        endpoint = otel_cfg.get("otlp_endpoint", "").strip()
        if not endpoint:
            results["otel"] = {"ok": True, "detail": "enabled, no endpoint (traces discarded)"}
        else:
            try:
                import urllib.request
                urllib.request.urlopen(endpoint, timeout=2)  # noqa: S310
                results["otel"] = {"ok": True, "detail": f"reachable: {endpoint}"}
            except Exception as exc:  # noqa: BLE001
                results["otel"] = {"ok": False, "detail": f"{endpoint} — {exc}"}

    # --- LLM providers -------------------------------------------------------
    from arke.chat_router import MODEL_ALIASES
    env_keys = _env_list()
    # Simple presence check — API key exists
    provider_checks = {
        "flash":   "GEMINI_API_KEY",
        "claude":  "ANTHROPIC_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "local":   None,  # no key needed
    }
    for alias, env_key in provider_checks.items():
        if env_key is None:
            results[f"llm:{alias}"] = {"ok": True, "detail": "local (no key needed)"}
        else:
            found = os.environ.get(env_key) or env_keys.get(env_key)
            if found:
                results[f"llm:{alias}"] = {"ok": True, "detail": f"{env_key} present"}
            else:
                results[f"llm:{alias}"] = {"ok": False, "detail": f"{env_key} not set"}

    return results


def print_check(printer=print) -> None:
    """Print /check dashboard to *printer*."""
    results = run_check()
    printer("\n[Arke] /check — état des composants\n")
    for component, status in results.items():
        icon = "✓" if status["ok"] else "✗"
        printer(f"  {icon}  {component:<20} {status['detail']}")
    printer("")


# ---------------------------------------------------------------------------
# /config — interactive configuration menu
# ---------------------------------------------------------------------------


def run_config(printer=print, reader=input) -> None:  # noqa: A002
    """Interactive configuration menu.

    Args:
        printer: Function used to display text (default: ``print``).
            Allows injection for testing.
        reader: Function used to read user input (default: ``input``).
    """
    while True:
        cfg = _read_toml()
        tel = cfg.get("telemetry", {})
        sbx = cfg.get("sandbox", {})
        vec = cfg.get("vector", {})

        printer("\n[Arke] /config — configuration\n")
        printer("  1. LLM Providers    (ajouter / supprimer des clés API)")
        printer(f"  2. Télémétrie       (enabled: {tel.get('enabled', False)})")
        printer(f"  3. Sandbox          (enabled: {sbx.get('enabled', True)})")
        printer(f"  4. Vector search    (enabled: {vec.get('enabled', True)})")
        printer("  5. Telegram Bot     (configurer le canal Telegram)")
        printer("  0. Retour\n")

        try:
            choice = reader("Choix : ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "0" or choice == "":
            break
        elif choice == "1":
            _config_llm_providers(printer, reader)
        elif choice == "2":
            _config_toggle(printer, reader, "telemetry", "enabled", tel.get("enabled", False))
            if tel.get("enabled", False) or _read_toml().get("telemetry", {}).get("enabled", False):
                _config_string(printer, reader, "telemetry", "otlp_endpoint",
                               tel.get("otlp_endpoint", ""), "Endpoint OTLP")
        elif choice == "3":
            _config_toggle(printer, reader, "sandbox", "enabled", sbx.get("enabled", True))
        elif choice == "4":
            _config_toggle(printer, reader, "vector", "enabled", vec.get("enabled", True))
        elif choice == "5":
            _config_telegram(printer, reader)
        else:
            printer(f"[Arke] Option inconnue : {choice!r}")


def _config_toggle(printer, reader, section: str, key: str, current: bool) -> None:
    state = "activé" if current else "désactivé"
    try:
        ans = reader(f"  Actuellement {state}. Basculer ? [oui/non] : ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if ans in ("oui", "o", "yes", "y"):
        _patch_toml_value(section, key, not current)
        new_state = "activé" if not current else "désactivé"
        printer(f"[Arke] {section}.{key} → {new_state}")


def _config_string(printer, reader, section: str, key: str, current: str, label: str) -> None:
    try:
        ans = reader(f"  {label} (actuel: {current!r}) — nouvelle valeur (vide = inchangé) : ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if ans:
        _patch_toml_value(section, key, ans)
        printer(f"[Arke] {section}.{key} → {ans!r}")


def _config_llm_providers(printer, reader) -> None:
    while True:
        env_keys = _env_list()
        printer("\n  [Arke] Providers LLM — ~/.arke/.env\n")

        from arke.chat_router import MODEL_ALIASES
        env_map = {
            "flash":   "GEMINI_API_KEY",
            "claude":  "ANTHROPIC_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "local":   None,
        }
        for alias, env_key in env_map.items():
            if env_key is None:
                printer(f"    {alias:<12} (local — aucune clé requise)")
            else:
                status = "✓ configuré" if env_key in env_keys else "✗ manquant"
                printer(f"    {alias:<12} {env_key:<25} {status}")

        printer("\n  a. Ajouter / mettre à jour une clé")
        printer("  r. Supprimer une clé")
        printer("  0. Retour\n")

        try:
            choice = reader("  Choix : ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "0" or choice == "":
            break
        elif choice == "a":
            try:
                key_name = reader("  Nom de la variable (ex: GEMINI_API_KEY) : ").strip()
                if not key_name:
                    continue
                key_value = reader(f"  Valeur de {key_name} : ").strip()
                if not key_value:
                    printer("[Arke] Annulé — valeur vide")
                    continue
            except (EOFError, KeyboardInterrupt):
                break
            _env_set(key_name, key_value)
            printer(f"[Arke] {key_name} enregistré dans ~/.arke/.env (permissions 600)")
        elif choice == "r":
            try:
                key_name = reader("  Nom de la variable à supprimer : ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if _env_remove(key_name):
                printer(f"[Arke] {key_name} supprimé")
            else:
                printer(f"[Arke] {key_name} introuvable")
        else:
            printer(f"[Arke] Option inconnue : {choice!r}")


def _config_telegram(printer, reader) -> None:
    """Interactive Telegram bot configuration menu."""
    while True:
        env_keys = _env_list()
        token_status = "✓ configuré" if "TELEGRAM_BOT_TOKEN" in env_keys else "✗ manquant"
        token_preview = ""
        if "TELEGRAM_BOT_TOKEN" in env_keys:
            token = env_keys["TELEGRAM_BOT_TOKEN"]
            # Show first and last 6 chars with ellipsis
            if len(token) > 12:
                token_preview = f" ({token[:6]}...{token[-6:]})"
            else:
                token_preview = f" ({token})"

        printer("\n╭─────────────────── Configuration Telegram ───────────────────╮")
        printer("│                                                             │")
        printer(f"│  Token : {token_status}{token_preview:<40} │")
        printer("│                                                             │")
        printer("│  1. Ajouter / mettre à jour le token                        │")
        printer("│  2. Afficher le guide BotFather                             │")
        printer("│  3. Supprimer le token                                      │")
        printer("│  0. Retour                                                  │")
        printer("│                                                             │")
        printer("╰─────────────────────────────────────────────────────────────╯\n")

        try:
            choice = reader("Choix : ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "0" or choice == "":
            break
        elif choice == "1":
            try:
                token = reader("Colle le token BotFather : ").strip()
                if not token:
                    printer("[Arke] Annulé — token vide")
                    continue
                # Validate token format: <numeric_id>:<api_token>
                parts = token.split(":")
                if len(parts) != 2 or not parts[0].isdigit() or not parts[1]:
                    printer("[Arke] ⚠️  Le token doit être au format: <numeric_id>:<api_token>")
                    printer("[Arke]    Ex: 8525805295:AAEX590iZgl50cYTYmMgQOPA2PJVPQmZQ6M")
                    continue
            except (EOFError, KeyboardInterrupt):
                break
            _env_set("TELEGRAM_BOT_TOKEN", token)
            printer("[Arke] TELEGRAM_BOT_TOKEN enregistré dans ~/.arke/.env (permissions 600)")
        elif choice == "2":
            _print_botfather_guide(printer)
        elif choice == "3":
            if _env_remove("TELEGRAM_BOT_TOKEN"):
                printer("[Arke] TELEGRAM_BOT_TOKEN supprimé")
            else:
                printer("[Arke] Aucun token configuré")
        else:
            printer(f"[Arke] Option inconnue : {choice!r}")


def _print_botfather_guide(printer) -> None:
    """Print the BotFather guide for Telegram bot creation."""
    printer("\n╭────────────── Guide: Créer un Bot Telegram ───────────────────╮")
    printer("│                                                              │")
    printer("│  1. Ouvre Telegram et cherche @BotFather                     │")
    printer("│  2. Envoie /newbot                                           │")
    printer("│  3. Choisis un nom (ex: MonArkeBot)                          │")
    printer("│  4. Choisis un username (doit finir par 'bot')               │")
    printer("│     ex: mon_arke_bot                                         │")
    printer("│  5. Copie le token reçu (format: 123456:ABC-DEF...)          │")
    printer("│  6. Reviens ici et choisis option 1                          │")
    printer("│  7. Colle le token                                           │")
    printer("│                                                              │")
    printer("│  Une fois configuré, utilise: arke --telegram                │")
    printer("│                                                              │")
    printer("╰──────────────────────────────────────────────────────────────╯\n")
