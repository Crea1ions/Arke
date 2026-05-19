# Stream Contract: Arke ↔ Proxy ↔ Frontend

**Version**: 1.0  
**Date**: 2026-05-18  
**Scope**: Session 041.1 streaming protocol between gateway, proxy, and UI  
**Architecture**: Archè (Agent) → Themelios (System) → Cosmos (UI)

---

## 1. Transport Layer

**Protocol**: HTTP/1.1 + Server-Sent Events (SSE)  
**Content-Type**: `text/event-stream`  
**Charset**: UTF-8  
**Connection**: Keep-Alive  
**Timeout**: Per-layer asymmetric (see section 5)

---

## 2. Event Types

All events follow SSE format: `event: <type>\ndata: <json>\n\n`

### 2.1 — `event: block`

Semantic content block (paragraph, code section, list, etc.)

**Data Schema**:
```json
{
  "id": "blk_1",
  "type": "text|code|list|table|section",
  "content": "...",
  "elapsed_ms": 120,
  "tokens": 42,
  "is_final": false
}
```

**Fields**:
- `id`: Unique block identifier in this stream (blk_1, blk_2, ...)
- `type`: Semantic type (text = paragraph, code = code block, etc.)
- `content`: UTF-8 text content (may contain newlines)
- `elapsed_ms`: Milliseconds since stream start
- `tokens`: Approximate token count in this block
- `is_final`: True if this is last block (or False)

**Example**:
```
event: block
data: {"id":"blk_1","type":"text","content":"Hello world","elapsed_ms":50,"tokens":2,"is_final":false}

```

**Frequency**: Every 50-5000ms depending on semantic boundary detection

---

### 2.2 — `event: heartbeat`

Keepalive signal (ensures connection stays open, no activity timeout)

**Data Schema**:
```json
{
  "elapsed_ms": 5000,
  "tokens_buffered": 147,
  "blocks_emitted": 2,
  "status": "processing|thinking|waiting"
}
```

**Fields**:
- `elapsed_ms`: Total time since stream start
- `tokens_buffered`: Tokens in current block (not yet emitted)
- `blocks_emitted`: Number of complete blocks sent so far
- `status`: Current processing stage

**Frequency**: Every 10 seconds if no block emitted

**Example**:
```
event: heartbeat
data: {"elapsed_ms":10000,"tokens_buffered":56,"blocks_emitted":2,"status":"thinking"}

```

**Use Case**: Frontend updates "Thinking..." indicator, resets inactivity timer

---

### 2.3 — `event: done`

Stream completion (success or timeout)

**Data Schema**:
```json
{
  "total_blocks": 7,
  "total_duration_ms": 12450,
  "total_tokens": 1834,
  "reason": "completed|timeout|abort|error",
  "session_id": "myth_..."
}
```

**Fields**:
- `total_blocks`: Final count of emitted blocks
- `total_duration_ms`: Total response time
- `total_tokens`: Total tokens in response
- `reason`: Completion reason (see table below)
- `session_id`: For correlation with logs

**Reasons**:
- `completed`: Normal end (all content sent)
- `timeout`: Response took > 120s (hard limit)
- `abort`: User closed connection or cancelled
- `error`: Error occurred, stream closed

**Example**:
```
event: done
data: {"total_blocks":7,"total_duration_ms":12450,"total_tokens":1834,"reason":"completed","session_id":"myth_abc"}

```

---

### 2.4 — `event: error`

Stream error (recoverable or fatal)

**Data Schema**:
```json
{
  "code": "TIMEOUT|GATEWAY_UNAVAILABLE|AUTH_FAILED|INTERNAL_ERROR|UNKNOWN",
  "message": "Human-readable error message",
  "recovery_action": "retry|workspace_select|contact_admin",
  "request_id": "req_xyz"
}
```

**Fields**:
- `code`: Error code (see table)
- `message`: Actionable error description
- `recovery_action`: What user should do
- `request_id`: Trace ID for debugging

**Error Codes**:

| Code | Cause | Recovery | Retryable |
|------|-------|----------|-----------|
| TIMEOUT | No token for 30s | retry | ✅ Yes |
| GATEWAY_UNAVAILABLE | Proxy ↔ Gateway connection failed | check service, retry | ✅ Yes |
| AUTH_FAILED | Invalid token/session | workspace_select | ❌ No |
| INTERNAL_ERROR | Unexpected error | contact_admin | ❌ No |
| UNKNOWN | Unclassified | retry | ⚠️ Maybe |

**Example**:
```
event: error
data: {"code":"TIMEOUT","message":"Response processing took too long","recovery_action":"retry","request_id":"req_xyz"}

```

