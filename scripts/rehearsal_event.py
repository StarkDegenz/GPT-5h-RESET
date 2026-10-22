"""Emit TEST-only PR transport events; never change quota or production state."""

import base64
import json
import os
import time
import urllib.request


MARKER = '<!-- reset-rehearsal/v1 -->'
BRANCH = 'test/existing-chat-reset-rehearsal'
LABELS = {'rehearsal-probe': 'binding_probe',
          'rehearsal-early-reset': 'synthetic_early_reset',
          'rehearsal-quota-observed': 'actual_quota_observed'}


def payload(state, now, kind, run_id):
    """Allow transport testing only inside a fresh, already active window."""
    if kind not in LABELS.values():
        raise ValueError('Unknown rehearsal event.')
    if state.get('status') in ('pending', 'unverified'):
        raise ValueError('An actual request is unresolved; rehearsal stopped.')
    observations = state.get('observations') or []
    if not observations:
        raise ValueError('No real quota observation available.')
    last = observations[-1]
    fields = ('first_at', 'second_at', 'first_reset', 'second_reset')
    if any(type(last.get(key)) is not int for key in fields):
        raise ValueError('Malformed quota observation.')
    if (not 0 <= now - last['second_at'] <= 1200
            or not 6 <= last['second_at'] - last['first_at'] <= 120
            or last.get('allowed') is not True
            or last['first_reset'] <= last['first_at']
            or last['second_reset'] <= last['second_at']
            or abs(last['second_reset'] - last['first_reset']) > 2
            or last['second_reset'] <= now + 900):
        raise ValueError('Need a fresh active real window with at least 15 minutes remaining.')
    result = {'schema': 'reset-rehearsal/v1', 'test_only': True,
              'kind': kind, 'event_id': f'rehearsal:{run_id}:{kind}',
              'created_at': now, 'expires_at': now + 900,
              'actual_observed_reset': last['second_reset'],
              'actual_observed_at': last['second_at'],
              'new_window_proven': False}
    if kind == 'synthetic_early_reset':
        result['synthetic_detection_at'] = now
        result['test_reminder_due_at'] = now + 300
    return result


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    number = os.environ['CONTROL_PR']
    if not number.isdigit() or int(number) <= 0:
        raise ValueError('Invalid control PR.')
    kind = LABELS[os.environ['REHEARSAL_LABEL']]

    def api(path, data=None):
        request = urllib.request.Request(
            'https://api.github.com/repos/' + repo + '/' + path,
            data=None if data is None else json.dumps(data).encode(),
            headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                     'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    pr = api('pulls/' + number)
    if (pr.get('state') != 'open' or pr.get('draft') is not True
            or pr.get('head', {}).get('ref') != BRANCH
            or pr.get('head', {}).get('repo', {}).get('full_name') != repo):
        raise ValueError('Events may only go to the dedicated same-repository draft test PR.')
    envelope = api('contents/state.json?ref=quota-test-state')
    state = json.loads(base64.b64decode(envelope['content']))
    event = payload(state, int(time.time()), kind, os.environ['GITHUB_RUN_ID'])
    # A workflow retry uses the same run ID. Scan for its durable marker first;
    # uncertain comment creation fails the job rather than blindly posting twice.
    comments = []
    for page in range(1, 11):
        batch = api(f'issues/{number}/comments?per_page=100&page={page}')
        comments.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError('Control thread history exceeds the bounded deduplication scan.')
    if any(event['event_id'] in comment.get('body', '')
           and comment.get('user', {}).get('login') == 'github-actions[bot]'
           for comment in comments):
        print('Test event already posted; no duplicate emitted.')
        return
    body = ('TEST ONLY — not a real reset or a quota-start confirmation.\n\n'
            + MARKER + '\n```json\n' + json.dumps(event, indent=2) + '\n```')
    api('issues/' + number + '/comments', {'body': body})
    print('Rehearsal event posted. This is transport acceptance, not proof of chat delivery.')


if __name__ == '__main__':
    main()
