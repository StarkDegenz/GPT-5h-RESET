import unittest

from scripts.quota_test import Blocked, Snapshot
from scripts.reminder_flow import ReminderFlow, TRIGGER_TEXT, paris
from scripts.simulate_reminder_flow import BASE, Simulation, run_scenarios


class ReminderFlowTests(unittest.TestCase):
    def queued(self):
        sim = Simulation()
        sim.observe(BASE)
        sim.observe(BASE + 900)
        return sim

    def verified(self):
        sim = self.queued()
        sim.deliver(BASE + 910)
        sim.observe(BASE + 1200)
        return sim

    def test_complete_simulation_and_seeded_restart_stress(self):
        report = run_scenarios()
        self.assertEqual(report['network_requests'], 0)
        self.assertEqual(report['live_account_operations'], 0)
        self.assertEqual(report['live_messages'], 0)
        stress = next(s for s in report['scenarios'] if s.get('seeds'))
        self.assertEqual(stress['event_deliveries'], 4000)
        gap = next(s for s in report['scenarios'] if s.get('known_platform_gap'))
        self.assertEqual(gap['model_turns'], 2)
        self.assertEqual(gap['messages'], [])

    def test_trigger_then_confirmed_backend_time_in_original_chat(self):
        sim = Simulation()
        sim.finish_cycle()
        first, second = sim.chat.messages
        self.assertEqual(first['text'], TRIGGER_TEXT)
        self.assertEqual(first['chat'], 'original-chat')
        self.assertEqual(second['chat'], first['chat'])
        self.assertLess(first['at'], second['at'])
        self.assertIn(paris(sim.quota.reset), second['text'])
        self.assertEqual(sim.store.load()['phase'], 'complete')

    def test_observer_reads_do_not_create_model_turns_or_chat_messages(self):
        sim = Simulation()
        for tick in range(288):
            try:
                sim.observe(BASE + tick * 300)
            except Blocked:
                # A pair straddling expiry is inconclusive; the next tick reads again.
                pass
        self.assertEqual(sim.quota.model_turns, 0)
        self.assertEqual(sim.chat.messages, [])
        self.assertEqual(len(sim.store.load()['events']), 1)

    def test_exact_five_minute_delay_after_expiry(self):
        sim = Simulation()
        sim.observe(BASE)
        sim.observe(BASE + 610)
        self.assertEqual(sim.store.load()['due_at'], BASE + 900)
        sim.observe(BASE + 899)
        self.assertEqual(sim.store.load()['events'], [])
        sim.observe(BASE + 900)
        self.assertEqual(sim.store.load()['phase'], 'waiting_trigger')

    def test_early_reset_after_completed_cycle_waits_from_detection(self):
        sim = Simulation()
        sim.finish_cycle()
        old_reset = sim.quota.reset
        sim.quota.reset = None
        sim.observe(BASE + 1500)
        self.assertLess(BASE + 1500, old_reset)
        self.assertEqual(sim.store.load()['due_at'], BASE + 1800)
        self.assertEqual(len(sim.store.load()['history']), 1)
        sim.observe(BASE + 1800)
        sim.deliver(BASE + 1810)
        sim.observe(BASE + 2100)
        sim.deliver(BASE + 2101)
        self.assertEqual(len(sim.chat.messages), 4)
        self.assertEqual(sim.store.load()['phase'], 'complete')

    def test_changed_active_deadline_prevents_old_due_time(self):
        sim = Simulation()
        sim.observe(BASE)
        sim.quota.reset = BASE + 3600
        sim.observe(BASE + 300)
        sim.observe(BASE + 900)
        self.assertFalse(sim.store.load()['events'])
        self.assertEqual(sim.store.load()['expected_reset'], BASE + 3600)

    def test_user_activity_cancels_queued_event_even_before_next_observer_tick(self):
        sim = self.queued()
        sim.quota.model_turn(BASE + 905)
        self.assertEqual(sim.deliver(BASE + 920), 'cancelled_new_activity')
        self.assertEqual(sim.chat.messages, [])
        sim.deliver(BASE + 930, 'cycle-1:trigger')
        self.assertEqual(sim.quota.model_turns, 1)  # Only the simulated user turn.

    def test_restart_does_not_duplicate_trigger(self):
        sim = self.queued()
        sim.deliver(BASE + 910)
        sim.restart()
        sim.deliver(BASE + 920, 'cycle-1:trigger')
        self.assertEqual(len(sim.chat.messages), 1)
        self.assertEqual(sim.quota.model_turns, 1)

    def test_restart_does_not_duplicate_confirmation(self):
        sim = self.verified()
        sim.deliver(BASE + 1201)
        sim.restart()
        sim.deliver(BASE + 1210, 'cycle-1:confirmation')
        self.assertEqual(len(sim.chat.messages), 2)

    def test_wrong_chat_is_rejected_before_delivery(self):
        sim = self.queued()
        with self.assertRaises(Blocked):
            sim.deliver(BASE + 910, destination='new-agent-chat')
        self.assertEqual(sim.chat.messages, [])

    def test_wrong_task_is_rejected_before_delivery(self):
        sim = self.queued()
        with self.assertRaises(Blocked):
            sim.deliver(BASE + 910, task='replacement-reminder')
        self.assertEqual(sim.chat.messages, [])

    def test_account_change_prevents_delivery(self):
        sim = self.queued()
        sim.quota.account = 'different-account'
        with self.assertRaises(Blocked):
            sim.deliver(BASE + 910)
        self.assertEqual(sim.chat.messages, [])

    def test_binding_change_on_restart_rejected(self):
        sim = self.queued()
        with self.assertRaises(Blocked):
            ReminderFlow(sim.store, sim.quota.account, 'different-chat', 'original-reminder')

    def test_stale_or_future_samples_do_not_authorize_delivery(self):
        for samples_at in (BASE, BASE + 1000):
            sim = self.queued()
            with self.assertRaises(Blocked):
                sim.flow.deliver('cycle-1:trigger', *sim.quota.pair(samples_at),
                                 BASE + 910, 'original-chat', 'original-reminder', sim.chat)
            self.assertEqual(sim.chat.messages, [])

    def test_out_of_order_observation_cannot_rewind_state(self):
        sim = self.queued()
        before = sim.store.load()
        with self.assertRaises(Blocked):
            sim.observe(BASE + 300)
        self.assertEqual(sim.store.load(), before)

    def test_ambiguous_quota_cannot_authorize_trigger(self):
        sim = self.queued()
        a, b = sim.quota.pair(BASE + 910)
        with self.assertRaises(Blocked):
            sim.flow.deliver('cycle-1:trigger',
                             Snapshot(a.at, a.reset - 1000, True, a.account), b,
                             BASE + 910, 'original-chat', 'original-reminder', sim.chat)
        self.assertEqual(sim.chat.messages, [])

    def test_disallowed_usage_prevents_model_turn(self):
        sim = self.queued()
        sim.quota.allowed = False
        self.assertEqual(sim.deliver(BASE + 910), 'usage_blocked')
        self.assertEqual(sim.quota.model_turns, 0)

    def test_confirmation_cannot_arrive_before_verified_quota(self):
        sim = self.queued()
        with self.assertRaises(Blocked):
            sim.deliver(BASE + 910, 'cycle-1:confirmation')
        self.assertEqual(sim.chat.messages, [])

    def test_expired_event_blocks_without_a_late_trigger(self):
        sim = self.queued()
        self.assertEqual(sim.deliver(BASE + 2000), 'expired')
        self.assertEqual(sim.quota.model_turns, 0)
        self.assertEqual(sim.store.load()['phase'], 'blocked')

    def test_delayed_observer_waits_for_actual_backend_update(self):
        sim = self.queued()
        sim.quota.visibility_lag = 600
        sim.deliver(BASE + 910)
        sim.observe(BASE + 1200)
        self.assertEqual(sim.store.load()['phase'], 'waiting_verification')
        sim.observe(BASE + 1800)
        self.assertEqual(sim.store.load()['phase'], 'confirmation_ready')
        sim.deliver(BASE + 1801)
        self.assertEqual(sim.store.load()['phase'], 'complete')

    def test_failed_persistence_before_claim_prevents_chat_effect(self):
        sim = self.queued()
        sim.store.fail_phase = 'trigger_claimed'
        with self.assertRaises(OSError):
            sim.deliver(BASE + 910)
        self.assertEqual(sim.chat.messages, [])
        self.assertEqual(sim.quota.model_turns, 0)

    def test_crash_after_trigger_before_receipt_save_never_resends(self):
        sim = self.queued()
        sim.store.fail_phase = 'waiting_verification'
        with self.assertRaises(OSError):
            sim.deliver(BASE + 910)
        self.assertEqual(len(sim.chat.messages), 1)
        sim.store.fail_phase = None
        sim.restart()
        sim.observe(BASE + 1200)
        sim.deliver(BASE + 1210, 'cycle-1:trigger')
        self.assertEqual(len(sim.chat.messages), 1)
        self.assertEqual(sim.store.load()['failure'], 'trigger_outcome_unknown')

    def test_crash_after_confirmation_never_resends(self):
        sim = self.verified()
        sim.store.fail_phase = 'complete'
        with self.assertRaises(OSError):
            sim.deliver(BASE + 1201)
        sim.store.fail_phase = None
        sim.restart()
        sim.observe(BASE + 1500)
        sim.deliver(BASE + 1510, 'cycle-1:confirmation')
        self.assertEqual(len(sim.chat.messages), 2)
        self.assertEqual(sim.store.load()['failure'], 'confirmation_outcome_unknown')

    def test_changed_deadline_before_confirmation_does_not_publish_stale_time(self):
        sim = self.verified()
        sim.quota.reset += 3600
        sim.deliver(BASE + 1210)
        self.assertEqual(len(sim.chat.messages), 1)
        self.assertEqual(sim.store.load()['failure'], 'deadline_changed_before_confirmation')

    def test_dropped_ticks_do_not_use_fictional_five_hours_from_current_time(self):
        sim = Simulation()
        sim.observe(BASE)
        sim.observe(BASE + 1800)
        self.assertEqual(sim.store.load()['due_at'], BASE + 900)
        sim.deliver(BASE + 1810)
        sim.observe(BASE + 2100)
        sim.deliver(BASE + 2101)
        self.assertIn(paris(BASE + 1810 + 18000), sim.chat.messages[-1]['text'])

    def test_blocked_cycle_is_not_rearmed_by_later_idle_reads(self):
        sim = self.queued()
        sim.chat.failure = 'before_send'
        sim.deliver(BASE + 910)
        sim.chat.failure = None
        for at in (BASE + 1200, BASE + 10000, BASE + 20000):
            sim.observe(at)
        self.assertEqual(sim.store.load()['phase'], 'blocked')
        self.assertEqual(sim.chat.messages, [])

    def test_paris_dst_is_not_a_fixed_utc_offset(self):
        from datetime import datetime, timezone
        winter = int(datetime(2026, 12, 1, 10, tzinfo=timezone.utc).timestamp())
        self.assertIn('11:00:00 CET', paris(winter))
        self.assertIn('10:00:00 CEST', paris(BASE))

    def test_expiry_transition_pair_is_ambiguous_and_never_triggers(self):
        sim = Simulation()
        sim.observe(BASE)
        with self.assertRaises(Blocked):
            sim.observe(BASE + 600)
        self.assertEqual(sim.chat.messages, [])
        sim.observe(BASE + 900)
        self.assertEqual(sim.store.load()['phase'], 'waiting_trigger')

    def test_clock_rollback_cannot_deliver_confirmation_before_verification(self):
        sim = self.verified()
        with self.assertRaises(Blocked):
            sim.deliver(BASE + 1100)
        self.assertEqual(len(sim.chat.messages), 1)

    def test_old_first_sample_cannot_be_paired_with_new_second_sample(self):
        sim = self.queued()
        first, second = sim.quota.pair(BASE + 910)
        first = Snapshot(BASE - 1000, first.reset, first.allowed, first.account)
        with self.assertRaises(Blocked):
            sim.flow.deliver('cycle-1:trigger', first, second, BASE + 910,
                             'original-chat', 'original-reminder', sim.chat)
        self.assertEqual(sim.quota.model_turns, 0)

    def test_missing_event_delivery_is_not_silently_rearmed(self):
        sim = self.queued()
        sim.observe(BASE + 2100)
        self.assertEqual(sim.store.load()['phase'], 'blocked')
        self.assertEqual(sim.store.load()['failure'], 'event_expired')
        sim.observe(BASE + 3000)
        self.assertEqual(len(sim.store.load()['events']), 1)
        self.assertEqual(sim.chat.messages, [])

    def test_concurrent_handlers_cannot_both_claim_the_same_trigger(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from unittest.mock import patch
        sim = self.queued()
        barrier = threading.Barrier(2)
        load = sim.store.load

        def racing_load():
            snapshot = load()
            barrier.wait(timeout=5)
            return snapshot

        def deliver():
            try:
                return sim.deliver(BASE + 910, 'cycle-1:trigger')
            except Blocked:
                return 'lost_atomic_claim'

        with patch.object(sim.store, 'load', side_effect=racing_load):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: deliver(), range(2)))
        self.assertEqual(len(sim.chat.messages), 1)
        self.assertEqual(sim.quota.model_turns, 1)
        self.assertIn('lost_atomic_claim', results)
        self.assertIn('waiting_verification', results)


if __name__ == '__main__':
    unittest.main()
