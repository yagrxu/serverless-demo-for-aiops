# Tasks: Conversation Memory

## Task 1: UI — Persist and load chat history
- [ ] 1.1 Load messages from localStorage on component mount (keyed by sessionId + agent)
- [ ] 1.2 Persist messages to localStorage on every state update
- [ ] 1.3 Clear localStorage on "Clear" button click
- [ ] 1.4 Include last 10 turns in request payload as `messages` array

## Task 2: API route — Pass messages through
- [ ] 2.1 Accept `messages` array in `/api/invoke` request body
- [ ] 2.2 Pass to `invokeAgent()` and through to agent-client

## Task 3: Agent client — Include messages in payload
- [ ] 3.1 Add `messages` to `invokeLocal` payload
- [ ] 3.2 Add `messages` to `invokeRuntime` (AgentCore) payload

## Task 4: LangGraph agent — Use native message history
- [ ] 4.1 Read `messages` from Invocation payload
- [ ] 4.2 Append current user message and pass full list to `agent.ainvoke()`
- [ ] 4.3 Verify multi-turn works (e.g., "火锅最近怎么样" → "那烧烤呢？")

## Task 5: Strands agent — Inject history as context
- [ ] 5.1 Read `messages` from Invocation payload
- [ ] 5.2 Format prior turns as context prefix in user_content
- [ ] 5.3 Verify multi-turn works with context injection

## Task 6: Test and verify
- [ ] 6.1 Test: conversation persists across browser refresh
- [ ] 6.2 Test: "Clear" button resets history
- [ ] 6.3 Test: agents correctly reference prior turns
- [ ] 6.4 Test: empty messages array = same behavior as before (backwards compatible)
