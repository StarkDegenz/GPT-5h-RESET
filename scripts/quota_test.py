"""One-shot quota experiment. No API keys; unknown states never permit a send."""

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request


class Blocked(RuntimeError):
    pass


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def parse_baseline(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise Blocked('The fictional baseline must include a timezone.')
    return int(parsed.timestamp())


@dataclass(frozen=True)
class Snapshot:
    at: float
    reset: int
    allowed: bool
    account: str  # Hash only; never log raw account identifiers.

    @classmethod
    def from_response(cls, data, at, expected_account):
        if data.get('accountId') != expected_account:
            raise Blocked('Quota response does not identify the configured account.')
        allowed = data.get('ordinaryUsageAllowed')
        if type(allowed) is not bool:
            raise Blocked('Included-usage permission unavailable; no inference from percentages.')
        limits = data.get('rateLimitsByLimitId')
        if not isinstance(limits, dict) or 'codex' not in limits:
            raise Blocked('The expected codex quota bucket is unavailable.')
        bucket = limits['codex']
        primary = bucket.get('primary') or {}
        if bucket.get('planType') != 'plus' or primary.get('windowDurationMins') != 300:
            raise Blocked('Expected a Plus account with a five-hour primary window.')
        reset = primary.get('resetsAt')
        if type(reset) is not int or reset <= 0:
            raise Blocked('Missing or invalid absolute reset time.')
        return cls(at, reset, allowed, hashlib.sha256(expected_account.encode()).hexdigest())


def classify(first, second):
    """Require a stable future deadline or a demonstrated moving idle deadline.

    No percentage threshold: a rounded 100% gauge proves neither state.
    A sliding full-window deadline is a hypothesis to validate on the account.
    """
    if first.account != second.account:
        raise Blocked('Account changed during observation.')
    if not first.allowed or not second.allowed:
        return 'blocked'
    dt = second.at - first.at
    if dt < 6:
        raise Blocked('Samples are too close together.')
    movement = second.reset - first.reset
    if first.reset <= first.at and second.reset <= second.at:
        return 'idle'
    if abs(movement) <= 2 and second.reset > second.at:
        return 'active'
    remaining = second.reset - second.at
    if abs(movement - dt) <= 3 and 17880 <= remaining <= 18030:
        return 'idle'
    raise Blocked('Ambiguous quota transition; wait for another run, no send.')


def decide(state, first, second):
    state = dict(state)
    if state.get('account') and state['account'] != second.account:
        raise Blocked('Configured account differs from the saved experiment.')
    state['account'] = second.account
    kind = classify(first, second)
    if kind == 'blocked':
        return state, 'usage_blocked'
    if state.get('status') in ('pending', 'unverified', 'complete'):
        return state, state['status']
    if kind == 'active':
        previous = state.get('expected_reset')
        state['expected_reset'] = second.reset
        state.pop('idle_since', None)
        if previous is not None and previous != second.reset:
            state['resync_from'] = previous
            state['resync_to'] = second.reset
        return state, 'active'
    if 'idle_since' not in state:
        old = state.get('expected_reset')
        # Natural expiry uses its known deadline. An early reset is timed
        # from its detection, never from the fictional or stale deadline.
        trusted_old = old is not None and old != state.get('fictional_baseline')
        state['idle_since'] = old if trusted_old and old <= second.at else int(second.at)
    if second.at < state['idle_since'] + 300:
        return state, 'waiting_five_minutes'
    return state, 'due'


class AppServer:
    """Official CLI JSON-RPC adapter; no model turn is created by this class."""

    def __init__(self, command, env, cwd, timeout=60):
        self.timeout = timeout
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, env=env, cwd=cwd)
        self.messages = queue.Queue()
        self.counter = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            try:
                self.messages.put(json.loads(line))
            except ValueError:
                self.messages.put({'invalid': True})
        self.messages.put({'eof': True})

    def send(self, message):
        try:
            self.proc.stdin.write(json.dumps(message) + '\n')
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise Blocked('Codex app-server disconnected.') from None

    def request(self, method, params):
        self.counter += 1
        request_id = self.counter
        self.send({'id': request_id, 'method': method, 'params': params})
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                message = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise Blocked('Codex app-server timed out.') from None
            if message.get('eof') or message.get('invalid'):
                raise Blocked('Invalid response from Codex app-server.')
            if message.get('id') != request_id:
                continue
            if 'error' in message:
                # Never print raw server errors, headers, account data, or tokens.
                raise Blocked('Codex rejected the quota read; check the dedicated login or CLI compatibility.')
            return message.get('result')

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc.stdin.close()
        self.proc.stdout.close()


