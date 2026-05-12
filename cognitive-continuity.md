# 🧠 Cognitive Continuity — Arke

> *"The system never takes initiative to create engagement.
> It only reactivates what already exists in memory."*

---

## Overview

**Cognitive Continuity** is the system through which Arke maintains active cognitive threads
between sessions. It observes exchanges, extracts dormant topics, and proposes soft
reactivations — without ever deciding in place of the user.

The system is organized into four main components:

```
ThreadExtractor         → silent extraction (LLM daemon)
SocialOrchestrator      → temporal orchestration + REPL delivery
CognitiveInitiativeGate → deterministic filtering pipeline (4 gates)
initiative_log          → bias-free traceability (accepted DEFAULT NULL)
```

---

## Components

### 1. ThreadExtractor (`arke/thread_extractor.py`)

Silent extraction of cognitive threads after each exchange.

- Runs as an asynchronous daemon (non-blocking)
- Discrete LLM call, cancellable via `CANCEL_GRACE_SECONDS`
- Stores threads in `cognitive_threads` (SQLite `global.db`)
- Invariant: never displayed to the user during extraction

```python
# Triggered automatically after each exchange in chat.py
extract_async(mm, session_id, intention, response_text)
```

---

### 2. SocialOrchestrator (`arke/social_orchestrator.py`)

Temporal orchestration of initiative delivery.

- **Phase 1 active**: `observation_mode = false`
- Checks user idle state (`is_user_idle()`) before delivering
- Fills the queue via `_generate_and_queue()` → `generate_soft_reactivation()` (CIG)
- Delivery in the REPL loop of `chat.py` via `pop_initiative()`

```toml
[social_orchestrator]
enabled = true
observation_mode = false     # Phase 1: active delivery
min_silence_minutes = 30
```

---

### 3. Cognitive Initiative Gate (`arke/cognitive_initiative_gate.py`)

Deterministic pipeline with 4 gates + divergence. No LLM in the decision pipeline.

#### Gates (evaluation order)

| Gate | Condition | Rejected if |
|------|-----------|-------------|
| **Gate 0** | `paused` | `paused=True` → `(None, None)` immediately |
| **Gate 1** | Density | `AVG(avg_depth_score) < threshold_density` over 7 days |
| **Gate 2** | Threads | No thread with `reactivation_score ≥ reactivation_threshold` (after decay) |
| **Divergence** | Probabilistic | `random.random() < divergence_rate` → bypass Gate 3 (serendipity) |
| **Gate 3** | Contextual anchor | Keyword overlap < 2 words OR cosine < semantic_threshold |

#### Configuration (`config/arke.toml`)

```toml
[cognitive_initiative_gate]
enabled = true
threshold_density = 0.5          # minimum density (AVG avg_depth_score over 7d)
reactivation_threshold = 0.65    # minimum score to be eligible
thread_max_age_days = 14         # dormant thread search window
auto_calibrate = true            # auto-calibration of threshold (Phase 2+)
calibration_min_samples = 30     # minimum explicit samples required
semantic_anchor = false          # hybrid anchor (false = keyword only, 0 latency)
semantic_threshold = 0.65        # cosine threshold when semantic_anchor = true
divergence_rate = 0.05           # probability of bypassing Gate 3 (serendipity)
decay_rate = 0.95                # exponential score decay per day of dormancy
```

---

## Feature Details (Sessions 023–028)

### Session 023 — CIG Phase 1: Core Pipeline

Initial implementation of the 4-gate deterministic pipeline:

- `compute_interaction_density()` — density = `AVG(avg_depth_score)` over 7 days
- `get_dormant_threads()` — eligible threads (`status='dormant'`, score > 0)
- `is_contextually_anchored()` — overlap ≥ 2 words (len ≥ 4)
- `generate_soft_reactivation()` — French open question template
- `log_initiative()` — INSERT into `initiative_log` (`accepted DEFAULT NULL`)
- `auto_calibrate_threshold()` — only on `WHERE accepted IS NOT NULL`

