from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from devagent.app import run_task
from devagent.demos.l01 import ScriptedTransport, fixture_config
from devagent.demos.l03 import CASES, run_case
from devagent.fake_model import FakeModelClient
from devagent.models import ModelRequest, ModelResponse
from devagent.providers.adapter import OpenAICompatibleAdapter
from devagent.tools import files
from devagent.tools.protocol import ToolCall, ToolError, ToolResult, ToolSpec
from devagent.tools.registry import ToolRegistry, validate_arguments


class TestL03ToolProtocol(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'a.py').write_bytes(b'first\nsecond\nthird\n')
        self.registry = ToolRegistry(self.root)

    def test_protocol_objects_and_result_invariants(self):
        call = ToolCall('c1', 'read_file', {'path': 'a.py'})
        self.assertEqual(set(asdict(call)), {'call_id', 'name', 'arguments'})
        failure = ToolResult(call.call_id, False, error=ToolError('not_found', 'missing'))
        self.assertEqual(asdict(failure)['error'],
                         {'code': 'not_found', 'message': 'missing', 'retryable': False})
        for kwargs in ({'ok': True, 'error': failure.error}, {'ok': False},
                       {'ok': False, 'error': failure.error, 'data': 'fake success'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ToolResult('c1', **kwargs)

    def test_specs_are_explicit_and_cannot_mutate_registry(self):
        specs = self.registry.specs
        self.assertEqual({s.name for s in specs}, {'read_file', 'list_files'})
        for spec in specs:
            self.assertIsInstance(spec, ToolSpec)
            self.assertFalse(spec.input_schema['additionalProperties'])
            self.assertIn('workspace', spec.description)
        read = next(s for s in specs if s.name == 'read_file')
        self.assertEqual(read.input_schema['required'], ['path'])
        self.assertIn('next_start_line', read.description)
        read.input_schema['properties']['root'] = {'type': 'string'}
        result = self.registry.execute(ToolCall('x', 'read_file', {'path': 'a.py', 'root': '/'}))
        self.assertEqual(result.error.code, 'invalid_args')
        self.assertEqual(self.registry.handler_calls, 0)

    def test_valid_read_uses_real_handler_and_preserves_id(self):
        with patch('devagent.tools.registry.files.read_file', wraps=files.read_file) as handler:
            result = self.registry.execute(ToolCall('read-1', 'read_file',
                                                   {'path': 'a.py', 'start_line': 2, 'end_line': 2}))
        self.assertEqual((result.call_id, result.ok, result.error), ('read-1', True, None))
        self.assertEqual(result.data['content'], 'second\n')
        self.assertEqual(result.data['next_start_line'], 3)
        handler.assert_called_once_with(self.root.resolve(), path='a.py', start_line=2, end_line=2)

    def test_valid_list_uses_real_handler(self):
        with patch('devagent.tools.registry.files.list_files', wraps=files.list_files) as handler:
            result = self.registry.execute(ToolCall('list-1', 'list_files', {}))
        self.assertEqual((result.call_id, result.ok), ('list-1', True))
        self.assertEqual(result.data, [{'path': 'a.py', 'size_bytes': 19}])
        handler.assert_called_once_with(self.root.resolve())

    def test_metadata_is_allowed_but_not_forwarded_to_real_read(self):
        for metadata in ({'client_note': 'debug'}, {'client_tags': ['lesson', 'debug']},
                         {'client_note': 'debug', 'client_tags': ['lesson']}):
            with self.subTest(metadata=metadata), \
                    patch('devagent.tools.registry.files.read_file', wraps=files.read_file) as reader:
                args = {'path': 'a.py', 'start_line': 2, 'end_line': 2, **metadata}
                original = dict(args)
                result = self.registry.execute(ToolCall('metadata', 'read_file', args))
                self.assertEqual((result.call_id, result.ok, result.error), ('metadata', True, None))
                self.assertEqual(result.data['content'], 'second\n')
                reader.assert_called_once_with(self.root.resolve(), path='a.py', start_line=2, end_line=2)
                self.assertEqual(args, original)

    def test_metadata_is_not_schema_or_list_execution_arguments(self):
        args = {'client_note': 'debug', 'client_tags': ['lesson', 'debug']}
        for spec in self.registry.specs:
            self.assertTrue(set(args).isdisjoint(spec.input_schema['properties']))
            supplied = {**args, 'path': 'a.py'} if spec.name == 'read_file' else args
            expected = {'path': 'a.py'} if spec.name == 'read_file' else {}
            self.assertEqual(validate_arguments(spec, supplied), expected)
        with patch('devagent.tools.registry.files.list_files', wraps=files.list_files) as listing:
            result = self.registry.execute(ToolCall('metadata-list', 'list_files', args))
        self.assertEqual((result.call_id, result.ok), ('metadata-list', True))
        self.assertEqual(result.data, [{'path': 'a.py', 'size_bytes': 19}])
        listing.assert_called_once_with(self.root.resolve())

    def test_metadata_does_not_bypass_required_type_or_range_validation(self):
        with patch('devagent.tools.registry.files.read_file') as reader:
            for args in ({}, {'path': 12}, {'path': 'a.py', 'start_line': True},
                         {'path': 'a.py', 'start_line': 3, 'end_line': 2}):
                with self.subTest(args=args):
                    result = self.registry.execute(ToolCall('bad-meta', 'read_file',
                                                           {**args, 'client_note': 'debug'}))
                    self.assertEqual((result.call_id, result.ok, result.error.code),
                                     ('bad-meta', False, 'invalid_args'))
            reader.assert_not_called()
        self.assertEqual(self.registry.handler_calls, 0)

    def test_metadata_does_not_allow_authority_budget_or_identity_fields(self):
        with patch('devagent.tools.registry.files.read_file') as reader, \
                patch('devagent.tools.registry.files.list_files') as listing:
            for field in ('root', 'workspace', 'allow_all', 'max_bytes', 'max_lines',
                          'credentials', 'principal'):
                for tool, base in (('read_file', {'path': 'a.py'}), ('list_files', {})):
                    with self.subTest(field=field, tool=tool):
                        args = {**base, 'client_note': 'debug', 'client_tags': [], field: True}
                        result = self.registry.execute(ToolCall('denied-meta', tool, args))
                        self.assertEqual((result.call_id, result.ok, result.error.code),
                                         ('denied-meta', False, 'invalid_args'))
            reader.assert_not_called()
            listing.assert_not_called()
        self.assertEqual(self.registry.handler_calls, 0)

    def test_metadata_does_not_hide_misspelled_execution_parameters(self):
        with patch('devagent.tools.registry.files.read_file') as reader:
            for field in ('paht', 'star_line', 'endline'):
                with self.subTest(field=field):
                    # Supply a valid path so missing-required validation cannot mask this bug.
                    args = {'path': 'a.py', 'client_note': 'debug', field: 2}
                    result = self.registry.execute(ToolCall('typo', 'read_file', args))
                    self.assertEqual(result.error.code, 'invalid_args')
            reader.assert_not_called()
        self.assertEqual(self.registry.handler_calls, 0)

    def test_other_unknown_fields_still_rejected_with_metadata(self):
        with patch('devagent.tools.registry.files.read_file') as reader, \
                patch('devagent.tools.registry.files.list_files') as listing:
            for field in ('foo', 'debug_mode'):
                for tool, base in (('read_file', {'path': 'a.py'}), ('list_files', {})):
                    with self.subTest(field=field, tool=tool):
                        args = {**base, 'client_tags': ['debug'], field: True}
                        result = self.registry.execute(ToolCall('unknown-arg', tool, args))
                        self.assertEqual(result.error.code, 'invalid_args')
            reader.assert_not_called()
            listing.assert_not_called()
        self.assertEqual(self.registry.handler_calls, 0)

    def test_unknown_tool_never_calls_any_handler(self):
        with patch('devagent.tools.registry.files.read_file') as reader, \
                patch('devagent.tools.registry.files.list_files') as listing:
            for name in ('not_registered', '__import__', 'os.system', ['read_file']):
                with self.subTest(name=name):
                    result = self.registry.execute(ToolCall('unknown', name, {}))
                    self.assertEqual((result.call_id, result.error.code), ('unknown', 'unknown_tool'))
            reader.assert_not_called()
            listing.assert_not_called()
        self.assertEqual(self.registry.handler_calls, 0)

    def test_invalid_arguments_never_reach_file_handler(self):
        cases = [None, [], 'a.py', 1, {}, {'path': 12}, {'path': 'a.py', 'start_line': '1'},
                 {'path': 'a.py', 'start_line': True}, {'path': 'a.py', 'end_line': False},
                 {'path': 'a.py', 'start_line': 0}, {'path': 'a.py', 'start_line': -1},
                 {'path': 'a.py', 'end_line': 2.5}, {'path': 'a.py', 'end_line': None},
                 {'path': 'a.py', 'start_line': 3, 'end_line': 2}]
        with patch('devagent.tools.registry.files.read_file') as reader:
            for args in cases:
                with self.subTest(args=args):
                    result = self.registry.execute(ToolCall('bad', 'read_file', args))
                    self.assertEqual((result.call_id, result.ok, result.error.code),
                                     ('bad', False, 'invalid_args'))
            reader.assert_not_called()
        self.assertEqual(self.registry.handler_calls, 0)

    def test_authority_and_claimed_success_fields_rejected(self):
        for name in ('root', 'workspace', 'allow_all', 'max_bytes', 'max_lines',
                     'credentials', 'principal', 'ok', 'success', 'data'):
            for tool, args in (('read_file', {'path': 'a.py'}), ('list_files', {})):
                with self.subTest(name=name, tool=tool):
                    result = self.registry.execute(ToolCall('c1', tool, {**args, name: True}))
                    self.assertEqual(result.error.code, 'invalid_args')
        self.assertEqual(self.registry.handler_calls, 0)

    def test_structurally_valid_escape_reaches_l02_and_is_denied(self):
        with patch('devagent.tools.registry.files.read_file', wraps=files.read_file) as reader:
            result = self.registry.execute(ToolCall('escape', 'read_file', {'path': '../secret.py'}))
        self.assertEqual((result.call_id, result.error.code), ('escape', 'permission_denied'))
        self.assertFalse(result.ok)
        reader.assert_called_once()
        self.assertEqual(self.registry.handler_calls, 1)

    def test_l02_business_error_codes_are_preserved(self):
        (self.root / 'binary.py').write_bytes(b'\xff')
        (self.root / 'large.py').write_bytes(b'x' * 65537)
        for path, code in (('missing.py', 'not_found'), ('binary.py', 'unsupported_content'),
                           ('large.py', 'unsupported_content'), ('.hidden.py', 'permission_denied')):
            with self.subTest(path=path):
                result = self.registry.execute(ToolCall(path, 'read_file', {'path': path}))
                self.assertEqual((result.call_id, result.error.code), (path, code))
                self.assertIsNone(result.data)
                self.assertFalse(result.error.retryable)

    def test_host_line_budget_and_complete_list_size_remain(self):
        raw = b'line\n' * 100
        (self.root / 'a.py').write_bytes(raw)
        result = self.registry.execute(ToolCall('read', 'read_file', {'path': 'a.py'}))
        self.assertEqual(result.data['end_line'], 50)
        self.assertEqual(result.data['next_start_line'], 51)
        listing = self.registry.execute(ToolCall('list', 'list_files', {}))
        self.assertEqual(listing.data[0]['size_bytes'], len(raw))

    def test_batch_keeps_distinct_success_and_failure_ids(self):
        results = self.registry.execute_batch([
            ToolCall('first', 'read_file', {'path': 'a.py'}),
            ToolCall('second', 'read_file', {'path': 'missing.py'})])
        self.assertEqual([(r.call_id, r.ok) for r in results], [('first', True), ('second', False)])
        self.assertEqual(results[1].error.code, 'not_found')

    def test_duplicate_ids_reject_entire_batch_before_execution(self):
        with patch('devagent.tools.registry.files.read_file') as reader, \
                patch('devagent.tools.registry.files.list_files') as listing:
            results = self.registry.execute_batch([
                ToolCall('unique', 'list_files', {}),
                ToolCall('same', 'read_file', {'path': 'a.py'}),
                ToolCall('same', 'read_file', {'path': 'missing.py'})])
            reader.assert_not_called()
            listing.assert_not_called()
        self.assertEqual([r.call_id for r in results], ['unique', 'same', 'same'])
        self.assertTrue(all(not r.ok and r.error.code == 'protocol_error' for r in results))
        self.assertEqual(self.registry.handler_calls, 0)
        # Only this batch is rejected, not a claim of persistent deduplication.
        self.assertTrue(self.registry.execute(ToolCall('same', 'list_files', {})).ok)

    def test_invalid_ids_and_empty_batch(self):
        for call_id in ('', ' ', None, 1, []):
            with self.subTest(call_id=call_id):
                call = ToolCall(call_id, 'list_files', {})
                for result in (self.registry.execute(call), self.registry.execute_batch([call])[0]):
                    self.assertEqual(result.call_id, call_id)
                    self.assertEqual(result.error.code, 'protocol_error')
        self.assertEqual(self.registry.execute_batch([]), [])
        self.assertEqual(self.registry.handler_calls, 0)

    def test_programming_error_is_not_swallowed(self):
        with patch('devagent.tools.registry.files.read_file', side_effect=RuntimeError('bug')):
            with self.assertRaisesRegex(RuntimeError, 'bug'):
                self.registry.execute(ToolCall('x', 'read_file', {'path': 'a.py'}))

    def test_fake_proposal_is_pending_not_empty_response_or_execution(self):
        client = FakeModelClient('tool_call')
        trace = self.root / 'trace.jsonl'
        with patch('devagent.tools.registry.files.read_file') as reader:
            result = run_task('read fixture', client, tools=self.registry.specs, trace_path=trace)
            reader.assert_not_called()
        self.assertEqual((result.status, result.error_code, result.exit_code), ('requires_tools', None, 0))
        self.assertIsNone(result.output)
        self.assertEqual(result.tool_calls, (ToolCall('c1', 'read_file',
                                                    {'path': 'pagination.py', 'end_line': 3}),))
        self.assertEqual(client.call_count, 1)
        events = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
        self.assertEqual([e['event'] for e in events],
                         ['run_started', 'model_started', 'model_finished', 'run_finished'])
        self.assertEqual(events[-1]['status'], 'requires_tools')
        self.assertNotIn('pagination.py', trace.read_text(encoding='utf-8'))

    def test_text_only_models_and_blank_response_remain_compatible(self):
        self.assertEqual(ModelRequest('task').tools, ())
        self.assertEqual(ModelResponse('answer', 'fake').tool_calls, ())
        for mode, status, code in (('success', 'succeeded', None), ('bad_response', 'failed', 'invalid_response')):
            result = run_task('question', FakeModelClient(mode), trace_path=self.root / f'{mode}.jsonl')
            self.assertEqual((result.status, result.error_code), (status, code))
            self.assertEqual(result.tool_calls, ())

    def test_real_adapter_explicitly_rejects_tool_mode_without_network(self):
        transport = ScriptedTransport(response={})
        client = OpenAICompatibleAdapter(config=fixture_config(), transport=transport)
        with self.assertRaisesRegex(NotImplementedError, 'text requests only'):
            client.complete(ModelRequest('task', self.registry.specs))
        self.assertEqual((client.call_count, transport.call_count), (0, 0))

    def test_demo_verdicts_are_derived_and_detect_fabricated_content(self):
        for case in CASES:
            with self.subTest(case=case):
                report = run_case(case)
                self.assertTrue(report['checks'])
                self.assertTrue(report['verified'])
                self.assertEqual(report['verified'], all(report['checks'].values()))
        with patch('devagent.tools.registry.files.read_file',
                   return_value=files.FileReadResult('pagination.py', 1, 3, 'made up', True, 4)):
            self.assertFalse(run_case('valid-call')['verified'])


if __name__ == '__main__':
    unittest.main()
