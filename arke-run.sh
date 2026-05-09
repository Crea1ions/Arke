#!/bin/bash
# Wrapper pour lancer Arke depuis n'importe quel terminal
# Reste dans son répertoire dédié avec son .venv

# Résoudre le chemin réel du script (même si appelé via symlink)
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
ARKE_ROOT="$(dirname "$SCRIPT_PATH")"

# Changer dans le répertoire du projet
cd "${ARKE_ROOT}"

# Utiliser directement l'exécutable arke du venv (déjà configuré par pip install -e)
exec "${ARKE_ROOT}/.venv/bin/python3" -m arke.cli "$@"
