"""Offline L04 evidence from actual model inputs and real workspace tools."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from ..agent.loop import run_agent
from ..agent.messages import ToolMessage
from ..fake_model import ScriptedModelClient
from ..models import ModelResponse
from ..providers.adapter import OpenAICompatibleAdapter
from ..tools.protocol import ToolCall
from ..tools.registry import ToolRegistry

CASES = ('read-then-answer', 'tool-error-recovery', 'round-budget', 'tool-budget',
         'repair-tool-error', 'step-limit', 'real-read')
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / 'fixtures' / 'tiny_repo'


def proposal(call_id, name, arguments):
    return ModelResponse('', 'scripted', tool_calls=(ToolCall(call_id, name, arguments),))


def observations(request):
    return [message.result for message in request.messages if isinstance(message, ToolMessage)]


def answer_from_read(request):
    result = observations(request)[-1]
    return ModelResponse(result.data['content'] if result.ok else 'read failed', 'scripted')


def run_case(case: str) -> dict:
    if case not in CASES:
        raise ValueError('unknown L04 case')
    registry = ToolRegistry(FIXTURE_ROOT)
    if case == 'real-read':
        client = OpenAICompatibleAdapter(environ={})
        result = run_agent('Read pagination.py', client, registry)
        return {'lesson': 'L04', 'case': case, 'observed': asdict(result),
                'checks': {'rejected_before_network': client.call_count == 0 and
                           result.termination_reason == 'unsupported_model_mode'},
                'verified': False, 'blocked': 'Real provider history/tools are unsupported; no API call.'}
    kwargs = {}
    if case == 'read-then-answer':
        client = ScriptedModelClient([
            proposal('read', 'read_file', {'path': 'pagination.py', 'end_line': 3}), answer_from_read])
    elif case in {'tool-error-recovery', 'repair-tool-error'}:
        invalid = case == 'repair-tool-error'
        first_args = {'path': 'pagination.py', 'start_line': 0} if invalid else {'path': 'missing.py'}
        code = 'invalid_args' if invalid else 'not_found'

        def recover(request):
            error = observations(request)[-1].error
            if error is None or error.code != code or not error.message:
                return ModelResponse('no actionable error received', 'scripted')
            return proposal('recover', 'read_file', {'path': 'pagination.py', 'end_line': 3}) if invalid else proposal('recover', 'list_files', {})

        def recovered_answer(request):
            result = observations(request)[-1]
            return ModelResponse(json.dumps(result.data, ensure_ascii=True) if result.ok else '', 'scripted')

        client = ScriptedModelClient([proposal('bad', 'read_file', first_args), recover, recovered_answer])
    else:
        client = ScriptedModelClient([proposal('again', 'read_file', {'path': 'pagination.py'})], repeat_last=True)
        kwargs = {'max_rounds': 5, 'max_tool_calls': 2} if case == 'tool-budget' else {'max_rounds': 3, 'max_tool_calls': 10}
    result = run_agent('Read the fixture and answer from observations', client, registry, **kwargs)
    feedback = observations(client.requests[1]) if client.call_count > 1 else []
    checks = {'actual_model_count': result.step_count == client.call_count}
    if case == 'read-then-answer':
        with (FIXTURE_ROOT / 'pagination.py').open('rb') as stream:
            expected = b''.join(stream.readlines(4096)[:3]).decode('utf-8')
        checks.update(answered=result.status == 'answered', model_calls=client.call_count == 2,
                      tool_calls=result.tool_call_count == registry.handler_calls == 1,
                      real_feedback=len(feedback) == 1 and feedback[0].ok and feedback[0].call_id == 'read'
                      and feedback[0].data['content'] == expected,
                      answer_from_feedback=result.output == expected)
    elif case in {'tool-error-recovery', 'repair-tool-error'}:
        checks.update(answered=result.status == 'answered', model_calls=client.call_count == 3,
                      tool_calls=result.tool_call_count == 2,
                      error_feedback=len(feedback) == 1 and feedback[0].call_id == 'bad'
                      and feedback[0].error is not None and feedback[0].error.code == code
                      and bool(feedback[0].error.message),
                      recovered=len(client.requests) == 3 and observations(client.requests[2])[-1].ok,
                      handler_calls=registry.handler_calls == (1 if invalid else 2))
    else:
        limit = 2 if case == 'tool-budget' else 3
        checks.update(stopped=result.status == 'budget_exhausted',
                      reason=result.termination_reason == ('tool_limit' if case == 'tool-budget' else 'step_limit'),
                      bounded=client.call_count == registry.handler_calls == result.tool_call_count == limit)
    return {'lesson': 'L04', 'case': case,
            'observed': {'state': asdict(result), 'model_calls': client.call_count,
                         'handler_calls': registry.handler_calls,
                         'second_request': asdict(client.requests[1]) if client.call_count > 1 else None},
            'checks': checks, 'verified': all(checks.values())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--list-cases', action='store_true')
    args = parser.parse_args()
    if args.list_cases:
        print(json.dumps({'lesson': 'L04', 'cases': CASES}))
        return 0
    if not args.case:
        parser.error('--case is required')
    report = run_case(args.case)
    print(json.dumps(report, ensure_ascii=True))
    return 2 if report.get('blocked') else (0 if report['verified'] else 1)


if __name__ == '__main__':
    raise SystemExit(main())
