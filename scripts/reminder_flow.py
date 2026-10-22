"""Transport-independent prototype for the required existing-chat flow.

No network, credentials, CLI calls, or live automation bindings. A live adapter
must supply serialized durable storage, fresh quota pairs, and actual same-chat
delivery receipts. Those capabilities are simulated, not established here.
"""

from copy import deepcopy
from datetime import datetime
import threading
from zoneinfo import ZoneInfo

from .quota_test import Blocked, classify


TRIGGER_TEXT = "Sup lazy human it's time to print"


class DeliveryUncertain(RuntimeError):
    pass


def paris(epoch):
    return datetime.fromtimestamp(epoch, ZoneInfo('Europe/Paris')).strftime('%Y-%m-%d %H:%M:%S %Z')


class ReminderFlow:
    """Serialized state machine; delivery is always injected, never built in."""

    def __init__(self, store, account, chat, task):
        self.store = store
        self.binding = {'account': account, 'chat': chat, 'task': task}
        state = store.load()
        if not state:
            store.save({'binding': self.binding, 'phase': 'monitoring',
                        'generation': 0, 'events': [], 'history': []})
        elif state.get('binding') != self.binding:
            raise Blocked('Observer/chat/task binding changed.')

    def pair_kind(self, first, second, now):
        if first.account != self.binding['account'] or second.account != self.binding['account']:
            raise Blocked('Account changed.')
        if second.at > now or now - second.at > 20 or now - first.at > 120:
            raise Blocked('Quota data is stale or from the future.')
        return classify(first, second)

    def observe(self, first, second, now):
        state = self.store.load()
        kind = self.pair_kind(first, second, now)
        if second.at <= state.get('last_sample', float('-inf')):
            raise Blocked('Out-of-order or replayed observation.')
        state['last_sample'] = second.at
        state['last_kind'] = kind
        if kind == 'blocked' or state['phase'] == 'blocked':
            self.store.save(state)
            return kind
        phase = state['phase']
        if phase == 'trigger_claimed':
            state['phase'] = 'blocked'
            state['failure'] = 'trigger_outcome_unknown'
            self.store.save(state)
            return 'blocked'
        if phase == 'confirmation_claimed':
            state['phase'] = 'blocked'
            state['failure'] = 'confirmation_outcome_unknown'
            self.store.save(state)
            return 'blocked'
        if phase == 'waiting_verification':
            start = state['trigger_receipt']['at']
            if (kind == 'active' and first.at >= start
                    and abs(second.reset - (start + 18000)) <= 180):
                state['verified_reset'] = second.reset
                state['verified_at'] = second.at
                state['expected_reset'] = second.reset
                state['phase'] = 'confirmation_ready'
                self.queue(state, 'confirmation', now)
            elif now - start >= 900:
                state['phase'] = 'blocked'
                state['failure'] = 'quota_start_unverified'
            self.store.save(state)
            return state['phase']
        if phase == 'confirmation_ready':
            # Never replace a receipt with the old fictional/expected deadline.
            # A changed window makes the pending confirmation unsafe to deliver.
            if kind != 'active' or abs(second.reset - state['verified_reset']) > 2:
                state['phase'] = 'blocked'
                state['failure'] = 'deadline_changed_before_confirmation'
            self.store.save(state)
            return state['phase']
        if phase == 'waiting_trigger':
            trigger = next(e for e in state['events']
                           if e['id'] == state['cycle'] + ':trigger')
            if now > trigger['expires_at']:
                trigger['status'] = 'expired'
                state['phase'] = 'blocked'
                state['failure'] = 'event_expired'
                self.store.save(state)
                return 'blocked'
        if kind == 'active':
            if phase == 'waiting_trigger':
                self.cancel_trigger(state, 'new_activity')
            state['expected_reset'] = second.reset
            state.pop('idle_since', None)
            state.pop('due_at', None)
            self.store.save(state)
            return 'active'
        if phase == 'complete':
            state['history'] = [*state['history'], {
                'cycle': state['cycle'], 'verified_reset': state['verified_reset'],
                'trigger_receipt': state['trigger_receipt'],
                'confirmation_receipt': state['confirmation_receipt'],
            }][-100:]
            state['phase'] = 'monitoring'
            for key in ('cycle', 'trigger_receipt', 'confirmation_receipt',
                        'verified_reset', 'verified_at', 'idle_since', 'due_at'):
                state.pop(key, None)
        if 'idle_since' not in state:
            old = state.get('expected_reset')
            state['idle_since'] = old if old is not None and old <= second.at else second.at
            state['due_at'] = state['idle_since'] + 300
        if now >= state['due_at'] and state['phase'] == 'monitoring':
            state['generation'] += 1
            state['cycle'] = f"cycle-{state['generation']}"
            state['phase'] = 'waiting_trigger'
            self.queue(state, 'trigger', now)
        self.store.save(state)
        return state['phase']

    @staticmethod
    def queue(state, kind, now):
        state['events'].append({'id': state['cycle'] + ':' + kind,
                                'kind': kind, 'cycle': state['cycle'],
                                'created_at': now, 'expires_at': now + 900,
                                'status': 'pending'})
        # Keep pending events; limit completed transport history.
        old = [e for e in state['events'] if e['status'] != 'pending'][-100:]
        pending = [e for e in state['events'] if e['status'] == 'pending']
        state['events'] = [*old, *pending]

    @staticmethod
    def cancel_trigger(state, reason):
        for event in state['events']:
            if event['cycle'] == state.get('cycle') and event['kind'] == 'trigger':
                event['status'] = 'cancelled'
        state['phase'] = 'monitoring'
        state['cancel_reason'] = reason
        state.pop('cycle', None)

    def deliver(self, event_id, first, second, now, destination, task, sink):
        """Validate and durably claim an event before the simulated chat effect.

        A real model-driven webhook handler may already consume quota before
        these checks execute. It cannot be assumed to provide this pre-effect
        gate. The simulator includes a counterexample for that platform gap.
        """
        state = self.store.load()
        if destination != self.binding['chat'] or task != self.binding['task']:
            raise Blocked('Wrong chat or reminder task; no delivery.')
        matches = [e for e in state['events'] if e['id'] == event_id]
        if not matches:
            raise Blocked('Unknown event.')
        event = matches[0]
        if event['status'] != 'pending' or event['cycle'] != state.get('cycle'):
            return 'ignored_duplicate_or_cancelled'
        if now < event['created_at']:
            raise Blocked('Event timestamp is in the future; clock moved backwards.')
        if now > event['expires_at']:
            event['status'] = 'expired'
            state['phase'] = 'blocked'
            state['failure'] = 'event_expired'
            self.store.save(state)
            return 'expired'
        kind = self.pair_kind(first, second, now)
        if kind == 'blocked':
            return 'usage_blocked'
        if event['kind'] == 'trigger':
            if state['phase'] != 'waiting_trigger' or now < state['due_at']:
                return 'not_due'
            if kind != 'idle':
                if kind == 'active':
                    self.cancel_trigger(state, 'activity_before_delivery')
                    state['expected_reset'] = second.reset
                    state.pop('idle_since', None)
                    state.pop('due_at', None)
                    self.store.save(state)
                return 'cancelled_new_activity'
            text = TRIGGER_TEXT
            state['phase'] = 'trigger_claimed'
        else:
            if state['phase'] != 'confirmation_ready':
                return 'not_verified'
            if (kind != 'active' or second.reset <= now
                    or abs(second.reset - state['verified_reset']) > 2):
                state['phase'] = 'blocked'
                state['failure'] = 'deadline_changed_before_confirmation'
                self.store.save(state)
                return 'blocked'
            text = f"Reset confirmed. Next reset: {paris(state['verified_reset'])} (Paris)."
            state['phase'] = 'confirmation_claimed'
        event['status'] = 'claimed'
        self.store.save(state)  # Failed persistence prevents the chat effect.
        try:
            receipt = sink.send(event['id'], destination, text, now, event['kind'])
        except DeliveryUncertain:
            state['phase'] = 'blocked'
            state['failure'] = 'delivery_outcome_unknown'
            self.store.save(state)
            return 'blocked'
        if (not isinstance(receipt, dict) or not receipt.get('message_id')
                or receipt.get('chat') != destination or receipt.get('at') != now):
            state['phase'] = 'blocked'
            state['failure'] = 'missing_same_chat_delivery_receipt'
            self.store.save(state)
            return 'blocked'
        event['status'] = 'delivered'
        state[event['kind'] + '_receipt'] = receipt
        state['phase'] = 'waiting_verification' if event['kind'] == 'trigger' else 'complete'
        self.store.save(state)
        return state['phase']


class MemoryStore:
    """JSON-like persistence used only by the simulation, not a live lock."""

    def __init__(self):
        self.state = {}
        self.fail_phase = None
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            return deepcopy(self.state)

    def save(self, state):
        with self.lock:
            if state['phase'] == self.fail_phase:
                raise OSError('Simulated persistence failure.')
            if state.get('_revision', 0) != self.state.get('_revision', 0):
                raise Blocked('State changed concurrently; reload before acting.')
            state['_revision'] = state.get('_revision', 0) + 1
            self.state = deepcopy(state)
