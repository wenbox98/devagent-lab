"""Offline L02 cases; temporary writes only construct controlled demonstrations."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from ..tools.files import FileAccessError, read_file

CASES = ('read-lines', 'escape', 'symlink', 'large-file')
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / 'fixtures' / 'tiny_repo'


def _attempt(root, path, **kwargs):
    try:
        return {'result': asdict(read_file(root, path, **kwargs))}
    except FileAccessError as exc:
        return {'error_code': exc.code, 'message': str(exc)}


def run_case(case: str) -> dict:
    observed, checks = {}, {}
    blocked = None
    if case == 'read-lines':
        result = read_file(FIXTURE_ROOT, 'pagination.py', end_line=3, max_bytes=4096)
        with (FIXTURE_ROOT / 'pagination.py').open('rb') as source:
            expected = source.read(4097).decode('utf-8').splitlines(keepends=True)[:3]
        observed = asdict(result)
        checks = {'line_numbers': (result.start_line, result.end_line) == (1, 3),
                  'actual_content': result.content == ''.join(expected),
                  'within_budget': len(result.content.encode('utf-8')) <= 4096,
                  'continuation': result.truncated and result.next_start_line == 4}
    elif case in ('escape', 'symlink', 'large-file'):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'repo'
            root.mkdir()
            outside = base / 'repo2'
            outside.mkdir()
            external = outside / 'outside.py'
            external.write_text('outside-marker\n', encoding='utf-8')
            if case == 'escape':
                observed = {'parent': _attempt(root, '../repo2/outside.py'),
                            'similar_prefix_absolute': _attempt(root, external)}
                checks = {name: value.get('error_code') == 'permission_denied'
                          for name, value in observed.items()}
            elif case == 'symlink':
                link = root / 'link.py'
                try:
                    link.symlink_to(external)
                except (OSError, NotImplementedError) as exc:
                    blocked = {'code': 'symlink_unavailable', 'reason': str(exc)}
                    checks = {'symlink_verified': False}
                else:
                    observed = _attempt(root, link)
                    observed['symlink_created'] = link.is_symlink()
                    checks = {'link_exists': observed['symlink_created'],
                              'outside_denied': observed.get('error_code') == 'permission_denied'}
            else:
                large = root / 'large.py'
                large.write_bytes(b'x' * 65)
                observed = _attempt(root, large, max_bytes=64)
                observed.update({'file_bytes': large.stat().st_size, 'max_bytes': 64})
                checks = {'over_budget': observed['file_bytes'] > observed['max_bytes'],
                          'rejected': observed.get('error_code') == 'unsupported_content',
                          'no_content_returned': 'result' not in observed}
    else:
        raise ValueError('unknown L02 case')
    report = {'lesson': 'L02', 'case': case, 'observed': observed,
              'checks': checks, 'verified': bool(checks) and all(checks.values())}
    if blocked:
        report['blocked'] = blocked
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--list-cases', action='store_true')
    args = parser.parse_args()
    if args.list_cases:
        print(json.dumps({'lesson': 'L02', 'cases': CASES}))
        return 0
    if not args.case:
        parser.error('--case is required')
    report = run_case(args.case)
    print(json.dumps(report, ensure_ascii=True))
    return 2 if 'blocked' in report else (0 if report['verified'] else 1)


if __name__ == '__main__':
    raise SystemExit(main())
