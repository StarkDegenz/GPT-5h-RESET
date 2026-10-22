# Proposed setup: existing chat with a GitHub event bridge

Status: documented candidate, not activated or proven end to end. Read
`../.agents/skills/gpt-reset-scope/SKILL.md` first. This proposal does not relax
the existing-chat requirement or treat the runner's Codex request as equivalent.

## Components

1. The existing free external scheduler invokes the public repository's standard
   GitHub Actions runner every five minutes. If the current scheduler is not
   free, cron-job.org documents a free HTTP scheduler with custom POST bodies.
2. The Python observer reads account quota through the dedicated Codex login.
   In the proposed mode, it does not call `codex exec` to start a window.
3. One dedicated draft pull request serves as an event transport. It is not a
   code change to merge and is not the user's notification destination. The
   script publishes typed comments only when action is needed, not every tick.
4. A GitHub event-triggered Work task belongs to the original reminder chat.
   Its first response is the actual reminder. Its later response is the quota
   confirmation. No separate Workspace Agent, Telegram bot, or paid API is used.

The same task/chat identity must be demonstrated. Documentation describing
event tasks in general is not proof that the current reminder can be converted
or that the account supports the required conversation destination.

## Flow

- While the quota is active, follow the latest observed deadline. Do not wake
  the chat or issue a model request just to poll.
- Once idle is established, wait at least five minutes from the real expiry,
  or from detection of an early reset when the former deadline is obsolete.
- Recheck quota immediately before publishing a `reminder_due` event. Persist
  the cycle identifier and pending intent first. Never publish two triggering
  events for an uncertain cycle.
- The event task fetches the current controller state and validates the event,
  author, cycle, account fingerprint, and freshness. It must refuse expired or
  already-handled trigger events. It sends the existing reminder phrase in the
  original chat. That chat turn, not a runner-side model call, must be shown to
  start the intended account quota bucket.
- The observer detects a stable new five-hour deadline on subsequent readings.
  It records the verified receipt and publishes `reset_confirmed` for the same
  cycle, containing the backend deadline. A five-minute observer gives this
  stage up to the next tick plus runner/read latency; it is not instantaneous.
- The event task posts the second message in the original chat, with date,
  time, and Europe/Paris CET/CEST. It must not trigger another model operation
  merely to start another window or claim success from an event acceptance.
- A changed deadline changes when the observer will publish the next due event.
  The reminder therefore runs from observed eligibility rather than an obsolete
  five-hour repeating calendar. This event-based execution must be acceptable
  as adapting the existing reminder; if the original task cannot be retained,
  the proposal has not met the contract.

Do not wake ChatGPT on every detected active-window change if the only action
is updating the observer's due time: that would create unnecessary AI turns.
The live state already records the new deadline, so the next trigger follows it.

## One-time configuration needed

On ChatGPT web, in the original reminder conversation, inspect whether its task
can use a GitHub pull-request-comment event and preserve the same conversation.
Scope the subscription to this repository and the single control PR, and to
the intended automation actor once verified. Do not subscribe to all PRs.

The automation tools exposed in the research session have time-based schedule
arguments but no webhook discovery tool, event-filter argument, or destination
rebinding argument. Do not invent those fields or try undocumented session APIs.
This is a concrete configuration blocker, not a reason to replace events with
hourly polling.

The future GitHub workflow would need permission to post comments on the control
PR using its repository-scoped Actions token. It must not send account login
credentials, raw account responses, or private conversation contents to the PR.
Use sanitized event metadata and event IDs. Public PR comments are transport,
not a place for credentials.

## Acceptance gates

| Requirement | Mechanism | Evidence/status |
| --- | --- | --- |
| Existing-chat trigger | Event task retained in original chat | Blocked pending destination/configuration test |
| Five-minute quota reads without model calls | Existing observer and external scheduler | Existing capability demonstrated |
| Prompt adaptation after changed reset | Observer recalculates eligibility before due event | Control logic exists; event mode still to implement/test |
| Two separate messages in same chat | Due event followed by backend-confirmed event | Untested; provider can group nearby events |
| Correct quota verification | Stable backend readings after chat trigger | Runner-side verification demonstrated; chat-trigger causality unverified |
| Unattended cloud operation | External scheduler, standard Actions runner, cloud event task | Component capabilities documented; full chain untested |
| No extra recurring fees | Free scheduler/public standard runner/existing Plus entitlement | Documented conditions; confirm account's event feature access |
| Minimal, duplicate-resistant system | One observer, one event task, one control PR, durable cycle/outbox | Design only; event retries and task deduplication need tests |

Do not enable the new flow on top of the current runner-side trigger. During a
controlled migration, prevent the runner and the chat from both starting the
same window. Do not disable the current flow until the event route is configured
and a concrete migration/test is ready. Verify a genuinely idle window without
concurrent account use, confirm the original chat's first message, read the new
quota deadline, and see the separate second response. Also test early resets,
stale/duplicate events, a missed tick, a task delay, and notification uncertainty.

If the platform batches the two events, rebinds to a new chat, requires an extra
paid feature, or the reminder does not start the intended bucket, record that
failure. Do not call the setup complete or substitute another message channel.

## Official references

- Connected app events delivered to authorized conversations:
  https://help.openai.com/en/articles/11487775-connected-apps-in-chatgpt
- Supported GitHub PR comments/commit events and event grouping:
  https://learn.chatgpt.com/docs/automations
- Eligible plans, cloud event tasks, and hourly polling limit:
  https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt
- Work/Codex usage is distinct from ordinary Chat defaults; validate the bucket:
  https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex
- Free standard Actions runners for public repositories:
  https://docs.github.com/en/billing/concepts/product-billing/github-actions
- Free HTTP scheduler and custom requests:
  https://cron-job.org/en/

Sources were reviewed on 2026-10-20. They document component capabilities, not
successful operation of this user's complete proposed chain.
