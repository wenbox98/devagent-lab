from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from devagent.agent.citations import Citation, CitationError, citation_from_read, validate_citation
from devagent.agent.loop import resume_agent, run_agent
from devagent.demos.l04 import observations, proposal
from devagent.demos.l05 import CASES, FIXTURE_ROOT, main, run_case, scripted_locator
from devagent.fake_model import ScriptedModelClient
from devagent.models import ModelResponse
from devagent.tools import files, search
from devagent.tools.protocol import ToolCall
from devagent.tools.registry import ToolRegistry


class TestL05SearchEvidence(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'repo'
        self.root.mkdir()
        self.path = self.root / 'a.py'
        self.path.write_bytes(b'first\nneedle here\nlast\n')
        self.registry = ToolRegistry(self.root)

    def evidence(self):
        return citation_from_read(files.read_file(self.root, 'a.py'))

    def answer(self, request):
        citations = tuple(citation_from_read(files.FileReadResult(**r.data)) for r in observations(request)
                          if r.ok and isinstance(r.data, dict) and r.data.get('source_hash'))
        return ModelResponse('based on read evidence', 'scripted', citations=citations)

    def test_actual_match_path_line_and_snippet(self):
        result = search.search_text(self.root, 'needle')
        self.assertEqual(result['matches'], [{'path': 'a.py', 'line': 2, 'snippet': 'needle here'}])
        self.assertFalse(result['truncated'])
        self.assertEqual(result['scanned_files'], 1)

    def test_unique_match_on_line_55_is_not_limited_by_read_window(self):
        lines = ['plain\n'] * 65
        lines[54] = 'UNIQUE_LINE_55\n'
        self.path.write_bytes(''.join(lines).encode())
        self.assertNotIn('UNIQUE_LINE_55', files.read_file(self.root, 'a.py').content)
        result = search.search_text(self.root, 'UNIQUE_LINE_55')
        self.assertEqual(result['matches'], [{'path': 'a.py', 'line': 55, 'snippet': 'UNIQUE_LINE_55'}])

    def test_result_cap_is_conservatively_truncated_even_at_exact_count(self):
        self.path.write_bytes(b'needle\nneedle\nneedle\n')
        for limit in (1, 2, 3):
            with self.subTest(limit=limit):
                result = search.search_text(self.root, 'needle', max_results=limit)
                self.assertEqual(len(result['matches']), limit)
                self.assertTrue(result['truncated'])
        self.assertFalse(search.search_text(self.root, 'needle', max_results=4)['truncated'])

    def test_invalid_search_parameters_are_rejected_before_filesystem(self):
        cases = [{'max_results': x} for x in (0, -1, True, 2.5, 101)]
        cases += [{'query': x} for x in ('', ' ', None, 'x' * 257)]
        cases += [{'include_globs': x} for x in ([], '*.py', [1], ['../*.py'], ['/repo2/*'],
                                                ['C:/repo2/*'], ['src\\*.py'], ['x' * 257])]
        with patch('devagent.tools.search.os.scandir') as scan:
            for args in cases:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    search.search_text(self.root, **{'query': 'needle', **args})
            scan.assert_not_called()

    def test_include_globs_narrows_paths_and_supports_zero_or_more_dirs(self):
        (self.root / 'src' / 'nested').mkdir(parents=True)
        (self.root / 'src' / 'direct.py').write_bytes(b'needle')
        (self.root / 'src' / 'nested' / 'deep.py').write_bytes(b'needle')
        (self.root / 'note.md').write_bytes(b'needle')
        paths = lambda patterns: {m['path'] for m in search.search_text(self.root, 'needle', patterns)['matches']}
        self.assertEqual(paths(['src/**/*.py']), {'src/direct.py', 'src/nested/deep.py'})
        self.assertEqual(paths(['*.md']), {'note.md'})
        self.assertEqual(paths(['*.py']), {'a.py', 'src/direct.py', 'src/nested/deep.py'})

    def test_no_match_is_success_with_empty_matches(self):
        result = self.registry.execute(ToolCall('none', 'search_text', {'query': 'absent'}))
        self.assertTrue(result.ok)
        self.assertIsNone(result.error)
        self.assertEqual(result.data['matches'], [])
        self.assertFalse(result.data['truncated'])

    def test_search_io_failure_is_not_successful_empty_result(self):
        for error, code in ((PermissionError('private path'), 'permission_denied'), (OSError('broken'), 'io_error')):
            with self.subTest(code=code), patch('devagent.tools.search.os.scandir', side_effect=error):
                result = self.registry.execute(ToolCall('bad', 'search_text', {'query': 'needle'}))
            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, code)
            self.assertIsNone(result.data)
            self.assertNotIn('private path', result.error.message)

    def test_content_read_failure_is_not_silently_skipped(self):
        with patch('devagent.tools.files._read_snapshot', side_effect=files.FileAccessError('io_error', 'failed')):
            result = self.registry.execute(ToolCall('bad', 'search_text', {'query': 'needle'}))
        self.assertEqual(result.error.code, 'io_error')

    def test_hidden_binary_oversized_and_unsupported_files_are_excluded(self):
        (self.root / '.private').mkdir()
        (self.root / '.private' / 'hidden.py').write_bytes(b'needle')
        for name, raw in (('.hidden.py', b'needle'), ('bad.py', b'needle\xff'), ('binary.py', b'needle\x00'),
                          ('image.bin', b'needle'), ('large.py', b'needle' * 12000)):
            (self.root / name).write_bytes(raw)
        with patch('devagent.tools.files._read_snapshot', wraps=files._read_snapshot) as read:
            result = search.search_text(self.root, 'needle')
        self.assertEqual([m['path'] for m in result['matches']], ['a.py'])
        self.assertFalse(any(Path(c.args[1]).name in {'.hidden.py', 'image.bin', 'hidden.py'} for c in read.call_args_list))

    def test_search_skips_symlink_entries_without_opening_or_following(self):
        link = MagicMock()
        link.name, link.path = 'linked.py', str(self.root / 'linked.py')
        link.is_symlink.return_value = True
        with patch('devagent.tools.search.os.scandir') as scan, patch('devagent.tools.files._read_snapshot') as read:
            scan.return_value.__enter__.return_value = iter([link])
            result = search.search_text(self.root, 'needle')
        read.assert_not_called()
        scan.assert_called_once()
        self.assertEqual(result['matches'], [])

    def test_search_skips_junction_directories(self):
        (self.root / 'linked').mkdir()
        (self.root / 'linked' / 'secret.py').write_bytes(b'needle')
        with patch.object(Path, 'is_junction', lambda p: p.name == 'linked'):
            result = search.search_text(self.root, 'needle')
        self.assertEqual([m['path'] for m in result['matches']], ['a.py'])

    def test_root_cannot_be_expanded_by_model_and_path_authorization_is_reused(self):
        outside = self.base / 'repo2'
        outside.mkdir()
        (outside / 'secret.py').write_bytes(b'needle')
        for field in ('root', 'workspace', 'max_files', 'max_bytes', 'max_entries', 'allow_all', 'principal'):
            result = self.registry.execute(ToolCall('bad', 'search_text', {'query': 'needle', field: str(outside)}))
            self.assertEqual(result.error.code, 'invalid_args')
        self.assertEqual(self.registry.handler_calls, 0)
        with patch('devagent.tools.files._authorize', wraps=files._authorize) as authorize:
            result = search.search_text(self.root, 'needle')
        self.assertTrue(authorize.called)
        self.assertEqual([m['path'] for m in result['matches']], ['a.py'])

    def test_file_entry_and_depth_budgets_report_incomplete(self):
        for i in range(4):
            (self.root / f'extra{i}.py').write_bytes(b'no match')
        with patch.object(search, 'MAX_FILES', 2), patch('devagent.tools.files._read_snapshot', wraps=files._read_snapshot) as read:
            result = search.search_text(self.root, 'absent')
        self.assertEqual(read.call_count, 2)
        self.assertTrue(result['truncated'])
        with patch.object(search, 'MAX_ENTRIES', 1):
            self.assertTrue(search.search_text(self.root, 'absent')['truncated'])
        (self.root / 'deeper').mkdir()
        with patch.object(search, 'MAX_DEPTH', 0):
            self.assertTrue(search.search_text(self.root, 'absent')['truncated'])

    def test_missing_workspace_is_failure(self):
        result = ToolRegistry(self.root / 'missing').execute(ToolCall('s', 'search_text', {'query': 'x'}))
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, 'not_found')

    def test_hash_is_stable_full_file_raw_sha256_not_window_hash(self):
        raw = b'first\r\nneedle here\r\nlast\r\n'
        self.path.write_bytes(raw)
        first = files.read_file(self.root, 'a.py', 2, 2)
        self.assertEqual(first.source_hash, sha256(raw).hexdigest())
        self.assertNotEqual(first.source_hash, sha256(first.content.encode()).hexdigest())
        self.assertEqual(first.source_hash, files.read_file(self.root, 'a.py').source_hash)
        self.path.write_bytes(raw + b'changed')
        self.assertNotEqual(first.source_hash, files.read_file(self.root, 'a.py').source_hash)

    def test_hash_and_content_use_one_snapshot_even_if_file_changes_after_read(self):
        raw = b'version A\nsecond\n'
        self.path.write_bytes(raw)
        original_open = Path.open
        opens, sizes = [], []

        class Reader:
            def __enter__(inner):
                inner.stream = original_open(self.path, 'rb', buffering=0)
                return inner

            def fileno(inner):
                return inner.stream.fileno()

            def read(inner, size):
                sizes.append(size)
                return inner.stream.read(size)

            def __exit__(inner, *args):
                inner.stream.close()
                with original_open(self.path, 'wb') as writer:
                    writer.write(b'version B\nchanged\n')

        def open_changed(path, *args, **kwargs):
            opens.append(path)
            return Reader()

        with patch.object(Path, 'open', open_changed):
            read = files.read_file(self.root, 'a.py', end_line=1)
        self.assertEqual(len(opens), 1)
        self.assertEqual(sizes, [files.DEFAULT_MAX_BYTES + 1])
        citation = citation_from_read(read)
        self.assertEqual((citation.source_hash, citation.content), (sha256(raw).hexdigest(), 'version A\n'))
        self.assertTrue(self.path.read_bytes().startswith(b'version B'))

    def test_read_window_and_list_whole_size_still_hold(self):
        raw = b'line\n' * 100
        self.path.write_bytes(raw)
        read = files.read_file(self.root, 'a.py')
        self.assertEqual((read.end_line, read.next_start_line, read.source_hash), (50, 51, sha256(raw).hexdigest()))
        self.assertEqual(files.list_files(self.root), [{'path': 'a.py', 'size_bytes': len(raw)}])
        self.assertIsNone(files.FileReadResult('a.py', 1, 1, 'old', False, None).source_hash)

    def test_valid_citation_and_invalid_line_content_fields(self):
        citation = self.evidence()
        self.assertIsNone(validate_citation(self.root, citation))
        for change in ({'start_line': 0}, {'start_line': True}, {'end_line': 999},
                       {'end_line': 1.5}, {'content': 'fabricated'}, {'source_hash': 'bad'}):
            with self.subTest(change=change), self.assertRaises(CitationError) as caught:
                validate_citation(self.root, replace(citation, **change))
            self.assertEqual(caught.exception.code, 'invalid_citation')

    def test_citation_path_stays_in_workspace_before_open(self):
        citation = self.evidence()
        for path in ('../repo2/a.py', str(self.base / 'repo2' / 'a.py')):
            with self.subTest(path=path), patch.object(Path, 'open', side_effect=AssertionError('escape')):
                with self.assertRaises(CitationError) as caught:
                    validate_citation(self.root, replace(citation, source_path=path))
                self.assertEqual(caught.exception.code, 'permission_denied')

    def test_citation_missing_unsupported_and_stale_are_distinct(self):
        citation = self.evidence()
        self.path.write_bytes(b'changed')
        with self.assertRaises(CitationError) as caught:
            validate_citation(self.root, citation)
        self.assertEqual(caught.exception.code, 'stale_evidence')
        self.path.write_bytes(b'\xff')
        with self.assertRaises(CitationError) as caught:
            validate_citation(self.root, citation)
        self.assertEqual(caught.exception.code, 'unsupported_content')
        self.path.unlink()
        with self.assertRaises(CitationError) as caught:
            validate_citation(self.root, citation)
        self.assertEqual(caught.exception.code, 'not_found')

    def test_fixed_registry_and_search_metadata_permissions(self):
        self.assertEqual({s.name for s in self.registry.specs}, {'read_file', 'list_files', 'search_text'})
        with patch('devagent.tools.registry.search_text', wraps=search.search_text) as handler:
            result = self.registry.execute(ToolCall('search', 'search_text', {
                'query': 'needle', 'client_note': 'debug', 'client_tags': ['L05']}))
        handler.assert_called_once_with(self.root.resolve(), query='needle')
        self.assertTrue(result.ok)
        for name in ('__import__', 'eval', 'getattr', 'os.system', 'unknown'):
            self.assertEqual(self.registry.execute(ToolCall('x', name, {})).error.code, 'unknown_tool')
        self.assertEqual(self.registry.handler_calls, 1)

    def test_search_schema_rejects_bad_parameters_before_handler(self):
        with patch('devagent.tools.registry.search_text') as handler:
            for args in ({}, {'query': ''}, {'query': 'x', 'max_results': True},
                         {'query': 'x', 'max_results': 101}, {'query': 'x', 'include_globs': None},
                         {'query': 'x', 'include_globs': ['../*']}, {'query': 'x', 'foo': 1}):
                self.assertEqual(self.registry.execute(ToolCall('x', 'search_text', args)).error.code, 'invalid_args')
            handler.assert_not_called()

    def test_agent_search_and_read_feedback_arrive_in_actual_requests(self):
        def choose(request):
            result = observations(request)[-1]
            self.assertEqual(result.call_id, 'search')
            self.assertEqual(result.data['matches'][0]['line'], 2)
            return proposal('read', 'read_file', {'path': result.data['matches'][0]['path']})
        client = ScriptedModelClient([proposal('search', 'search_text', {'query': 'needle'}), choose, self.answer])
        state = run_agent('find needle', client, self.registry)
        self.assertEqual((state.status, client.call_count), ('answered', 3))
        self.assertEqual(observations(client.requests[2])[-1].data['source_hash'], state.citations[0].source_hash)
        self.assertEqual(state.citations, (self.evidence(),))

    def test_unread_or_search_only_citations_cannot_be_fabricated(self):
        forged = self.evidence()  # Current, valid file; NOT read by this Agent conversation.
        final = ModelResponse('claim', 'scripted', citations=(forged,))
        for steps in ([final], [proposal('s', 'search_text', {'query': 'needle'}), final]):
            state = run_agent('claim', ScriptedModelClient(steps), self.registry)
            self.assertEqual((state.status, state.termination_reason, state.citations), ('failed', 'invalid_citation', ()))

    def test_modified_citation_content_cannot_pass_read_provenance(self):
        final = ModelResponse('claim', 'scripted', citations=(replace(self.evidence(), content='forged'),))
        state = run_agent('read', ScriptedModelClient([proposal('r', 'read_file', {'path': 'a.py'}), final]), self.registry)
        self.assertEqual(state.termination_reason, 'invalid_citation')

    def test_file_changed_between_read_and_final_is_rejected(self):
        def changed(request):
            answer = self.answer(request)
            self.path.write_bytes(b'changed version')
            return answer
        state = run_agent('read', ScriptedModelClient([proposal('r', 'read_file', {'path': 'a.py'}), changed]), self.registry)
        self.assertEqual((state.status, state.termination_reason, state.citations), ('failed', 'stale_evidence', ()))

    def test_multiple_citations_can_be_returned_from_actual_reads(self):
        (self.root / 'b.py').write_bytes(b'second file\n')
        calls = tuple(ToolCall(p, 'read_file', {'path': p}) for p in ('a.py', 'b.py'))
        state = run_agent('read', ScriptedModelClient([ModelResponse('', 'scripted', tool_calls=calls), self.answer]), self.registry)
        self.assertEqual(state.status, 'answered')
        self.assertEqual([c.source_path for c in state.citations], ['a.py', 'b.py'])

    def test_waiting_resume_retains_evidence_and_revalidates_it(self):
        client = ScriptedModelClient([proposal('r', 'read_file', {'path': 'a.py'}),
            ModelResponse('Continue?', 'scripted', requires_user_input=True), self.answer])
        waiting = run_agent('read', client, self.registry)
        self.assertEqual(waiting.status, 'waiting_user')
        self.assertEqual(len(waiting.evidence), 1)
        self.assertEqual(resume_agent(waiting, 'yes', client, self.registry).status, 'answered')
        self.path.write_bytes(b'changed')
        state = resume_agent(waiting, 'yes', ScriptedModelClient([self.answer]), self.registry)
        self.assertEqual(state.termination_reason, 'stale_evidence')

    def test_three_same_name_candidates_are_all_read_before_selecting(self):
        client = scripted_locator('page')
        state = run_agent('find list pagination', client, ToolRegistry(FIXTURE_ROOT))
        self.assertEqual((state.status, client.call_count), ('answered', 3))
        expected = {'pagination.py', 'reporting.py', 'export.py'}
        paths = {m['path'] for m in observations(client.requests[1])[0].data['matches']}
        self.assertEqual(paths, expected)
        reads = [r for r in observations(client.requests[2])
                 if r.ok and isinstance(r.data, dict) and r.data.get('source_hash')]
        self.assertEqual(len(reads), 3)
        self.assertEqual({r.data['path'] for r in reads}, expected)
        self.assertEqual(len(state.evidence), 3)
        self.assertEqual({c.source_path for c in state.evidence}, expected)
        for citation in state.evidence:
            self.assertEqual(citation.content, (FIXTURE_ROOT / citation.source_path).read_bytes().decode('utf-8'))
            validate_citation(FIXTURE_ROOT, citation)
        self.assertEqual([c.source_path for c in state.citations], ['pagination.py'])
        self.assertIn('page_no * size', state.citations[0].content)
        self.assertIn('items[', state.citations[0].content)
        distractor = next(c for c in state.evidence if c.source_path == 'export.py')
        self.assertIn('def page(export_name):', distractor.content)
        self.assertNotIn('page_no * size', distractor.content)
        self.assertNotIn('items[', distractor.content)

    def test_scripted_selection_depends_on_content_not_filename_or_first_hit(self):
        (self.root / 'reporting.py').write_bytes(b'def page(items, page_no, size):\n start = page_no * size\n return items[start:]\n')
        (self.root / 'pagination.py').write_bytes(b'def page(report_name):\n return report_name\n')
        (self.root / 'export.py').write_bytes((FIXTURE_ROOT / 'export.py').read_bytes())

        def distractor_first(*args, **kwargs):
            result = search.search_text(*args, **kwargs)
            # Reorder real matches only; do not fabricate candidates or read results.
            result['matches'].sort(key=lambda match: match['path'])
            return result

        client = scripted_locator('page')
        with patch('devagent.tools.registry.search_text', side_effect=distractor_first):
            state = run_agent('find offset', client, self.registry)
        matches = observations(client.requests[1])[0].data['matches']
        self.assertEqual(matches[0]['path'], 'export.py')
        self.assertEqual({m['path'] for m in matches}, {'pagination.py', 'reporting.py', 'export.py'})
        self.assertEqual(state.status, 'answered')
        self.assertEqual(len(state.evidence), 3)
        self.assertEqual({c.source_path for c in state.evidence}, {'pagination.py', 'reporting.py', 'export.py'})
        self.assertEqual([c.source_path for c in state.citations], ['reporting.py'])
        self.assertIn('page_no * size', state.citations[0].content)
        self.assertIn('items[', state.citations[0].content)

    def test_demos_derive_verdict_and_real_is_blocked(self):
        for case in CASES:
            with self.subTest(case=case):
                report = run_case(case)
                self.assertTrue(report['checks'])
                if case == 'real-locate':
                    self.assertFalse(report['verified'])
                    self.assertTrue(report['blocked'])
                    self.assertEqual(report['observed']['http_requests'], 0)
                else:
                    self.assertTrue(report['verified'])
        with patch('devagent.demos.l05.validate_citation', return_value=None):
            self.assertFalse(run_case('citation-check')['verified'])
        with patch('sys.argv', ['l05', '--case', 'real-locate']), patch('builtins.print'), patch(
                'devagent.demos.l05.run_case', return_value={
                    'checks': {'network_not_called': False}, 'verified': False, 'blocked': True}):
            self.assertEqual(main(), 1)


if __name__ == '__main__':
    unittest.main()
