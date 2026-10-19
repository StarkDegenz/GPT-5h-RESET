"""Route external ticks before any ChatGPT credential can be accessed."""

from datetime import datetime, timezone
import os
from pathlib import Path


def flag(value):
    if value not in ('', 'false', 'true'):
        raise ValueError('Controller flags must be true, false or unset.')
    return value == 'true'


def route(mode, armed_value='', observe_value='', baseline=''):
    armed = flag(armed_value)
    observing = flag(observe_value)
    if mode not in ('probe', 'external', 'observe', 'test', 'continue'):
        raise ValueError('Unknown controller mode.')
    if baseline and mode != 'test':
        raise ValueError('A fictional baseline is only accepted for the manual test.')
    if mode == 'probe':
        return 'probe', False
    if mode == 'external':
        return ('continue', True) if armed else ('observe', observing)
    if mode == 'observe':
        return mode, True
    return mode, armed


def main():
    mode, run_quota = route(os.environ.get('REQUEST_MODE', 'probe'),
                            os.environ.get('QUOTA_TEST_ARMED', ''),
                            os.environ.get('QUOTA_OBSERVE_ENABLED', ''),
                            os.environ.get('BASELINE_RESET', ''))
    received = datetime.now(timezone.utc).isoformat()
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
        output.write(f'mode={mode}\nrun_quota={str(run_quota).lower()}\n')
    print(f'Controller received at {received}; mode={mode}; account_access={run_quota}')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with Path(summary).open('a') as output:
            output.write(f'Controller received UTC: {received}\n\n'
                         f'Effective mode: `{mode}`. Account access: `{run_quota}`.\n')


if __name__ == '__main__':
    main()
