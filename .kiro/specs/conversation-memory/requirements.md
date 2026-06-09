# Requirements: Conversation Memory

## Overview
Add multi-turn conversation support to the chatbot so agents retain context across messages within a session.

## Functional Requirements

### FR-1: Conversation Persistence
- Chat history persists across browser refreshes within the same session
- Each agent (langgraph, strands) maintains independent conversation history
- History is stored client-side in localStorage keyed by sessionId

### FR-2: History Passed to Agents
- On each request, the last N turns (configurable, default 10) are included in the payload
- The existing `messages` field in the Invocation model carries the history
- Agents use the history to provide contextual responses

### FR-3: Token Budget Management
- Conversation history is truncated to stay within a configurable token/turn limit
- Older messages are dropped first (sliding window)
- System prompt + tools + history must fit within model context window

### FR-4: Clear/Reset
- User can clear conversation history via the existing "Clear" button
- Clearing removes localStorage entry and resets UI state

## Non-Functional Requirements

### NFR-1: No New Infrastructure
- No DynamoDB table, no Redis, no session microservice
- Client-side storage only (localStorage)

### NFR-2: Demo UX
- Conversations feel natural for live presentations
- No noticeable latency increase from passing history (< 500ms overhead)

### NFR-3: Agent Compatibility
- LangGraph: pass history as graph input messages (native support)
- Strands: inject prior turns as context in the user message or system prompt