**Critical invariant:** `accepted DEFAULT NULL` — absence of reply is NOT a rejection.
Calibration uses only explicit signals.

---

### Session 024 — Semantic Anchor (Hybrid keyword/vector)

Added hybrid anchor mode to `is_contextually_anchored()`:

- `_cosine_similarity(a, b)` — pure Python cosine, returns 0.0 on zero vector
- `_semantic_similarity(thread, context)` — `Embedder().embed()` → cosine
- Hybrid mode: if `semantic_anchor=True` → cosine ≥ `semantic_threshold`; else keyword
- Automatic fallback on `VectorDisabledError` or network error → keyword

```python
# semantic_anchor = false by default → 0 latency, S023 behavior preserved
is_contextually_anchored(thread, context)  # → bool
```

---

### Session 025 — SocialOrchestrator Phase 1

Activation of active initiative delivery:

- `_generate_and_queue()` implemented (was a Phase 0 stub)
- Imports `generate_soft_reactivation` from CIG
- `observation_mode = false` in `arke.toml`
- No changes to `chat.py` — the REPL block was already wired

---

### Session 026 — Feedback Loop

Detection of positive user engagement:

```python
detect_positive_signal(raw: str, initiative_text: str) -> bool
```

- Overlap ≥ 2 words (len ≥ 4) between user input and last displayed initiative
- Returns `False` if either argument is empty
- In `chat.py`: `_last_cig = [log_id, initiative_text]` — REPL state
- If positive signal detected → `mark_initiative_accepted(mm, log_id)` called automatically
- `_last_cig` is reset in all cases (signal or not)

```python
# chat.py — REPL loop
if _last_cig[0] is not None:
    if detect_positive_signal(raw, _last_cig[1]):
        mark_initiative_accepted(mm, _last_cig[0])
    _last_cig[0] = None
    _last_cig[1] = ""
```

---

### Session 027 — Fertile Divergence (Serendipity Principle)

Unexpected reactivation of a thread without contextual link:

```python
get_divergent_thread(mm, max_age_days) -> Optional[dict]
```

- `random.choice()` among eligible dormant threads
- Bypasses Gate 3 (contextual anchor) — intentional random selection
- Triggered with probability `divergence_rate` in `cognitive_initiative_engine()`

Divergent template:
```
⚡ Unexpected connection: we had a lead on « {anchor} ».
Nothing to do with what you're talking about, but it seems interesting. Want to revisit it?
```

Traceability:
```python
log_initiative(..., initiative_type="divergent_reactivation")
# → initiative_log.type = 'divergent_reactivation'
```

Invariant: if no divergent thread is available, the pipeline falls through to the normal contextual path.

---

### Session 028 — Progressive Forgetting (Exponential Decay)

Threads age — their reactivation score decreases over time:

```python
_apply_decay(score: float, days_dormant: int, rate: float = 0.95) -> float
```

- Formula: `score * (rate ** days_dormant)`
- Floor: `max(0.05, decayed)` — threads remain marginally discoverable
- `rate=1.0` → no decay (disableable)
- `0 days` → score unchanged

Applied **in-memory only** in `get_dormant_threads()`:

```python
# Computed on the fly — never written to DB
days_dormant = (today - date.fromisoformat(created_at[:10])).days
score_after_decay = _apply_decay(original_score, days_dormant, decay_rate)
```

**Critical invariant:** the score stored in `cognitive_threads.reactivation_score` is
**never modified** by decay. Decay is a computed view, not a mutation.

---

## SQLite Tables

### `cognitive_threads` (global.db)

| Column | Type | Role |
|--------|------|------|
| `id` | INTEGER PK | identifier |
| `session_id` | TEXT | originating session |
| `content` | TEXT | thread content |
| `summary` | TEXT | condensed summary |
| `status` | TEXT | `open` / `dormant` / `consumed` |
| `reactivation_score` | REAL | original score (never modified by decay) |
| `importance_score` | REAL | general importance score |
| `last_activated_at` | TEXT | last activation (max_age_days window filter) |
| `created_at` | TEXT | creation date (used for decay calculation) |

