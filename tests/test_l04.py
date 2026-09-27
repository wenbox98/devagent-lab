from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from devagent.agent.loop import AgentState, resume_agent, run_agent
from devagent.agent.messages import AssistantMessage, ToolMessage, UserMessage
from devagent.app import run_task
from devagent.demos.l01 import ScriptedTransport, fixture_config
from devagent.demos.l04 import CASES, observations, proposal, run_case
from devagent.fake_model import FakeModelClient, ScriptedModelClient
from devagent.models import ModelRequest, ModelResponse
from devagent.providers.adapter import OpenAICompatibleAdapter, ProviderTimeoutError
from devagent.tools import files
from devagent.tools.protocol import ToolCall
from devagent.tools.registry import ToolRegistry


class TestL04AgentLoop(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'a.py').write_bytes(b'actual source\nsecond\n')
        self.registry = ToolRegistry(self.root)

    def read(self, call_id='c1', **kwargs):
        return proposal(call_id, 'read_file', {'path': 'a.py', **kwargs})

    def final(self, text='done'):
        return ModelResponse(text, 'scripted')

    def test_waiting_user_returns_and_resume_preserves_history(self):
        question = 'Please provide the project path'

        def answer(request):
            self.assertEqual(request.task, 'Explain the startup failure')
            self.assertEqual(request.messages, (
                UserMessage('Explain the startup failure'),
                AssistantMessage(question), UserMessage('E:/workSpace/demo')))
            return self.final()

        client = ScriptedModelClient([
            ModelResponse(question, 'scripted', requires_user_input=True), answer])
        with patch.object(self.registry, 'execute_batch', wraps=self.registry.execute_batch) as batch:
            waiting = run_agent('Explain the startup failure', client, self.registry)
            self.assertEqual(client.call_count, 1)
            self.assertEqual((waiting.status, waiting.termination_reason, waiting.output),
                             ('waiting_user', 'user_input_required', question))
            self.assertEqual((waiting.step_count, waiting.tool_call_count), (1, 0))
            self.assertEqual(waiting.messages, [UserMessage('Explain the startup failure'),
                                              AssistantMessage(question)])
            snapshot = asdict(waiting)
            result = resume_agent(waiting, 'E:/workSpace/demo', client, self.registry)
            batch.assert_not_called()
        self.assertEqual((result.status, result.output, client.call_count), ('answered', 'done', 2))
        self.assertEqual((result.step_count, result.tool_call_count), (1, 0))
        self.assertEqual(asdict(waiting), snapshot)
        self.assertIsNot(result.messages, waiting.messages)

    def test_resume_can_read_file_and_feed_result_to_next_model_call(self):
        def read_supplied_path(request):
            self.assertEqual(request.messages[-1], UserMessage('a.py'))
            return proposal('resumed-read', 'read_file', {'path': request.messages[-1].content})

        def answer(request):
            self.assertEqual(request.task, 'read a file')
            feedback = observations(request)[-1]
            self.assertEqual(feedback.call_id, 'resumed-read')
            self.assertEqual(feedback.data['content'], 'actual source\nsecond\n')
            return self.final(feedback.data['content'])

        client = ScriptedModelClient([
            ModelResponse('Which file?', 'scripted', requires_user_input=True), read_supplied_path, answer])
        waiting = run_agent('read a file', client, self.registry)
        with patch('devagent.tools.registry.files.read_file', wraps=files.read_file) as reader:
            result = resume_agent(waiting, 'a.py', client, self.registry)
        reader.assert_called_once_with(self.root.resolve(), path='a.py')
        self.assertEqual((result.status, result.step_count, result.tool_call_count), ('answered', 2, 1))
        self.assertEqual(result.messages[:2], waiting.messages)

    def test_resume_resets_both_window_counts_and_preserves_tool_evidence(self):
        first = tuple(ToolCall(f'old-{i}', 'list_files', {}) for i in range(3))
        second = tuple(ToolCall(f'new-{i}', 'list_files', {}) for i in range(2))
        client = ScriptedModelClient([
            ModelResponse('', 'scripted', tool_calls=first),
            ModelResponse('What next?', 'scripted', requires_user_input=True),
            ModelResponse('', 'scripted', tool_calls=second), self.final()])
        waiting = run_agent('task', client, self.registry, max_rounds=2, max_tool_calls=4)
        self.assertEqual((waiting.status, waiting.step_count, waiting.tool_call_count), ('waiting_user', 2, 3))
        result = resume_agent(waiting, 'list again', client, self.registry)
        self.assertEqual((result.status, result.step_count, result.tool_call_count), ('answered', 2, 2))
        self.assertEqual((result.max_rounds, result.max_tool_calls), (2, 4))
        self.assertEqual((client.call_count, self.registry.handler_calls), (4, 5))
        self.assertEqual(client.requests[2].messages, tuple(waiting.messages) + (UserMessage('list again'),))
        self.assertEqual([r.call_id for r in observations(client.requests[3])],
                         ['old-0', 'old-1', 'old-2', 'new-0', 'new-1'])
        result.messages[2].result.data[0]['path'] = 'changed in new state'
        self.assertEqual(waiting.messages[2].result.data[0]['path'], 'a.py')

    def test_resumed_window_still_enforces_each_budget(self):
        for rounds, tools, reason, expected_calls in ((2, 5, 'step_limit', 2), (5, 2, 'tool_limit', 2)):
            with self.subTest(reason=reason):
                registry = ToolRegistry(self.root)
                client = ScriptedModelClient([
                    ModelResponse('Continue?', 'scripted', requires_user_input=True), self.read()], repeat_last=True)
                waiting = run_agent('task', client, registry, max_rounds=rounds, max_tool_calls=tools)
                result = resume_agent(waiting, 'yes', client, registry)
                self.assertEqual((result.status, result.termination_reason), ('budget_exhausted', reason))
                self.assertEqual(result.step_count, expected_calls)
                self.assertEqual(client.call_count, 1 + expected_calls)
                self.assertEqual(registry.handler_calls, expected_calls)

    def test_resume_rejects_wrong_state_and_nonwaiting_status_without_calls(self):
        client = ScriptedModelClient([self.final()])
        for state in (None, {}, 'waiting_user'):
            with self.subTest(state=state), self.assertRaises(TypeError):
                resume_agent(state, 'reply', client, self.registry)
        for status in ('answered', 'failed', 'running', 'requires_tools', 'budget_exhausted'):
            state = AgentState(5, 10, status=status, messages=[UserMessage('task')])
            snapshot = asdict(state)
            with self.subTest(status=status), self.assertRaises(ValueError):
                resume_agent(state, 'reply', client, self.registry)
            self.assertEqual(asdict(state), snapshot)
        self.assertEqual((client.call_count, self.registry.handler_calls), (0, 0))

    def test_resume_rejects_invalid_input_without_changing_snapshot(self):
        client = ScriptedModelClient([ModelResponse('Which file?', 'scripted', requires_user_input=True)])
        waiting = run_agent('task', client, self.registry)
        snapshot = asdict(waiting)
        for text in ('', '  ', None, 1, True, 'x' * 5001):
            with self.subTest(text=text), self.assertRaises(ValueError):
                resume_agent(waiting, text, client, self.registry)
            self.assertEqual(asdict(waiting), snapshot)
        self.assertEqual((client.call_count, self.registry.handler_calls), (1, 0))

    def test_waiting_flag_requires_bool_and_nonempty_question(self):
        self.assertFalse(self.final().requires_user_input)
        responses = [ModelResponse(text, 'scripted', requires_user_input=True) for text in ('', ' ', None)]
        responses += [ModelResponse('question', 'scripted', requires_user_input=value) for value in (1, 'true', None)]
        responses.append(ModelResponse('', 'scripted', tool_calls=self.read().tool_calls, requires_user_input=True))
        for response in responses:
            with self.subTest(response=response):
                client = ScriptedModelClient([response, self.final()])
                result = run_agent('task', client, self.registry)
                self.assertEqual((result.status, result.termination_reason), ('failed', 'protocol_error'))
                self.assertEqual(client.call_count, 1)
        self.assertEqual(self.registry.handler_calls, 0)

    def test_tool_calls_take_priority_over_waiting_flag(self):
        client = ScriptedModelClient([
            ModelResponse('Read this first', 'scripted', tool_calls=self.read().tool_calls, requires_user_input=True),
            self.final()])
        result = run_agent('task', client, self.registry)
        self.assertEqual((result.status, client.call_count, self.registry.handler_calls), ('answered', 2, 1))
        self.assertEqual(observations(client.requests[1])[0].call_id, 'c1')

    def test_resume_can_pause_again_without_polling(self):
        client = ScriptedModelClient([
            ModelResponse('Which file?', 'scripted', requires_user_input=True),
            ModelResponse('Which lines?', 'scripted', requires_user_input=True), self.final()])
        first = run_agent('task', client, self.registry, max_rounds=1)
        second = resume_agent(first, 'a.py', client, self.registry)
        self.assertEqual((second.status, second.step_count, client.call_count), ('waiting_user', 1, 2))
        result = resume_agent(second, 'first line', client, self.registry)
        self.assertEqual(client.requests[2].messages, (
            UserMessage('task'), AssistantMessage('Which file?'), UserMessage('a.py'),
            AssistantMessage('Which lines?'), UserMessage('first line')))
        self.assertEqual((result.status, result.termination_reason, result.step_count), ('answered', 'final_answer', 1))
        self.assertEqual(self.registry.handler_calls, 0)

    def test_resume_rejects_invalid_snapshot_budget_or_missing_original_task(self):
        client = ScriptedModelClient([self.final()])
        bad_states = [AgentState(5, 10, status='waiting_user'),
                      AgentState(True, 10, status='waiting_user', messages=[UserMessage('task')]),
                      AgentState(5, 0, status='waiting_user', messages=[UserMessage('task')])]
        for state in bad_states:
            with self.subTest(state=state), self.assertRaises(ValueError):
                resume_agent(state, 'reply', client, self.registry)
        self.assertEqual(client.call_count, 0)

    def test_two_rounds_use_real_feedback_in_actual_second_request(self):
        def answer(request):
            self.assertEqual(request.task, '  original task  ')
            self.assertEqual(request.messages[0], UserMessage('  original task  '))
            self.assertIsInstance(request.messages[1], AssistantMessage)
            result = request.messages[2].result
            self.assertEqual(result.call_id, request.messages[1].tool_calls[0].call_id)
            self.assertTrue(result.ok)
            self.assertEqual(result.data['content'], 'actual source\n')
            return self.final(result.data['content'])
        client = ScriptedModelClient([self.read(end_line=1), answer])
        with patch('devagent.tools.registry.files.read_file', wraps=files.read_file) as reader:
            state = run_agent('  original task  ', client, self.registry)
        reader.assert_called_once_with(self.root.resolve(), path='a.py', end_line=1)
        self.assertEqual((state.status, state.termination_reason, state.output),
                         ('answered', 'final_answer', 'actual source\n'))
        self.assertEqual((state.step_count, state.tool_call_count, client.call_count), (2, 1, 2))
        self.assertEqual(len(client.requests[0].messages), 1)
        self.assertEqual(state.messages[-1], AssistantMessage(state.output))

    def test_error_code_and_message_allow_not_found_recovery(self):
        def recover(request):
            error = observations(request)[-1].error
            self.assertEqual((error.code, error.message, error.retryable),
                             ('not_found', 'workspace or file not found', False))
            return proposal('list', 'list_files', {})
        client = ScriptedModelClient([proposal('missing', 'read_file', {'path': 'missing.py'}),
                                      recover, self.final()])
        state = run_agent('recover', client, self.registry)
        self.assertEqual(state.status, 'answered')
        self.assertEqual([(r.call_id, r.ok) for r in observations(client.requests[2])],
                         [('missing', False), ('list', True)])

    def test_permission_denied_is_safe_observation_not_terminal(self):
        client = ScriptedModelClient([proposal('escape', 'read_file', {'path': '../outside.py'}), self.final()])
        with patch.object(Path, 'open', side_effect=AssertionError('must not open')):
            state = run_agent('read', client, self.registry)
        error = observations(client.requests[1])[0].error
        self.assertEqual((error.code, error.message), ('permission_denied', 'path escapes workspace'))
        self.assertNotIn(str(self.root), error.message)
        self.assertEqual(state.status, 'answered')

    def test_multiple_calls_execute_sequentially_and_keep_ids(self):
        calls = (ToolCall('second-line', 'read_file', {'path': 'a.py', 'start_line': 2}),
                 ToolCall('first-line', 'read_file', {'path': 'a.py', 'end_line': 1}),
                 ToolCall('missing', 'read_file', {'path': 'missing.py'}))
        client = ScriptedModelClient([ModelResponse('', 'scripted', tool_calls=calls), self.final()])
        with patch.object(self.registry, 'execute', wraps=self.registry.execute) as execute:
            state = run_agent('read all', client, self.registry)
        self.assertEqual([item.args[0] for item in execute.call_args_list], list(calls))
        results = observations(client.requests[1])
        self.assertEqual([r.call_id for r in results], [c.call_id for c in calls])
        self.assertEqual([r.data['content'] for r in results[:2]], ['second\n', 'actual source\n'])
        self.assertEqual(results[2].error.code, 'not_found')
        self.assertEqual((state.step_count, state.tool_call_count), (2, 3))

    def test_round_budget_stops_ever_calling_model(self):
        client = ScriptedModelClient([self.read()], repeat_last=True)
        state = run_agent('repeat', client, self.registry, max_rounds=3, max_tool_calls=10)
        self.assertEqual((state.status, state.termination_reason), ('budget_exhausted', 'step_limit'))
        self.assertEqual((client.call_count, self.registry.handler_calls, state.step_count), (3, 3, 3))
        self.assertEqual(len([m for m in state.messages if isinstance(m, ToolMessage)]), 3)
        self.assertIsNone(state.output)

    def test_tool_budget_stops_both_next_model_and_handler(self):
        client = ScriptedModelClient([self.read()], repeat_last=True)
        state = run_agent('repeat', client, self.registry, max_rounds=9, max_tool_calls=2)
        self.assertEqual((state.status, state.termination_reason), ('budget_exhausted', 'tool_limit'))
        self.assertEqual((client.call_count, self.registry.handler_calls, state.tool_call_count), (2, 2, 2))

    def test_oversized_batch_is_not_partially_executed(self):
        calls = (ToolCall('a', 'list_files', {}), ToolCall('b', 'list_files', {}))
        client = ScriptedModelClient([ModelResponse('', 'scripted', tool_calls=calls), self.final()])
        with patch.object(self.registry, 'execute_batch', wraps=self.registry.execute_batch) as execute:
            state = run_agent('read', client, self.registry, max_tool_calls=1)
        execute.assert_not_called()
        self.assertEqual((state.termination_reason, state.tool_call_count, client.call_count), ('tool_limit', 0, 1))
        self.assertEqual(state.messages[-1].tool_calls, calls)

    def test_exact_batch_budget_executes_all_then_stops(self):
        calls = (ToolCall('a', 'list_files', {}), ToolCall('b', 'list_files', {}))
        client = ScriptedModelClient([ModelResponse('', 'scripted', tool_calls=calls), self.final()])
        state = run_agent('read', client, self.registry, max_tool_calls=2)
        self.assertEqual((state.termination_reason, client.call_count, self.registry.handler_calls), ('tool_limit', 1, 2))

    def test_rejected_calls_also_consume_dispatch_budget(self):
        client = ScriptedModelClient([proposal('bad', 'read_file', {})], repeat_last=True)
        state = run_agent('retry', client, self.registry, max_tool_calls=2)
        self.assertEqual((state.tool_call_count, client.call_count, self.registry.handler_calls), (2, 2, 0))
        self.assertEqual(state.termination_reason, 'tool_limit')

    def test_budget_values_must_be_positive_nonboolean_integers(self):
        for name in ('max_rounds', 'max_tool_calls'):
            for value in (0, -1, True, 2.5, '2', None):
                with self.subTest(name=name, value=value):
                    client = ScriptedModelClient([self.final()])
                    with self.assertRaises(ValueError):
                        run_agent('task', client, self.registry, **{name: value})
                    self.assertEqual(client.call_count, 0)

    def test_invalid_task_does_not_call_model(self):
        for task in ('', ' ', None, 'x' * 5001):
            client = ScriptedModelClient([self.final()])
            self.assertEqual(run_agent(task, client, self.registry).termination_reason, 'invalid_input')
            self.assertEqual(client.call_count, 0)

    def test_empty_or_malformed_response_is_not_final(self):
        for response in (None, {}, 'done', self.final(' '), ModelResponse(None, 'bad'),
                         ModelResponse('', 'bad', tool_calls=('not a ToolCall',)),
                         ModelResponse('done', 'bad', tool_calls=None)):
            with self.subTest(response=response):
                state = run_agent('task', ScriptedModelClient([response]), self.registry)
                self.assertEqual((state.status, state.termination_reason), ('failed', 'protocol_error'))
        self.assertEqual(self.registry.handler_calls, 0)

    def test_duplicate_and_invalid_ids_reuse_registry_rejection(self):
        for ids in (('same', 'same'), ('valid', ''), ('valid', None)):
            calls = tuple(ToolCall(call_id, 'list_files', {}) for call_id in ids)
            client = ScriptedModelClient([ModelResponse('', 'scripted', tool_calls=calls), self.final()])
            with patch.object(self.registry, 'execute_batch', wraps=self.registry.execute_batch) as batch:
                state = run_agent('task', client, self.registry)
            batch.assert_called_once_with(calls)
            results = [m.result for m in state.messages if isinstance(m, ToolMessage)]
            self.assertEqual([r.call_id for r in results], list(ids))
            self.assertTrue(all(r.error.code == 'protocol_error' for r in results))
            self.assertEqual((state.status, client.call_count, self.registry.handler_calls), ('failed', 1, 0))

    def test_internal_tool_runtime_error_stops_without_fake_tool_result(self):
        client = ScriptedModelClient([self.read(), self.final()])
        with patch('devagent.tools.registry.files.read_file', side_effect=RuntimeError('secret traceback')):
            state = run_agent('task', client, self.registry)
        self.assertEqual((state.status, state.termination_reason, client.call_count), ('failed', 'internal_error', 1))
        self.assertFalse(any(isinstance(m, ToolMessage) for m in state.messages))
        self.assertNotIn('secret traceback', str(asdict(state)))

    def test_model_errors_are_terminal_without_retry_or_exception_text(self):
        for error, reason in ((ProviderTimeoutError('secret'), 'model_error'),
                              (RuntimeError('secret'), 'internal_error')):
            client = ScriptedModelClient([self.final()])
            with patch.object(client, 'complete', side_effect=error) as complete:
                state = run_agent('task', client, self.registry)
            complete.assert_called_once()
            self.assertEqual((state.status, state.termination_reason), ('failed', reason))
            self.assertNotIn('secret', str(asdict(state)))

    def test_metadata_does_not_expand_host_authority_through_loop(self):
        calls = (ToolCall('safe', 'read_file', {'path': 'a.py', 'client_note': 'debug', 'client_tags': []}),
                 ToolCall('unsafe', 'read_file', {'path': 'a.py', 'workspace': '/', 'max_lines': 999}))
        client = ScriptedModelClient([ModelResponse('', 'scripted', tool_calls=calls), self.final()])
        with patch('devagent.tools.registry.files.read_file', wraps=files.read_file) as reader:
            run_agent('task', client, self.registry)
        reader.assert_called_once_with(self.root.resolve(), path='a.py')
        self.assertEqual(observations(client.requests[1])[1].error.code, 'invalid_args')

    def test_client_cannot_mutate_previous_evidence_or_registry_specs(self):
        def mutate(request):
            observations(request)[0].data['content'] = 'forged'
            request.tools[0].input_schema['properties']['workspace'] = {'type': 'string'}
            return self.final()
        client = ScriptedModelClient([self.read(), mutate])
        state = run_agent('task', client, self.registry)
        self.assertEqual(state.messages[2].result.data['content'], 'actual source\nsecond\n')
        self.assertEqual(observations(client.requests[1])[0].data['content'], 'actual source\nsecond\n')
        self.assertNotIn('workspace', self.registry.specs[0].input_schema['properties'])

    def test_text_accompanying_tools_is_not_final(self):
        client = ScriptedModelClient([ModelResponse('I am done', 'scripted', tool_calls=self.read().tool_calls), self.final()])
        state = run_agent('task', client, self.registry)
        self.assertEqual((state.output, client.call_count, self.registry.handler_calls), ('done', 2, 1))

    def test_l00_text_and_l03_requires_tools_remain_single_call(self):
        self.assertEqual(ModelRequest('old').messages, ())
        for mode, status in (('success', 'succeeded'), ('tool_call', 'requires_tools')):
            client = FakeModelClient(mode)
            result = run_task('task', client, trace_path=self.root / 'trace.jsonl')
            self.assertEqual((result.status, client.call_count), (status, 1))
        self.assertEqual(self.registry.handler_calls, 0)

    def test_real_adapter_rejects_history_alone_and_loop_before_network(self):
        transport = ScriptedTransport(response={})
        client = OpenAICompatibleAdapter(config=fixture_config(), transport=transport)
        with self.assertRaises(NotImplementedError):
            client.complete(ModelRequest('task', messages=(UserMessage('task'),)))
        state = run_agent('task', client, self.registry)
        self.assertEqual((state.status, state.termination_reason), ('failed', 'unsupported_model_mode'))
        self.assertEqual((client.call_count, transport.call_count), (0, 0))

    def test_all_offline_demos_and_real_blocked(self):
        for case in CASES:
            with self.subTest(case=case):
                report = run_case(case)
                self.assertTrue(report['checks'])
                if case == 'real-read':
                    self.assertTrue(report['blocked'])
                    self.assertFalse(report['verified'])
                else:
                    self.assertTrue(report['verified'])
                    self.assertEqual(report['verified'], all(report['checks'].values()))

    def test_demo_detects_fabricated_read_content(self):
        with patch('devagent.tools.registry.files.read_file',
                   return_value=files.FileReadResult('pagination.py', 1, 3, 'fabricated', True, 4)):
            self.assertFalse(run_case('read-then-answer')['verified'])


if __name__ == '__main__':
    unittest.main()