class GitHubState:
    """Dedicated state branch; no auth or raw quota snapshots are committed."""

    branch = 'quota-test-state'
    path = 'state.json'

    def __init__(self):
        self.repo = os.environ['GITHUB_REPOSITORY']
        self.token = os.environ['GH_TOKEN']
        self.sha = None
        self.ensure_branch()

    def api(self, path, method='GET', data=None, missing_ok=False):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request('https://api.github.com/repos/' + self.repo + '/' + path,
                                     data=body, method=method, headers={
                                         'Authorization': 'Bearer ' + self.token,
                                         'Accept': 'application/vnd.github+json',
                                         'Content-Type': 'application/json',
                                         'X-GitHub-Api-Version': '2022-11-28',
                                     })
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            raise Blocked(f'GitHub state operation failed (HTTP {error.code}); no blind retry.') from None
        except (OSError, ValueError):
            raise Blocked('GitHub state operation failed; state persistence is unconfirmed.') from None

    def ensure_branch(self):
        ref = self.api('git/ref/heads/' + self.branch, missing_ok=True)
        if ref is None:
            self.api('git/refs', 'POST', {'ref': 'refs/heads/' + self.branch,
                                        'sha': os.environ['GITHUB_SHA']})

    def load(self):
        response = self.api('contents/' + self.path + '?ref=' + self.branch, missing_ok=True)
        if response is None:
            return {}
        self.sha = response['sha']
        try:
            state = json.loads(base64.b64decode(response['content']))
        except (ValueError, KeyError):
            raise Blocked('Invalid saved experiment state.') from None
        if not isinstance(state, dict):
            raise Blocked('Invalid saved experiment state.')
        return state

    def save(self, state):
        payload = {'message': 'Record guarded quota experiment', 'branch': self.branch,
                   'content': base64.b64encode(json.dumps(state, sort_keys=True).encode()).decode()}
        if self.sha:
            payload['sha'] = self.sha
        response = self.api('contents/' + self.path, 'PUT', payload)
        self.sha = response['content']['sha']


