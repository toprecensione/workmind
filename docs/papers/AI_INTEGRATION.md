# AI Integration Architecture in WorkMind v2

**Type:** Technical Whitepaper
**Date:** 2026-04-26
**Audience:** AI/ML engineers, technical leadership

---

## Abstract

WorkMind v2 integrates Large Language Models (LLMs) and embedding models from multiple providers to deliver an AI-augmented business assistant. This paper describes the architectural patterns used to:

- Route requests across multiple AI providers with cost-aware fallback
- Stream responses to users via Server-Sent Events
- Ground AI answers in customer-specific knowledge through Retrieval-Augmented Generation (RAG)
- Anonymize personally identifiable information (PII) before external API calls
- Track and bound AI costs at the org and platform level
- Operate AI features without locking the platform to any single provider

The result is an AI integration that is **provider-agnostic**, **privacy-respecting**, **cost-controlled**, and **production-resilient**.

---

## 1. Challenges of AI in B2B SaaS

Building production AI features for B2B customers presents distinct challenges:

| Challenge | Why It Matters |
|---|---|
| **Provider lock-in risk** | A single vendor's API changes, price increases, or downtime can disrupt service |
| **Privacy concerns** | Sensitive customer data being sent to third-party AI providers |
| **Cost unpredictability** | Token-based pricing makes per-request cost variable; abuse can spike bills |
| **Hallucination** | LLMs confidently produce wrong information without grounding |
| **Latency** | Cloud LLMs can be slow; first-token latency varies 2–10 seconds |
| **Regulation** | GDPR, sector-specific regulations affect what can be sent where |

WorkMind addresses these through architectural choices, not by relying on any single AI provider's promises.

---

## 2. The ModelRouter Abstraction

At the heart of WorkMind's AI layer is the **ModelRouter** (`app/services/model_router.py`), a unified interface to multiple LLM providers.

### 2.1 Supported Providers

| Provider | Models | Hosting | Cost Tier |
|---|---|---|---|
| **Anthropic** | Claude Sonnet, Claude Haiku | Cloud (USA) | Premium |
| **DeepSeek** | DeepSeek Chat, DeepSeek Coder | Cloud (China) | Budget |
| **Ollama** | Llama 3.2, Mistral, custom | Self-hosted | Free (compute cost only) |

### 2.2 Common Interface

```python
class ModelRouter:
    async def complete(
        self,
        messages: list[dict],
        org_id: str,
        user_id: str,
        model_preference: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> AIResponse:
        """Non-streaming completion."""
        ...

    async def complete_stream(
        self,
        messages: list[dict],
        org_id: str,
        user_id: str,
        ...
    ) -> AsyncIterator[StreamChunk]:
        """SSE-style streaming completion."""
        ...
```

The application code calls these methods without knowing which provider will handle the request.

### 2.3 Provider Selection Logic

```
1. If user explicitly requested model_preference → use it (if available)
2. Try Anthropic Claude (preferred for quality)
3. If Claude fails (timeout, API error, budget exhausted) → DeepSeek
4. If DeepSeek fails → Ollama (local, last resort)
5. If all fail → return error
```

This cascading fallback ensures resilience: a temporary outage at one provider doesn't take down chat.

### 2.4 Pricing Awareness

Each call computes cost in USD using the pricing table (`_PRICING` dict):

```python
_PRICING = {
    "claude-sonnet-4-5": {"in": 3.0, "out": 15.0},  # $/million tokens
    "claude-haiku-4-5":  {"in": 1.0, "out": 5.0},
    "deepseek-chat":     {"in": 0.14, "out": 0.28},
    "ollama-local":      {"in": 0.0, "out": 0.0},
    # ...
}
```

After each call:
```python
cost_usd = (tokens_in * pricing["in"] + tokens_out * pricing["out"]) / 1_000_000
```

Recorded in `model_usage` table for analytics and billing reconciliation.

### 2.5 Daily Budget Cap

Before making a call, the router checks today's cumulative cost:

```python
if self._daily_usage[provider] + estimated_cost > settings.max_daily_cost_usd:
    # Skip this provider, try next
    continue
```

This prevents runaway costs from compromised accounts or buggy clients.

**Limitation (P1 in code review):** budget tracking is in-memory; resets on restart. Roadmap: persist in Redis with 24h TTL.

---

## 3. Retrieval-Augmented Generation (RAG)

### 3.1 Why RAG?

LLMs trained on the public internet don't know your company's documents, procedures, or terminology. **RAG** bridges this by:

1. Indexing your documents as vector embeddings
2. At query time, finding the most relevant document chunks via similarity search
3. Including those chunks in the LLM prompt as context
4. The LLM cites and uses this grounded context in its answer

### 3.2 RAG Pipeline in WorkMind

