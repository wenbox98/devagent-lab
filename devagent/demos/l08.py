"""L08 strict repository/sandbox demos; never fall back to host probes."""
import argparse
from dataclasses import asdict
import json
from tempfile import TemporaryDirectory

from ..runtime.environment import inspect_environment
from ..runtime.runner import ControlledTestRunner

CASES = ('normal', 'timeout', 'output-limit', 'boundary')


def run_case(case: str) -> dict:
    if case not in CASES:
        raise ValueError('unknown L08 case')
    capabilities = inspect_environment()
    with TemporaryDirectory() as directory:
        runner = ControlledTestRunner(directory)
        result = runner.run_tests()
        argv = runner.test_argv
    checks = {'isolation_verified': capabilities.repository_execution,
              'execution_started': result.started,
              'case_executed': result.started and result.scope == 'repository'}
    report = {'lesson': 'L08', 'case': case,
              'observed': {'result': asdict(result), 'capabilities': asdict(capabilities),
                           'command_template': argv,
                           'scope': 'repository isolation required; trusted probes are separate'},
              'checks': checks, 'verified': all(checks.values())}
    if result.status == 'blocked':
        report['blocked'] = asdict(result.error)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--list-cases', action='store_true')
    args = parser.parse_args()
    if args.list_cases:
        print(json.dumps({'lesson': 'L08', 'cases': CASES}))
        return 0
    if not args.case:
        parser.error('--case is required')
    report = run_case(args.case)
    print(json.dumps(report, ensure_ascii=True))
    return 2 if 'blocked' in report else (0 if report['verified'] else 1)


if __name__ == '__main__':
    raise SystemExit(main())
