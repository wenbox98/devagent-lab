"""L06 controlled structured inputs; no general NLP extraction or real LLM call."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter

from .l04 import observations, proposal
from ..agent.citations import citation_from_read
from ..agent.loop import AgentState
from ..agent.workflow import ReadPlan
from ..fake_model import ScriptedModelClient
from ..models import ModelResponse
from ..tasks.clarification import Constraints, TaskGoal
from ..tasks.session import TaskSession
from ..tools.files import FileReadResult
from ..tools.registry import ToolRegistry

CASES = ('clear-task', 'ambiguous-task', 'resume-answer', 'workflow-compare')
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / 'fixtures' / 'tiny_repo'
PLAN = ReadPlan('pagination.py', 1, 6)


def clear_goal():
    return TaskGoal('修正分页边界：第一页编号为 1，不改函数签名',
                    Constraints(('pagination.py',), preserve_signature=True),
                    ('第一页返回前 size 项，第二页返回接下来的 size 项',),
                    ('暂假定没有外部调用方依赖当前错误偏移，尚未验证',))


def ambiguous_goal():
    # Scope/signature are explicit host task context, not inferred permission.
    return TaskGoal('优化接口', Constraints(('pagination.py',), preserve_signature=True),
                    assumptions=('可能是性能问题，尚未确认',))


def answer_fields():
    # Explicit fixture/form fields; NOT a parser claiming arbitrary text is authorization.
    return {'optimization_dimension': '首屏耗时', 'preserve_return_structure': True,
            'acceptance': ('相同输入下首屏耗时低于当前基线，返回结构保持不变',)}


def scripted_reader(plan):
    def read_after_list(request):
        listing = observations(request)[-1]
        if not listing.ok:
            return ModelResponse('Listing failed.', 'scripted')
        return proposal('read', 'read_file', plan.arguments)

    def answer_after_read(request):
        read = observations(request)[-1]
        if not read.ok:
            return ModelResponse('Reading failed.', 'scripted')
        citation = citation_from_read(FileReadResult(**read.data))
        return ModelResponse(read.data['content'], 'scripted', citations=(citation,))

    return ScriptedModelClient([proposal('list', 'list_files', {}), read_after_list, answer_after_read])


def summarize(state, registry):
    result = state.investigation
    return {'task_id': state.task_id, 'original_task': state.original_task, 'status': state.status,
            'reason': state.reason, 'goal': asdict(state.goal),
            'pending': asdict(state.pending) if state.pending else None, 'question_id': state.question_id,
            'plan': asdict(state.plan) if state.plan else None,
            'model_calls': result.step_count if isinstance(result, AgentState) else result.model_calls if result else 0,
            'tool_calls': result.tool_call_count if isinstance(result, AgentState) else result.tool_calls if result else 0,
            'handler_calls': registry.handler_calls,
            'output': result.output if result else None,
            'evidence': [asdict(c) for c in result.evidence] if result else []}


def run_case(case):
    if case not in CASES:
        raise ValueError('unknown L06 case')
    expected = (FIXTURE_ROOT / PLAN.path).read_bytes().decode('utf-8')
    if case == 'workflow-compare':
        runs = {}
        for strategy in ('workflow', 'agent'):
            registry = ToolRegistry(FIXTURE_ROOT)
            session = TaskSession(PLAN.task, TaskGoal(PLAN.task), registry)
            client = scripted_reader(PLAN) if strategy == 'agent' else None
            start = perf_counter()
            state = session.investigate(PLAN, strategy=strategy, client=client)
            runs[strategy] = summarize(state, registry)
            runs[strategy]['elapsed_seconds'] = perf_counter() - start
        checks = {'both_answer_from_real_content': all(r['status'] == 'evidence_collected' and r['output'] == expected for r in runs.values()),
                  'same_evidence': bool(runs['workflow']['evidence']) and runs['workflow']['evidence'] == runs['agent']['evidence'],
                  'actual_counts': all(r['handler_calls'] == r['tool_calls'] == 2 for r in runs.values())
                  and runs['workflow']['model_calls'] == 0 and runs['agent']['model_calls'] == 3}
        observed = runs
    else:
        registry = ToolRegistry(FIXTURE_ROOT)
        goal = clear_goal() if case == 'clear-task' else ambiguous_goal()
        session = TaskSession(goal.goal, goal, registry)
        reading = session.investigate(PLAN)
        state = session.assess('modify_code' if case == 'clear-task' else 'optimize_code')
        checks = {'real_read': reading.status == 'evidence_collected' and reading.investigation.output == expected,
                  'evidence': len(reading.investigation.evidence) == 1}
        if case == 'clear-task':
            checks.update(no_question=state.pending is None, conditions_ready=state.status == 'ready_for_policy_check',
                          only_reads=registry.handler_calls == 2)
            observed = summarize(state, registry)
        else:
            before = registry.handler_calls
            same = session.assess('optimize_code')
            session.investigate(PLAN)
            checks.update(waiting=state.status == 'waiting_input',
                          specific=state.pending is not None and state.pending.missing_fields == ('optimization_dimension',),
                          stable_question=same.question_id == state.question_id,
                          stopped=registry.handler_calls == before)
            observed = {'waiting': summarize(state, registry)}
            if case == 'resume-answer':
                resumed = session.resume(state.task_id, state.question_id, '优化首屏耗时，保持返回结构', answer_fields())
                session.investigate(PLAN)
                checks.update(same_task=resumed.task_id == state.task_id and resumed.original_task == state.original_task,
                              evidence_preserved=resumed.investigation == state.investigation,
                              no_repeat=registry.handler_calls == before and resumed.pending is None,
                              merged=resumed.goal.optimization_dimension == '首屏耗时'
                              and resumed.goal.constraints.preserve_return_structure is True,
                              ready_not_authorized=resumed.status == 'ready_for_policy_check')
                observed['resumed'] = summarize(resumed, registry)
    return {'lesson': 'L06', 'case': case, 'observed': observed, 'checks': checks,
            'verified': all(checks.values()), 'scope': 'deterministic structured inputs and scripted model; no real LLM or write execution'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--list-cases', action='store_true')
    args = parser.parse_args()
    if args.list_cases:
        print(json.dumps({'lesson': 'L06', 'cases': CASES}))
        return 0
    if not args.case:
        parser.error('--case is required')
    try:
        report = run_case(args.case)
    except FileNotFoundError:
        report = {'lesson': 'L06', 'case': args.case, 'observed': {}, 'checks': {'fixture_available': False},
                  'verified': False, 'blocked': 'Required local fixture is missing.'}
    print(json.dumps(report, ensure_ascii=True))
    return 2 if report.get('blocked') else 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