```
Document upload
    │
    ▼
[FileParser]
    │ (extract text from PDF/DOCX/XLSX/DXF)
    ▼
[Chunker]
    │ (split into ~500-token chunks with overlap)
    ▼
[Embedder] ──────────►  [Ollama nomic-embed-text]
    │                    (768-dim vector per chunk)
    ▼
[document_chunks table]
    │ (with HNSW index on embedding)
    ▼
   ...

User query
    │
    ▼
[Embedder] ──────────►  Same embedding model
    │
    ▼
[Vector similarity search] (cosine, top-K=5)
    │
    ▼
[Construct prompt]
    │ (system + context chunks + history + user message)
    ▼
[ModelRouter]
    │
    ▼
[LLM response] → user
```

### 3.3 Embedding Model

We use **nomic-embed-text** via Ollama:
- 768-dim embeddings
- Fast on CPU (~50ms per chunk)
- Multilingual (handles Italian and English well)
- Free (self-hosted)

For larger-scale or higher-quality needs, we plan to evaluate:
- OpenAI text-embedding-3-small (1536-dim, cloud)
- Cohere embed-multilingual-v3 (1024-dim, cloud)

### 3.4 Vector Storage

Embeddings stored in PostgreSQL with **pgvector** extension:

```sql
CREATE TABLE document_chunks (
    ...
    embedding vector(768) NOT NULL,
    ...
);

CREATE INDEX ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

HNSW (Hierarchical Navigable Small World) indexes give O(log n) search with high recall. At our scale (≤500K chunks), search latency is <50ms.

### 3.5 Search Query

```python
result = await db.execute(
    text("""
        SELECT c.id, c.content, c.metadata_json, d.title,
               (1 - (c.embedding <=> CAST(:query_vec AS vector))) AS similarity
        FROM document_chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE d.org_id = :org_id AND d.status = 'ready'
        ORDER BY c.embedding <=> CAST(:query_vec AS vector)
        LIMIT :k
    """),
    {"query_vec": query_embedding, "org_id": org_id, "k": 5},
)
```

The `<=>` operator is pgvector's cosine distance.

### 3.6 Prompt Construction

```python
def build_prompt(query, history, context_chunks, system_prompt):
    return [
        {"role": "system", "content": f"""{system_prompt}

Context from knowledge base:
{format_chunks(context_chunks)}

Cite chunks by [{{document_title}}] when using their content.
"""},
        *history,
        {"role": "user", "content": query},
    ]
```

The system instructs the LLM to use and cite the provided context, encouraging traceable answers.

### 3.7 Limitations

- **Context window**: chunks must fit within the LLM's context (typically 200K tokens for Claude). We cap at top-5 chunks (~5K tokens).
- **Recency**: RAG retrieves what's indexed; if a doc was just uploaded, indexing may not be complete.
- **Synthesis**: LLM may still hallucinate even with context. Mitigate via prompts asking for citations.

---

## 4. Anonymization

### 4.1 Why Anonymize?

Sending raw user data to external AI providers risks:
- **GDPR violations** (Article 6 — lawful basis)
- **Vendor data retention** (some providers train on submitted data)
- **Cross-border transfers** to non-adequate countries (e.g., DeepSeek in China)
- **Customer concerns** about confidential data leaving their environment

WorkMind anonymizes PII **before** sending text to external providers.

### 4.2 The Anonymizer Service

`app/services/anonymizer.py` defines patterns:

```python
PATTERNS = {
    "fiscal_code_it": r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b",
    "iban":           r"\bIT\d{2}[A-Z]\d{22}\b",
    "phone":          r"\b(\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b",
    "email":          r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
    "credit_card":    r"\b\d{4}[-.\s]?\d{4}[-.\s]?\d{4}[-.\s]?\d{4}\b",
    "name_heuristic": r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b",  # heuristic, prone to FP
}
```

### 4.3 Session-based Anonymization

For each conversation, an `AnonymizationSession` is created:

```python
session = AnonymizationSession(conversation_id)
anonymized_text = session.anonymize("My name is Mario Rossi, CF: RSSMRA80A01H501Z")
# → "My name is [PII_001], CF: [PII_002]"