### `interaction_density` (global.db)

| Column | Type | Role |
|--------|------|------|
| `day` | TEXT PK | date (`YYYY-MM-DD`) |
| `exchange_count` | INTEGER | number of exchanges |
| `avg_depth_score` | REAL | average score (0–1) for Gate 1 |

### `initiative_log` (global.db)

| Column | Type | Role |
|--------|------|------|
| `id` | TEXT UUID | log identifier |
| `thread_id` | TEXT | reactivated thread |
| `type` | TEXT | `soft_reactivation` / `divergent_reactivation` |
| `density_snapshot` | REAL | density at time of initiative |
| `context_anchor` | TEXT | contextual anchor used |
| `accepted` | INTEGER DEFAULT NULL | `1`=accepted, `NULL`=unknown, never automatic `0` |

---

## Full Flow

```
User exchange
       ↓
extract_async()          ← ThreadExtractor (daemon, non-blocking)
       ↓
cognitive_initiative_engine(mm, context, paused=False)
       ↓
  Gate 0: paused?         → (None, None)
       ↓
  Gate 1: density OK?     → (None, None) if too low
       ↓
  Gate 2: threads OK?     → (None, None) if none eligible (after decay)
       ↓
  Divergence gate (5%)?   → get_divergent_thread() → ⚡ divergent initiative
       ↓
  Gate 3: anchor OK?      → (None, None) if no overlap
       ↓
  generate_soft_reactivation(thread)
       ↓
  log_initiative(...)     → initiative_log INSERT (accepted=NULL)
       ↓
  Return (text, log_id)
       ↓
chat.py displays T.initiative_block(text)
_last_cig = [log_id, text]
       ↓
Next user input
       ↓
detect_positive_signal(raw, text)?
  → yes: mark_initiative_accepted(mm, log_id)
  → no : _last_cig reset, no write
```

---

## Non-Negotiable Invariants

```
system_never_engages_for_engagement = true
```

- The system only reactivates what exists in memory — never invented content
- `accepted DEFAULT NULL` — absence of reply is not a rejection, never logged as `0`
- Decay never modifies scores stored in the database
- Divergence never produces an initiative if no memory thread is available
- Auto-calibration only uses explicit positive signals (`WHERE accepted IS NOT NULL`)
- `mark_initiative_accepted()` is never called automatically without a detected positive signal

---

## Tests

```bash
pytest tests/test_cognitive_initiative_gate.py -v   # 39 CIG tests
pytest tests/test_social_orchestrator.py -v         # 19 SO tests
pytest tests/test_thread_extractor.py -v            # 9 TE tests
pytest tests/ -q                                    # 433 tests total
```

CIG test classes:

| Class | Tests | Session |
|-------|-------|---------|
| `TestCigGates` | 5 | S023 |
| `TestCigHappyPath` | 1 | S023 |
| `TestInitiativeLog` | 2 | S023 |
| `TestAutoCalibrate` | 2 | S023 |
| `TestHelpers` | 4 | S023 |
| `TestSemanticAnchor` | 7 | S024 |
| `TestPositiveSignalDetection` | 5 | S026 |
| `TestDivergenceFertile` | 7 | S027 |
| `TestOubliProgressif` | 6 | S028 |

---

*Generated 2026-05-12 — Arke v1.7.0*


---

## Vue d'ensemble

La **Continuité Cognitive** est le système par lequel Arke maintient des fils cognitifs actifs
entre les sessions. Elle observe les échanges, extrait des thèmes dormants, et propose des
réactivations douces — sans jamais décider à la place de l'utilisateur.

Le système est organisé en quatre composants principaux :

```
ThreadExtractor         → extraction silencieuse (daemon LLM)
SocialOrchestrator      → orchestration temporelle + livraison REPL
CognitiveInitiativeGate → pipeline de filtrage déterministe (4 gates)
initiative_log          → traçabilité sans biais (accepted DEFAULT NULL)
```

