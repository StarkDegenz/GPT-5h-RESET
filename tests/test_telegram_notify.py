import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from telegram_notify import plan, telegram_api, send, TelegramError
from configure_telegram import paired_chat


class NotificationTests(unittest.TestCase):
    def test_healthy_is_quiet(self):
        messages, state = plan({}, 10, 'success', {})
        self.assertEqual(messages, [])
        self.assertFalse(state['incident'])

    def test_failure_deduplicates_and_recovers(self):
        messages, state = plan({}, 10, 'failure', {})
        self.assertEqual(len(messages), 1)
        self.assertEqual(plan(state, 11, 'failure', {})[0], [])
        messages, state = plan(state, 12, 'success', {})
        self.assertEqual(len(messages), 1)
        self.assertFalse(state['incident'])
        self.assertEqual(plan(state, 11, 'failure', {})[0], [])

    def test_result_once_per_attempt_and_status(self):
        for status in ('complete', 'unverified', 'pending'):
            with self.subTest(status=status):
                experiment = {'status': status, 'attempt_id': '30',
                              'raw_error': 'DO NOT TRANSMIT'}
                messages, state = plan({}, 31, 'success', experiment)
                self.assertEqual(len(messages), 1)
                self.assertNotIn('DO NOT TRANSMIT', str(messages) + str(state))
                self.assertEqual(plan(state, 32, 'success', experiment)[0], [])

    def test_pending_can_progress_to_complete(self):
        _, state = plan({}, 40, 'failure', {'status': 'pending', 'attempt_id': '40'})
        messages, _ = plan(state, 41, 'success', {'status': 'complete', 'attempt_id': '40'})
        self.assertEqual(len(messages), 2)

    def test_network_exception_hides_token_and_response(self):
        with patch('urllib.request.urlopen', side_effect=OSError('123:PRIVATE backend error')):
            with self.assertRaises(TelegramError) as error:
                telegram_api('123:PRIVATE', 'getMe')
        self.assertNotIn('PRIVATE', str(error.exception))
        self.assertNotIn('backend', str(error.exception))

    def test_reject_group_destination_without_network(self):
        with patch('urllib.request.urlopen') as network:
            with self.assertRaises(TelegramError):
                send('123:PRIVATE', '-100123', 'test')
            network.assert_not_called()

    def test_pairing_requires_exact_nonce_and_private_sender(self):
        valid = {'message': {'text': '/start nonce', 'chat': {'id': 123, 'type': 'private'},
                             'from': {'id': 123, 'is_bot': False}}}
        self.assertEqual(paired_chat([valid], 'nonce'), 123)
        self.assertIsNone(paired_chat([valid], 'other'))
        valid['message']['chat']['type'] = 'group'
        self.assertIsNone(paired_chat([valid], 'nonce'))
        valid['message']['chat']['type'] = 'private'
        valid['message']['from']['id'] = 456
        self.assertIsNone(paired_chat([valid], 'nonce'))


if __name__ == '__main__':
    unittest.main()
