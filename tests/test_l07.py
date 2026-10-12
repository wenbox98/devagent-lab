from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

from devagent.demos import l07
from devagent.tools.edit import WorkspaceEditor
from devagent.tools.files import read_file
from devagent.tools.protocol import ToolCall
from devagent.tools.registry import ToolRegistry


class TestL07SafeEdits(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'repo'
        copytree(l07.FIXTURE_ROOT, self.root)
        self.target = self.root / 'pagination.py'
        self.before = self.target.read_bytes()
        self.version = sha256(self.before).hexdigest()
        self.editor = WorkspaceEditor(self.root)

    def apply(self, **changes):
        arguments = {'path': 'pagination.py', 'expected_hash': self.version,
                     'old_text': l07.OLD_TEXT, 'new_text': l07.NEW_TEXT, 'operation_id': 'op-1'}
        arguments.update(changes)
        return self.editor.apply_edit(**arguments)

    def assert_rejected_unchanged(self, code, **changes):
        before = self.target.read_bytes()
        with patch('devagent.tools.edit._atomic_replace', side_effect=AssertionError('must reject before write')):
            result = self.apply(**changes)
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, code)
        self.assertIsNone(result.after_hash)
        self.assertEqual(result.diff, '')
        self.assertEqual(self.target.read_bytes(), before)
        self.assertFalse(list(self.root.glob('.devagent-edit-*')))
        return result

    def test_apply_returns_actual_hashes_diff_and_only_expected_change(self):
        result = self.apply()
        expected = self.before.replace(l07.OLD_TEXT.encode(), l07.NEW_TEXT.encode(), 1)
        self.assertTrue(result.ok)
        self.assertIsNone(result.error)
        self.assertEqual((result.path, result.operation_id), ('pagination.py', 'op-1'))
        self.assertEqual(self.target.read_bytes(), expected)
        self.assertEqual(result.before_hash, self.version)
        self.assertEqual(result.after_hash, sha256(expected).hexdigest())
        self.assertIn('--- a/pagination.py\n+++ b/pagination.py\n', result.diff)
        self.assertIn('-    start = page_no * size', result.diff)
        self.assertIn('+    start = (page_no - 1) * size', result.diff)
        self.assertEqual(read_file(self.root, 'pagination.py').source_hash, result.after_hash)

    def test_stale_version_keeps_new_developer_bytes(self):
        self.target.write_bytes(self.before + b'\n# another developer\n')
        result = self.assert_rejected_unchanged('stale_version')
        self.assertEqual(result.before_hash, sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(self.editor.rollback('op-1').error.code, 'unknown_operation')

    def test_missing_fragment_rejected(self):
        self.assert_rejected_unchanged('no_match', old_text='missing-fragment')

    def test_duplicate_fragment_rejected(self):
        self.target.write_bytes(self.before + f'\n# {l07.OLD_TEXT}\n'.encode())
        self.assert_rejected_unchanged('ambiguous_match', expected_hash=sha256(self.target.read_bytes()).hexdigest())

    def test_overlapping_fragment_is_also_ambiguous(self):
        self.target.write_bytes(b'aaa')
        self.assert_rejected_unchanged('ambiguous_match', expected_hash=sha256(b'aaa').hexdigest(),
                                       old_text='aa', new_text='b')

    def test_workspace_escape_and_similar_prefix_rejected_before_open(self):
        outside = self.base / 'repo2'
        outside.mkdir()
        secret = outside / 'secret.py'
        secret.write_bytes(b'external')
        for path in ('../repo2/secret.py', secret):
            with self.subTest(path=path), patch.object(Path, 'open', side_effect=AssertionError('unauthorized open')):
                result = self.apply(path=path)
                self.assertEqual(result.error.code, 'permission_denied')
                self.assertEqual(result.path, '')
        self.assertEqual(secret.read_bytes(), b'external')
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_missing_hidden_binary_and_oversized_files_keep_read_policy(self):
        for name, raw, code in (('.hidden.py', b'text', 'permission_denied'),
                                ('binary.py', b'\xff', 'unsupported_content'),
                                ('control.py', b'a\x00b', 'unsupported_content'),
                                ('large.py', b'x' * 65537, 'unsupported_content'),
                                ('image.bin', b'text', 'unsupported_content')):
            target = self.root / name
            target.write_bytes(raw)
            with self.subTest(name=name):
                result = self.apply(path=name, expected_hash=sha256(raw).hexdigest(), old_text='text')
                self.assertEqual(result.error.code, code)
                self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(self.apply(path='missing.py').error.code, 'not_found')
        self.assertEqual(self.apply(path='.').error.code, 'unsupported_content')

    def test_host_budget_applies_to_generated_content(self):
        self.editor = WorkspaceEditor(self.root, max_bytes=len(self.before))
        self.assert_rejected_unchanged('unsupported_content', new_text='x' * (len(self.before) + 1))
        for text in ('bad\x00text', '\ud800'):
            with self.subTest(text=repr(text)):
                self.assert_rejected_unchanged('unsupported_content', new_text=text)

    def test_invalid_inputs_do_not_write(self):
        for changes in ({'expected_hash': ''}, {'expected_hash': 'x' * 64},
                        {'old_text': ''}, {'old_text': None}, {'new_text': None},
                        {'operation_id': ''}, {'operation_id': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.apply(**changes)
        for budget in (0, -1, True, 2.5):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                WorkspaceEditor(self.root, max_bytes=budget)
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_replacement_is_same_directory_complete_and_target_stays_old_until_replace(self):
        original_replace = os.replace
        observations = []

        def inspect(source, destination):
            source, destination = Path(source), Path(destination)
            self.assertEqual(source.parent, self.target.parent)
            self.assertEqual(destination, self.target)
            self.assertEqual(self.target.read_bytes(), self.before)
            self.assertEqual(source.read_bytes(), self.before.replace(l07.OLD_TEXT.encode(), l07.NEW_TEXT.encode(), 1))
            observations.append(True)
            original_replace(source, destination)

        with patch('devagent.tools.edit.os.replace', side_effect=inspect):
            self.assertTrue(self.apply().ok)
        self.assertEqual(observations, [True])
        self.assertFalse(list(self.root.glob('.devagent-edit-*')))

    def test_temp_creation_failure_keeps_target(self):
        with patch('devagent.tools.edit.tempfile.NamedTemporaryFile', side_effect=OSError('creation failed')):
            result = self.apply()
        self.assertEqual(result.error.code, 'io_error')
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertFalse(list(self.root.glob('.devagent-edit-*')))

    def test_write_flush_or_replace_failure_cleans_temp_and_keeps_target(self):
        # Basic IO-failure protection. Real read-only/permission experiments remain
        # the learner's independent variant; no OS permissions are changed here.
        for boundary in ('os.fsync', 'os.replace'):
            with self.subTest(boundary=boundary):
                with patch(f'devagent.tools.edit.{boundary}', side_effect=OSError('injected failure')):
                    result = self.apply()
                self.assertFalse(result.ok)
                self.assertEqual(result.error.code, 'io_error')
                self.assertEqual(self.target.read_bytes(), self.before)
                self.assertFalse(list(self.root.glob('.devagent-edit-*')))
                self.assertEqual(self.editor.rollback('op-1').error.code, 'unknown_operation')

    def test_short_temp_write_is_rejected_and_cleaned(self):
        import tempfile
        original_factory = tempfile.NamedTemporaryFile

        class ShortWrite:
            def __enter__(inner):
                inner.stream = original_factory(mode='wb', dir=self.root, prefix='.devagent-edit-', delete=False)
                inner.name = inner.stream.name
                return inner

            def write(inner, raw):
                return inner.stream.write(raw[:3])

            def __exit__(inner, *args):
                inner.stream.close()

        with patch('devagent.tools.edit.tempfile.NamedTemporaryFile', return_value=ShortWrite()):
            result = self.apply()
        self.assertEqual(result.error.code, 'io_error')
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertFalse(list(self.root.glob('.devagent-edit-*')))

    def test_internal_programming_error_is_not_hidden(self):
        with patch('devagent.tools.edit._atomic_replace', side_effect=RuntimeError('bug')):
            with self.assertRaises(RuntimeError):
                self.apply()
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_rollback_restores_exact_bytes_with_reverse_hashes_and_diff(self):
        applied = self.apply()
        restored = self.editor.rollback('op-1')
        self.assertTrue(restored.ok)
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual((restored.before_hash, restored.after_hash), (applied.after_hash, applied.before_hash))
        self.assertIn('+    start = page_no * size', restored.diff)
        self.assertEqual(self.editor.rollback('op-1').error.code, 'unknown_operation')

    def test_rollback_conflict_keeps_latest_bytes(self):
        self.assertTrue(self.apply().ok)
        latest = self.target.read_bytes() + b'\n# subsequent developer\n'
        self.target.write_bytes(latest)
        with patch('devagent.tools.edit._atomic_replace', side_effect=AssertionError('conflict must not write')):
            result = self.editor.rollback('op-1')
        self.assertEqual(result.error.code, 'rollback_conflict')
        self.assertIsNone(result.after_hash)
        self.assertEqual(result.before_hash, sha256(latest).hexdigest())
        self.assertEqual(self.target.read_bytes(), latest)

    def test_rollback_io_failure_keeps_undo_for_later_retry(self):
        self.assertTrue(self.apply().ok)
        after = self.target.read_bytes()
        with patch('devagent.tools.edit.os.replace', side_effect=OSError('failed replacement')):
            result = self.editor.rollback('op-1')
        self.assertEqual(result.error.code, 'io_error')
        self.assertEqual(self.target.read_bytes(), after)
        self.assertFalse(list(self.root.glob('.devagent-edit-*')))
        self.assertTrue(self.editor.rollback('op-1').ok)
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_rollback_reauthorizes_saved_path(self):
        self.assertTrue(self.apply().ok)
        self.target.unlink()
        with patch('devagent.tools.edit._atomic_replace', side_effect=AssertionError('missing file must not write')):
            self.assertEqual(self.editor.rollback('op-1').error.code, 'not_found')
        self.assertFalse(self.target.exists())

    def test_operation_record_cannot_be_overwritten_or_fabricated(self):
        applied = self.apply()
        self.assert_rejected_unchanged('operation_conflict', expected_hash=applied.after_hash,
                                       old_text=l07.NEW_TEXT, new_text='other')
        self.assertEqual(WorkspaceEditor(self.root).rollback('op-1').error.code, 'unknown_operation')
        self.assertTrue(self.editor.rollback('op-1').ok)
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_crlf_bom_and_deletion_preserve_exact_unmodified_bytes(self):
        raw = b'\xef\xbb\xbffirst\r\nsecond\r\nthird\r\n'
        self.target.write_bytes(raw)
        result = self.apply(expected_hash=sha256(raw).hexdigest(), old_text='second\r\n', new_text='')
        self.assertTrue(result.ok)
        self.assertEqual(self.target.read_bytes(), b'\xef\xbb\xbffirst\r\nthird\r\n')
        self.assertTrue(self.editor.rollback('op-1').ok)
        self.assertEqual(self.target.read_bytes(), raw)

    def test_diff_separates_changed_lines_without_final_newline(self):
        self.target.write_bytes(b'old')
        result = self.apply(expected_hash=sha256(b'old').hexdigest(), old_text='old', new_text='new')
        self.assertTrue(result.ok)
        self.assertIn('-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n', result.diff)
        self.assertEqual(self.target.read_bytes(), b'new')

    def test_cooperating_editors_share_lock_and_cannot_both_commit_same_version(self):
        other = WorkspaceEditor(self.root / '..' / 'repo')
        self.assertIs(self.editor._lock, other._lock)
        start = Barrier(2)

        def write(editor, operation):
            start.wait(timeout=5)
            return editor.apply_edit('pagination.py', self.version, l07.OLD_TEXT, l07.NEW_TEXT, operation)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write, self.editor, 'one'), pool.submit(write, other, 'two')]
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(sum(result.ok for result in results), 1)
        self.assertEqual([result.error.code for result in results if not result.ok], ['stale_version'])
        self.assertEqual(self.target.read_bytes(), self.before.replace(l07.OLD_TEXT.encode(), l07.NEW_TEXT.encode(), 1))

    def test_model_registry_stays_read_only_and_cannot_override_host_root(self):
        registry = ToolRegistry(self.root)
        self.assertEqual({spec.name for spec in registry.specs}, {'read_file', 'list_files', 'search_text'})
        result = registry.execute(ToolCall('write', 'apply_edit', {'path': 'pagination.py'}))
        self.assertEqual(result.error.code, 'unknown_tool')
        self.assertEqual(registry.handler_calls, 0)
        result = registry.execute(ToolCall('read', 'read_file', {'path': 'pagination.py', 'root': str(self.base)}))
        self.assertEqual(result.error.code, 'invalid_args')
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_demos_use_real_results_preserve_fixtures_and_derive_verdict(self):
        fixture_bytes = {p.name: p.read_bytes() for p in l07.FIXTURE_ROOT.iterdir() if p.is_file()}
        for case in l07.CASES:
            with self.subTest(case=case):
                report = l07.run_case(case)
                self.assertTrue(report['verified'])
                self.assertEqual(report['verified'], all(report['checks'].values()))
        actual = self.apply()
        with patch('devagent.demos.l07.WorkspaceEditor.apply_edit', return_value=replace(actual, diff='invented')):
            self.assertFalse(l07.run_case('apply')['verified'])
        self.assertEqual({p.name: p.read_bytes() for p in l07.FIXTURE_ROOT.iterdir() if p.is_file()}, fixture_bytes)

    def test_demo_json_list_and_exit_codes(self):
        for arguments, expected in ((['--list-cases'], 0), (['--case', 'apply'], 0)):
            with self.subTest(arguments=arguments), patch('sys.argv', ['l07', *arguments]):
                with patch('sys.stdout', new_callable=io.StringIO) as output:
                    self.assertEqual(l07.main(), expected)
                self.assertEqual(json.loads(output.getvalue())['lesson'], 'L07')
        for report, expected in (({'verified': False}, 1), ({'verified': False, 'blocked': {}}, 2)):
            with patch('sys.argv', ['l07', '--case', 'apply']), patch('sys.stdout', new_callable=io.StringIO):
                with patch('devagent.demos.l07.run_case', return_value=report):
                    self.assertEqual(l07.main(), expected)
        with patch('sys.argv', ['l07', '--case', 'apply']), patch('sys.stdout', new_callable=io.StringIO) as output:
            with patch('devagent.demos.l07.copytree', side_effect=FileNotFoundError):
                self.assertEqual(l07.main(), 2)
            self.assertFalse(json.loads(output.getvalue())['verified'])


if __name__ == '__main__':
    unittest.main()