# Stored in Redis: redis.set(f"anon:{session_id}", session.mapping)
```

The mapping is stored server-side (Redis with TTL). When the AI response comes back:

```python
deanonymized_response = session.deanonymize(ai_response)
# Replaces [PII_001] → Mario Rossi, [PII_002] → RSSMRA80A01H501Z
```

The user sees the original information; the AI provider only saw the placeholders.

### 4.4 Limitations

- **Heuristic name detection** has false positives (any "Pascal Case" pair) and false negatives (lowercase names, multi-word)
- **Context loss**: replacing names with `[PII_001]` may lose semantic info ("Mario, an Italian male" → "[PII_001], an Italian male" — AI loses gender hint)
- **Re-identification risk**: if the message has unique structure (e.g., a specific medical condition + age + city), the AI provider could re-identify even without explicit PII

### 4.5 Future Hardening

- Use a proper NER (Named Entity Recognition) model (spaCy, Italian-trained) for higher accuracy
- Per-org configurable patterns (some orgs might want to anonymize product codes, internal IDs)
- Differential privacy techniques for high-sensitivity orgs
- Optional pass-through mode for orgs with on-premise AI (no anonymization needed)

---

## 5. Streaming Responses (SSE)

For chat responses, WorkMind uses **Server-Sent Events** (SSE) — unidirectional streaming over standard HTTP.

### 5.1 Why SSE Instead of WebSockets?

| Aspect | SSE | WebSocket |
|---|---|---|
| Direction | Server → Client | Bi-directional |
| Protocol | Plain HTTP | WS upgrade |
| Proxying | Works through any HTTP proxy | Some proxies break |
| Complexity | Trivial client code | Requires WebSocket lib |
| Reconnection | Built-in | Manual |
| Header overhead | Yes (each event) | Minimal |

Chat is one-way (server streams to client), so SSE is the simpler, more compatible choice.

### 5.2 Server Implementation

```python
@router.post("/api/chat/stream")
async def chat_stream(body: ChatRequest, ...):
    async def event_generator():
        async for chunk in model_router.complete_stream(messages, ...):
            if chunk.kind == "token":
                yield f"event: token\ndata: {json.dumps({'text': chunk.text})}\n\n"
            elif chunk.kind == "done":
                yield f"event: done\ndata: {json.dumps(chunk.dict())}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 5.3 Client Implementation

```javascript
const response = await fetch('/api/chat/stream', { method: 'POST', body: ... });
const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split('\n\n');
    buffer = events.pop() ?? '';

    for (const eventText of events) {
        const data = parseSSE(eventText);
        if (data.event === 'token') appendToken(data.text);
    }
}
```

### 5.4 Provider-specific Streaming

Each AI provider streams differently:
- **Anthropic**: SSE with `event: content_block_delta`
- **DeepSeek**: SSE with OpenAI-style `data: {"choices":[{"delta":{"content":"..."}}]}`
- **Ollama**: Newline-delimited JSON

The ModelRouter normalizes all of these into a uniform `StreamChunk` interface.

---

## 6. Cost & Usage Tracking

### 6.1 Per-Message Cost

Every message is recorded with:
- Provider used
- Model used
- Input tokens
- Output tokens
- Cost in USD (computed)
- Latency

Stored in `model_usage` table.

### 6.2 Aggregations

The admin dashboard displays:
- Today's cost by provider
- This month's cost
- Top users by cost
- Cost per conversation
- Token rate (messages/hour)

### 6.3 Budget Alerts

Currently planned:
- Email alert when daily budget reaches 80%
- Email alert at 100%
- Auto-disable AI for the day at 100%
- Per-user limits (in addition to org-wide)

---

## 7. Reliability Patterns

### 7.1 Retry with Exponential Backoff

For transient errors (5xx, timeouts), the ModelRouter retries up to 3 times:

```python
for attempt in range(3):
    try:
        return await call_provider(...)
    except (httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
        if attempt == 2:
            raise
        await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
```

### 7.2 Circuit Breaker (planned)

If a provider fails N times in M minutes, automatically skip it for a cooldown period. Prevents flooding a struggling service and reduces user-facing latency.

### 7.3 Timeout Discipline

Each call has explicit timeouts:
- Connect: 10s
- Read: 60s (allows for streaming)
- Total: 120s

Beyond these, the request is canceled and an error is returned.

### 7.4 Graceful Degradation

If all providers fail, WorkMind doesn't crash. The chat endpoint returns:

```json
{
  "detail": "Tutti i provider AI non sono raggiungibili. Riprova tra qualche minuto."
}
```

The user experience is degraded, but the app remains functional for non-AI tasks.

---

## 8. Quality Considerations

### 8.1 Hallucination Mitigation

- **RAG grounding**: chunks from KB reduce wild claims
- **Citation prompts**: instruct LLM to cite sources
- **Verification UI**: surface citations in the chat (planned)
- **Conservative temperature**: 0.7 for chat, lower for factual tasks

### 8.2 Prompt Engineering

System prompts in `app/prompts/`:
- `medic_system_prompt.txt` — MEDIC-specific persona, terminology, regulations
- (more planned per Client)

The prompts are versioned. A/B testing of prompt variations is possible (planned UI).

### 8.3 Evaluation (planned)

