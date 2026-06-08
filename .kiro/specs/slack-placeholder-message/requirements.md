# Slack Placeholder Message (Progressive Response)

## Context

The Slack integration's interactive Q&A (Path B) uses a two-Lambda async pattern: the Handler Lambda acks within 3 seconds, then the Worker Lambda calls the DevOps Agent (~18s round-trip) and posts the answer. During this 18-second gap the user sees nothing — they cannot tell whether the bot is working or has silently failed. This spec adds an immediate "Investigating..." placeholder message that is later updated in-place with the real answer.

## User stories

- As a Slack user, I want to see immediate feedback after asking a question, so that I know the bot received my request and is working on it.
- As a Slack user, I want the placeholder to be replaced with the actual answer in the same message, so that the channel stays clean (no extra noise).
- As a Slack user, I want to see a clear error state if the investigation fails, so that I know to retry rather than waiting indefinitely.

## Acceptance criteria

- [ ] Within 3 seconds of sending a question, the user sees a placeholder message (e.g., "Investigating...") in the channel.
- [ ] The placeholder message is posted by the Handler Lambda before it returns 200 to Slack.
- [ ] The Worker Lambda receives the placeholder message's `ts` (timestamp ID) and uses `chat.update` to replace it with the final answer.
- [ ] If the Worker Lambda fails, the placeholder is updated to an error message (not left as "Investigating..." forever).
- [ ] The slash command (`/devops`) also shows the placeholder before the async investigation.
- [ ] No new secrets or permissions are required (the existing `bot_token` already supports `chat.postMessage` and `chat.update`).
- [ ] Existing unit tests are updated; new tests cover the placeholder + update flow.

## Out of scope

- Streaming partial responses to Slack (typing indicator or incremental text updates).
- Threading replies (answer goes in the same channel, same message — not a thread).
- Customizable placeholder text via configuration.
