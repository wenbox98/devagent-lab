from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import sleep
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from devagent.demos import l08
from devagent.runtime.environment import child_environment, inspect_environment
from devagent.runtime.runner import ControlledTestRunner, RunnerLimits, _OutputCapture
from devagent.runtime.windows_job import WindowsJob
from devagent.tools.files import FileAccessError
from devagent.tools.protocol import ToolCall
from devagent.tools.registry import ToolRegistry


class TestL08Boundaries(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runner = ControlledTestRunner(self.root)

    def test_repository_execution_blocked_before_popen(self):
        self.assertTrue(Path(self.runner.test_argv[0]).is_absolute())
        self.assertEqual(self.runner.test_argv[1:], ('-I', '-m', 'unittest', 'discover', '-s', 'tests', '-v'))
        with patch('devagent.runtime.runner.subprocess.Popen', side_effect=AssertionError('must not execute repo')):
            result = self.runner.run_tests()
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(result.error.code, 'isolation_unavailable')
        self.assertFalse(result.started)
        self.assertIsNone(result.exit_code)
        self.assertIsNone(result.termination_confirmed)
        self.assertEqual((result.stdout, result.stderr, result.captured_bytes), ('', '', 0))

    def test_command_and_parameter_boundary_has_no_arbitrary_argv(self):
        with patch('devagent.runtime.runner.subprocess.Popen', side_effect=AssertionError('no process allowed')):
            for value in ('cmd /c echo secret', ['python', '-c', 'print(1)']):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    self.runner.run_tests(value)
            with self.assertRaises(ValueError):
                self.runner.run_probe('unittest')
            with self.assertRaises(TypeError):
                self.runner.run_probe('normal', argv=['cmd.exe'])
            with self.assertRaises(TypeError):
                self.runner.run_tests(cwd=str(self.root))

    def test_invalid_host_budgets_rejected(self):
        for field in ('timeout_ms', 'max_output_bytes', 'cleanup_ms'):
            for value in (0, -1, True, 2.5, 2_000_000):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    RunnerLimits(**{field: value})
        with self.assertRaises(ValueError):
            ControlledTestRunner(self.root, limits={})

    def test_executable_permission_precheck_denies_before_spawn(self):
        with patch('devagent.runtime.runner.os.access', return_value=False):
            with patch('devagent.runtime.runner.subprocess.Popen', side_effect=AssertionError('no spawn')):
                result = self.runner.run_probe('normal')
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(result.error.code, 'permission_denied')
        self.assertFalse(result.started)

    def test_missing_root_and_non_directory_rejected(self):
        with self.assertRaises(FileAccessError) as caught:
            ControlledTestRunner(self.root / 'missing')
        self.assertEqual(caught.exception.code, 'not_found')
        file = self.root / 'file.py'
        file.write_bytes(b'')
        with self.assertRaises(FileAccessError) as caught:
            ControlledTestRunner(file)
        self.assertEqual(caught.exception.code, 'unsupported_content')

    def test_missing_process_control_blocks_probes_before_popen(self):
        with patch('devagent.runtime.environment.WindowsJob', side_effect=OSError('unavailable')):
            with patch('devagent.runtime.runner.subprocess.Popen', side_effect=AssertionError('no fallback')):
                result = self.runner.run_probe('normal')
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(result.error.code, 'process_control_unavailable')
        self.assertFalse(result.started)

    def test_child_environment_is_an_allowlist_not_parent_copy(self):
        with patch.dict(os.environ, {'DEVAGENT_API_KEY': 'test-only', 'TOKEN': 'test-only',
                                    'HTTP_PROXY': 'test-only', 'PYTHONPATH': 'test-only'}):
            environment = child_environment(self.root)
        self.assertLessEqual(set(environment), {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP',
                                                'PYTHONIOENCODING', 'PYTHONUTF8'})
        self.assertEqual(environment['TEMP'], str(self.root))
        self.assertEqual(environment['PYTHONIOENCODING'], 'utf-8')
        self.assertNotIn('test-only', environment.values())

    def test_unconfirmed_cleanup_blocks_further_dispatch(self):
        self.runner._unhealthy = True
        with patch('devagent.runtime.runner.subprocess.Popen', side_effect=AssertionError('must stop dispatch')):
            result = self.runner.run_probe('normal')
        self.assertEqual(result.error.code, 'cleanup_unconfirmed')
        self.assertFalse(result.started)

    def test_registry_and_l06_state_do_not_grant_command_execution(self):
        registry = ToolRegistry(self.root)
        self.assertEqual({spec.name for spec in registry.specs}, {'read_file', 'list_files', 'search_text'})
        result = registry.execute(ToolCall('c1', 'run_tests', {'template': 'unittest'}))
        self.assertEqual(result.error.code, 'unknown_tool')
        self.assertEqual(registry.handler_calls, 0)

    def test_demos_are_blocked_not_passed_and_never_use_probes(self):
        for case in l08.CASES:
            with self.subTest(case=case), patch.object(ControlledTestRunner, 'run_probe', side_effect=AssertionError('no fallback')):
                report = l08.run_case(case)
            self.assertEqual(report['blocked']['code'], 'isolation_unavailable')
            self.assertFalse(report['verified'])
            self.assertFalse(report['observed']['result']['started'])
            self.assertEqual(report['verified'], all(report['checks'].values()))

    def test_demo_list_json_and_blocked_exit(self):
        for arguments, exit_code in ((['--list-cases'], 0), (['--case', 'normal'], 2)):
            with self.subTest(arguments=arguments), patch('sys.argv', ['l08', *arguments]):
                with patch('sys.stdout', new_callable=io.StringIO) as output:
                    self.assertEqual(l08.main(), exit_code)
                report = json.loads(output.getvalue())
                self.assertEqual(report['lesson'], 'L08')
                if exit_code == 2:
                    self.assertFalse(report['verified'])


class TestL08IncrementalOutput(unittest.TestCase):
    def test_root_exit_before_job_accounting_update_is_not_a_descendant_failure(self):
        from time import monotonic
        with TemporaryDirectory() as directory:
            runner = ControlledTestRunner(directory)
            process = SimpleNamespace(poll=lambda: 7)
            capture = _OutputCapture(16)
            accounting = iter((1, 0))
            job = SimpleNamespace(active_processes=lambda: next(accounting))
            self.assertEqual(runner._observe(process, job, capture, monotonic() + 1), 'completed')

    def test_two_readers_share_one_budget(self):
        capture = _OutputCapture(16)
        process = SimpleNamespace(stdout=io.BytesIO(b'O' * 1000), stderr=io.BytesIO(b'E' * 1000))
        capture.start(process)
        from time import monotonic
        self.assertTrue(capture.joined(monotonic() + 2))
        self.assertEqual(capture.saved, 16)
        self.assertEqual(len(capture.text('stdout')) + len(capture.text('stderr')), 16)
        self.assertTrue(capture.truncated.is_set())

    def test_exact_limit_is_not_reported_as_discarded_output(self):
        capture = _OutputCapture(3)
        capture._read('stdout', io.BytesIO(b'abc'))
        self.assertEqual(capture.saved, 3)
        self.assertFalse(capture.truncated.is_set())

    def test_reads_are_bounded_instead_of_communicate_then_slice(self):
        class TrackedStream(io.BytesIO):
            def read(inner, size=-1):
                self.assertEqual(size, 1024)
                return super().read(size)
        capture = _OutputCapture(3)
        capture._read('stdout', TrackedStream(b'x' * 10000))
        self.assertEqual(capture.saved, 3)
        self.assertEqual(capture.text('stdout'), 'xxx')
        self.assertTrue(capture.truncated.is_set())

    def test_partial_utf8_does_not_expand_byte_budget(self):
        capture = _OutputCapture(7)
        capture._read('stdout', io.BytesIO(('中文' * 20).encode('utf-8')))
        self.assertEqual(capture.text('stdout'), '中文')
        self.assertLessEqual(len(capture.text('stdout').encode('utf-8')), 7)
        self.assertTrue(capture.truncated.is_set())

    def test_reader_error_is_not_empty_success(self):
        stream = io.BytesIO()
        with patch.object(stream, 'read', side_effect=OSError('injected read failure')):
            capture = _OutputCapture(10)
            capture._read('stderr', stream)
        self.assertTrue(capture.failed.is_set())
        self.assertTrue(stream.closed)


@unittest.skipUnless(os.name == 'nt', 'Windows Job Object integration requires Windows')
class TestL08WindowsLifecycle(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runner = ControlledTestRunner(self.root)

    def assert_stopped(self, result):
        self.assertTrue(result.started)
        self.assertTrue(result.termination_confirmed)
        self.assertTrue(result.cleanup_confirmed)
        self.assertEqual(result.active_processes_after, 0)
        self.assertIsNotNone(result.exit_code)
        self.assertEqual(result.scope, 'trusted_fixed_probe')

    def test_actual_job_limits_are_set_and_queried_without_isolation_claim(self):
        capability = inspect_environment()
        self.assertTrue(capability.job_objects)
        self.assertEqual(capability.resource_limits['flags'], WindowsJob.FLAGS)
        self.assertEqual(capability.resource_limits['max_processes'], 4)
        self.assertEqual(capability.resource_limits['job_memory_bytes'], 256 * 1024 * 1024)
        self.assertEqual(WindowsJob.FLAGS & (0x0800 | 0x1000), 0)  # no breakaway flags
        self.assertFalse(capability.filesystem_isolation)
        self.assertFalse(capability.network_isolation)
        self.assertFalse(capability.repository_execution)

    def test_real_normal_exit_and_sensitive_environment_absence(self):
        with patch.dict(os.environ, {'DEVAGENT_API_KEY': 'test-only', 'AWS_SECRET_ACCESS_KEY': 'test-only'}):
            result = self.runner.run_probe('normal')
        self.assert_stopped(result)
        self.assertEqual((result.status, result.exit_code, result.timed_out, result.truncated), ('completed', 0, False, False))
        body = json.loads(result.stdout)
        self.assertEqual(body['tests_run'], 1)
        self.assertTrue(body['passed'])
        self.assertNotIn('DEVAGENT_API_KEY', body['env_keys'])
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', body['env_keys'])
        self.assertIn('Ran 1 test', result.stderr)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_nonzero_exit_not_inferred_from_pass_text(self):
        result = self.runner.run_probe('nonzero')
        self.assert_stopped(result)
        self.assertEqual((result.status, result.exit_code), ('failed', 7))
        self.assertIn('PASS', result.stdout)
        self.assertEqual(result.error.code, 'nonzero_exit')

    def test_timeout_terminates_child_tree_and_heartbeat_stops(self):
        result = self.runner.run_probe('timeout')
        self.assert_stopped(result)
        self.assertEqual(result.status, 'timed_out')
        self.assertTrue(result.timed_out)
        self.assertNotEqual(result.exit_code, 0)
        identities = json.loads(result.stdout)
        self.assertNotEqual(identities['parent_pid'], identities['child_pid'])
        heartbeat = self.root / 'heartbeat.txt'
        first = heartbeat.read_bytes()
        self.assertGreater(len(first), 0)
        sleep(0.1)
        self.assertEqual(heartbeat.read_bytes(), first)

    def test_output_limit_terminates_and_keeps_combined_budget(self):
        self.runner = ControlledTestRunner(self.root, limits=RunnerLimits(max_output_bytes=128))
        result = self.runner.run_probe('output-limit')
        self.assert_stopped(result)
        self.assertEqual(result.status, 'output_limit')
        self.assertTrue(result.truncated)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.captured_bytes, 128)
        self.assertLessEqual(len(result.stdout.encode()) + len(result.stderr.encode()), 128)

    def test_large_stdout_and_stderr_are_drained_concurrently(self):
        self.runner = ControlledTestRunner(self.root, limits=RunnerLimits(max_output_bytes=262144))
        result = self.runner.run_probe('dual-stream')
        self.assert_stopped(result)
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.stdout, 'O' * 65536)
        self.assertEqual(result.stderr, 'E' * 65536)
        self.assertEqual(result.captured_bytes, 131072)
        self.assertFalse(result.truncated)

    def test_parent_exit_does_not_leave_live_descendants(self):
        result = self.runner.run_probe('orphan')
        self.assert_stopped(result)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.status, 'descendants_remaining')
        self.assertEqual(result.error.code, 'descendants_remaining')

    def test_start_uses_absolute_argv_minimal_env_and_job_before_gate(self):
        original_popen, original_assign = subprocess.Popen, WindowsJob.assign
        events = []
        def popen(*args, **kwargs):
            events.append('popen')
            self.assertTrue(Path(args[0][0]).is_absolute())
            self.assertEqual(args[0][1:5], ['-I', '-S', '-u', '-c'])
            self.assertFalse(kwargs['shell'])
            self.assertTrue(kwargs['close_fds'])
            self.assertEqual(kwargs['cwd'], self.root.resolve())
            self.assertNotIn('DEVAGENT_API_KEY', kwargs['env'])
            process = original_popen(*args, **kwargs)
            original_write = process.stdin.write
            def gate(value):
                events.append('gate')
                return original_write(value)
            process.stdin.write = gate
            return process
        def assign(job, pid):
            events.append('assign')
            return original_assign(job, pid)
        with patch('devagent.runtime.runner.subprocess.Popen', side_effect=popen), patch.object(WindowsJob, 'assign', assign):
            result = self.runner.run_probe('normal')
        self.assert_stopped(result)
        self.assertEqual(events, ['popen', 'assign', 'gate'])

    def test_popen_failure_has_no_fabricated_exit(self):
        with patch('devagent.runtime.runner.subprocess.Popen', side_effect=OSError('injected spawn failure')):
            result = self.runner.run_probe('normal')
        self.assertEqual(result.status, 'start_failed')
        self.assertFalse(result.started)
        self.assertIsNone(result.exit_code)
        self.assertTrue(result.cleanup_confirmed)

    def test_job_assignment_failure_kills_gated_root_before_probe(self):
        with patch.object(WindowsJob, 'assign', side_effect=OSError('injected assignment failure')):
            result = self.runner.run_probe('timeout')
        self.assertEqual(result.status, 'start_failed')
        self.assertTrue(result.started)
        self.assertTrue(result.termination_confirmed)
        self.assertFalse((self.root / 'heartbeat.txt').exists())

    def test_internal_observation_error_still_cleans_process(self):
        original_popen = subprocess.Popen
        processes = []
        def record(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process
        with patch('devagent.runtime.runner.subprocess.Popen', side_effect=record):
            with patch.object(self.runner, '_observe', side_effect=RuntimeError('bug')):
                with self.assertRaises(RuntimeError):
                    self.runner.run_probe('timeout')
        self.assertIsNotNone(processes[0].poll())

    def test_unconfirmed_job_termination_is_reported_and_blocks_reuse(self):
        with patch.object(WindowsJob, 'terminate', side_effect=OSError('injected termination failure')):
            result = self.runner.run_probe('timeout')
        self.assertEqual(result.status, 'cleanup_failed')
        self.assertTrue(result.timed_out)
        self.assertFalse(result.termination_confirmed)
        self.assertFalse(result.cleanup_confirmed)
        self.assertEqual(result.error.code, 'cleanup_unconfirmed')
        with patch('devagent.runtime.runner.subprocess.Popen', side_effect=AssertionError('must not dispatch again')):
            self.assertEqual(self.runner.run_probe('normal').error.code, 'cleanup_unconfirmed')


if __name__ == '__main__':
    unittest.main()