---

### 2.5 — `event: session_expired`

Session no longer valid (12h inactivity exceeded)

**Data Schema**:
```json
{
  "message": "Session expired, select workspace to continue",
  "recovery_action": "workspace_select"
}
```

**Example**:
```
event: session_expired
data: {"message":"Session expired","recovery_action":"workspace_select"}

```

---

## 3. Block Boundary Rules (Deterministic)

Gateway emits blocks using STRICT RULES (no semantic judgment):

### Rule 1: DOUBLE_NEWLINE
- **Trigger**: Token is `\n\n`
- **Action**: Emit current buffer as block
- **Rationale**: Explicit paragraph boundary (author-intended)

### Rule 2: TIMEOUT_500MS
- **Trigger**: No token received for 500ms
- **Action**: Emit current buffer as block (if non-empty)
- **Rationale**: Inactivity pause (not semantic judgment)

### Rule 3: MAX_BUFFER_500_CHARS
- **Trigger**: Buffer size ≥ 500 characters
- **Action**: Emit first 500 chars, keep rest in buffer
- **Rationale**: Prevent unbounded buffering, not semantic

### Rule 4: HEARTBEAT_10S
- **Trigger**: 10 seconds elapsed without emitting any block
- **Action**: Emit heartbeat event (no content block)
- **Rationale**: Ensure UI receives signal (prevents perceived freeze)

**Implementation Guarantee**: Every rule is deterministic, documentable, and contains NO interpretation of content.

---

## 4. Timing Guarantees

| Metric | Target | Worst Case | Notes |
|--------|--------|-----------|-------|
| TTFB (Time to First Byte) | < 100ms | < 500ms | Local network, warm cache |
| Block emission interval | 50-2000ms | 5000ms | Depends on semantic boundary |
| Heartbeat interval | 10s (if no block) | 10s hard | Keep connection alive |
| Total response timeout | 120s (hard limit) | 120s hard | Session expires if exceeded |
| Per-block inactivity | 30s | 30s hard | If no token for 30s, error |

---

## 5. Layer Timeouts (Asymmetric Enforcement)

**Rule**: Frontend timeout > Proxy timeout > Processing timeout

| Layer | Timeout | Reason |
|-------|---------|--------|
| **Frontend** | 8 seconds | UI abort, user perception |
| **Proxy** | 5 seconds | Fail-fast, detect gateway stall |
| **Gateway** | 90 seconds | Arke cognitive processing |
| **Per-block** | 30 seconds | Inactivity (no token received) |

**Cascading Behavior**:
1. If gateway processes > 30s with no token → emit `event: error` (timeout)
2. If proxy sees no data for 5s → close stream, emit error to UI
3. If frontend waits > 8s → abort fetch, preserve blocks, show retry

---

## 6. Layer Responsibilities

### Archè (Agent: Arke)
- Emits raw tokens (streaming generator)
- No knowledge of transport format
- Decides content; blind to blockage
- Yields tokens as they are generated

### Themelios (System: Gateway + Proxy)
- **Gateway** (`myteam_api.py`):
  - Buffer tokens, detect block boundaries (Rule 1-4)
  - Emit SSE events with metadata
  - Implement heartbeat (every 10s)
  - Track metrics: TTFB, block count, duration
  - Log to `stream_metrics_YYYYMMDD.log`
  
- **Proxy** (`proxy-llm/server.js`):
  - Health check gateway before streaming
  - Pass through SSE events (transparent)
  - Enforce proxy timeout (5s)
  - Detect stream stall, emit error if stalled
  - Handle backpressure (TCP flow control)
  - Never interpret content

### Cosmos (Result: Frontend UI)
- Parse SSE events
- Accumulate blocks into final response
- Render blocks progressively
- Handle heartbeat (update indicator)
- Show errors with recovery actions
- Preserve partial blocks on abort

---

## 7. Error Handling & Recovery

### Client-Side (Frontend)
```javascript
// Pseudo-code
const stream = fetch(url, { method: 'POST' });
const reader = stream.body.getReader();

while (true) {
  const { value, done } = await reader.read();
  
  if (done) break;
  
  const lines = parseLines(value);
  for (const { event, data } of lines) {
    switch (event) {
      case 'block': appendBlock(data.content); break;
      case 'heartbeat': showThinking(); break;
      case 'error': showError(data.message, offerRetry()); break;
      case 'done': markComplete(); break;
    }
  }
}

// If fetch aborts (timeout or user close):
// → Preserve current blocks + show "Partial response"
```

