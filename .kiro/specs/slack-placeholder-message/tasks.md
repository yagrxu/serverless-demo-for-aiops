# Tasks: Slack Placeholder Message

- [ ] T1 — Add `post_placeholder` function to Handler Lambda that calls `chat.postMessage` and returns the message `ts` (depends on: —)
- [ ] T2 — Modify Handler's `dispatch_worker` to include `message_ts` in the Worker invocation payload (depends on: T1)
- [ ] T3 — Call `post_placeholder` in Handler for both `app_mention` and slash command paths before dispatching (depends on: T1)
- [ ] T4 — Add `update_slack_message` function to Worker Lambda that calls `chat.update` with channel + ts + text (depends on: —)
- [ ] T5 — Modify Worker's `post_to_slack` to use `chat.update` when `message_ts` is present, fall back to `chat.postMessage` when absent (depends on: T4)
- [ ] T6 — Update Worker's error handling path to call `chat.update` (replace placeholder with error) instead of posting a new message (depends on: T4)
- [ ] T7 — Update Handler unit tests: verify `chat.postMessage` is called before worker dispatch, verify `message_ts` passed in payload (depends on: T3)
- [ ] T8 — Update Worker unit tests: verify `chat.update` called with correct ts, verify fallback to `chat.postMessage` when `message_ts` is None (depends on: T5, T6)
- [ ] T9 — Run live integration test: send app_mention, confirm placeholder appears then gets replaced (depends on: T1–T8)
