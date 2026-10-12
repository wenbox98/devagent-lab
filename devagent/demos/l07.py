"""L07 offline edits run only in a temporary copy of the exercise fixture."""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory

from ..tools.edit import WorkspaceEditor
from ..tools.files import read_file

CASES = ('apply', 'stale-hash', 'ambiguous-match', 'rollback-conflict')
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / 'fixtures' / 'tiny_repo'
OLD_TEXT = 'start = page_no * size'
NEW_TEXT = 'start = (page_no - 1) * size'


def run_case(case: str) -> dict:
    if case not in CASES:
        raise ValueError('unknown L07 case')
    with TemporaryDirectory() as directory:
        root = Path(directory) / 'repo'
        copytree(FIXTURE_ROOT, root)
        target = root / 'pagination.py'
        editor = WorkspaceEditor(root)
        if case == 'ambiguous-match':
            target.write_bytes(target.read_bytes() + f'\n# {OLD_TEXT}\n'.encode('utf-8'))
        read = read_file(root, 'pagination.py')
        before = target.read_bytes()
        if case == 'stale-hash':
            target.write_bytes(before + b'\n# another developer\n')
        before_attempt = target.read_bytes()
        result = editor.apply_edit('pagination.py', read.source_hash, OLD_TEXT, NEW_TEXT, 'demo-L07')
        observed = {'request': {'path': 'pagination.py', 'expected_hash': read.source_hash,
                                'old_text': OLD_TEXT, 'new_text': NEW_TEXT, 'operation_id': 'demo-L07'},
                    'apply': asdict(result)}
        if case == 'apply':
            after = target.read_bytes()
            checks = {'applied': result.ok,
                      'only_expected_change': after == before.replace(OLD_TEXT.encode(), NEW_TEXT.encode(), 1),
                      'before_hash': result.before_hash == sha256(before).hexdigest(),
                      'after_hash': result.after_hash == sha256(after).hexdigest(),
                      'real_diff': f'-    {OLD_TEXT}' in result.diff and f'+    {NEW_TEXT}' in result.diff,
                      'no_temp_left': not list(root.glob('.devagent-edit-*'))}
        elif case == 'rollback-conflict':
            target.write_bytes(target.read_bytes() + b'\n# newer developer change\n')
            latest = target.read_bytes()
            rollback = editor.rollback('demo-L07')
            observed['rollback'] = asdict(rollback)
            checks = {'applied_first': result.ok,
                      'rollback_rejected': not rollback.ok and rollback.error.code == 'rollback_conflict',
                      'latest_bytes_preserved': target.read_bytes() == latest,
                      'current_version': rollback.before_hash == sha256(latest).hexdigest()}
        else:
            code = 'stale_version' if case == 'stale-hash' else 'ambiguous_match'
            checks = {'write_rejected': not result.ok and result.error.code == code,
                      'bytes_preserved': target.read_bytes() == before_attempt,
                      'current_version': result.before_hash == sha256(before_attempt).hexdigest(),
                      'no_success_evidence': result.after_hash is None and result.diff == '',
                      'no_temp_left': not list(root.glob('.devagent-edit-*'))}
        observed['final_hash'] = sha256(target.read_bytes()).hexdigest()
    return {'lesson': 'L07', 'case': case, 'observed': observed,
            'checks': checks, 'verified': bool(checks) and all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--list-cases', action='store_true')
    args = parser.parse_args()
    if args.list_cases:
        print(json.dumps({'lesson': 'L07', 'cases': CASES}))
        return 0
    if not args.case:
        parser.error('--case is required')
    try:
        report = run_case(args.case)
    except OSError:
        report = {'lesson': 'L07', 'case': args.case, 'observed': {},
                  'checks': {'environment_available': False}, 'verified': False,
                  'blocked': {'code': 'fixture_environment_unavailable',
                              'reason': 'cannot prepare or inspect the temporary exercise copy'}}
    print(json.dumps(report, ensure_ascii=True))
    return 2 if 'blocked' in report else (0 if report['verified'] else 1)


if __name__ == '__main__':
    raise SystemExit(main())
