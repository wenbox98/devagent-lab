import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from devagent.app import run_task
from devagent.config import ConfigMissingError, ProviderConfig, load_provider_config
from devagent.demos.l01 import ScriptedTransport, fixture_config, run_case
from devagent.models import ModelRequest
from devagent.providers.adapter import (OpenAICompatibleAdapter, ProviderAuthenticationError,
                                        ProviderRateLimitError, ProviderResponseError,
                                        ProviderTimeoutError, UrllibJsonTransport,
                                        normalize_response)


class TestL01ProviderBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_task(self, client, name='trace'):
        return run_task('short question', client, trace_path=self.root / f'{name}.jsonl')

    def test_missing_config_is_distinct_and_never_calls_network(self):
        transport = ScriptedTransport(response={})
        result = self.run_task(OpenAICompatibleAdapter(environ={}, transport=transport))
        self.assertEqual((result.error_code, result.exit_code), ('config_missing', 6))
        self.assertEqual(transport.call_count, 0)
        with self.assertRaises(ConfigMissingError):
            load_provider_config({})

    def test_config_is_environment_only_and_secret_is_hidden_from_repr(self):
        environ = {'DEVAGENT_PROVIDER': 'fixture', 'DEVAGENT_MODEL': 'm',
                   'DEVAGENT_API_KEY': 'private-value',
                   'DEVAGENT_API_BASE_URL': 'https://provider.invalid/v1',
                   'DEVAGENT_TIMEOUT_SECONDS': '2.5'}
        config = load_provider_config(environ)
        self.assertEqual(config.timeout_seconds, 2.5)
        self.assertNotIn('private-value', repr(config))
        for value in ('0', '-1', 'abc'):
            with self.subTest(value=value), self.assertRaises(ConfigMissingError):
                load_provider_config({**environ, 'DEVAGENT_TIMEOUT_SECONDS': value})

    def test_two_provider_names_normalize_to_same_domain_contract(self):
        raw = {'model': 'returned', 'choices': [{'message': {'content': 'answer'}}],
               'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}
        for provider in ('fixture-a', 'fixture-b'):
            with self.subTest(provider=provider):
                response = normalize_response(raw, fixture_config(provider))
                self.assertEqual((response.text, response.provider, response.model),
                                 ('answer', provider, 'returned'))
                self.assertEqual((response.input_tokens, response.output_tokens), (3, 2))

    def test_missing_usage_remains_unknown_while_explicit_zero_is_zero(self):
        base = {'choices': [{'message': {'content': 'answer'}}]}
        unknown = normalize_response(base, fixture_config())
        zero = normalize_response({**base, 'usage': {'prompt_tokens': 0, 'completion_tokens': 0}},
                                  fixture_config())
        self.assertEqual((unknown.input_tokens, unknown.output_tokens), (None, None))
        self.assertEqual((zero.input_tokens, zero.output_tokens), (0, 0))

    def test_provider_errors_stay_distinct_and_are_not_retried(self):
        cases = [(ProviderAuthenticationError('x'), 'provider_authentication', 7),
                 (ProviderRateLimitError('x'), 'provider_rate_limit', 8),
                 (ProviderTimeoutError('x'), 'provider_timeout', 3)]
        for index, (failure, code, exit_code) in enumerate(cases):
            with self.subTest(code=code):
                transport = ScriptedTransport(failure=failure)
                result = self.run_task(OpenAICompatibleAdapter(config=fixture_config(), transport=transport), str(index))
                self.assertEqual((result.error_code, result.exit_code), (code, exit_code))
                self.assertEqual(transport.call_count, 1)

    def test_http_transport_maps_status_and_timeout_without_retry(self):
        transport = UrllibJsonTransport()
        cases = [(HTTPError('https://provider.invalid', 401, 'unauthorized', None, None),
                  ProviderAuthenticationError),
                 (HTTPError('https://provider.invalid', 429, 'limited', None, None),
                  ProviderRateLimitError),
                 (TimeoutError('late'), ProviderTimeoutError)]
        for failure, expected in cases:
            with self.subTest(expected=expected.__name__), \
                    patch('devagent.providers.adapter.request.urlopen', side_effect=failure) as urlopen, \
                    self.assertRaises(expected):
                transport.post_json('https://provider.invalid/v1/chat/completions', {}, {}, 1)
            self.assertEqual(urlopen.call_count, 1)

    def test_response_schema_failures_are_not_empty_success(self):
        malformed = ({}, {'choices': []}, {'choices': [{'message': {'content': None}}]},
                     {'choices': [{'message': {'content': 'ok'}}], 'usage': 'unknown'})
        for index, raw in enumerate(malformed):
            with self.subTest(raw=raw):
                transport = ScriptedTransport(response=raw)
                result = self.run_task(OpenAICompatibleAdapter(config=fixture_config(), transport=transport), str(index))
                self.assertEqual((result.error_code, result.exit_code), ('provider_parse_error', 4))
                self.assertEqual(transport.call_count, 1)

    def test_adapter_sends_domain_request_and_returns_domain_response(self):
        transport = ScriptedTransport(response={'model': 'returned',
            'choices': [{'message': {'content': 'answer'}}],
            'usage': {'prompt_tokens': 4, 'completion_tokens': 1}})
        client = OpenAICompatibleAdapter(config=fixture_config(), transport=transport)
        response = client.complete(ModelRequest('question'))
        self.assertEqual((response.text, response.provider, response.model),
                         ('answer', 'fixture-provider', 'returned'))
        self.assertEqual((response.input_tokens, response.output_tokens), (4, 1))
        self.assertEqual(transport.call_count, 1)

    def test_offline_demos_derive_verdict_and_real_once_is_blocked_without_config(self):
        for case in ('fake-regression', 'missing-config', 'provider-errors', 'usage-unknown'):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                report = run_case(case, Path(directory), {})
                self.assertTrue(report['checks'])
                self.assertTrue(report['verified'])
                self.assertEqual(report['verified'], all(report['checks'].values()))
        report = run_case('real-once', self.root, {})
        self.assertFalse(report['verified'])
        self.assertEqual(report['blocked']['code'], 'config_missing')
        self.assertFalse(report['observed']['paid_api_called'])

    def test_cli_real_without_config_reports_blocked_business_result(self):
        clean_env = {key: value for key, value in os.environ.items() if not key.startswith('DEVAGENT_')}
        proc = subprocess.run([sys.executable, '-B', '-m', 'devagent', '--client', 'real',
                               '--task', 'short question', '--trace-path', str(self.root / 'cli.jsonl')],
                              capture_output=True, text=True, timeout=10, env=clean_env)
        self.assertEqual(proc.returncode, 6)
        self.assertEqual(json.loads(proc.stdout)['error_code'], 'config_missing')
        self.assertEqual(proc.stderr, '')


if __name__ == '__main__':
    unittest.main()