A dedicated evaluation harness will:
- Run a fixed test set of queries
- Compare model outputs against expected answers
- Score on accuracy, helpfulness, faithfulness to context
- Flag regressions on prompt or provider changes

---

## 9. Privacy and Compliance

See `docs/security/PRIVACY_GDPR.md` for the full picture. AI-specific points:

| Aspect | Approach |
|---|---|
| Data sent to AI providers | Anonymized via PII masking |
| Provider DPAs | Required for Anthropic, DeepSeek (in progress) |
| Customer consent | Required at org onboarding for AI processing |
| Data retention by providers | Anthropic: 30 days max; DeepSeek: TOS unclear (caution) |
| Training on customer data | Forbidden by contract; anonymized data still avoided |
| Right to deletion | Customer can disable AI per-org; existing logs preserved per retention policy |

---

## 10. Cost Profiles

### 10.1 Typical Per-Message Cost

For an average chat exchange (300 input tokens, 500 output tokens):

| Provider | Cost |
|---|---|
| Claude Sonnet | $0.0084 |
| Claude Haiku | $0.0028 |
| DeepSeek | $0.000182 |
| Ollama | $0 (compute only) |

For a typical month with 10 active users, ~50 messages/user/day, ~22 working days:

- 11,000 messages
- ~$92.40 if all on Claude Sonnet
- ~$30.80 if all on Haiku
- ~$2.00 if all on DeepSeek
- ~$0 on Ollama (CPU compute amortized)

### 10.2 Cost Optimization Strategies

1. **Default to DeepSeek** for cost-sensitive orgs (90% cheaper than Claude)
2. **Cache common answers** (planned: semantic cache layer)
3. **Use Haiku for short tasks** (90% cheaper than Sonnet for simple summarization)
4. **Use Ollama for non-critical tasks** (e.g., title generation, draft summaries)
5. **Batch requests** where possible (e.g., embed many chunks in one API call)

---

## 11. Future Directions

### 11.1 Function Calling / Tool Use

LLMs can call platform functions ("query the inventory", "send a notification"). This unlocks:
- AI-driven workflows
- Data queries via natural language
- Automated actions with user confirmation

Roadmap: introduce a controlled tool registry where admins enable/disable tools per org.

### 11.2 Long-context RAG

Claude supports 200K-token contexts. We can shift from "top-5 chunks" to "all relevant chunks within budget", dramatically improving answer quality on broad questions.

### 11.3 Specialized Models

For specific tasks:
- **Code generation**: route to DeepSeek Coder
- **Vision**: integrate Claude Sonnet vision for image analysis (e.g., scanned documents)
- **Speech**: integrate Whisper (already used for Telegram voice) more broadly

### 11.4 On-premise Models

For high-sensitivity customers:
- **Ollama hosting** of larger models (Llama 3.1 70B, Qwen 2.5)
- **No data leaves customer infrastructure**
- **Performance trade-off** but compliance benefit

### 11.5 Evaluation & Continuous Improvement

- Daily eval runs on a fixed test set
- Comparison across providers, prompt versions
- Regression alerts when quality drops
- Incremental prompt refinement based on user feedback

---

## 12. Conclusion

WorkMind's AI integration is built on three pillars:

1. **Provider abstraction** — never tie the platform to a single vendor
2. **Cost-aware routing** — every call is tracked, budgeted, and fallible to cheaper alternatives
3. **Privacy-by-design** — anonymization is on by default, not bolted on

The result is an AI layer that's **resilient** (fallback chains), **economical** (DeepSeek default with Claude for quality), **private** (no raw PII to external providers), and **observable** (every cent tracked).

This stands in contrast to common patterns where teams hardcode `openai.client.complete()` calls throughout their codebase. By centralizing through ModelRouter, we get changes to providers, pricing models, and even AI strategies as configuration, not refactor.

---

## Appendix A: Glossary

| Term | Definition |
|---|---|
| **LLM** | Large Language Model (e.g., Claude, DeepSeek-Chat, Llama) |
| **Embedding** | Numerical vector representation of text, used for similarity search |
| **RAG** | Retrieval-Augmented Generation — grounding LLM responses in external documents |
| **Token** | Subword unit; English averages ~0.75 words per token |
| **Context window** | Maximum tokens an LLM can process in one request |
| **Hallucination** | LLM producing factually wrong or invented information |
| **Temperature** | Sampling randomness parameter (0=deterministic, 1+=creative) |
| **Cosine similarity** | Measure of vector closeness, range [-1, 1]; higher = more similar |
| **HNSW** | Approximate nearest-neighbor index algorithm for fast vector search |
| **PII** | Personally Identifiable Information |
| **NER** | Named Entity Recognition |
| **DPA** | Data Processing Agreement (GDPR) |

---

**End of Whitepaper**
