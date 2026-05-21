from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


_CodexKind = str
_ALLOWED_KINDS: set[str] = {"ask", "opt"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_codex_paths(workspace_root: str | Path) -> dict[str, Path]:
    root = Path(workspace_root)
    arke_dir = root / ".arke"
    return {
        "arke_dir": arke_dir,
        "ask": arke_dir / "codex_ask.yaml",
        "opt": arke_dir / "codex_opt.yaml",
    }


def _default_codex_ask(workspace: str, author: str) -> dict[str, Any]:
    return {
        "version": "1.0",
        "metadata": {
            "workspace": workspace,
            "created_at": _utc_now_iso(),
            "author": author,
        },
        "axioms": [
            "Ἀπορία — Habiter la question sans précipiter la réponse.",
        ],
        "theoria": [
            "Privilégier les reformulations qui clarifient la structure du problème.",
            "Autoriser les intuitions ouvertes tout en cherchant leur cohérence interne.",
            "Construire des explications progressives plutôt que des conclusions abruptes.",
            "Ne pas opposer intuition et formalisation, mais chercher leur continuité.",
            "Albert Einstein — transformation des perspectives et exploration des hypothèses implicites.",
            "James Clerk Maxwell — unification des intuitions en structures cohérentes et continues.",
        ],
    }


def _default_codex_opt(workspace: str, author: str) -> dict[str, Any]:
    return {
        "version": "1.0",
        "metadata": {
            "workspace": workspace,
            "created_at": _utc_now_iso(),
            "author": author,
        },
        "axioms": [
            "Γνῶθι σεαυτόν — Connais ton workspace avant d'agir.",
        ],
        "theoria": [
            "Euclide — privilégier les structures simples, décomposables et vérifiables.",
            "Newton — interpréter les systèmes comme régis par des régularités stables et reproductibles.",
        ],
        "telos": [
            "Comprendre le contexte avant de modifier un fichier.",
            "Préserver une organisation simple et lisible.",
        ],
        "topos": [
            "notes/ → espace principal de travail et de réflexion.",
            "archive/ → anciens éléments conservés pour référence.",
        ],
        "nomos": [
            "Demander confirmation avant une modification importante.",
            "Privilégier les changements simples et réversibles.",
            "Toute décision doit pouvoir être retracée et justifiée par des étapes claires.",
            "Maintenir une constance méthodique même en contexte complexe ou incertain.",
        ],
        "praxis": [
            "Consulter les fichiers récemment modifiés avant une intervention.",
            "Vérifier l'état général du workspace avant toute action.",
        ],
    }


def _validate_metadata(data: dict[str, Any]) -> None:
    meta = data.get("metadata")
    if not isinstance(meta, dict):
        raise ValueError("metadata manquant ou invalide")
    for key in ("workspace", "created_at", "author"):
        if key not in meta or not isinstance(meta[key], str) or not meta[key].strip():
            raise ValueError(f"metadata.{key} manquant ou invalide")


def _validate_list_field(data: dict[str, Any], key: str) -> None:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"Section {key} manquante ou vide")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"Section {key} doit contenir des chaînes non vides")


def validate_codex(kind: _CodexKind, data: dict[str, Any]) -> None:
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Codex kind invalide: {kind}")
    if not isinstance(data, dict):
        raise ValueError("Codex invalide: objet YAML attendu")
    if data.get("version") != "1.0":
        raise ValueError("version invalide: attendu '1.0'")

    _validate_metadata(data)
    _validate_list_field(data, "axioms")
    _validate_list_field(data, "theoria")

    if kind == "opt":
        for key in ("telos", "topos", "nomos", "praxis"):
            _validate_list_field(data, key)


def _dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        raise ValueError(f"Fichier vide: {path}")
    if not isinstance(loaded, dict):
        raise ValueError(f"Format YAML invalide: {path}")
    return loaded


def _atomic_write(path: Path, content: str) -> None:
    backup = path.with_suffix(path.suffix + ".bak")
    tmp = path.with_suffix(path.suffix + ".tmp")

    if path.exists():
        shutil.copy2(path, backup)

    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        if backup.exists():
            backup.replace(path)
        raise
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        if backup.exists():
            backup.unlink(missing_ok=True)


def ensure_codex_files(workspace_root: str | Path, *, author: str = "dev") -> list[Path]:
    paths = get_codex_paths(workspace_root)
    paths["arke_dir"].mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    workspace_label = "current-directory"

    if not paths["ask"].exists():
        ask_data = _default_codex_ask(workspace=workspace_label, author=author)
        validate_codex("ask", ask_data)
        paths["ask"].write_text(_dump_yaml(ask_data), encoding="utf-8")
        created.append(paths["ask"])

    if not paths["opt"].exists():
        opt_data = _default_codex_opt(workspace=workspace_label, author=author)
        validate_codex("opt", opt_data)
        paths["opt"].write_text(_dump_yaml(opt_data), encoding="utf-8")
        created.append(paths["opt"])

    return created


def load_codex(kind: _CodexKind, workspace_root: str | Path) -> dict[str, Any]:
    ensure_codex_files(workspace_root)
    paths = get_codex_paths(workspace_root)
    path = paths[kind]
    data = _read_yaml(path)
    validate_codex(kind, data)
    return data


def read_codex_text(kind: _CodexKind, workspace_root: str | Path) -> str:
    ensure_codex_files(workspace_root)
    paths = get_codex_paths(workspace_root)
    return paths[kind].read_text(encoding="utf-8")


def write_codex(kind: _CodexKind, workspace_root: str | Path, data: dict[str, Any]) -> None:
    validate_codex(kind, data)
    paths = get_codex_paths(workspace_root)
    _atomic_write(paths[kind], _dump_yaml(data))


def append_codex_entry(
    kind: _CodexKind,
    workspace_root: str | Path,
    section: str,
    entry: str,
) -> dict[str, Any]:
    section = section.strip().lower()
    entry = entry.strip()
    if not entry:
        raise ValueError("Entrée vide")

    data = load_codex(kind, workspace_root)
    if section not in data or not isinstance(data[section], list):
        raise ValueError(f"Section invalide: {section}")

    if entry not in data[section]:
        data[section].append(entry)
    write_codex(kind, workspace_root, data)
    return data


def get_codex_for_mode(mode: str, workspace_root: str | Path) -> dict[str, Any]:
    if mode == "ask":
        kind = "ask"
    elif mode in {"search", "plan", "agent"}:
        kind = "opt"
    else:
        return {}

    data = load_codex(kind, workspace_root)
    return {
        "kind": kind,
        "path": f".arke/codex_{kind}.yaml",
        "data": data,
    }


def render_codex_summary(workspace_root: str | Path) -> str:
    ensure_codex_files(workspace_root)
    return (
        "# 📋 Codex du workspace Arke\n\n"
        "Deux Codex sont disponibles dans ce workspace :\n\n"
        "• /codex opt — Codex opérationnel (modes /search, /plan, /agent)\n"
        "  Conventions du projet, commandes préférées, contraintes locales\n\n"
        "• /codex ask — Codex réflexif (mode /ask)\n"
        "  Cadres de pensée, références, principes.\n\n"
        "Commandes :\n"
        "  /codex opt        Afficher le Codex opérationnel\n"
        "  /codex ask        Afficher le Codex réflexif\n"
        "  /codex opt edit   Modifier le Codex opérationnel\n"
        "  /codex ask edit   Modifier le Codex réflexif\n\n"
        "Pour en savoir plus : /about\n"
    )
