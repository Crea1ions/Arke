# Session 037 — Viabilisation : Workspace Dynamique Global

**Date** : 15 mai 2026  
**Auteur** : Dev  
**Objet** : Refactorisation pour unifier le contexte de workspace dans tous les modes d'Arke

---

## 1. Contexte

- Avant : chaque mode (/ask, /search, /plan, /agent) utilisait un workspace isolé ou un chemin par défaut, jamais le CWD utilisateur.
- Problème : Rupture de contexte, sandbox complexe, UX incohérente, difficultés d'accès aux fichiers réels du projet.

## 2. Objectif

- Capturer le répertoire courant (CWD) au lancement d'Arke et l'utiliser comme WORKSPACE_ROOT global pour tous les modes.
- Propager ce contexte dans tout le pipeline (contrat cognitif, orchestrator, workspace, sandbox, etc.).
- Adapter la sécurité et les permissions par mode.

## 3. Audit initial

- **sandbox.py** : CWD fixé à /workspace (bubblewrap) ou fallback natif sans cwd explicite.
- **workspace.py** : wcu_root fixé à l'init, jamais dynamique.
- **orchestrator.py** : workspace initialisé depuis ctx['wcu_root'] ou par défaut, jamais le CWD.
- **mode_manager.py** : permissions par mode, mais pas de référence au CWD dans le contexte cognitif.

## 4. Plan d'action

1. Refactoriser pour capturer le CWD au lancement (arke/main.py ou point d'entrée CLI).
2. Propager WORKSPACE_ROOT dans tout le pipeline (orchestrator, workspace, build_input_context, sandbox).
3. Adapter la sécurité (is_safe_path, blacklist, confinement logique).
4. Mettre à jour la matrice de permissions par mode.
5. Ajouter des tests de lecture/écriture et de sécurité.

## 5. Implémentation réalisée

### 5.1 Capture et propagation de WORKSPACE_ROOT

- **CLI (`arke run`)** : injection du CWD dans `context["WORKSPACE_ROOT"]` avant appel orchestrator.
- **Chat (`arke chat`)** : injection du CWD dans :
	- le contexte cognitif (`build_input_context`) ;
	- le contexte orchestrator pour l'exécution d'outils.
- **Orchestrator** :
	- initialisation workspace prioritaire depuis `ctx["WORKSPACE_ROOT"]` ;
	- fallback conservé vers `ctx["wcu_root"]`, puis valeur par défaut historique.

### 5.2 Sandbox dynamique

- Ajout d'une résolution de racine effective côté sandbox (`workspace_root` optionnel).
- En mode `workspace` bubblewrap : bind de la racine effective sur `/workspace`.
- En fallback sans bwrap : exécution `subprocess.run(..., cwd=<workspace_root>)`.

### 5.3 Robustesse tests

- Correction d'un test non idempotent sur SQLite (`skills.name` unique) via nom de skill dynamique.

### 5.4 Durcissement sécurité FS

- Ajout de `is_safe_path(path, workspace_root)` dans `security.py`.
- Intégration dans `orchestrator._exec_fs(...)` :
	- résolution des chemins relatifs depuis `WORKSPACE_ROOT` ;
	- blocage explicite des chemins sortant du workspace ;
	- maintien de la compatibilité quand `WORKSPACE_ROOT` est absent.
- Ajout de tests dédiés dans `tests/test_security_paths.py` (inside/outside workspace + blocage traversal + lecture autorisée).

### 5.5 Blacklist explicite et symlinks

- Ajout de `is_blacklisted_path(path)` dans `security.py`.
- Blacklist explicite de préfixes sensibles (`/etc`, `/proc`, `/sys`, `/dev`, `/root`, `/boot`, `/run`, `/var/log`, `~/.ssh`).
- Enforcement dans `orchestrator._exec_fs(...)` : blocage des chemins blacklistés même hors mode workspace.
- Tests ajoutés :
	- blocage de chemin absolu sensible ;
	- blocage d'un symlink situé dans le workspace mais pointant hors workspace.

### 5.6 Normalisation stricte CLI avant sandbox

- Ajout de `normalize_cli_command_paths(command, workspace_root)` dans `security.py`.
- Normalisation des arguments de chemins vers `/workspace/...` avant exécution sandbox.
- Validation stricte avant exécution :
	- blocage des chemins hors workspace ;
	- blocage des chemins blacklistés ;
	- prise en charge des options `--key=path`.
- Intégration dans `orchestrator._exec_cli(...)` avant `check_command(...)` et avant `sandboxed_run(...)`.
- Tests avancés ajoutés dans `tests/test_security_cli_paths.py` :
	- normalisation chemins relatifs ;
	- blocage `../` ;
	- blocage `/etc/...` ;
	- blocage symlink relatif sortant workspace ;
	- vérification que `_exec_cli` transmet la commande normalisée à la sandbox.

### 5.7 Détection path-like avancée (pipelines/quotes)

- Renforcement du parser shell côté sécurité :
	- lexer avec séparation robuste des opérateurs (`|`, `&&`, `;`, `<`, `>`) même sans espaces ;
	- reconstruction sûre de la commande (préservation opérateurs shell) ;
	- normalisation récursive des fragments shell quotés (ex. `bash -lc "..."`).
- Cas complexes désormais couverts :
	- pipelines collés (`cat ./file|wc -l`) ;
	- snippets shell imbriqués en argument ;
	- blocage des escapes (`../`) dans fragments imbriqués.

## 6. Validation

- Lots ciblés : **50 passed** puis **88 passed**.
- Validation intermédiaire post-refactor : **79 passed** puis **75 passed** (sous-ensembles ciblés).
- Suite complète finale (après path-like avancé pipelines/quotes) : **689 passed, 7 skipped**.

## 7. Éditeur / Pylance

- Erreur réelle corrigée : import manquant `threading` dans `chat.py`.
- Faux positifs d'import liés au contexte workspace :
	- ajout de `pyrightconfig.json` dans le repo Arke ;
	- ajout/ajustement de `.vscode/settings.json` (repo + workspace agent-dev) pour `.venv` + `extraPaths`.

## 8. Reste à faire

1. Ajouter des cas limites supplémentaires pour redirections composées (`2>`, `2>>`) et substitutions shell selon les besoins terrain.
2. Vérification/extension de la matrice de permissions par mode pour les opérations FS/CLI les plus sensibles.
3. Ajout de tests sécurité dédiés (tentatives de sortie workspace, chemins relatifs malveillants, symlinks).

## 9. Bénéfices confirmés

- Cohérence totale du contexte projet
- UX fluide et prévisible
- Sécurité renforcée par le confinement logique
- Débogage et audit facilités

---

**Statut** : Implémentation majeure terminée et validée par tests ; durcissement sécurité complémentaire à planifier.

---

*Synthèse mise à jour automatiquement par GitHub Copilot (GPT-5.3-Codex)*
