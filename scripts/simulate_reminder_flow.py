"""Deterministic, account-free simulation. Run with python -m scripts.simulate_reminder_flow."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import random
from unittest.mock import patch

from .quota_test import Snapshot
from .reminder_flow import DeliveryUncertain, MemoryStore, ReminderFlow


BASE = int(datetime(2026, 10, 20, 8, tzinfo=timezone.utc).timestamp())


class Quota:
    def __init__(self, reset=BASE + 600):
        self.reset = reset
        self.account = 'simulated-account-hash'
        self.allowed = True
        self.visibility_lag = 0
        self.started = None
        self.model_turns = 0

    def pair(self, at):
        def sample(when):
            active = self.reset is not None and when < self.reset
            visible = self.started is None or when >= self.started + self.visibility_lag
            deadline = self.reset if active and visible else int(when + 18000)
            return Snapshot(when, deadline, self.allowed, self.account)
        return sample(at - 8), sample(at)

    def model_turn(self, at):
        self.model_turns += 1
        if self.reset is None or at >= self.reset:
            self.started = at
            self.reset = at + 18000


class Chat:
    """An intentionally fake same-chat adapter; not a ChatGPT integration."""

    def __init__(self, quota):
        self.quota = quota
        self.messages = []
        self.failure = None
        self.affects_quota = True

    def send(self, event_id, chat, text, at, kind):
        if self.failure == 'before_send':
            raise DeliveryUncertain()
        receipt = {'message_id': str(len(self.messages) + 1), 'chat': chat, 'at': at}
        self.messages.append({**receipt, 'event_id': event_id, 'kind': kind, 'text': text})
        if self.affects_quota:
            self.quota.model_turn(at)
        if self.failure == 'after_send':
            raise DeliveryUncertain()
        if self.failure == 'accepted_only':
            return {'accepted': True}
        return receipt


class Simulation:
    def __init__(self, reset=BASE + 600):
        self.store = MemoryStore()
        self.quota = Quota(reset)
        self.chat = Chat(self.quota)
        self.flow = ReminderFlow(self.store, self.quota.account, 'original-chat', 'original-reminder')
        self.trace = []

    def restart(self):
        self.flow = ReminderFlow(self.store, self.quota.account, 'original-chat', 'original-reminder')

    def observe(self, at):
        result = self.flow.observe(*self.quota.pair(at), at)
        self.trace.append({'at': at, 'action': 'observe', 'result': result,
                           'phase': self.store.load()['phase']})
        return result

    def deliver(self, at, event_id=None, destination='original-chat', task='original-reminder'):
        if event_id is None:
            pending = [e for e in self.store.load()['events'] if e['status'] == 'pending']
            if not pending:
                return 'no_pending_event'
            event_id = pending[0]['id']
        result = self.flow.deliver(event_id, *self.quota.pair(at), at,
                                   destination, task, self.chat)
        self.trace.append({'at': at, 'action': 'deliver', 'event': event_id, 'result': result})
        return result

    def finish_cycle(self, due=BASE + 900):
        self.observe(BASE)
        self.observe(due)
        self.deliver(due + 10)
        self.observe(due + 300)
        self.deliver(due + 301)

    def summary(self, name):
        state = self.store.load()
        return {'scenario': name, 'phase': state['phase'],
                'model_turns': self.quota.model_turns,
                'messages': self.chat.messages, 'trace': self.trace,
                'failure': state.get('failure')}


@contextmanager
def offline_guard():
    """Fail immediately if the simulation tries networking or a child process."""
    with patch('socket.socket', side_effect=AssertionError('Network forbidden in simulation')), \
         patch('subprocess.Popen', side_effect=AssertionError('Child processes forbidden in simulation')), \
         patch('subprocess.run', side_effect=AssertionError('Child processes forbidden in simulation')):
        yield


def run_scenarios():
    with offline_guard():
        return _run_scenarios()


def _run_scenarios():
    results = []
    normal = Simulation()
    normal.finish_cycle()
    assert normal.store.load()['phase'] == 'complete'
    assert [m['kind'] for m in normal.chat.messages] == ['trigger', 'confirmation']
    assert len({m['chat'] for m in normal.chat.messages}) == 1
    results.append(normal.summary('normal_same_chat_two_messages'))

    early = Simulation(reset=BASE + 12000)
    early.observe(BASE)
    early.quota.reset = None
    early.observe(BASE + 300)
    assert early.store.load()['due_at'] == BASE + 600
    early.observe(BASE + 600)
    early.deliver(BASE + 610)
    early.observe(BASE + 900)
    early.deliver(BASE + 901)
    assert early.store.load()['phase'] == 'complete'
    results.append(early.summary('early_reset_does_not_wait_for_old_deadline'))

    changed = Simulation()
    changed.observe(BASE)
    changed.quota.reset = BASE + 3600
    changed.observe(BASE + 300)
    changed.observe(BASE + 900)
    assert not changed.store.load()['events']
    changed.observe(BASE + 3900)
    changed.deliver(BASE + 3910)
    changed.observe(BASE + 4200)
    changed.deliver(BASE + 4201)
    assert changed.store.load()['phase'] == 'complete'
    results.append(changed.summary('moved_deadline_cancels_obsolete_timing'))

    for moment in ('before_send', 'after_send', 'accepted_only'):
        sim = Simulation()
        sim.observe(BASE)
        sim.observe(BASE + 900)
        sim.chat.failure = moment
        sim.deliver(BASE + 910)
        sim.restart()
        sim.deliver(BASE + 920, 'cycle-1:trigger')
        sim.observe(BASE + 1200)
        assert sim.store.load()['phase'] == 'blocked'
        assert len(sim.chat.messages) <= 1
        results.append(sim.summary('uncertain_delivery_' + moment))

    wrong_bucket = Simulation()
    wrong_bucket.chat.affects_quota = False
    wrong_bucket.observe(BASE)
    wrong_bucket.observe(BASE + 900)
    wrong_bucket.deliver(BASE + 910)
    for offset in (1200, 1500, 1800, 2100):
        wrong_bucket.observe(BASE + offset)
    assert wrong_bucket.store.load()['failure'] == 'quota_start_unverified'
    assert len(wrong_bucket.chat.messages) == 1
    results.append(wrong_bucket.summary('chat_does_not_start_intended_quota_no_false_success'))

    # Many duplicate/reordered event deliveries and repeated process restarts.
    random_checks = 0
    for seed in range(100):
        rng = random.Random(seed)
        sim = Simulation()
        sim.observe(BASE)
        sim.observe(BASE + 900)
        for step in range(20):
            if rng.choice((False, True)):
                sim.restart()
            sim.deliver(BASE + 910 + step, 'cycle-1:trigger')
            random_checks += 1
        assert len(sim.chat.messages) == 1
        sim.observe(BASE + 1200)
        for step in range(20):
            if rng.choice((False, True)):
                sim.restart()
            sim.deliver(BASE + 1210 + step, 'cycle-1:confirmation')
            random_checks += 1
        assert len(sim.chat.messages) == 2
        assert sim.quota.model_turns == 2
        assert sim.store.load()['phase'] == 'complete'
    results.append({'scenario': 'randomized_duplicate_events_and_restarts',
                    'seeds': 100, 'event_deliveries': random_checks, 'passed': True})

    # Counterexample: if ChatGPT starts inference BEFORE the event body can
    # validate/deduplicate, prompt-level duplicate checks do not prevent turns.
    unsafe = Simulation()
    unsafe.observe(BASE)
    unsafe.observe(BASE + 900)
    unsafe.quota.model_turn(BASE + 910)  # platform wakes model before our gate
    unsafe.deliver(BASE + 920, 'cycle-1:trigger')  # gate finds active and cancels
    unsafe.quota.model_turn(BASE + 930)  # duplicate provider wakeup
    unsafe.deliver(BASE + 940, 'cycle-1:trigger')
    assert unsafe.quota.model_turns == 2
    assert not unsafe.chat.messages
    results.append({**unsafe.summary('platform_pre_gate_inference_counterexample'),
                    'known_platform_gap': True,
                    'explanation': 'Model can start the window before reminder delivery; prompt dedupe is too late.'})
    return {'network_and_subprocess_guard': 'enabled',
            'live_account_operations': 0, 'live_messages': 0,
            'network_requests': 0, 'scenarios': results,
            'live_gates': ['same existing chat/task binding',
                           'chat reminder starts intended quota bucket',
                           'pre-inference event validation/deduplication or equivalent provider guarantee',
                           'separate unbatched messages and delivery receipts',
                           'cloud/free entitlement and latency']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = run_scenarios()
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + '\n')
    else:
        print(rendered)


if __name__ == '__main__':
    main()