---

## Composants

### 1. ThreadExtractor (`arke/thread_extractor.py`)

Extraction silencieuse des fils cognitifs après chaque échange.

- Fonctionne comme un daemon asynchrone (non-bloquant)
- Appel LLM discret, annulable via `CANCEL_GRACE_SECONDS`
- Stocke les fils dans `cognitive_threads` (SQLite `global.db`)
- Invariant : jamais affiché à l'utilisateur pendant l'extraction

```python
# Déclenché automatiquement après chaque exchange dans chat.py
extract_async(mm, session_id, intention, response_text)
```

---

### 2. SocialOrchestrator (`arke/social_orchestrator.py`)

Orchestration temporelle de la livraison des initiatives.

- **Phase 1 active** : `observation_mode = false`
- Vérifie l'idle utilisateur (`is_user_idle()`) avant de délivrer
- Remplit la queue via `_generate_and_queue()` → `generate_soft_reactivation()` (CIG)
- Livraison dans la boucle REPL de `chat.py` via `pop_initiative()`

```toml
[social_orchestrator]
enabled = true
observation_mode = false     # Phase 1 : livraison active
min_silence_minutes = 30
```

---

### 3. Cognitive Initiative Gate (`arke/cognitive_initiative_gate.py`)

Pipeline déterministe en 4 gates + divergence. Aucun LLM dans le pipeline de décision.

#### Gates (ordre d'évaluation)

| Gate | Condition | Rejet si |
|------|-----------|----------|
| **Gate 0** | `paused` | `paused=True` → `(None, None)` immédiat |
| **Gate 1** | Densité | `AVG(avg_depth_score) < threshold_density` sur 7 jours |
| **Gate 2** | Threads | Aucun thread avec `reactivation_score ≥ reactivation_threshold` (après decay) |
| **Divergence** | Probabiliste | `random.random() < divergence_rate` → bypass Gate 3 (sérendipité) |
| **Gate 3** | Ancrage contextuel | Overlap keyword < 2 mots OU cosine < semantic_threshold |

#### Configuration (`config/arke.toml`)

```toml
[cognitive_initiative_gate]
enabled = true
threshold_density = 0.5          # densité minimale (AVG avg_depth_score sur 7j)
reactivation_threshold = 0.65    # score minimal pour être éligible
thread_max_age_days = 14         # fenêtre de recherche des threads dormants
auto_calibrate = true            # auto-calibration du seuil (Phase 2+)
calibration_min_samples = 30     # minimum d'échantillons explicites requis
semantic_anchor = false          # ancrage hybride (false = keyword uniquement, 0 latence)
semantic_threshold = 0.65        # seuil cosine si semantic_anchor = true
divergence_rate = 0.05           # probabilité de bypass Gate 3 (sérendipité)
decay_rate = 0.95                # decay exponentiel du score par jour de dormance
```

---

## Fonctionnalités détaillées (Sessions 023–028)

### Session 023 — CIG Phase 1 : Pipeline de base

Mise en place du pipeline déterministe à 4 gates :

- `compute_interaction_density()` — densité = `AVG(avg_depth_score)` sur 7 jours
- `get_dormant_threads()` — threads éligibles (`status='dormant'`, score > 0)
- `is_contextually_anchored()` — overlap ≥ 2 mots (len ≥ 4)
- `generate_soft_reactivation()` — template français, question ouverte
- `log_initiative()` — INSERT dans `initiative_log` (`accepted DEFAULT NULL`)
- `auto_calibrate_threshold()` — uniquement sur `WHERE accepted IS NOT NULL`

**Invariant critique :** `accepted DEFAULT NULL` — l'absence de réponse n'est PAS un rejet.
La calibration n'utilise que les signaux explicites.

---

### Session 024 — Ancrage Sémantique (Hybrid keyword/vector)

