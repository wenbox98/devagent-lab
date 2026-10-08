from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from devagent.agent.workflow import ReadPlan, run_readonly_workflow
from devagent.demos.l06 import CASES, answer_fields, main, run_case, scripted_reader
from devagent.demos.l01 import ScriptedTransport, fixture_config
from devagent.fake_model import ScriptedModelClient
from devagent.models import ModelResponse
from devagent.providers.adapter import OpenAICompatibleAdapter
from devagent.tasks.clarification import Constraints, TaskGoal, decide, merge_answer
from devagent.tasks.session import TaskSession
from devagent.tools.protocol import ToolCall
from devagent.tools.registry import ToolRegistry


class TestL06Clarification(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'a.py'
        self.path.write_bytes(b'actual source\nsecond line\n')
        self.registry = ToolRegistry(self.root)
        self.plan = ReadPlan('a.py', 1, 2)
        self.goal = TaskGoal('优化接口', Constraints(('a.py',), preserve_signature=True),
                             assumptions=('可能是性能问题',))

    def waiting(self, *, strategy='workflow'):
        session = TaskSession('优化接口', self.goal, self.registry)
        client = scripted_reader(self.plan) if strategy == 'agent' else None
        session.investigate(self.plan, strategy=strategy, client=client)
        return session, session.assess('optimize_code'), client

    def test_structures_separate_requirements_preferences_and_assumptions(self):
        goal = replace(self.goal, constraints=replace(self.goal.constraints, preferences=('简短解释',)))
        decision = decide(goal, 'optimize_code')
        self.assertEqual(decision.clarification.missing_fields, ('optimization_dimension',))
        self.assertIsNone(goal.optimization_dimension)
        self.assertEqual(goal.assumptions, ('可能是性能问题',))
        self.assertEqual(goal.constraints.preferences, ('简短解释',))

    def test_malformed_structured_input_is_rejected(self):
        for kwargs in ({'goal': ''}, {'acceptance': ['unchecked']}, {'constraints': {}},
                       {'assumptions': (1,)}, {'optimization_dimension': ' '}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                TaskGoal(**{'goal': 'task', **kwargs})
        with self.assertRaises(ValueError):
            Constraints(preserve_signature=1)
        for start, end in ((True, 2), (0, 2), (3, 2), (1, 2.5)):
            with self.assertRaises(ValueError):
                ReadPlan('a.py', start, end)

    def test_missing_conditions_do_not_block_read_proposals(self):
        for action in ('read_file', 'list_files', 'search_text'):
            self.assertEqual(decide(TaskGoal('解释分页'), action).status, 'can_gather_evidence')

    def test_host_action_classification_cannot_be_overridden(self):
        for action in ('run_command', 'delete_file', 'write_file', 'safe_write', '__import__'):
            self.assertEqual(decide(self.goal, action).status, 'rejected')
        with self.assertRaises(TypeError):
            decide(self.goal, 'optimize_code', has_side_effect=False, confidence=1.0)
        self.assertEqual(decide(self.goal, 'optimize_code').status, 'waiting_input')

    def test_one_specific_missing_field_at_a_time(self):
        goal = TaskGoal('优化')
        updates = ({'optimization_dimension': '首屏耗时'}, {'allowed_scope': ('a.py',)},
                   {'preserve_signature': True}, {'acceptance': ('耗时低于基线',)})
        for fields in updates:
            decision = decide(goal, 'optimize_code')
            self.assertEqual(decision.status, 'waiting_input')
            self.assertEqual(decision.clarification.missing_fields, tuple(fields))
            self.assertTrue(decision.reason)
            goal = merge_answer(goal, decision.clarification, fields)
        self.assertEqual(decide(goal, 'optimize_code').status, 'ready_for_policy_check')

    def test_clear_task_collects_evidence_without_question(self):
        goal = replace(self.goal, goal='修正第一页偏移', acceptance=('第一页从索引0开始',))
        session = TaskSession(goal.goal, goal, self.registry)
        state = session.investigate(self.plan)
        self.assertEqual(state.investigation.output, self.path.read_text(encoding='utf-8'))
        self.assertEqual(state.status, 'evidence_collected')
        state = session.assess('modify_code')
        self.assertEqual(state.status, 'ready_for_policy_check')
        self.assertIsNone(state.pending)

    def test_ready_is_not_write_authorization_or_execution(self):
        original = self.path.read_bytes()
        session, waiting, _ = self.waiting()
        state = session.resume(waiting.task_id, waiting.question_id, '首屏耗时，保持返回结构', answer_fields())
        self.assertEqual(state.status, 'ready_for_policy_check')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.registry.handler_calls, 2)
        self.assertEqual(self.registry.execute(ToolCall('write', 'write_file', {'path': 'a.py'})).error.code, 'unknown_tool')

    def test_waiting_does_not_poll_or_repeat_question_or_read(self):
        session, waiting, client = self.waiting(strategy='agent')
        calls = client.call_count, self.registry.handler_calls
        for _ in range(3):
            self.assertEqual(session.assess('optimize_code').question_id, waiting.question_id)
            session.investigate(self.plan, strategy='agent', client=client)
        self.assertEqual((client.call_count, self.registry.handler_calls), calls)
        with self.assertRaises(ValueError):
            session.assess('read_file')

    def test_resume_retains_task_goal_history_and_evidence_without_replaying_tools(self):
        session, waiting, client = self.waiting(strategy='agent')
        before = client.call_count, self.registry.handler_calls
        state = session.resume(waiting.task_id, waiting.question_id, '优化首屏耗时，保持返回结构', answer_fields())
        self.assertEqual((state.task_id, state.original_task, state.goal.goal), (waiting.task_id, '优化接口', '优化接口'))
        self.assertEqual(state.investigation, waiting.investigation)
        self.assertEqual(state.goal.constraints.preserve_signature, True)
        self.assertEqual(state.goal.constraints.preserve_return_structure, True)
        self.assertEqual(state.goal.assumptions, waiting.goal.assumptions)
        self.assertEqual(state.status, 'ready_for_policy_check')
        self.assertIsNone(state.pending)
        session.investigate(self.plan, strategy='agent', client=client)
        self.assertEqual((client.call_count, self.registry.handler_calls), before)

    def test_resume_requires_current_task_question_and_waiting_state(self):
        session, waiting, _ = self.waiting()
        for task_id, question_id in (('other-task', waiting.question_id), (waiting.task_id, 'other-question')):
            with self.assertRaises(ValueError):
                session.resume(task_id, question_id, 'answer', answer_fields())
            self.assertEqual(session.state, waiting)
        session.resume(waiting.task_id, waiting.question_id, 'answer', answer_fields())
        with self.assertRaises(ValueError):
            session.resume(waiting.task_id, waiting.question_id, 'answer', answer_fields())

    def test_conflicting_or_injected_answer_is_atomic_and_preserves_hard_conditions(self):
        session, waiting, _ = self.waiting()
        for extra in ({'preserve_signature': False}, {'allowed_scope': ('../outside.py',)},
                      {'workspace': '/'}, {'tools': ['write_file']}, {'confidence': 1}, {'confirmed_by': 'model'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                session.resume(waiting.task_id, waiting.question_id, 'answer', {**answer_fields(), **extra})
            self.assertEqual(session.state, waiting)
        for updates in ({}, {'optimization_dimension': ''}, {'optimization_dimension': 'latency', 'acceptance': ()}):
            with self.assertRaises(ValueError):
                session.resume(waiting.task_id, waiting.question_id, 'answer', updates)
            self.assertEqual(session.state, waiting)

    def test_acceptance_cannot_be_removed_and_scope_can_only_narrow(self):
        goal = replace(self.goal, acceptance=('keep tests passing',), constraints=Constraints(('a.py', 'b.py'), True))
        question = decide(goal, 'optimize_code').clarification
        with self.assertRaises(ValueError):
            merge_answer(goal, question, {'optimization_dimension': 'latency', 'acceptance': ('ignore tests',)})
        updated = merge_answer(goal, question, {'optimization_dimension': 'latency', 'allowed_scope': ('a.py',)})
        self.assertEqual(updated.acceptance, goal.acceptance)
        self.assertEqual(updated.constraints.allowed_scope, ('a.py',))

    def test_partial_answer_only_asks_next_missing_condition(self):
        session, waiting, _ = self.waiting()
        state = session.resume(waiting.task_id, waiting.question_id, '首屏耗时', {'optimization_dimension': '首屏耗时'})
        self.assertEqual(state.status, 'waiting_input')
        self.assertEqual(state.pending.missing_fields, ('acceptance',))
        self.assertEqual(state.goal.optimization_dimension, '首屏耗时')
        self.assertEqual(self.registry.handler_calls, 2)

    def test_stale_evidence_after_wait_is_not_silently_accepted(self):
        session, waiting, _ = self.waiting()
        self.path.write_bytes(b'changed')
        state = session.resume(waiting.task_id, waiting.question_id, 'answer', answer_fields())
        self.assertEqual((state.status, state.reason), ('failed', 'stale_evidence'))
        self.assertEqual(state.investigation, waiting.investigation)
        self.assertEqual(state.goal, waiting.goal)

    def test_public_snapshot_mutation_does_not_change_live_task(self):
        session, snapshot, _ = self.waiting(strategy='agent')
        snapshot.goal = TaskGoal('forged')
        snapshot.investigation.evidence.clear()
        snapshot.answers.append('fake')
        self.assertEqual(session.state.goal, self.goal)
        self.assertEqual(len(session.state.investigation.evidence), 1)
        self.assertEqual(session.state.answers, [])

    def test_workflow_uses_real_tools_and_bounded_line_window(self):
        result = run_readonly_workflow(ReadPlan('a.py', 2, 2), self.registry)
        self.assertEqual(result.output, 'second line\n')
        self.assertEqual((result.status, result.tool_calls, result.model_calls), ('answered', 2, 0))
        self.assertEqual(result.evidence[0].start_line, 2)
        self.assertEqual([r.call_id for r in result.results], ['list', 'read'])

    def test_workflow_stops_on_listing_failure(self):
        result = run_readonly_workflow(self.plan, ToolRegistry(self.root / 'missing'))
        self.assertEqual((result.status, result.error_code, result.tool_calls), ('failed', 'not_found', 1))
        self.assertFalse(result.evidence)

    def test_model_or_goal_cannot_expand_workspace_or_tool_permissions(self):
        session = TaskSession('read outside', TaskGoal('read', Constraints(('../outside.py',))), self.registry)
        state = session.investigate(ReadPlan('../outside.py'))
        self.assertEqual((state.status, state.reason), ('failed', 'permission_denied'))
        self.assertFalse(state.investigation.evidence)
        self.assertEqual({s.name for s in self.registry.specs}, {'read_file', 'list_files', 'search_text'})

    def test_workflow_missing_and_empty_files_are_not_success_evidence(self):
        for name, code in (('missing.py', 'not_found'), ('empty.py', 'invalid_citation')):
            (self.root / 'empty.py').write_bytes(b'')
            result = run_readonly_workflow(ReadPlan(name), self.registry)
            self.assertEqual((result.status, result.error_code), ('failed', code))
            self.assertFalse(result.evidence)

    def test_internal_error_not_disguised_as_clarification(self):
        with patch.object(self.registry, 'execute', side_effect=RuntimeError('bug')):
            with self.assertRaises(RuntimeError):
                run_readonly_workflow(self.plan, self.registry)

    def test_workflow_and_existing_agent_compare_real_results_and_counts(self):
        states = []
        for strategy in ('workflow', 'agent'):
            session = TaskSession(self.plan.task, TaskGoal(self.plan.task), ToolRegistry(self.root))
            states.append(session.investigate(self.plan, strategy=strategy, client=scripted_reader(self.plan)))
        self.assertEqual(states[0].investigation.output, states[1].investigation.output)
        self.assertEqual(tuple(states[1].investigation.evidence), states[0].investigation.evidence)
        self.assertEqual(states[1].investigation.step_count, 3)
        self.assertEqual(states[1].investigation.tool_call_count, 2)
        self.assertEqual(states[0].investigation.model_calls, 0)
        self.assertEqual(states[0].investigation.tool_calls, 2)

    def test_completed_read_cannot_be_replaced_or_repeated(self):
        session = TaskSession('read', self.goal, self.registry)
        first = session.investigate(self.plan)
        self.assertEqual(session.investigate(self.plan), first)
        self.assertEqual(self.registry.handler_calls, 2)
        with self.assertRaises(ValueError):
            session.investigate(ReadPlan('b.py'))

    def test_model_claim_without_actual_read_is_not_evidence(self):
        session = TaskSession('read', self.goal, self.registry)
        client = ScriptedModelClient([ModelResponse('Already investigated.', 'scripted')])
        state = session.investigate(self.plan, strategy='agent', client=client)
        self.assertEqual((state.status, state.reason), ('failed', 'no_read_evidence'))
        self.assertEqual(self.registry.handler_calls, 0)

    def test_real_provider_loop_still_rejects_before_network(self):
        transport = ScriptedTransport(response={})
        client = OpenAICompatibleAdapter(config=fixture_config(), transport=transport)
        session = TaskSession('read', self.goal, self.registry)
        state = session.investigate(self.plan, strategy='agent', client=client)
        self.assertEqual((state.status, state.reason), ('failed', 'unsupported_model_mode'))
        self.assertEqual((transport.call_count, self.registry.handler_calls), (0, 0))

    def test_demos_and_exit_codes_reflect_actual_checks(self):
        for case in CASES:
            with self.subTest(case=case):
                report = run_case(case)
                self.assertTrue(report['checks'])
                self.assertTrue(report['verified'])
        with patch('sys.argv', ['l06', '--case', 'clear-task']), patch('builtins.print'):
            with patch('devagent.demos.l06.run_case', return_value={'verified': False}):
                self.assertEqual(main(), 1)
            with patch('devagent.demos.l06.run_case', side_effect=FileNotFoundError):
                self.assertEqual(main(), 2)


if __name__ == '__main__':
    unittest.main()
