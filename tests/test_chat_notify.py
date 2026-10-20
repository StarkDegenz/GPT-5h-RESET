import io
import json
import unittest
from unittest.mock import patch

from scripts.chat_notify import NoRedirect, WorkspaceChat, message


class Response(io.BytesIO):
    status = 202


class Opener:
    def __init__(self, response=None):
        self.requests = []
        self.response = response or {'conversation_url': 'https://chatgpt.com/c/reset-chat'}

    def open(self, request, timeout):
        self.requests.append(request)
        return Response(json.dumps(self.response).encode())


class ChatNotificationTests(unittest.TestCase):
    def test_two_events_use_same_chat_and_retries_use_same_idempotency_key(self):
        opener = Opener()
        chat = WorkspaceChat('agtch_test', 'not-a-real-token', 'quota-reset',
                             'owner/repo', opener)
        trigger = {'id': 'trigger:123', 'kind': 'trigger_requested', 'at': 1}
        confirmed = {'id': 'confirmed:123', 'kind': 'reset_confirmed',
                     'at': 2, 'reset': 1792492567}
        chat.send(trigger)
        chat.send(confirmed)
        chat.send(confirmed)
        requests = opener.requests
        bodies = [json.loads(r.data) for r in requests]
        self.assertEqual({b['conversation_key'] for b in bodies}, {'quota-reset'})
        self.assertNotEqual(requests[0].get_header('Idempotency-key'),
                            requests[1].get_header('Idempotency-key'))
        self.assertEqual(requests[1].get_header('Idempotency-key'),
                         requests[2].get_header('Idempotency-key'))
        self.assertIn('12:36:07 CEST', bodies[1]['input'])
        self.assertNotIn('not-a-real-token', str(bodies))

    def test_paris_timezone_tracks_winter_time(self):
        from datetime import datetime, timezone
        reset = int(datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc).timestamp())
        self.assertIn('11:00:00 CET', message({'kind': 'reset_confirmed', 'reset': reset}))

    def test_disabled_configuration_needs_no_credentials(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertIsNone(WorkspaceChat.from_environment())

    def test_enabled_but_incomplete_configuration_fails(self):
        with patch.dict('os.environ', {'QUOTA_CHAT_ENABLED': 'true'}, clear=True):
            with self.assertRaises(ValueError):
                WorkspaceChat.from_environment()

    def test_foreign_receipt_and_redirects_rejected(self):
        chat = WorkspaceChat('agtch_test', 'token', 'quota-reset', 'owner/repo',
                             Opener({'conversation_url': 'https://example.com/c/chat'}))
        with self.assertRaises(ValueError):
            chat.send({'id': 'trigger:123', 'kind': 'trigger_requested', 'at': 1})
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {},
                                                        'https://example.com'))


if __name__ == '__main__':
    unittest.main()