Ajout de l'ancrage hybride à `is_contextually_anchored()` :

- `_cosine_similarity(a, b)` — cosine pure Python, retourne 0.0 sur vecteur nul
- `_semantic_similarity(thread, context)` — `Embedder().embed()` → cosine
- Mode hybride : si `semantic_anchor=True` → cosine ≥ `semantic_threshold` ; sinon keyword
- Fallback automatique sur `VectorDisabledError` ou erreur réseau → keyword

```python
# semantic_anchor = false par défaut → 0 latence, comportement S023 préservé
is_contextually_anchored(thread, context)  # → bool
```

---

### Session 025 — SocialOrchestrator Phase 1

Activation de la livraison active des initiatives :

- `_generate_and_queue()` implémenté (était un stub Phase 0)
- Import de `generate_soft_reactivation` depuis CIG
- `observation_mode = false` dans `arke.toml`
- Aucun changement dans `chat.py` — le bloc REPL était déjà câblé

---

### Session 026 — Feedback Loop

Détection de l'engagement positif de l'utilisateur :

```python
detect_positive_signal(raw: str, initiative_text: str) -> bool
```

- Overlap ≥ 2 mots (len ≥ 4) entre input utilisateur et dernière initiative affichée
- Retourne `False` si l'un des arguments est vide
- Dans `chat.py` : `_last_cig = [log_id, initiative_text]` — état REPL
- Si signal positif détecté → `mark_initiative_accepted(mm, log_id)` appelé automatiquement
- `_last_cig` est réinitialisé dans tous les cas (signal ou non)

```python
# chat.py — boucle REPL
if _last_cig[0] is not None:
    if detect_positive_signal(raw, _last_cig[1]):
        mark_initiative_accepted(mm, _last_cig[0])
    _last_cig[0] = None
    _last_cig[1] = ""
```

---

### Session 027 — Divergence Fertile (Principe de Sérendipité)

Réactivation inattendue d'un thread sans lien contextuel :

```python
get_divergent_thread(mm, max_age_days) -> Optional[dict]
```

- `random.choice()` parmi les threads dormants éligibles
- Ignore le Gate 3 (ancrage contextuel) — sélection aléatoire intentionnelle
- Déclenché avec probabilité `divergence_rate` dans `cognitive_initiative_engine()`

Template divergent :
```
⚡ Connexion inattendue : on avait une piste sur « {anchor} ».
Rien à voir avec ce dont tu parles, mais ça me semble intéressant. Tu veux y revenir ?
```

Traçabilité :
```python
log_initiative(..., initiative_type="divergent_reactivation")
# → initiative_log.type = 'divergent_reactivation'
```

Invariant : si aucun thread divergent disponible, le pipeline continue sur le chemin contextuel normal.

---

### Session 028 — Oubli Progressif (Decay Exponentiel)

Les threads vieillissent — leur score de réactivation diminue avec le temps :

```python
_apply_decay(score: float, days_dormant: int, rate: float = 0.95) -> float
```

- Formule : `score * (rate ** days_dormant)`
- Floor : `max(0.05, decayed)` — les threads restent marginalement découvrables
- `rate=1.0` → aucun decay (désactivable)
- `0 jours` → score inchangé

Appliqué **in-memory uniquement** dans `get_dormant_threads()` :

```python
# Calcul à la volée — jamais écrit en base
days_dormant = (today - date.fromisoformat(created_at[:10])).days
score_after_decay = _apply_decay(original_score, days_dormant, decay_rate)
```

**Invariant critique :** le score stocké dans `cognitive_threads.reactivation_score` n'est
**jamais modifié** par le decay. Le decay est une vue calculée, pas une mutation.

---

## Tables SQLite utilisées

### `cognitive_threads` (global.db)