def child_environment():
    # Never pass the GitHub write tokens or the raw auth secret to the agent.
    names = ('PATH', 'HOME', 'CODEX_HOME', 'TMPDIR', 'HTTP_PROXY', 'HTTPS_PROXY',
             'NO_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'NODE_EXTRA_CA_CERTS')
    return {key: os.environ[key] for key in names if key in os.environ}


class Codex:
    def __init__(self):
        self.auth_path = Path(os.environ['CODEX_HOME']) / 'auth.json'
        self.env = child_environment()
        self.cwd = os.environ['CODEX_WORKDIR']

    def persist_auth(self):
        result = subprocess.run(['gh', 'secret', 'set', 'CODEX_AUTH_JSON', '--repo',
                                 os.environ['GITHUB_REPOSITORY']],
                                input=self.auth_path.read_bytes(), stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=40,
                                env={**os.environ, 'GH_TOKEN': os.environ['QUOTA_SECRETS_TOKEN']})
        if result.returncode:
            raise Blocked('Unable to persist authentication; stop before any further request.')

    def sample(self):
        before = self.auth_path.read_bytes()
        account = json.loads(before)['tokens']['account_id']
        server = AppServer(['codex', 'app-server'], self.env, self.cwd)
        try:
            server.request('initialize', {'clientInfo': {'name': 'quota_test', 'version': '1.0'}})
            server.send({'method': 'initialized', 'params': {}})
            data = server.request('account/rateLimits/read', {'excludeResetCreditDetails': True,
                                                             'supportsLunaReserve': False})
            return Snapshot.from_response(data, time.time(), account)
        finally:
            server.close()
            if self.auth_path.read_bytes() != before:
                self.persist_auth()

    def pair(self):
        first = self.sample()
        time.sleep(8)
        return first, self.sample()

    def warm(self):
        # Isolated empty directory, read-only sandbox, ChatGPT credentials only.
        # No fallback model or API-key billing; no automatic retry of a model turn.
        try:
            result = subprocess.run([
                'codex', 'exec', '--skip-git-repo-check', '--sandbox', 'read-only',
                '-m', os.environ.get('CODEX_WARM_MODEL', 'gpt-5.6-sol'),
                '-c', 'model_reasoning_effort="low"',
                'Réponds uniquement OK. N’utilise aucun outil et ne lis aucun fichier.',
            ], cwd=self.cwd, env=self.env, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, timeout=90)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        finally:
            self.persist_auth()


def run(store, codex, mode, baseline=None, armed=False, sleep=time.sleep):
    state = store.load()
    if mode == 'test':
        if state.get('status') in ('pending', 'unverified', 'complete'):
            raise Blocked('A request was already attempted; review its result before resetting state.')
        if state.get('armed_at'):
            raise Blocked('Test already armed. Use scheduled checks or observe; do not re-arm.')
        state['armed_at'] = int(time.time())
        state['test_expires'] = state['armed_at'] + 24 * 3600
        if baseline is not None:
            state['expected_reset'] = baseline
            state['fictional_baseline'] = baseline
            state.pop('idle_since', None)
        store.save(state)
    first, second = codex.pair()
    updated, decision = decide(state, first, second)
    if updated != state:
        store.save(updated)
    print(f'Observation: {decision}; observed deadline UTC: {iso(second.reset)}')
    if updated.get('resync_to') and updated.get('resync_to') != state.get('resync_to'):
        print(f'Realigned: {iso(updated["resync_from"])} -> {iso(updated["resync_to"])}')
    if decision != 'due' or mode == 'observe':
        return decision
    if not armed or not updated.get('armed_at'):
        print('Sending disabled. A manual test AND QUOTA_TEST_ARMED=true are required.')
        return 'disabled'
    if second.at > updated['test_expires']:
        raise Blocked('The 24-hour test authorization expired; no request sent.')
    # Re-read immediately before the irreversible step; user activity wins.
    before_first, before_second = codex.pair()
    updated, final_decision = decide(updated, before_first, before_second)
    if final_decision != 'due':
        store.save(updated)
        print('New activity or changed quota detected; request cancelled.')
        return final_decision
    # Durable intent BEFORE sending. On a crash, the next run will not retry.
    updated['status'] = 'pending'
    updated['attempt_at'] = int(before_second.at)
    updated['attempt_id'] = os.environ.get('GITHUB_RUN_ID', 'local')
    store.save(updated)
    cli_ok = codex.warm()
    # A CLI error can occur after metering. Always observe, never blindly resend.
    sleep(15)
    after_first, after_second = codex.pair()
    kind = classify(after_first, after_second)
    expected = updated['attempt_at'] + 18000
    if (kind == 'active' and after_second.account == before_second.account
            and abs(after_second.reset - expected) <= 180):
        updated['status'] = 'complete'
        updated['verified_reset'] = after_second.reset
        updated['cli_ok'] = cli_ok
        store.save(updated)
        print('One-shot test complete: a stable five-hour deadline was observed after the request.')
        print('Compare this deadline with the account UI; concurrent use cannot be ruled out by code.')
        return 'complete'
    updated['status'] = 'unverified'
    store.save(updated)
    raise Blocked('Request attempted but window start unverified. No second request will be sent.')


def main():
    mode = os.environ.get('MODE', 'observe')
    if mode not in ('observe', 'test', 'continue'):
        raise Blocked('Unknown mode.')
    baseline = parse_baseline(os.environ.get('BASELINE_RESET', ''))
    if baseline is not None and mode != 'test':
        raise Blocked('A fictional baseline is only accepted when arming the one-shot test.')
    run(GitHubState(), Codex(), mode, baseline,
        armed=os.environ.get('QUOTA_TEST_ARMED') == 'true')


if __name__ == '__main__':
    try:
        main()
    except (Blocked, subprocess.TimeoutExpired) as error:
        print('STOP: ' + (str(error) if isinstance(error, Blocked) else 'External operation timed out.'))
        raise SystemExit(1)
