"""Run real application functions in an isolated temporary directory."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from ..app import run_task
from ..fake_model import FakeModelClient

CASES = ('success', 'timeout', 'empty-response', 'empty-task', 'trace-append')


def read_events(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def run_case(case, root):
    path = root / 'runs.jsonl'
    mode = {'timeout': 'timeout', 'empty-response': 'bad_response'}.get(case, 'success')
    client = FakeModelClient(mode)
    task = '   ' if case == 'empty-task' else '  explain pagination  '
    result = run_task(task, client, trace_path=path)
    events = read_events(path)
    code, exit_code = {'timeout': ('model_timeout', 3), 'empty-response': ('invalid_response', 4),
                       'empty-task': ('invalid_input', 2)}.get(case, (None, 0))
    order = ['run_started', 'run_finished'] if case == 'empty-task' else [
        'run_started', 'model_started', 'model_finished', 'run_finished']
    checks = {
        'status': result.status == ('succeeded' if code is None else 'failed'),
        'error_code': result.error_code == code,
        'business_exit_code': result.exit_code == exit_code,
        'call_count': client.call_count == (0 if case == 'empty-task' else 1),
        'event_order': [e['event'] for e in events] == order,
        'correlation': all(e['run_id'] == result.run_id for e in events),
    }
    observed = dict(result=asdict(result), call_count=client.call_count, events=events)
    if code is None:
        checks['clean_simulated_output'] = result.output == '【模拟输出】explain pagination'
    if case == 'empty-response':
        checks['call_ok_task_failed'] = events[2]['status'] == 'succeeded' and events[3]['status'] == 'failed'
    if case == 'timeout':
        checks['call_failed'] = events[2]['status'] == 'failed'
    if case == 'trace-append':
        before = path.read_bytes()
        second = run_task('second task', client, trace_path=path)
        combined = read_events(path)
        blocker = root / 'ordinary-file'
        blocker.write_text('not a directory', encoding='utf-8')
        blocked_client = FakeModelClient()
        blocked = run_task('third task', blocked_client, trace_path=blocker / 'runs.jsonl')
        checks.update(
            old_bytes_preserved=path.read_bytes().startswith(before),
            eight_events=len(combined) == 8,
            different_run_ids=second.run_id != result.run_id,
            second_succeeded=second.status == 'succeeded',
            trace_failure=blocked.error_code == 'trace_io' and blocked.exit_code == 5,
            trace_failure_no_call=blocked_client.call_count == 0,
        )
        observed.update(second_result=asdict(second), appended_events=combined[4:],
                        blocked_result=asdict(blocked), blocked_call_count=blocked_client.call_count)
    return dict(lesson='L00', case=case, observed=observed, checks=checks, verified=all(checks.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--list-cases', action='store_true')
    args = parser.parse_args()
    if args.list_cases:
        print(json.dumps(dict(lesson='L00', cases=CASES)))
        return 0
    if args.case is None:
        parser.error('--case or --list-cases is required')
    try:
        with TemporaryDirectory(prefix='devagent-l00-') as directory:
            report = run_case(args.case, Path(directory))
    except OSError as exc:
        report = dict(lesson='L00', case=args.case,
                      observed=dict(status='blocked', reason=type(exc).__name__),
                      checks=dict(environment_ready=False), verified=False)
        print(json.dumps(report, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
