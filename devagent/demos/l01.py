"""L01 provider-boundary demonstrations with deterministic fault injection."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from ..app import run_task
from ..config import ConfigMissingError, ProviderConfig, load_provider_config
from ..fake_model import FakeModelClient
from ..providers.adapter import (OpenAICompatibleAdapter, ProviderAuthenticationError,
                                 ProviderRateLimitError, ProviderTimeoutError)

CASES = ('fake-regression', 'missing-config', 'provider-errors', 'usage-unknown', 'real-once')


class ScriptedTransport:
    def __init__(self, *, response=None, failure=None):
        self.response = response
        self.failure = failure
        self.call_count = 0

    def post_json(self, url, headers, payload, timeout):
        self.call_count += 1
        if self.failure is not None:
            raise self.failure
        return self.response


def fixture_config(provider='fixture-provider'):
    return ProviderConfig(provider=provider, model='fixture-model', api_key='fixture',
                          base_url='https://provider.invalid/v1', timeout_seconds=1)


def _run(task, client, root, name):
    return run_task(task, client, trace_path=root / f'{name}.jsonl')


def run_case(case: str, root: Path, environ=None) -> dict:
    blocked = None
    observed = {}
    checks = {}
    if case == 'fake-regression':
        success_client = FakeModelClient()
        timeout_client = FakeModelClient('timeout')
        bad_client = FakeModelClient('bad_response')
        success = _run('  explain pagination  ', success_client, root, 'fake-success')
        timeout = _run('fix', timeout_client, root, 'fake-timeout')
        invalid = _run('fix', bad_client, root, 'fake-invalid')
        observed = {'success': asdict(success), 'timeout': asdict(timeout), 'invalid': asdict(invalid)}
        checks = {
            'success_preserved': success.status == 'succeeded' and success.provider == 'fake',
            'timeout_preserved': timeout.error_code == 'model_timeout' and timeout_client.call_count == 1,
            'invalid_response_preserved': invalid.error_code == 'invalid_response' and bad_client.call_count == 1,
        }
    elif case == 'missing-config':
        transport = ScriptedTransport(response={})
        client = OpenAICompatibleAdapter(environ={}, transport=transport)
        result = _run('short question', client, root, case)
        observed = {'result': asdict(result), 'network_call_count': transport.call_count}
        checks = {'classified': result.error_code == 'config_missing', 'no_network_call': transport.call_count == 0}
    elif case == 'provider-errors':
        scenarios = {
            'authentication': (ProviderAuthenticationError('fixture'), 'provider_authentication'),
            'rate_limit': (ProviderRateLimitError('fixture'), 'provider_rate_limit'),
            'timeout': (ProviderTimeoutError('fixture'), 'provider_timeout'),
        }
        results = {}
        calls = {}
        for name, (failure, expected) in scenarios.items():
            transport = ScriptedTransport(failure=failure)
            result = _run('short question', OpenAICompatibleAdapter(config=fixture_config(), transport=transport),
                          root, name)
            results[name] = asdict(result)
            calls[name] = transport.call_count
            checks[name] = result.error_code == expected and transport.call_count == 1
        observed = {'results': results, 'network_call_counts': calls}
    elif case == 'usage-unknown':
        transport = ScriptedTransport(response={
            'model': 'fixture-returned-model',
            'choices': [{'message': {'content': 'fixture answer'}}],
        })
        result = _run('short question', OpenAICompatibleAdapter(config=fixture_config(), transport=transport),
                      root, case)
        observed = {'result': asdict(result), 'network_call_count': transport.call_count}
        checks = {
            'content_available': result.status == 'succeeded' and result.output == 'fixture answer',
            'usage_unknown': result.input_tokens is None and result.output_tokens is None,
            'provider_metadata': result.provider == 'fixture-provider' and result.model == 'fixture-returned-model',
        }
    elif case == 'real-once':
        values = os.environ if environ is None else environ
        try:
            config = load_provider_config(values)
        except ConfigMissingError as exc:
            blocked = {'code': 'config_missing', 'reason': str(exc)}
            observed = {'paid_api_called': False}
            checks = {'configuration_available': False}
        else:
            result = _run('Reply with the single word OK.', OpenAICompatibleAdapter(config=config), root, case)
            observed = {'result': asdict(result), 'paid_api_called': True,
                        'client_version': config.client_version}
            checks = {'real_response': result.status == 'succeeded',
                      'provider_recorded': result.provider == config.provider,
                      'model_recorded': result.model is not None}
    else:
        raise ValueError('unknown case')
    report = {'lesson': 'L01', 'case': case, 'observed': observed, 'checks': checks,
              'verified': blocked is None and bool(checks) and all(checks.values())}
    if blocked is not None:
        report['blocked'] = blocked
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--list-cases', action='store_true')
    args = parser.parse_args()
    if args.list_cases:
        print(json.dumps({'lesson': 'L01', 'cases': CASES}))
        return 0
    if args.case is None:
        parser.error('--case or --list-cases is required')
    try:
        with TemporaryDirectory(prefix='devagent-l01-') as directory:
            report = run_case(args.case, Path(directory))
    except OSError as exc:
        report = {'lesson': 'L01', 'case': args.case,
                  'observed': {'status': 'blocked', 'reason': type(exc).__name__},
                  'checks': {'environment_ready': False}, 'verified': False,
                  'blocked': {'code': 'environment', 'reason': str(exc)}}
    print(json.dumps(report, ensure_ascii=False))
    if 'blocked' in report:
        return 2
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
