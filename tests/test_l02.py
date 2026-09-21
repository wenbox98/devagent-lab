from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from devagent.demos.l02 import FIXTURE_ROOT, run_case
from devagent.tools.files import FileAccessError, list_files, read_file


class TestL02WorkspaceFiles(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'repo'
        self.root.mkdir()
        self.source = self.root / 'sample.py'
        self.source.write_bytes('first\n第二行\nthird\nlast'.encode('utf-8'))
        self.outside = self.base / 'repo2'
        self.outside.mkdir()
        (self.outside / 'secret.py').write_text('external', encoding='utf-8')

    def assert_error(self, code, path, **kwargs):
        with self.assertRaises(FileAccessError) as caught:
            read_file(self.root, path, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_read_actual_content_and_inclusive_one_based_range(self):
        result = read_file(self.root, 'sample.py', 2, 3)
        self.assertEqual((result.path, result.start_line, result.end_line), ('sample.py', 2, 3))
        self.assertEqual(result.content, '第二行\nthird\n')
        self.assertTrue(result.truncated)
        self.assertEqual(result.next_start_line, 4)
        resumed = read_file(self.root, 'sample.py', result.next_start_line)
        self.assertEqual(resumed.content, 'last')
        self.assertFalse(resumed.truncated)
        self.assertIsNone(resumed.next_start_line)
        self.source.write_bytes(b'changed\n')
        self.assertEqual(read_file(self.root, 'sample.py').content, 'changed\n')

    def test_max_lines_windows_preserve_file_continuation_semantics(self):
        lines = [f'line {number}\n' for number in range(1, 101)]
        self.source.write_bytes(''.join(lines).encode('utf-8'))
        for start, end, expected_end, count, truncated, next_line in (
            (1, 100, 50, 50, True, 51),
            (1, 50, 50, 50, True, 51),
            (80, 150, 100, 21, False, None),
        ):
            with self.subTest(start=start, end=end):
                result = read_file(self.root, 'sample.py', start, end, max_lines=50)
                self.assertEqual((result.start_line, result.end_line), (start, expected_end))
                self.assertEqual(result.content, ''.join(lines[start - 1:expected_end]))
                self.assertEqual(len(result.content.splitlines()), count)
                self.assertEqual(result.truncated, truncated)
                self.assertEqual(result.next_start_line, next_line)

    def test_invalid_max_lines_rejected_before_open(self):
        with patch.object(Path, 'open', side_effect=AssertionError('invalid budget must not open')):
            for budget in (0, -1, True, 2.5):
                with self.subTest(budget=budget), self.assertRaises(ValueError):
                    read_file(self.root, 'sample.py', max_lines=budget)

    def test_default_and_custom_max_lines_with_continuation(self):
        lines = [f'{number}\n' for number in range(1, 101)]
        self.source.write_bytes(''.join(lines).encode('utf-8'))
        first = read_file(self.root, 'sample.py')
        self.assertEqual(first.content, ''.join(lines[:50]))
        self.assertEqual(first.next_start_line, 51)
        rest = read_file(self.root, 'sample.py', first.next_start_line)
        self.assertEqual(rest.content, ''.join(lines[50:]))
        self.assertFalse(rest.truncated)
        self.assertIsNone(rest.next_start_line)
        short = read_file(self.root, 'sample.py', max_lines=3)
        self.assertEqual(short.content, ''.join(lines[:3]))
        self.assertEqual(short.next_start_line, 4)

    def test_list_size_is_whole_file_bytes_after_line_limit(self):
        raw = ''.join(f'第{number}行\r\n' for number in range(1, 101)).encode('utf-8')
        self.source.write_bytes(raw)
        returned = read_file(self.root, 'sample.py')
        self.assertEqual(len(returned.content.splitlines()), 50)
        self.assertGreater(len(raw), len(returned.content.encode('utf-8')))
        self.assertEqual(list_files(self.root), [{'path': 'sample.py', 'size_bytes': len(raw)}])

    def test_crlf_content_is_preserved(self):
        self.source.write_bytes(b'first\r\nsecond\r\n')
        result = read_file(self.root, 'sample.py', 2, 2)
        self.assertEqual(result.content, 'second\r\n')
        self.assertEqual((result.start_line, result.end_line), (2, 2))

    def test_empty_and_beyond_eof_have_no_invented_lines(self):
        self.source.write_bytes(b'')
        result = read_file(self.root, 'sample.py')
        self.assertEqual((result.content, result.start_line, result.end_line), ('', 1, 0))
        result = read_file(self.root, 'sample.py', 8)
        self.assertEqual((result.content, result.end_line, result.next_start_line), ('', 7, None))

    def test_invalid_ranges_and_budgets_are_rejected(self):
        for start, end in ((0, None), (-1, None), (True, None), (2, 1), (1, False), (1, 2.5)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                read_file(self.root, 'sample.py', start, end)
        for budget in (0, -1, True, 2.5):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                read_file(self.root, 'sample.py', max_bytes=budget)

    def test_parent_prefix_and_absolute_escapes_never_open_content(self):
        with patch.object(Path, 'open', side_effect=AssertionError('must authorize before open')):
            for path in ('../repo2/secret.py', self.outside / 'secret.py',
                         self.base / 'missing.py', '../missing.py'):
                with self.subTest(path=path):
                    self.assert_error('permission_denied', path)

    def test_canonical_root_and_internal_absolute_path(self):
        result = read_file(self.root / '..' / 'repo', self.source.resolve())
        self.assertEqual(result.path, 'sample.py')

    def test_missing_file_and_missing_root_are_distinct_from_denial(self):
        self.assert_error('not_found', 'missing.py')
        with self.assertRaises(FileAccessError) as caught:
            list_files(self.root / 'missing')
        self.assertEqual(caught.exception.code, 'not_found')

    def test_nontext_invalid_utf8_and_directory_are_unsupported(self):
        for content in (b'\xff\xfe', b'a\x00b', b'\x01binary'):
            self.source.write_bytes(content)
            self.assert_error('unsupported_content', 'sample.py')
        self.assert_error('unsupported_content', '.')
        (self.root / 'image.bin').write_bytes(b'plain')
        self.assert_error('unsupported_content', 'image.bin')

    def test_hidden_and_alternate_stream_paths_denied(self):
        (self.root / '.secret.py').write_text('hidden', encoding='utf-8')
        self.assert_error('permission_denied', '.secret.py')
        self.assert_error('permission_denied', 'sample.py:secret')

    def test_budget_exact_limit_and_oversized_file_before_open(self):
        self.source.write_bytes(b'x' * 64)
        self.assertEqual(len(read_file(self.root, 'sample.py', max_bytes=64).content), 64)
        self.source.write_bytes(b'x' * 65)
        with patch.object(Path, 'open', side_effect=AssertionError('oversized file must not open')):
            self.assert_error('unsupported_content', 'sample.py', max_bytes=64)

    def test_growing_file_still_reads_at_most_budget_plus_one(self):
        self.source.write_bytes(b'x')
        original_open = Path.open
        sizes = []

        class TrackedReader:
            def __enter__(inner):
                inner.stream = original_open(self.source, 'rb', buffering=0)
                return inner

            def __exit__(inner, *args):
                inner.stream.close()

            def fileno(inner):
                return inner.stream.fileno()

            def read(inner, size):
                sizes.append(size)
                self.assertEqual(size, 65)
                return inner.stream.read(size)

        def grow_then_open(path, *args, **kwargs):
            with original_open(path, 'wb') as writer:
                writer.write(b'x' * 1000)
            return TrackedReader()

        with patch.object(Path, 'open', grow_then_open):
            self.assert_error('unsupported_content', 'sample.py', max_bytes=64)
        self.assertEqual(sizes, [65])

    def test_os_permission_error_has_stable_code(self):
        with patch.object(Path, 'open', side_effect=PermissionError('denied')):
            self.assert_error('permission_denied', 'sample.py')

    def test_list_only_exposes_allowed_files(self):
        (self.root / '.git').mkdir()
        (self.root / '.git' / 'config.py').write_text('hidden', encoding='utf-8')
        (self.root / 'bad.py').write_bytes(b'\xff')
        (self.root / 'huge.py').write_bytes(b'x' * 65537)
        (self.root / 'image.bin').write_bytes(b'abc')
        self.assertEqual(list_files(self.root), [
            {'path': 'sample.py', 'size_bytes': self.source.stat().st_size}])

    def test_external_symlink_file_and_directory_are_denied(self):
        link = self.root / 'link.py'
        directory_link = self.root / 'linked'
        try:
            link.symlink_to(self.outside / 'secret.py')
            directory_link.symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'symlink unavailable: {exc}')
        self.assertTrue(link.is_symlink())
        self.assert_error('permission_denied', link)
        self.assert_error('permission_denied', 'linked/secret.py')
        self.assertEqual([item['path'] for item in list_files(self.root)], ['sample.py'])

    def test_fixtures_remain_readable_with_deliberate_bug(self):
        result = read_file(FIXTURE_ROOT, 'pagination.py', end_line=3)
        self.assertEqual((result.start_line, result.end_line), (1, 3))
        self.assertIn('def page(items, page_no, size):', result.content)
        self.assertIn('start = page_no * size', read_file(FIXTURE_ROOT, 'pagination.py').content)
        self.assertIn('def page(report_name):', read_file(FIXTURE_ROOT, 'reporting.py').content)

    def test_demo_verdicts_depend_on_real_results(self):
        for case in ('read-lines', 'escape', 'large-file'):
            with self.subTest(case=case):
                report = run_case(case)
                self.assertTrue(report['checks'])
                self.assertTrue(report['verified'])
                self.assertEqual(report['verified'], all(report['checks'].values()))
        incorrect = replace(read_file(FIXTURE_ROOT, 'pagination.py', end_line=3), content='invented')
        with patch('devagent.demos.l02.read_file', return_value=incorrect):
            self.assertFalse(run_case('read-lines')['verified'])

    def test_symlink_demo_unavailable_is_blocked_not_passed(self):
        with patch.object(Path, 'symlink_to', side_effect=NotImplementedError('unavailable')):
            report = run_case('symlink')
        self.assertFalse(report['verified'])
        self.assertEqual(report['blocked']['code'], 'symlink_unavailable')


if __name__ == '__main__':
    unittest.main()
