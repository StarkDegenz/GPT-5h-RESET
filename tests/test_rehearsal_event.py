import unittest

from scripts.rehearsal_event import payload


class RehearsalEventTests(unittest.TestCase):
    def state(self):
        return {'status': 'complete', 'observations': [
            {'first_at': 99992, 'second_at': 100000,
             'first_reset': 110000, 'second_reset': 110000, 'allowed': True}]}

    def test_probe_has_no_synthetic_or_verified_reset_claim(self):
        event = payload(self.state(), 100010, 'binding_probe', '123')
        self.assertTrue(event['test_only'])
        self.assertFalse(event['new_window_proven'])
        self.assertEqual(event['actual_observed_reset'], 110000)
        self.assertNotIn('test_reminder_due_at', event)

    def test_synthetic_deadline_is_separate_from_actual_quota(self):
        state = self.state()
        event = payload(state, 100010, 'synthetic_early_reset', '123')
        self.assertEqual(event['test_reminder_due_at'], 100310)
        self.assertEqual(event['actual_observed_reset'], 110000)
        self.assertEqual(state['observations'][-1]['second_reset'], 110000)

    def test_observed_quota_event_never_claims_new_window(self):
        self.assertFalse(payload(self.state(), 100010, 'actual_quota_observed', '123')
                         ['new_window_proven'])

    def test_stale_and_future_samples_rejected(self):
        for now in (99999, 101201):
            with self.assertRaises(ValueError):
                payload(self.state(), now, 'binding_probe', '123')

    def test_expiring_or_idle_real_window_rejected(self):
        for reset in (100000, 100500):
            state = self.state()
            state['observations'][-1].update(first_reset=reset, second_reset=reset)
            with self.assertRaises(ValueError):
                payload(state, 100010, 'binding_probe', '123')

    def test_uncertain_request_rejected(self):
        for status in ('pending', 'unverified'):
            state = self.state()
            state['status'] = status
            with self.assertRaises(ValueError):
                payload(state, 100010, 'binding_probe', '123')

    def test_ambiguous_quota_and_disallowed_usage_rejected(self):
        for change in ({'first_reset': 109000}, {'allowed': False}):
            state = self.state()
            state['observations'][-1].update(change)
            with self.assertRaises(ValueError):
                payload(state, 100010, 'binding_probe', '123')

    def test_bad_kind_and_malformed_data_rejected(self):
        with self.assertRaises(ValueError):
            payload(self.state(), 100010, 'reset_confirmed', '123')
        state = self.state()
        state['observations'][-1]['first_reset'] = True
        with self.assertRaises(ValueError):
            payload(state, 100010, 'binding_probe', '123')
