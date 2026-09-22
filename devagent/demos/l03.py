"""L03 executes a single proposal/batch against real L02 tools; no model loop."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from ..tools.protocol import ToolCall
from ..tools.registry import ToolRegistry

CASES = ('valid-call', 'unknown-tool', 'invalid-args', 'business-error')
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / 'fixtures' / 'tiny_repo'


def run_case(case: str) -> dict:
    registry = ToolRegistry(FIXTURE_ROOT)
    if case == 'valid-call':
        calls = [ToolCall('c1', 'read_file', {'path': 'pagination.py', 'end_line': 3})]
        expected_codes, expected_count = [None], 1
    elif case == 'unknown-tool':
        calls = [ToolCall('c1', 'not_registered', {})]
        expected_codes, expected_count = ['unknown_tool'], 0
    elif case == 'invalid-args':
        args = [{}, {'path': 'pagination.py', 'start_line': '1'},
                {'path': 'pagination.py', 'start_line': True},
                {'path': 'pagination.py', 'allow_all': True}]
        calls = [ToolCall(f'c{i}', 'read_file', arg) for i, arg in enumerate(args, 1)]
        expected_codes, expected_count = ['invalid_args'] * 4, 0
    elif case == 'business-error':
        calls = [ToolCall('range', 'read_file', {'path': 'pagination.py', 'start_line': 0}),
                 ToolCall('escape', 'read_file', {'path': '../outside.py'})]
        expected_codes, expected_count = ['invalid_args', 'permission_denied'], 1
    else:
        raise ValueError('unknown L03 case')
    results = registry.execute_batch(calls)
    checks = {
        'call_ids': [r.call_id for r in results] == [c.call_id for c in calls],
        'error_codes': [r.error.code if r.error else None for r in results] == expected_codes,
        'ok_flags': [r.ok for r in results] == [code is None for code in expected_codes],
        'handler_calls': registry.handler_calls == expected_count,
    }
    if case == 'valid-call':
        with (FIXTURE_ROOT / 'pagination.py').open('rb') as stream:
            expected = ''.join(stream.read(4097).decode('utf-8').splitlines(keepends=True)[:3])
        data = results[0].data or {}
        checks['real_content'] = data.get('content') == expected
        checks['line_numbers'] = (data.get('start_line'), data.get('end_line')) == (1, 3)
    return {'lesson': 'L03', 'case': case,
            'observed': {'results': [asdict(r) for r in results], 'handler_calls': registry.handler_calls},
            'checks': checks, 'verified': bool(checks) and all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--list-cases', action='store_true')
    args = parser.parse_args()
    if args.list_cases:
        print(json.dumps({'lesson': 'L03', 'cases': CASES}))
        return 0
    if not args.case:
        parser.error('--case is required')
    report = run_case(args.case)
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
