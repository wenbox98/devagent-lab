"""L00的第一条红色验收；不要删除测试或把NotImplementedError算通过。"""
import unittest
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID
from devagent.app import run_task
from devagent.fake_model import FakeModelClient
from devagent.models import ModelResponse
from devagent.trace import TraceWriter

class TestL00StartingContract(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'runs.jsonl'

    def run_task(self, task, client):
        return run_task(task, client, trace_path=self.path)

    def events(self):
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]

    def test_empty_input_never_calls_client(self):
        class NeverCall:
            def complete(self, request):
                raise AssertionError('invalid input must not call model')
        result=self.run_task('  ',NeverCall())
        self.assertEqual(result.status,'failed')
        self.assertEqual(result.error_code,'invalid_input')
        self.assertEqual(result.exit_code,2)
        self.assertEqual([e['event'] for e in self.events()], ['run_started', 'run_finished'])

    def test_success_cleans_input_and_calls_once(self):
        client = FakeModelClient()
        result = self.run_task('  explain pagination  ', client)
        self.assertEqual((result.status, result.output, result.error_code, result.exit_code),
                         ('succeeded', '【模拟输出】explain pagination', None, 0))
        self.assertEqual(client.call_count, 1)
        self.assertEqual([e['event'] for e in self.events()],
                         ['run_started', 'model_started', 'model_finished', 'run_finished'])

    def test_timeout_is_not_retried(self):
        client = FakeModelClient('timeout')
        result = self.run_task('fix', client)
        self.assertEqual((result.status, result.error_code, result.exit_code), ('failed', 'model_timeout', 3))
        self.assertIsNone(result.output)
        self.assertEqual(client.call_count, 1)
        self.assertEqual(self.events()[2]['status'], 'failed')

    def test_input_length_boundaries_before_client(self):
        for character in ('a', '中'):
            for length, expected_calls in ((5000, 1), (5001, 0)):
                with self.subTest(character=character, length=length):
                    client = FakeModelClient()
                    result = self.run_task('  ' + character * length + '  ', client)
                    self.assertEqual(client.call_count, expected_calls)
                    if expected_calls:
                        self.assertEqual(result.status, 'succeeded')
                        self.assertEqual(result.output, '【模拟输出】' + character * length)
                    else:
                        self.assertEqual((result.error_code, result.exit_code), ('input_too_long', 2))
                        events = [e for e in self.events() if e['run_id'] == result.run_id]
                        self.assertEqual([e['event'] for e in events], ['run_started', 'run_finished'])

    def test_custom_length_limit_and_invalid_configuration(self):
        client = FakeModelClient()
        result = run_task('abcd', client, trace_path=self.path, max_chars=3)
        self.assertEqual(result.error_code, 'input_too_long')
        self.assertEqual(client.call_count, 0)
        for limit in (0, -1, True, 2.5, '3'):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                run_task('a', client, trace_path=self.path, max_chars=limit)

    def test_blank_response_has_successful_call_but_failed_task(self):
        for text in ('', '  \t'):
            with self.subTest(text=text):
                class BlankClient:
                    def complete(self, request):
                        return ModelResponse(text, 'fake')
                result = self.run_task('fix', BlankClient())
                self.assertEqual((result.error_code, result.exit_code), ('invalid_response', 4))
                self.assertIsNone(result.output)
                self.assertEqual(self.events()[-2]['status'], 'succeeded')
                self.assertEqual(self.events()[-1]['status'], 'failed')

    def test_trace_appends_and_ids_correlate(self):
        first = self.run_task('first', FakeModelClient())
        before = self.path.read_bytes()
        second = self.run_task('second', FakeModelClient())
        self.assertTrue(self.path.read_bytes().startswith(before))
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(UUID(first.run_id).version, 4)
        self.assertEqual(UUID(second.run_id).version, 4)
        events = self.events()
        self.assertEqual(len(events), 8)
        self.assertEqual([e['run_id'] for e in events], [first.run_id] * 4 + [second.run_id] * 4)
        self.assertEqual([e['sequence'] for e in events], [1, 2, 3, 4] * 2)

    def test_trace_metadata_has_no_bodies_and_uses_monotonic_time(self):
        secret_task = 'private-task-marker'
        with patch('devagent.trace.perf_counter', side_effect=[10, 10.01, 10.02, 10.03, 10.04]):
            self.run_task(secret_task, FakeModelClient())
        raw = self.path.read_text(encoding='utf-8')
        self.assertNotIn(secret_task, raw)
        self.assertNotIn('【模拟输出】', raw)
        for event, expected in zip(self.events(), [10, 20, 30, 40]):
            self.assertAlmostEqual(event['elapsed_ms'], expected)

    def test_first_trace_failure_never_calls_client(self):
        blocker = Path(self.temp.name) / 'blocker'
        blocker.write_text('file', encoding='utf-8')
        client = FakeModelClient()
        result = run_task('fix', client, trace_path=blocker / 'runs.jsonl')
        self.assertEqual((result.status, result.error_code, result.exit_code), ('failed', 'trace_io', 5))
        self.assertEqual(client.call_count, 0)

    def test_later_trace_failure_is_explicit_without_recalling_client(self):
        original = TraceWriter.emit
        for failed_event, expected_calls in [('model_started', 0), ('model_finished', 1), ('run_finished', 1)]:
            with self.subTest(event=failed_event):
                def failing(writer, event, **fields):
                    if event == failed_event:
                        raise OSError('injected write failure')
                    original(writer, event, **fields)
                client = FakeModelClient()
                with patch.object(TraceWriter, 'emit', failing):
                    result = self.run_task('fix', client)
                self.assertEqual(result.error_code, 'trace_io')
                self.assertEqual(client.call_count, expected_calls)

    def test_unexpected_client_errors_are_not_relabelled(self):
        for error in (ValueError('bug'), OSError('client failure')):
            with self.subTest(error=type(error).__name__):
                class BrokenClient:
                    def complete(self, request):
                        raise error
                with self.assertRaises(type(error)):
                    self.run_task('fix', BrokenClient())

    def test_cli_json_and_business_exit_codes(self):
        for task, mode, expected in [('fix', 'success', 0), (' ', 'success', 2),
                                     ('fix', 'timeout', 3), ('fix', 'bad_response', 4)]:
            with self.subTest(mode=mode, task=task):
                proc = subprocess.run([sys.executable, '-B', '-m', 'devagent', '--task', task,
                                       '--mode', mode, '--trace-path', str(self.path)],
                                      capture_output=True, text=True, encoding='utf-8', timeout=10,
                                      env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
                self.assertEqual(proc.returncode, expected)
                self.assertEqual(json.loads(proc.stdout)['exit_code'], expected)
                self.assertEqual(proc.stderr, '')

    def test_demo_cases_execute_and_derive_verdict(self):
        from devagent.demos.l00 import CASES, run_case
        for case in CASES:
            with self.subTest(case=case), TemporaryDirectory() as directory:
                report = run_case(case, Path(directory))
                self.assertTrue(report['checks'])
                self.assertTrue(report['verified'])
                self.assertEqual(report['verified'], all(report['checks'].values()))
        with TemporaryDirectory() as directory, patch('devagent.fake_model.FakeModelClient.complete',
                                                       return_value=ModelResponse('wrong', 'fake')):
            report = run_case('success', Path(directory))
            self.assertFalse(report['verified'])
