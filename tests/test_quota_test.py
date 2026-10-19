import tempfile
import sys
import unittest

from scripts.quota_test import AppServer, Blocked, Snapshot, classify, decide, parse_baseline, run


def pair(kind, at=100000, reset=None, allowed=True, account='account-hash'):
    if kind == 'idle':
        return (Snapshot(at - 8, int(at - 8 + 18000), allowed, account),
                Snapshot(at, int(at + 18000), allowed, account))
    deadline = reset if reset is not None else int(at + 1000)
    return (Snapshot(at - 8, deadline, allowed, account), Snapshot(at, deadline, allowed, account))


class Store:
    def __init__(self, state=None):
        self.state = dict(state or {})
        self.saves = []

    def load(self):
        return dict(self.state)

    def save(self, state):
        self.state = dict(state)
        self.saves.append(dict(state))


class FakeCodex:
    def __init__(self, observations, store=None, cli_ok=True):
        self.observations = iter(observations)
        self.sends = 0
        self.store = store
        self.cli_ok = cli_ok

    def pair(self):
        return next(self.observations)

    def warm(self):
        if self.store:
            assert self.store.state['status'] == 'pending'
        self.sends += 1
        return self.cli_ok


class QuotaTests(unittest.TestCase):
    def test_fictional_19h_is_replaced_by_observed_2118(self):
        fake = parse_baseline('2026-10-19T19:00:00+02:00')
        actual = parse_baseline('2026-10-19T21:18:00+02:00')
        a, b = pair('active', at=actual - 10000, reset=actual)
        state, action = decide({'expected_reset': fake}, a, b)
        self.assertEqual(action, 'active')
        self.assertEqual(state['expected_reset'], actual)
        self.assertEqual((state['resync_from'], state['resync_to']), (fake, actual))

    def test_naive_baseline_rejected(self):
        with self.assertRaises(Blocked):
            parse_baseline('2026-10-19T19:00:00')

    def test_new_active_window_is_not_mistaken_for_idle(self):
        self.assertEqual(classify(*pair('active', reset=117940)), 'active')

    def test_natural_expiration_waits_five_minutes(self):
        state = {'expected_reset': 99750}
        state, action = decide(state, *pair('idle'))
        self.assertEqual(action, 'waiting_five_minutes')
        self.assertEqual(state['idle_since'], 99750)
        _, action = decide(state, *pair('idle', at=100050))
        self.assertEqual(action, 'due')

    def test_expired_deadline_is_not_called_active(self):
        self.assertEqual(classify(*pair('active', reset=99000)), 'idle')

    def test_early_reset_waits_from_detection(self):
        state = {'expected_reset': 110000, 'last_send': 99400}
        state, action = decide(state, *pair('idle'))
        self.assertEqual(action, 'waiting_five_minutes')
        self.assertEqual(state['idle_since'], 100000)
        _, action = decide(state, *pair('idle', at=100300))
        self.assertEqual(action, 'due')

    def test_fictional_expired_baseline_is_not_a_real_expiration(self):
        state, action = decide({'expected_reset': 90000, 'fictional_baseline': 90000}, *pair('idle'))
        self.assertEqual(action, 'waiting_five_minutes')
        self.assertEqual(state['idle_since'], 100000)

    def test_returning_user_cancels_idle_timer(self):
        state, action = decide({'idle_since': 99000}, *pair('active'))
        self.assertEqual(action, 'active')
        self.assertNotIn('idle_since', state)

    def test_ambiguous_transition_fails_closed(self):
        a, _ = pair('active')
        with self.assertRaises(Blocked):
            classify(a, Snapshot(100000, 102000, True, a.account))

    def test_included_usage_blocked_never_sends(self):
        _, action = decide({}, *pair('idle', allowed=False))
        self.assertEqual(action, 'usage_blocked')

    def test_unknown_permission_and_wrong_bucket_rejected(self):
        response = {'accountId': 'x', 'ordinaryUsageAllowed': None,
                    'rateLimitsByLimitId': {'codex': {'planType': 'plus',
                        'primary': {'windowDurationMins': 300, 'resetsAt': 118000}}}}
        with self.assertRaises(Blocked):
            Snapshot.from_response(response, 100000, 'x')
        response['ordinaryUsageAllowed'] = True
        response['rateLimitsByLimitId'] = {'another_model': {}}
        with self.assertRaises(Blocked):
            Snapshot.from_response(response, 100000, 'x')

    def test_percentage_does_not_decide_whether_active(self):
        response = {'accountId': 'x', 'ordinaryUsageAllowed': True,
                    'rateLimitsByLimitId': {'codex': {'planType': 'plus',
                        'primary': {'windowDurationMins': 300, 'resetsAt': 117940,
                                    'usedPercent': 0}}}}
        a = Snapshot.from_response(response, 99992, 'x')
        b = Snapshot.from_response(response, 100000, 'x')
        self.assertEqual(classify(a, b), 'active')

    def test_wrong_account_rejected(self):
        with self.assertRaises(Blocked):
            decide({'account': 'another-account'}, *pair('active'))

    def test_observe_never_sends_even_if_due_and_armed(self):
        store = Store({'expected_reset': 99000, 'armed_at': 90000, 'test_expires': 180000})
        codex = FakeCodex([pair('idle')])
        self.assertEqual(run(store, codex, 'observe', armed=True), 'due')
        self.assertEqual(codex.sends, 0)

    def test_both_activation_gates_required(self):
        for armed, state in ((False, {'armed_at': 90000}), (True, {})):
            store = Store({'expected_reset': 99000, **state})
            codex = FakeCodex([pair('idle')])
            self.assertEqual(run(store, codex, 'continue', armed=armed), 'disabled')
            self.assertEqual(codex.sends, 0)

    def test_user_activity_immediately_before_send_cancels(self):
        store = Store({'expected_reset': 99000, 'armed_at': 90000, 'test_expires': 180000})
        codex = FakeCodex([pair('idle'), pair('active', at=100008)], store)
        self.assertEqual(run(store, codex, 'continue', armed=True), 'active')
        self.assertEqual(codex.sends, 0)

    def test_real_send_requires_and_records_a_stable_new_deadline(self):
        store = Store({'expected_reset': 99000, 'armed_at': 90000, 'test_expires': 180000})
        codex = FakeCodex([pair('idle'), pair('idle', at=100008),
                           pair('active', at=100030, reset=118008)], store)
        self.assertEqual(run(store, codex, 'continue', armed=True, sleep=lambda _: None), 'complete')
        self.assertEqual(codex.sends, 1)
        self.assertEqual(store.state['verified_reset'], 118008)

    def test_cli_failure_after_metering_never_triggers_a_retry(self):
        store = Store({'expected_reset': 99000, 'armed_at': 90000, 'test_expires': 180000})
        codex = FakeCodex([pair('idle'), pair('idle', at=100008),
                           pair('active', at=100030, reset=118008)], store, cli_ok=False)
        self.assertEqual(run(store, codex, 'continue', armed=True, sleep=lambda _: None), 'complete')
        self.assertFalse(store.state['cli_ok'])
        self.assertEqual(codex.sends, 1)

    def test_meter_does_not_change_blocks_future_attempts(self):
        store = Store({'expected_reset': 99000, 'armed_at': 90000, 'test_expires': 180000})
        codex = FakeCodex([pair('idle'), pair('idle', at=100008), pair('idle', at=100030)], store)
        with self.assertRaises(Blocked):
            run(store, codex, 'continue', armed=True, sleep=lambda _: None)
        self.assertEqual(store.state['status'], 'unverified')
        next_codex = FakeCodex([pair('idle', at=100400)])
        self.assertEqual(run(store, next_codex, 'continue', armed=True), 'unverified')
        self.assertEqual(next_codex.sends, 0)

    def test_restart_after_uncertain_attempt_never_repeats(self):
        for status in ('pending', 'unverified', 'complete'):
            store = Store({'status': status})
            codex = FakeCodex([pair('idle')])
            self.assertEqual(run(store, codex, 'continue', armed=True), status)
            self.assertEqual(codex.sends, 0)

    def test_failed_durable_intent_prevents_send(self):
        class FailingStore(Store):
            def save(self, state):
                if state.get('status') == 'pending':
                    raise Blocked('State write failed')
                super().save(state)
        store = FailingStore({'expected_reset': 99000, 'armed_at': 90000, 'test_expires': 180000})
        codex = FakeCodex([pair('idle'), pair('idle', at=100008)], store)
        with self.assertRaises(Blocked):
            run(store, codex, 'continue', armed=True)
        self.assertEqual(codex.sends, 0)

    def test_expired_test_does_not_send(self):
        store = Store({'expected_reset': 99000, 'armed_at': 1, 'test_expires': 86401})
        codex = FakeCodex([pair('idle')])
        with self.assertRaises(Blocked):
            run(store, codex, 'continue', armed=True)
        self.assertEqual(codex.sends, 0)

    def test_arming_records_fictional_baseline_but_does_not_force_send(self):
        store = Store()
        codex = FakeCodex([pair('active')])
        self.assertEqual(run(store, codex, 'test', baseline=99000, armed=False), 'active')
        self.assertEqual(store.state['fictional_baseline'], 99000)
        self.assertEqual(store.state['expected_reset'], 101000)
        self.assertEqual(codex.sends, 0)

    def test_app_server_protocol_handles_notifications(self):
        fake = '''import json, sys
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 print(json.dumps({'method':'notification', 'params':{}}), flush=True)
 print(json.dumps({'id':m['id'], 'result':{'method':m['method']}}), flush=True)
'''
        with tempfile.TemporaryDirectory() as directory:
            app = AppServer([sys.executable, '-u', '-c', fake], {}, directory, timeout=2)
            try:
                self.assertEqual(app.request('initialize', {}), {'method': 'initialize'})
                app.send({'method': 'initialized', 'params': {}})
                self.assertEqual(app.request('account/rateLimits/read', {}),
                                 {'method': 'account/rateLimits/read'})
            finally:
                app.close()


if __name__ == '__main__':
    unittest.main()
