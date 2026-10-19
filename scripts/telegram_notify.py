"""Telegram alerts independent of the quota runner. Never expose API errors/URLs."""

import json
import os
import re
from pathlib import Path
import urllib.request

from quota_test import Blocked, GitHubState


class TelegramError(RuntimeError):
    pass


def telegram_api(token, method, data=None):
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
        raise TelegramError('Invalid Telegram credential format.')
    if method not in ('getMe', 'getWebhookInfo', 'getUpdates', 'sendMessage'):
        raise TelegramError('Unsupported Telegram operation.')
    request = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/{method}',
        data=json.dumps(data or {}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        if result.get('ok') is not True:
            raise ValueError()
        return result['result']
    except Exception:
        # urllib errors contain the URL, which contains the credential.
        raise TelegramError('Telegram operation failed; no raw response was logged.') from None


def send(token, chat_id, text):
    if not re.fullmatch(r'[1-9][0-9]*', str(chat_id)):
        raise TelegramError('A private Telegram chat is required.')
    telegram_api(token, 'sendMessage', {
        'chat_id': str(chat_id), 'text': text,
        'link_preview_options': {'is_disabled': True},
    })


def plan(previous, run_id, conclusion, experiment):
    """Return generic alerts and allowlisted deduplication state only."""
    updated = dict(previous)
    if run_id <= previous.get('last_run_id', 0):
        return [], updated
    messages = []
    failed = conclusion != 'success'
    if failed and not previous.get('incident', False):
        messages.append('⚠️ GPT-5h-RESET : le contrôle GitHub a échoué ou a été interrompu. Consulter le run ci-dessous.')
    elif not failed and previous.get('incident', False):
        messages.append('✅ GPT-5h-RESET : les contrôles GitHub fonctionnent à nouveau.')
    updated['incident'] = failed
    status = experiment.get('status')
    attempt = experiment.get('attempt_id')
    if status in ('complete', 'unverified', 'pending') and attempt:
        key = f'{attempt}:{status}'
        if key != previous.get('result_key'):
            messages.append({
                'complete': '✅ GPT-5h-RESET : une échéance stable compatible avec cinq heures après le message a été confirmée. Vérifier le résultat dans GitHub.',
                'unverified': '⚠️ GPT-5h-RESET : le message a été tenté, mais le démarrage du compteur n’a pas été confirmé. Aucun renvoi automatique.',
                'pending': '⚠️ GPT-5h-RESET : une tentative est enregistrée, mais son résultat reste incertain. Aucun renvoi automatique.',
            }[status])
            updated['result_key'] = key
    updated['last_run_id'] = run_id
    return messages, updated


class NotificationStore(GitHubState):
    branch = 'telegram-notification-state'
    path = 'notification-state.json'


def main():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat:
        print('Telegram not configured; no notification sent.')
        return
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    run = event['workflow_run']
    repo = os.environ['GITHUB_REPOSITORY']
    if (run['repository']['full_name'] != repo or
            run['head_repository']['full_name'] != repo or
            run['head_branch'] != 'main' or
            run['path'] != '.github/workflows/quota-test.yml'):
        raise TelegramError('Untrusted workflow source; no notification sent.')
    experiment = GitHubState().load()
    store = NotificationStore()
    previous = store.load()
    messages, updated = plan(previous, int(run['id']), run['conclusion'], experiment)
    url = f'https://github.com/{repo}/actions/runs/{int(run["id"])}'
    for message in messages:
        send(token, chat, message + '\n' + url)
    # Record only after acknowledgement. A network/persistence ambiguity can
    # duplicate an alert on a later run, but never invokes a quota/model request.
    if updated != previous:
        store.save(updated)
    print(f'Telegram: {len(messages)} notification(s) acknowledged.')


if __name__ == '__main__':
    try:
        main()
    except (TelegramError, Blocked, KeyError, ValueError, OSError):
        print('Telegram notification failed; inspect configuration. No secret or raw error was logged.')
        raise SystemExit(1)