| Colonne | Type | Rôle |
|---------|------|------|
| `id` | INTEGER PK | identifiant |
| `session_id` | TEXT | session d'origine |
| `content` | TEXT | contenu du fil |
| `summary` | TEXT | résumé condensé |
| `status` | TEXT | `open` / `dormant` / `consumed` |
| `reactivation_score` | REAL | score original (jamais modifié par decay) |
| `importance_score` | REAL | score d'importance général |
| `last_activated_at` | TEXT | dernière activation (filtre fenêtre max_age_days) |
| `created_at` | TEXT | date de création (utilisé pour calcul decay) |

### `interaction_density` (global.db)

| Colonne | Type | Rôle |
|---------|------|------|
| `day` | TEXT PK | date (`YYYY-MM-DD`) |
| `exchange_count` | INTEGER | nombre d'échanges |
| `avg_depth_score` | REAL | score moyen (0–1) pour Gate 1 |

### `initiative_log` (global.db)

| Colonne | Type | Rôle |
|---------|------|------|
| `id` | TEXT UUID | identifiant log |
| `thread_id` | TEXT | fil réactivé |
| `type` | TEXT | `soft_reactivation` / `divergent_reactivation` |
| `density_snapshot` | REAL | densité au moment de l'initiative |
| `context_anchor` | TEXT | ancre contextuelle utilisée |
| `accepted` | INTEGER DEFAULT NULL | `1`=accepté, `NULL`=inconnu, jamais `0` automatique |

---

## Flux complet

```
Échange utilisateur
       ↓
extract_async()          ← ThreadExtractor (daemon, non-bloquant)
       ↓
cognitive_initiative_engine(mm, context, paused=False)
       ↓
  Gate 0: paused?         → (None, None)
       ↓
  Gate 1: density OK?     → (None, None) si trop faible
       ↓
  Gate 2: threads OK?     → (None, None) si aucun éligible (après decay)
       ↓
  Divergence gate (5%)?   → get_divergent_thread() → ⚡ initiative divergente
       ↓
  Gate 3: ancre OK?       → (None, None) si pas d'overlap
       ↓
  generate_soft_reactivation(thread)
       ↓
  log_initiative(...)     → initiative_log INSERT (accepted=NULL)
       ↓
  Retour (text, log_id)
       ↓
chat.py affiche T.initiative_block(text)
_last_cig = [log_id, text]
       ↓
Prochain input utilisateur
       ↓
detect_positive_signal(raw, text)?
  → oui : mark_initiative_accepted(mm, log_id)
  → non : _last_cig reset sans écriture
```

---

## Invariants non-négociables

```
system_never_engages_for_engagement = true
```

- Le système ne réactive que ce qui existe dans la mémoire — jamais de contenu inventé
- `accepted DEFAULT NULL` — l'absence de réponse n'est pas un rejet, jamais loggée comme `0`
- Le decay ne modifie jamais les scores stockés en base
- La divergence ne produit jamais d'initiative si aucun thread mémoire n'est disponible
- La calibration automatique n'utilise que les signaux positifs explicites (`WHERE accepted IS NOT NULL`)
- `mark_initiative_accepted()` n'est jamais appelé automatiquement sans signal positif détecté

---

## Tests

```bash
pytest tests/test_cognitive_initiative_gate.py -v   # 39 tests CIG
pytest tests/test_social_orchestrator.py -v         # 19 tests SO
pytest tests/test_thread_extractor.py -v            # 9 tests TE
pytest tests/ -q                                    # 433 tests total
```

Classes de tests CIG :

| Classe | Tests | Session |
|--------|-------|---------|
| `TestCigGates` | 5 | S023 |
| `TestCigHappyPath` | 1 | S023 |
| `TestInitiativeLog` | 2 | S023 |
| `TestAutoCalibrate` | 2 | S023 |
| `TestHelpers` | 4 | S023 |
| `TestSemanticAnchor` | 7 | S024 |
| `TestPositiveSignalDetection` | 5 | S026 |
| `TestDivergenceFertile` | 7 | S027 |
| `TestOubliProgressif` | 6 | S028 |

---

*Document généré le 2026-05-12 — Arke v1.7.0*
