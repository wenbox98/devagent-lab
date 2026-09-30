"""Deterministic feedback/evidence demos, not measurements of LLM accuracy."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .l01 import ScriptedTransport, fixture_config
from .l04 import observations, proposal
from ..agent.citations import CitationError, citation_from_read, validate_citation
from ..agent.loop import run_agent
from ..fake_model import ScriptedModelClient
from ..models import ModelResponse
from ..providers.adapter import OpenAICompatibleAdapter
from ..tools.files import FileReadResult, read_file
from ..tools.protocol import ToolCall
from ..tools.registry import ToolRegistry

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / 'fixtures' / 'tiny_repo'
CASES = ('same-name', 'no-match', 'citation-check', 'real-locate', 'exact-symbol', 'feature-description')
TASKS = {
    'same-name': ('Locate list pagination among same-name functions', 'page'),
    'exact-symbol': ('Locate page(items, page_no, size)', 'def page(items,'),
    'feature-description': ('Locate the computation of a page offset', 'start ='),
    'no-match': ('Locate a deliberately absent marker', 'L05_missing_marker_92e16'),
}


def scripted_locator(query):
    def read_candidates(request):
        search = observations(request)[-1]
        if not search.ok:
            return ModelResponse('Search failed; no conclusion.', 'scripted')
        paths = sorted({item['path'] for item in search.data['matches']}, reverse=True)
        if not paths:
            return ModelResponse('No evidence in this search scope.', 'scripted')
        # Read all candidates, deliberately not just the first search hit.
        calls = tuple(ToolCall(f'read-{i}', 'read_file', {'path': path, 'end_line': 20})
                      for i, path in enumerate(paths))
        return ModelResponse('', 'scripted', tool_calls=calls)

    def select_from_context(request):
        evidence = []
        for result in observations(request):
            if result.ok and isinstance(result.data, dict) and result.data.get('source_hash'):
                content = result.data['content']
                # A fixture-specific lexical rule, never a filename decision or LLM claim.
                if 'page_no * size' in content and 'items[' in content:
                    evidence.append(citation_from_read(FileReadResult(**result.data)))
        return ModelResponse('The read context contains the pagination offset calculation.'
                             if evidence else 'No matching read evidence.', 'scripted', citations=tuple(evidence))

    return ScriptedModelClient([
        proposal('search', 'search_text', {'query': query, 'include_globs': ['*.py']}),
        read_candidates, select_from_context])


def _rejection(root, citation):
    try:
        validate_citation(root, citation)
    except CitationError as exc:
        return exc.code
    return None


def run_case(case):
    if case not in CASES:
        raise ValueError('unknown L05 case')
    if case == 'real-locate':
        transport = ScriptedTransport(response={})
        client = OpenAICompatibleAdapter(config=fixture_config(), transport=transport)
        state = run_agent('Locate the pagination offset', client, ToolRegistry(FIXTURE_ROOT))
        return {'lesson': 'L05', 'case': case, 'observed': {
            'status': state.status, 'reason': state.termination_reason, 'http_requests': transport.call_count},
            'checks': {'network_not_called': transport.call_count == 0,
                       'unsupported': state.termination_reason == 'unsupported_model_mode'},
            'verified': False, 'blocked': 'Provider tools/history unsupported; real localization not verified.'}
    if case == 'citation-check':
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'sample.py'
            path.write_bytes(b'old content\n')
            evidence = citation_from_read(read_file(temp, path.name))
            invalid = _rejection(temp, replace(evidence, end_line=900))
            path.write_bytes(b'changed content\n')
            stale = _rejection(temp, evidence)
        observed = {'out_of_range': invalid, 'old_version': stale}
        checks = {'invalid_rejected': invalid == 'invalid_citation', 'stale_rejected': stale == 'stale_evidence'}
    else:
        task, query = TASKS[case]
        client = scripted_locator(query)
        registry = ToolRegistry(FIXTURE_ROOT)
        state = run_agent(task, client, registry)
        search = observations(client.requests[1])[0]
        read_results = [m.result for m in state.messages if hasattr(m, 'result')
                        and m.result.ok and isinstance(m.result.data, dict) and 'source_hash' in m.result.data]
        observed = {'status': state.status, 'search': asdict(search),
                    'read_paths': [r.data['path'] for r in read_results],
                    'evidence_paths': [c.source_path for c in state.evidence],
                    'citations': [asdict(c) for c in state.citations], 'model_calls': client.call_count,
                    'scope': 'scripted feedback and evidence assembly only; not real LLM accuracy'}
        checks = {'answered': state.status == 'answered', 'search_succeeded': search.ok}
        if case == 'no-match':
            checks.update(empty=search.data['matches'] == [], complete=not search.data['truncated'],
                          no_evidence=not state.citations and not state.evidence, two_rounds=client.call_count == 2)
        else:
            checks.update(three_rounds=client.call_count == 3, selected=len(state.citations) == 1
                          and state.citations[0].source_path == 'pagination.py',
                          read_provenance=bool(state.citations) and all(c in state.evidence for c in state.citations))
            if case == 'same-name':
                candidates = {m['path'] for m in search.data['matches']}
                expected = {'pagination.py', 'reporting.py', 'export.py'}
                checks.update(three_candidates=candidates == expected,
                              three_read=len(read_results) == 3 and set(observed['read_paths']) == expected,
                              three_evidence=len(state.evidence) == 3 and set(observed['evidence_paths']) == expected,
                              pagination_content=len(state.citations) == 1
                              and 'page_no * size' in state.citations[0].content
                              and 'items[' in state.citations[0].content)
    return {'lesson': 'L05', 'case': case, 'observed': observed, 'checks': checks, 'verified': all(checks.values())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--list-cases', action='store_true')
    args = parser.parse_args()
    if args.list_cases:
        print(json.dumps({'lesson': 'L05', 'cases': CASES}))
        return 0
    if not args.case:
        parser.error('--case is required')
    report = run_case(args.case)
    print(json.dumps(report, ensure_ascii=True))
    if not all(report['checks'].values()):
        return 1
    return 2 if report.get('blocked') else (0 if report['verified'] else 1)


if __name__ == '__main__':
    raise SystemExit(main())
