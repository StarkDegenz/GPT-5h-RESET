# Near-live test: synthetic early reset, real chat delivery

Status: prepared, not armed. No live reset was caused, no new model request was
sent by the test, and the original reminder has not been retimed for this test.
The GitHub-to-existing-chat event binding is still unconfigured.

Read the project scope skill and `EXISTING-CHAT-SETUP.md` first.

## Observed baseline

The read-only account-state snapshot inspected on 2026-10-20 at 09:38:58 CEST
recorded a stable next reset around **13:41:17 CEST (Europe/Paris)**. The existing
reminder was scheduled at 13:46:16 CEST, using the latest stable reading plus
five minutes. Adjacent readings differed by one second. These are a baseline,
not a permanent promise: reread actual quota immediately before arming any test.

An explicitly virtual replay using that observed baseline and an injected early
idle reset passed locally. Its future deadlines and messages are simulated;
they must not be presented as live account readings or delivered notifications.

## Stage A: rescheduling and delivery, with a synthetic reset signal

1. Configure the supported GitHub PR-event trigger in the **original reminder
   conversation**. Verify the retained chat and task identity. This session's
   automation tools do not expose the required event-trigger fields.
2. Use a dedicated test fixture and distinct test/cycle identifier. Store no
   synthetic reading in `quota-test-state/state.json` and no production receipt
   in the fixture. Do not reuse the production one-shot arm or clear its state.
3. Check actual quota read-only. Keep the genuine next-reset deadline visible as
   the baseline throughout the rehearsal.
4. At an agreed ready time T0, inject a test-only early-reset signal. The observer
   must bring the same reminder forward to T0 + five minutes, with normal
   scheduler/queue latency recorded. The signal simulates reset detection; it
   does not reset the account and is not backend evidence.
5. The actual original chat must deliver the first reminder, marked as a TEST.
   Record its task identity, conversation, execution time, and message receipt.
6. Read actual quota again. While the old real window is still active, the second
   message must say the rehearsal delivery succeeded and report the **actual
   observed deadline**. It must explicitly say a new window has not been proven.
   Do not use the simulated five-hour deadline or a dummy "reset confirmed".
7. Confirm both messages appeared separately in that same chat and return the
   reminder to its current real deadline plus five minutes. Avoid a competing
   hourly sync overwriting the temporary test timing; isolate or pause it only
   for the concrete rehearsal and restore its exact saved state afterward.

Stage A proves transport/rescheduling only. A real message inside an already
active quota window cannot establish that it started a fresh five-hour window.

## Stage B: actual window-start verification

- Wait for genuine backend idle state, either natural expiry or an actually
  observed early reset. A fictional timestamp cannot make the account idle.
- Isolate the current runner-side Codex trigger during this controlled test so
  it cannot start the window before the original chat reminder and confound the
  result. Do not disable it until the bridge and a concrete migration are ready.
- Use only the original reminder as the trigger, after the required five-minute
  delay and a fresh check for intervening user activity.
- Read the intended quota bucket after the trigger. Confirm a stable new
  deadline with no concurrent account use; do not infer it from delivery alone.
- Deliver the second confirmation promptly in the same original chat using that
  deadline in Paris time. No hourly handoff and no runner-side fallback send.
- Stop rather than duplicate a request if delivery or quota start is uncertain.

## Required evidence

| Gate | Stage A | Stage B |
| --- | --- | --- |
| Early-reset signal changes same reminder timing | Required, synthetic signal labeled | Required for an actual observed change |
| Two real messages in original chat | Required | Required |
| Actual new five-hour quota window | Not claimed if account was already active | Required |
| No separate runner-side trigger confounding result | Record any activity | Required isolation |
| Duplicate/stale events handled before unintended model inference | Platform semantics must be checked | Required |
| No paid API or additional subscription, unattended cloud execution | Required | Required |

Do not label Stage A as an end-to-end success or start it through an unrelated
new chat. If the original-chat event binding is unavailable, it is a blocker
for the rehearsal, not permission to substitute a different channel.
