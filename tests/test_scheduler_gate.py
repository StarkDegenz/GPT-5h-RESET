import unittest

from scripts.scheduler_gate import route


class SchedulerGateTests(unittest.TestCase):
    def test_external_disarmed_does_not_access_account(self):
        for armed in ('', 'false'):
            self.assertEqual(route('external', armed), ('observe', False))

    def test_external_observation_can_never_send(self):
        self.assertEqual(route('external', 'false', 'true'), ('observe', True))

    def test_external_resumes_existing_authorization_instead_of_rearming(self):
        for observe in ('', 'false', 'true'):
            self.assertEqual(route('external', 'true', observe), ('continue', True))

    def test_probe_cannot_access_account_even_when_test_is_armed(self):
        self.assertEqual(route('probe', 'true', 'true'), ('probe', False))

    def test_manual_test_and_continue_require_armed_flag(self):
        for mode in ('test', 'continue'):
            self.assertEqual(route(mode, 'false'), (mode, False))
            self.assertEqual(route(mode, 'true'), (mode, True))

    def test_explicit_manual_observation_remains_read_only(self):
        self.assertEqual(route('observe', 'true'), ('observe', True))

    def test_invalid_flags_fail_closed(self):
        for invalid in ('TRUE', 'yes', '1', 'false\ntrue'):
            with self.assertRaises(ValueError):
                route('external', invalid)
            with self.assertRaises(ValueError):
                route('external', 'false', invalid)

    def test_external_tick_cannot_inject_a_new_baseline(self):
        for mode in ('external', 'continue', 'probe', 'observe'):
            with self.assertRaises(ValueError):
                route(mode, 'true', baseline='2026-10-19T19:10:00+02:00')
        self.assertEqual(route('test', 'true', baseline='2026-10-19T19:10:00+02:00'),
                         ('test', True))

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            route('send-now', 'true')


if __name__ == '__main__':
    unittest.main()
