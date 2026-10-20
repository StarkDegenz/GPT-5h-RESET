"""Optional event delivery through the documented Workspace Agents API.

This creates/continues an agent conversation; it cannot post to an arbitrary
existing personal ChatGPT or Codex conversation. No ChatGPT login token is used.
"""

from datetime import datetime
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo


def message(event):
    kind = event['kind']
    if kind == 'trigger_requested':
        return ("Sup lazy human it's time to print\n"
                'The controller requested the Codex trigger. '
                'The next reset time is not confirmed yet.')
    if kind == 'early_reset_detected':
        return ('An early quota reset was observed. The controller will wait '
                'five minutes from detection before attempting the next trigger, '
                'unless a new active window appears. The next reset time is not confirmed yet.')
    reset = datetime.fromtimestamp(event['reset'], ZoneInfo('Europe/Paris'))
    formatted = reset.strftime('%Y-%m-%d %H:%M:%S %Z')
    if kind == 'reset_confirmed':
        return f'Reset confirmed. Next reset: {formatted} (Paris).'
    if kind == 'deadline_changed':
        return f'Reset deadline changed. Current observed next reset: {formatted} (Paris).'
    raise ValueError('Unknown chat event.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the dedicated bearer token to another endpoint.
        return None


class WorkspaceChat:
    def __init__(self, trigger_id, token, conversation_key, repo, opener=None):
        if not re.fullmatch(r'agtch_[A-Za-z0-9_-]+', trigger_id):
            raise ValueError('Invalid Workspace Agent API trigger identifier.')
        if not token or not conversation_key or not repo:
            raise ValueError('Incomplete chat delivery configuration.')
        self.url = f'https://api.chatgpt.com/v1/workspace_agents/{trigger_id}/trigger'
        self.token = token
        self.conversation_key = conversation_key
        self.repo = repo
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    @classmethod
    def from_environment(cls):
        enabled = os.environ.get('QUOTA_CHAT_ENABLED', '')
        if enabled in ('', 'false'):
            return None
        if enabled != 'true':
            raise ValueError('QUOTA_CHAT_ENABLED must be true, false or unset.')
        return cls(os.environ.get('QUOTA_CHAT_TRIGGER_ID', ''),
                   os.environ.get('QUOTA_CHAT_ACCESS_TOKEN', ''),
                   os.environ.get('QUOTA_CHAT_CONVERSATION_KEY', ''),
                   os.environ.get('GITHUB_REPOSITORY', ''))

    def send(self, event):
        # Reuse a stable event key on uncertain HTTP outcomes. The API queues
        # the event once, even if the runner crashed before saving its receipt.
        key = hashlib.sha256((self.repo + ':' + self.conversation_key + ':'
                              + event['id']).encode()).hexdigest()
        body = json.dumps({'conversation_key': self.conversation_key,
                           'input': 'Relay this controller event verbatim. Do not use tools, '
                                    'schedule anything or trigger Codex.\n\n' + message(event)}).encode()
        request = urllib.request.Request(self.url, data=body, method='POST', headers={
            'Authorization': 'Bearer ' + self.token,
            'Content-Type': 'application/json',
            'Idempotency-Key': key,
        })
        with self.opener.open(request, timeout=15) as response:
            if response.status != 202:
                raise ValueError('Chat trigger was not accepted.')
            result = json.load(response)
        url = result.get('conversation_url', '')
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != 'chatgpt.com'
                or not re.fullmatch(r'/c/[A-Za-z0-9_-]+', parsed.path)
                or parsed.query or parsed.fragment):
            raise ValueError('Missing or invalid chat conversation receipt.')
        # Acceptance is queueing, not proof that the agent delivered a message.
        return url
