# Design: Conversation Memory

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Browser (React state + localStorage)             │
│  - lgMsgs / stMsgs persisted per sessionId       │
│  - On send: include last N turns in payload       │
└─────────────────────┬────────────────────────────┘
                      │ POST /api/invoke
                      │ { message, agent, messages: [...last N turns] }
                      ▼
┌──────────────────────────────────────────────────┐
│  /api/invoke (Next.js route)                      │
│  - Pass messages array to agent-client            │
└─────────────────────┬────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────┐
│  agent-client.ts                                  │
│  - Include messages in AgentCore Runtime payload  │
└─────────────────────┬────────────────────────────┘
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
┌──────────────────┐   ┌──────────────────┐
│  LangGraph Agent │   │  Strands Agent   │
│  Native: pass as │   │  Inject as       │
│  graph messages  │   │  context prefix  │
└──────────────────┘   └──────────────────┘
```

## Component Changes

### 1. Chatbot UI (`ui/chatbot/app/page.tsx`)

- On mount: load messages from `localStorage.getItem(`chat-${sessionId}-lg`)` etc.
- On new message: append to state + persist to localStorage
- On send: include `messages` (last 10 turns) in request payload
- On clear: remove localStorage keys + reset state

Message format for payload:
```json
{
  "messages": [
    {"role": "user", "content": "查看火锅的健康数据"},
    {"role": "assistant", "content": "火锅的健康数据如下..."},
    {"role": "user", "content": "那烧烤呢？"}
  ]
}
```

### 2. API Route (`ui/chatbot/app/api/invoke/route.ts`)

- Accept optional `messages` array from request body
- Pass through to `invokeAgent()`

### 3. Agent Client (`ui/chatbot/lib/agent-client.ts`)

- Add `messages` to the payload sent to AgentCore Runtime
- Both `invokeLocal` and `invokeRuntime` include it

### 4. LangGraph Agent (`agents/langgraph/server.py`)

LangGraph natively supports multi-turn via message list:

```python
# Current (single turn):
result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": user_content}]}
)

# New (multi-turn):
history = payload.messages or []
history.append({"role": "user", "content": user_content})
result = await agent.ainvoke({"messages": history})
```

### 5. Strands Agent (`agents/strands/server.py`)

Strands Agent is single-turn. Inject history as context prefix:

```python
# Build context from history
if messages:
    context_lines = []
    for msg in messages[-10:]:  # last 10 turns
        role = "User" if msg["role"] == "user" else "Assistant"
        context_lines.append(f"{role}: {msg['content']}")
    context = "\n".join(context_lines)
    user_content = f"[Conversation history]\n{context}\n\n[Current message]\n{user_content}"
```

## Token Budget

- Default: last 10 turns (user + assistant = ~20 messages)
- Estimated tokens: ~2000-4000 per 10-turn conversation
- Well within context window for all supported models (haiku: 200K, sonnet: 200K, nova-lite: 128K)
- If needed: add client-side character limit (e.g., total history < 8000 chars)

## localStorage Schema

```
Key: chat-{sessionId}-lg
Value: JSON array of {role, content, ts}

Key: chat-{sessionId}-st
Value: JSON array of {role, content, ts}
```

## No-op Backwards Compatibility

- If `messages` is empty or absent, agents behave exactly as today (single-turn)
- No breaking changes to existing API contract
