---
name: gpt-reset-scope
description: Preserve and validate the agreed scope for this repository's five-hour GPT/Codex reset reminder. Apply when researching tools, designing integrations, modifying the controller or reminders, or reporting success.
---

# Agreed user outcome

Maintain a self-running system that starts the intended five-hour usage window
through the user's existing GPT/Codex chat reminder, adjusts that reminder when
the actual reset deadline changes, and confirms the next reset in the same chat.

## Mandatory requirements

1. **Existing chat reminder is the trigger.** Preserve the reminder in the
   user's existing GPT/Codex chat. Its message must initiate the intended
   usage-window start a few minutes after the actual reset. The current intended
   delay is five minutes. A separate runner-side Codex call or an external
   notification is not an established equivalent or a replacement.
2. **Read actual quota every five minutes.** The observer reads account quota
   data, without creating an AI/model turn on every check. A quota read and a
   model request are distinct operations.
3. **Adapt the same reminder promptly.** A changed deadline, including an early
   reset, must cause the existing reminder's next execution time to change
   automatically. An hourly handoff does not meet this requirement. Do not keep
   waiting for an obsolete deadline or assume a fixed repeating five-hour cron
   remains correct. For an early idle reset without a new stable deadline, time
   the delay from detection rather than inventing a future reset.
4. **Two messages in the same existing chat.** First comes the trigger/reminder
   message (retain the user's phrase, "Sup lazy human it's time to print").
   Once the script verifies the new window, that same chat sends a separate
   confirmation containing the next reset's date, time, and Europe/Paris zone
   (CET/CEST as appropriate). It must not wait for hourly polling.
5. **Evidence-based confirmation.** Read the actual backend quota to confirm a
   new stable reset deadline. Do not use an estimated "now + five hours", a GPT
   text reply, an HTTP dispatch acceptance, or a successful CLI exit alone as
   proof. Verify that the chat-triggered action affects the intended quota
   bucket; runner-side success does not establish this.
6. **Standalone cloud operation.** After initial setup, it must run unattended
   with the user's computer off. A local daemon, an always-open desktop app, or
   manual re-arming/rescheduling is not a complete solution.
7. **No extra recurring fees.** Use no additional paid subscription, paid model
   API, server rental, expiring trial, or unexamined billable service. The user's
   existing ChatGPT subscription is already part of the setup. Check current
   free-tier eligibility and usage limits; do not promise a service is free
   without checking the actual proposed usage.
8. **Minimal, robust design.** Minimize services, credentials, model turns, and
   independent schedules. Preserve durable state, account checks, and protection
   against duplicate model requests. Retrying notification delivery must not
   retry an uncertain model request.

## Research and proposal method

- Evaluate what tools and APIs permit, not only their advertised or customary
  use. Creative combinations are welcome when their capabilities are supported.
- Treat implementation choices as open. No particular bot, agent, provider,
  scheduler, or notification app is mandatory.
- For each serious candidate, map every requirement above to a concrete
  mechanism. Mark each one demonstrated, documented-but-untested, or blocked.
- Distinguish the account-quota observer, window-starting action, reminder
  scheduler, and chat-delivery path. Name which component owns each operation.
- A GitHub issue, Telegram/Discord message, email, or new Workspace Agent chat
  may help with transport or testing, but it does not replace the required
  existing-chat trigger and messages. Do not present a partial alternative as
  satisfying the whole scope.
- Do not assume an API can attach to an existing chat, that a scheduled task can
  be woken by an arbitrary webhook, or that two events produce two separate
  chat messages. Check the available schema and prove the relevant behavior.
- Check event grouping, disabled tasks, missed ticks, changed deadlines, and
  uncertain delivery outcomes where they affect these requirements. State real
  timing limits rather than promising exact delivery on best-effort services.
- Do not attribute an observed early reset to a person or a global action
  without evidence; reacting to the observed account state is sufficient.
- When a required capability is unavailable, identify the precise missing
  connection or API and finish independent authorized work. Do not repeatedly
  seek approval for unchanged scope or claim the blocked result is operational.

## Evidence required before claiming completion

Observe the chat's trigger action, confirm the intended quota bucket starts a
new window, and see the second message with the backend-confirmed deadline in
that same chat. Demonstrate that a changed deadline updates the reminder before
its obsolete scheduled execution, and that restarts or notification retries do
not duplicate the quota-starting request. Confirm cloud operation and the free
usage envelope. Report untested or blocked items explicitly.

## Existing implementation is not the finished specification

At the time this contract was saved, the repository had a five-minute external
scheduler and runner-side Codex controller, a separate hourly ChatGPT sync, and
a disabled optional Workspace Agent delivery adapter. Those are intermediate
implementations. The hourly sync, separate Codex trigger, and a new agent chat
do not by themselves satisfy the agreed outcome above.

Do not change running reminders or controller behavior merely while saving or
reading this scope. Make implementation changes only within the user's active
request. Update this contract when the user explicitly changes the scope.