### Server-Side (Gateway)
```python
# Pseudo-code
try:
  for token in arke_generator():
    buffer += token
    check_boundaries()  # Rules 1-4
    if should_emit():
      emit_block(buffer)
    
    if elapsed_since_last_token > 30:
      emit_error(TIMEOUT)
      break
  
  if elapsed_total > 120:
    emit_done(reason='timeout')
  else:
    emit_done(reason='completed')
    
except Exception as e:
  emit_error(INTERNAL_ERROR)
```

---

## 8. Backpressure Handling

**Scenario**: Frontend slow to consume blocks (network congestion, slow device)

**Mechanism**:
1. Proxy buffers at most 1 block in memory
2. If client read buffer fills, Proxy pauses reading from Gateway
3. TCP flow control naturally slows Gateway token emission
4. After 5s of stall, Proxy emits `event: error` (timeout)

**Result**: No memory explosion; graceful degradation

---

## 9. Backward Compatibility

**Fallback Path** (if streaming unavailable):
- Client detects no `event-stream` support
- Gateway returns single-block response (existing behavior)
- Works on older browsers (no SessionStorage needed)

---

## 10. Observability & Metrics

**Logged to** `stream_metrics_YYYYMMDD.log` (JSONL format):

```json
{
  "timestamp": "2026-05-18T14:30:00Z",
  "session_id": "myth_abc123",
  "request_id": "req_xyz",
  "ttfb_ms": 245,
  "block_count": 7,
  "total_duration_ms": 12450,
  "total_tokens": 1834,
  "status": "completed",
  "errors": []
}
```

**Correlation**: `request_id` links to `actions.log` entries

---

## 11. Examples

### Example 1: Successful Multi-Block Response

```
POST /api/v1/chat
← HTTP 200 OK
← Content-Type: text/event-stream

event: block
data: {"id":"blk_1","type":"text","content":"First paragraph.","elapsed_ms":50,"tokens":4,"is_final":false}

event: block
data: {"id":"blk_2","type":"code","content":"def hello():\n    print('world')","elapsed_ms":500,"tokens":12,"is_final":false}

event: heartbeat
data: {"elapsed_ms":10000,"tokens_buffered":20,"blocks_emitted":2,"status":"processing"}

event: block
data: {"id":"blk_3","type":"text","content":"Final paragraph.","elapsed_ms":12400,"tokens":3,"is_final":true}

event: done
data: {"total_blocks":3,"total_duration_ms":12450,"total_tokens":19,"reason":"completed","session_id":"myth_abc"}
```

### Example 2: Error Recovery

```
POST /api/v1/chat
← HTTP 200 OK
← Content-Type: text/event-stream

event: block
data: {"id":"blk_1","type":"text","content":"Processing...","elapsed_ms":100,"tokens":2,"is_final":false}

event: error
data: {"code":"TIMEOUT","message":"No response from Arke in 30s","recovery_action":"retry","request_id":"req_xyz"}
```

**Frontend Action**: Show "Timeout: Retry?" button. User clicks, new request sent with same `session_id`.

### Example 3: Session Expired

```
POST /api/v1/chat
← HTTP 200 OK
← Content-Type: text/event-stream

event: session_expired
data: {"message":"Session inactive 12h, select workspace to continue","recovery_action":"workspace_select"}
```

**Frontend Action**: Navigate to workspace selection dialog.

---

## 12. Testing Checklist

- [ ] Block boundaries detected correctly (all 4 rules)
- [ ] Heartbeat emitted every 10s if no block
- [ ] SSE events formatted correctly (event/data/blank-line)
- [ ] TTFB measured and logged
- [ ] Backpressure doesn't cause proxy memory spike
- [ ] Timeout at 30s per-block enforced
- [ ] Timeout at 120s total enforced
- [ ] Error events received by frontend
- [ ] Session expiration detected
- [ ] Retry idempotent (same session_id works)
- [ ] Partial block preserved on abort
- [ ] No 500 errors visible to user

---

## 13. References

- [W3C EventSource Spec](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [MDN EventSource](https://developer.mozilla.org/en-US/docs/Web/API/EventSource)
- [Node.js Streaming](https://nodejs.org/api/stream.html)
- [OpenAI Streaming](https://platform.openai.com/docs/api-reference/chat/create#chat-create-stream)
- [Anthropic Streaming](https://docs.anthropic.com/en/api/messages-streaming)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-05-18 | Initial spec (Session 041.1) |

---

## Sign-Off

- **Architecture**: Archè/Themelios/Cosmos separation maintained ✅
- **Determinism**: Block boundaries fully deterministic ✅
- **Cognitive Contract**: Arke blind to transport ✅
- **Error Resilience**: All error paths defined ✅
